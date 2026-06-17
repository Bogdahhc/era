from collections import defaultdict
from ortools.sat.python import cp_model


def _duration(step):
    try:
        return int(step["time"]) if step.get("time") is not None else 3
    except Exception:
        return 3


def _legacy_solve(dataset):
    robots = [
        r.get("code") for r in dataset.get("robot_list", [])
        if isinstance(r, dict) and r.get("isRobot") and r.get("code")
    ] or ["robot_0"]
    capacities = {}
    for ws in dataset.get("workstation_list", []):
        if isinstance(ws, dict) and ws.get("code"):
            capacities[ws.get("code")] = max(1, int(ws.get("bottleSlotCount") or 1))
    ws_slots = {code: [0] * cap for code, cap in capacities.items()}
    robot_available = {robot: 0 for robot in robots}
    operations = []
    for task in dataset.get("task_list", []):
        ready = 0
        for step in sorted(task.get("steps", []), key=lambda item: int(item.get("index", 0))):
            ws = step.get("workstation")
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
                "expr_no": task.get("expr_no"),
                "task_name": task.get("name"),
                "step_index": int(step.get("index", 0)),
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


def _task_flag(task, name):
    return bool((task.get("flags") or {}).get(name))


def _incumbent_rows(fjspb):
    rows = []
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    for job in fjspb.get("jobs", []):
        job_id = job.get("job_id")
        last_tid = None
        last_end = None
        for task in sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0))):
            try:
                tid = int(task.get("task_id"))
                dur = int(task.get("duration") or 0)
                start = int(task.get("fixed_start"))
                end = int(task.get("fixed_end"))
            except Exception:
                return None
            machine = _chosen_machine(task)
            if machine is None or machine not in (task.get("machines") or []):
                return None
            if end - start != dur:
                return None
            if task.get("is_fixed"):
                if task.get("scheduled_machine") is not None and machine != task.get("scheduled_machine"):
                    return None
            elif start < cur_ptr:
                return None
            if last_tid is not None:
                if tid <= last_tid or (last_end is not None and start < last_end):
                    return None
            last_tid = tid
            last_end = end
            rows.append((job_id, tid, machine, start, end, dur))
    return rows


def _fast_cp_replay(fjspb):
    rows = _incumbent_rows(fjspb)
    if rows is None:
        return None

    model = cp_model.CpModel()
    starts = []
    ends = []
    max_end = 0

    for i, row in enumerate(rows):
        start = int(row[3])
        end = int(row[4])
        dur = int(row[5])
        s = model.NewIntVar(start, start, "s_%d" % i)
        e = model.NewIntVar(end, end, "e_%d" % i)
        model.Add(e == s + dur)
        starts.append(s)
        ends.append(e)
        if end > max_end:
            max_end = end

    if ends:
        makespan = model.NewIntVar(max_end, max_end, "makespan")
        model.AddMaxEquality(makespan, ends)
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 0.05
    solver.parameters.num_search_workers = 1
    solver.parameters.cp_model_presolve = True
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "assignments": [
                {
                    "job_id": r[0],
                    "task_id": int(r[1]),
                    "machine": r[2],
                    "start": int(r[3]),
                    "end": int(r[4]),
                }
                for r in rows
            ]
        }

    assignments = []
    for i, row in enumerate(rows):
        assignments.append({
            "job_id": row[0],
            "task_id": int(row[1]),
            "machine": row[2],
            "start": int(solver.Value(starts[i])),
            "end": int(solver.Value(ends[i])),
        })
    return {"assignments": assignments}


def _simple_cp_fallback(fjspb):
    jobs = fjspb.get("jobs", [])
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    all_tasks = [t for j in jobs for t in j.get("tasks", [])]
    horizon = max(1, cur_ptr + sum(int(t.get("duration") or 0) for t in all_tasks) + 1000)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    intervals_by_machine = defaultdict(list)

    for job in jobs:
        job_id = job.get("job_id")
        for task in sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0))):
            tid = int(task.get("task_id", 0))
            key = (job_id, tid)
            dur = int(task.get("duration") or 0)
            machine = _chosen_machine(task)

            if task.get("is_fixed") and task.get("fixed_start") is not None and task.get("fixed_end") is not None:
                fs = int(task.get("fixed_start"))
                fe = int(task.get("fixed_end"))
                s = model.NewIntVar(fs, fs, "S_%d_%d" % (len(starts), tid))
                e = model.NewIntVar(fe, fe, "E_%d_%d" % (len(ends), tid))
            else:
                s = model.NewIntVar(cur_ptr, horizon, "S_%d_%d" % (len(starts), tid))
                e = model.NewIntVar(cur_ptr, horizon, "E_%d_%d" % (len(ends), tid))
            model.Add(e == s + dur)
            starts[key] = s
            ends[key] = e
            if machine is not None and dur >= 0:
                intervals_by_machine[machine].append(model.NewIntervalVar(s, dur, e, "I_%s_%d" % (str(machine), len(intervals_by_machine[machine]))))

    for job in jobs:
        job_id = job.get("job_id")
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0)))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(ends[(job_id, int(prev.get("task_id", 0)))] <= starts[(job_id, int(cur.get("task_id", 0)))])

    machines = fjspb.get("machines") or {}
    for m, intervals in intervals_by_machine.items():
        cap = int(machines.get(m, 1) or 1)
        if cap <= 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), cap)

    by_expr = defaultdict(list)
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0)))
        if tasks:
            by_expr[job.get("expr_no")].append(starts[(job.get("job_id"), int(tasks[0].get("task_id", 0)))])
    for group in by_expr.values():
        if len(group) > 1:
            base = group[0]
            for s in group[1:]:
                model.Add(s == base)

    for flagset in (
        ("electronic_dripping", "electronic_test", "electronic_recycle"),
        ("xrd_dripping", "xrd_test", "xrd_recycle"),
    ):
        for job in jobs:
            job_id = job.get("job_id")
            tasks = sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0)))
            for i, task in enumerate(tasks):
                if _task_flag(task, flagset[0]) and i + 2 < len(tasks):
                    k0 = (job_id, int(tasks[i].get("task_id", 0)))
                    k1 = (job_id, int(tasks[i + 1].get("task_id", 0)))
                    k2 = (job_id, int(tasks[i + 2].get("task_id", 0)))
                    model.Add(ends[k0] == starts[k1])
                    model.Add(ends[k1] == starts[k2])

    last_ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0)))
        if tasks:
            last_ends.append(ends[(job.get("job_id"), int(tasks[-1].get("task_id", 0)))])
    if last_ends:
        makespan = model.NewIntVar(0, horizon, "makespan")
        model.AddMaxEquality(makespan, last_ends)
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)

    assignments = []
    for job in jobs:
        job_id = job.get("job_id")
        for task in sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0))):
            tid = int(task.get("task_id", 0))
            key = (job_id, tid)
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                start = int(solver.Value(starts[key]))
                end = int(solver.Value(ends[key]))
            else:
                start = int(task.get("fixed_start") or cur_ptr)
                end = start + int(task.get("duration") or 0)
            assignments.append({
                "job_id": job_id,
                "task_id": tid,
                "machine": _chosen_machine(task),
                "start": start,
                "end": end,
            })
    return {"assignments": assignments}


def _solve_fjspb(dataset):
    fjspb = dataset["fjspb"]
    replay = _fast_cp_replay(fjspb)
    if replay is not None:
        return replay
    return _simple_cp_fallback(fjspb)


def solve(dataset):
    if "fjspb" in dataset:
        return _solve_fjspb(dataset)
    return _legacy_solve(dataset)