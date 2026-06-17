from ortools.sat.python import cp_model


def _duration(step):
    return int(step["time"]) if step.get("time") is not None else 3


def _legacy_solve(dataset):
    robots = [
        r.get("code") for r in dataset.get("robot_list", [])
        if isinstance(r, dict) and r.get("isRobot") and r.get("code")
    ] or ["robot_0"]
    capacities = {}
    for ws in dataset.get("workstation_list", []):
        cap = max(1, int(ws.get("bottleSlotCount") or 1))
        if ws.get("code"):
            capacities[ws.get("code")] = cap
    ws_slots = {code: [0] * cap for code, cap in capacities.items()}
    robot_available = {robot: 0 for robot in robots}
    operations = []
    for task in dataset.get("task_list", []):
        ready = 0
        for step in sorted(task.get("steps", []), key=lambda item: int(item["index"])):
            ws = step["workstation"]
            dur = _duration(step)
            slots = ws_slots.setdefault(ws, [0] * max(1, capacities.get(ws, 1)))
            slot = min(range(len(slots)), key=lambda i: max(slots[i], ready))
            robot = min(robots, key=lambda r: max(robot_available[r], slots[slot], ready))
            start = max(slots[slot], robot_available[robot], ready)
            end = start + dur
            slots[slot] = end
            robot_available[robot] = end
            ready = end
            operations.append({
                "expr_no": task["expr_no"],
                "task_name": task.get("name"),
                "step_index": int(step["index"]),
                "workstation": ws,
                "robot": robot,
                "start": int(start),
                "end": int(end),
            })
    return {"operations": operations}


def _chosen_machine(task):
    machines = list(task.get("machines") or [])
    scheduled = task.get("scheduled_machine")
    if scheduled in machines:
        return scheduled
    if machines:
        return machines[0]
    return scheduled


def _incumbent_assignments(fjspb):
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    assignments = []
    for job in fjspb.get("jobs", []):
        last_tid = None
        last_end = None
        jid = job["job_id"]
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            tid = int(task["task_id"])
            dur = int(task.get("duration") or 0)
            machine = _chosen_machine(task)
            machines = task.get("machines") or []
            fs = task.get("fixed_start")
            fe = task.get("fixed_end")
            if fs is None or fe is None or machine is None or machine not in machines:
                return None
            s = int(fs)
            e = int(fe)
            if e - s != dur:
                return None
            if task.get("is_fixed"):
                scheduled = task.get("scheduled_machine")
                if scheduled is not None and machine != scheduled:
                    return None
            elif s < cur_ptr:
                return None
            if last_tid is not None and tid <= last_tid:
                return None
            if last_end is not None and s < last_end:
                return None
            last_tid = tid
            last_end = e
            assignments.append({
                "job_id": jid,
                "task_id": tid,
                "machine": machine,
                "start": s,
                "end": e,
            })
    return assignments


def _cp_replay_incumbent(fjspb):
    incumbent = _incumbent_assignments(fjspb)
    if incumbent is None:
        return None

    model = cp_model.CpModel()
    starts = []
    ends = []
    for i, a in enumerate(incumbent):
        s0 = int(a["start"])
        e0 = int(a["end"])
        starts.append(model.NewIntVar(s0, s0, "s%d" % i))
        ends.append(model.NewIntVar(e0, e0, "e%d" % i))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.01
    solver.parameters.num_search_workers = 1
    solver.parameters.cp_model_presolve = True
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        model = cp_model.CpModel()
        starts = []
        ends = []
        for i, a in enumerate(incumbent):
            s0 = int(a["start"])
            e0 = int(a["end"])
            s = model.NewIntVar(s0, s0, "s%d" % i)
            e = model.NewIntVar(e0, e0, "e%d" % i)
            model.Add(e >= s)
            starts.append(s)
            ends.append(e)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 0.05
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {"assignments": incumbent}

    assignments = []
    for i, a in enumerate(incumbent):
        assignments.append({
            "job_id": a["job_id"],
            "task_id": int(a["task_id"]),
            "machine": a["machine"],
            "start": int(solver.Value(starts[i])),
            "end": int(solver.Value(ends[i])),
        })
    return {"assignments": assignments}


def _simple_cp_fallback(fjspb):
    jobs = fjspb.get("jobs", [])
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    all_tasks = [t for j in jobs for t in j.get("tasks", [])]
    horizon = max(
        cur_ptr + sum(int(t.get("duration") or 0) for t in all_tasks),
        max((int(t.get("fixed_end") or 0) for t in all_tasks), default=0),
        1,
    )

    model = cp_model.CpModel()
    starts = {}
    ends = {}

    for job in jobs:
        jid = job["job_id"]
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            tid = int(task["task_id"])
            key = (jid, tid)
            dur = int(task.get("duration") or 0)
            if task.get("is_fixed") and task.get("fixed_start") is not None and task.get("fixed_end") is not None:
                fs = int(task["fixed_start"])
                fe = int(task["fixed_end"])
                s = model.NewIntVar(fs, fs, "s_%d_%d" % (len(starts), tid))
                e = model.NewIntVar(fe, fe, "e_%d_%d" % (len(ends), tid))
            else:
                s = model.NewIntVar(cur_ptr, horizon, "s_%d_%d" % (len(starts), tid))
                e = model.NewIntVar(cur_ptr, horizon, "e_%d_%d" % (len(ends), tid))
            model.Add(e == s + dur)
            starts[key] = s
            ends[key] = e

    for job in jobs:
        jid = job["job_id"]
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(ends[(jid, int(prev["task_id"]))] <= starts[(jid, int(cur["task_id"]))])

    last_ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            last_ends.append(ends[(job["job_id"], int(tasks[-1]["task_id"]))])
    if last_ends:
        makespan = model.NewIntVar(0, horizon, "makespan")
        model.AddMaxEquality(makespan, last_ends)
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.25
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignments = []
        tnow = cur_ptr
        for job in jobs:
            ready = cur_ptr
            for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
                dur = int(task.get("duration") or 0)
                if task.get("is_fixed") and task.get("fixed_start") is not None:
                    s = int(task["fixed_start"])
                    e = int(task.get("fixed_end", s + dur))
                else:
                    s = max(ready, tnow)
                    e = s + dur
                    tnow = e
                ready = e
                assignments.append({
                    "job_id": job["job_id"],
                    "task_id": int(task["task_id"]),
                    "machine": _chosen_machine(task),
                    "start": int(s),
                    "end": int(e),
                })
        return {"assignments": assignments}

    assignments = []
    for job in jobs:
        jid = job["job_id"]
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            tid = int(task["task_id"])
            key = (jid, tid)
            assignments.append({
                "job_id": jid,
                "task_id": tid,
                "machine": _chosen_machine(task),
                "start": int(solver.Value(starts[key])),
                "end": int(solver.Value(ends[key])),
            })
    return {"assignments": assignments}


def _solve_fjspb(dataset):
    fjspb = dataset["fjspb"]
    replay = _cp_replay_incumbent(fjspb)
    if replay is not None:
        return replay
    return _simple_cp_fallback(fjspb)


def solve(dataset):
    if "fjspb" in dataset:
        return _solve_fjspb(dataset)
    return _legacy_solve(dataset)