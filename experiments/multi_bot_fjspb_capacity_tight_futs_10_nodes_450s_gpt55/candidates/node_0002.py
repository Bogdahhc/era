from collections import defaultdict
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


def _incumbent_available(fjspb):
    assignments = []
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    for job in fjspb.get("jobs", []):
        last_tid = None
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            dur = int(task.get("duration") or 0)
            start = task.get("fixed_start")
            end = task.get("fixed_end")
            machine = _chosen_machine(task)
            if start is None or end is None or machine is None:
                return None
            start = int(start)
            end = int(end)
            if end - start != dur:
                return None
            if not task.get("is_fixed") and start < cur_ptr:
                return None
            if machine not in (task.get("machines") or []):
                return None
            if last_tid is not None and int(task["task_id"]) <= last_tid:
                return None
            last_tid = int(task["task_id"])
            assignments.append({
                "job_id": job["job_id"],
                "task_id": int(task["task_id"]),
                "machine": machine,
                "start": start,
                "end": end,
            })
    return {"assignments": assignments}


def _task_flag(task, name):
    return bool((task.get("flags") or {}).get(name))


def _cp_replay_incumbent(fjspb):
    inc = _incumbent_available(fjspb)
    if inc is None:
        return None

    jobs = fjspb.get("jobs", [])
    by_key = {(a["job_id"], int(a["task_id"])): a for a in inc["assignments"]}
    max_end = max((int(a["end"]) for a in inc["assignments"]), default=0)
    model = cp_model.CpModel()
    starts = {}
    ends = {}

    for job in jobs:
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            key = (job["job_id"], int(task["task_id"]))
            a = by_key[key]
            dur = int(task.get("duration") or 0)
            s0 = int(a["start"])
            e0 = int(a["end"])
            s = model.NewIntVar(s0, s0, "S_%s_%s" % (key[0], key[1]))
            e = model.NewIntVar(e0, e0, "E_%s_%s" % (key[0], key[1]))
            model.Add(e == s + dur)
            if task.get("is_fixed"):
                model.Add(s == int(task["fixed_start"]))
                model.Add(e == int(task["fixed_end"]))
            else:
                model.Add(s >= int(fjspb.get("cur_ptr") or 0))
            starts[key] = s
            ends[key] = e

    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(ends[(job["job_id"], int(prev["task_id"]))] <= starts[(job["job_id"], int(cur["task_id"]))])

    by_expr = defaultdict(list)
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            by_expr[job.get("expr_no")].append(starts[(job["job_id"], int(tasks[0]["task_id"]))])
    for group in by_expr.values():
        if len(group) > 1:
            base = group[0]
            for s in group[1:]:
                model.Add(s == base)

    for flags in (
        ("electronic_dripping", "electronic_test", "electronic_recycle"),
        ("xrd_dripping", "xrd_test", "xrd_recycle"),
    ):
        for job in jobs:
            tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
            for i, task in enumerate(tasks):
                if _task_flag(task, flags[0]) and i + 2 < len(tasks):
                    k0 = (job["job_id"], int(tasks[i]["task_id"]))
                    k1 = (job["job_id"], int(tasks[i + 1]["task_id"]))
                    k2 = (job["job_id"], int(tasks[i + 2]["task_id"]))
                    model.Add(ends[k0] == starts[k1])
                    model.Add(ends[k1] == starts[k2])

    last_ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            last_ends.append(ends[(job["job_id"], int(tasks[-1]["task_id"]))])
    if last_ends:
        makespan = model.NewIntVar(0, max_end, "makespan")
        model.AddMaxEquality(makespan, last_ends)
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return inc

    assignments = []
    for job in jobs:
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            key = (job["job_id"], int(task["task_id"]))
            a = by_key[key]
            assignments.append({
                "job_id": key[0],
                "task_id": key[1],
                "machine": a["machine"],
                "start": int(solver.Value(starts[key])),
                "end": int(solver.Value(ends[key])),
            })
    return {"assignments": assignments}


def _simple_cp_fallback(fjspb):
    jobs = fjspb.get("jobs", [])
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    all_tasks = [t for j in jobs for t in j.get("tasks", [])]
    horizon = max(1, sum(int(t.get("duration") or 0) for t in all_tasks) + cur_ptr)
    model = cp_model.CpModel()
    starts = {}
    ends = {}
    for job in jobs:
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            key = (job["job_id"], int(task["task_id"]))
            dur = int(task.get("duration") or 0)
            if task.get("is_fixed") and task.get("fixed_start") is not None and task.get("fixed_end") is not None:
                s = model.NewIntVar(int(task["fixed_start"]), int(task["fixed_start"]), "S_%s_%s" % key)
                e = model.NewIntVar(int(task["fixed_end"]), int(task["fixed_end"]), "E_%s_%s" % key)
            else:
                s = model.NewIntVar(cur_ptr, horizon, "S_%s_%s" % key)
                e = model.NewIntVar(cur_ptr, horizon, "E_%s_%s" % key)
            model.Add(e == s + dur)
            starts[key] = s
            ends[key] = e
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(ends[(job["job_id"], int(prev["task_id"]))] <= starts[(job["job_id"], int(cur["task_id"]))])
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
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 1
    solver.Solve(model)
    assignments = []
    for job in jobs:
        for task in sorted(job.get("tasks", []), key=lambda t: int(t["task_id"])):
            key = (job["job_id"], int(task["task_id"]))
            machine = _chosen_machine(task)
            assignments.append({
                "job_id": key[0],
                "task_id": key[1],
                "machine": machine,
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