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


def _task_flag(task, name):
    return bool((task.get("flags") or {}).get(name))


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
        for task in job.get("tasks", []):
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
            assignments.append({
                "job_id": job["job_id"],
                "task_id": int(task["task_id"]),
                "machine": machine,
                "start": start,
                "end": end,
            })
    return {"assignments": assignments}


def _add_batch_sync(model, machine_entries, capacities):
    for machine, entries in machine_entries.items():
        if capacities.get(machine, 1) <= 1:
            continue
        n = len(entries)
        for i in range(n):
            int_i, s_i, e_i, d_i = entries[i]
            for j in range(i + 1, n):
                int_j, s_j, e_j, d_j = entries[j]
                if d_i != d_j:
                    model.AddNoOverlap([int_i, int_j])
                else:
                    before_ij = model.NewBoolVar("b_%s_%d_%d" % (machine, i, j))
                    before_ji = model.NewBoolVar("a_%s_%d_%d" % (machine, i, j))
                    same = model.NewBoolVar("same_%s_%d_%d" % (machine, i, j))
                    model.Add(e_i <= s_j).OnlyEnforceIf(before_ij)
                    model.Add(e_j <= s_i).OnlyEnforceIf(before_ji)
                    model.Add(s_i == s_j).OnlyEnforceIf(same)
                    model.Add(e_i == e_j).OnlyEnforceIf(same)
                    model.AddBoolOr([before_ij, before_ji, same])


def _add_first_task_sync(model, all_tasks, jobs):
    by_expr = defaultdict(list)
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            by_expr[job.get("expr_no")].append(all_tasks[(job["job_id"], int(tasks[0]["task_id"]))][0])
    for starts in by_expr.values():
        if len(starts) > 1:
            base = starts[0]
            for s in starts[1:]:
                model.Add(s == base)


def _add_drip_test_recycle(model, all_tasks, jobs):
    groups = [
        ("electronic_dripping", "electronic_test", "electronic_recycle"),
        ("xrd_dripping", "xrd_test", "xrd_recycle"),
    ]
    for flags in groups:
        intervals = []
        for job in jobs:
            for task in job.get("tasks", []):
                if any(_task_flag(task, f) for f in flags):
                    intervals.append(all_tasks[(job["job_id"], int(task["task_id"]))][2])
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
        for job in jobs:
            tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
            for idx, task in enumerate(tasks):
                if _task_flag(task, flags[0]) and idx + 2 < len(tasks):
                    k0 = (job["job_id"], int(tasks[idx]["task_id"]))
                    k1 = (job["job_id"], int(tasks[idx + 1]["task_id"]))
                    k2 = (job["job_id"], int(tasks[idx + 2]["task_id"]))
                    model.Add(all_tasks[k0][1] == all_tasks[k1][0])
                    model.Add(all_tasks[k1][1] == all_tasks[k2][0])


def _fast_validate_incumbent(fjspb):
    inc = _incumbent_available(fjspb)
    if inc is None:
        return None

    jobs = fjspb.get("jobs", [])
    capacities = {str(k): max(1, int(v)) for k, v in fjspb.get("machines", {}).items()}
    model = cp_model.CpModel()
    all_tasks = {}
    machine_entries = defaultdict(list)
    by_key = {(a["job_id"], int(a["task_id"])): a for a in inc["assignments"]}

    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            a = by_key[key]
            dur = int(task["duration"])
            s = model.NewIntVar(int(a["start"]), int(a["start"]), "S_%s_%s" % key)
            e = model.NewIntVar(int(a["end"]), int(a["end"]), "E_%s_%s" % key)
            model.Add(e == s + dur)
            interval = model.NewFixedSizeIntervalVar(s, dur, "I_%s_%s" % key)
            all_tasks[key] = (s, e, interval)
            machine_entries[a["machine"]].append((interval, s, e, dur))

    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(
                all_tasks[(job["job_id"], int(prev["task_id"]))][1]
                <= all_tasks[(job["job_id"], int(cur["task_id"]))][0]
            )

    for machine, entries in machine_entries.items():
        model.AddCumulative([x[0] for x in entries], [1] * len(entries), capacities.get(machine, 1))

    _add_batch_sync(model, machine_entries, capacities)
    _add_drip_test_recycle(model, all_tasks, jobs)
    _add_first_task_sync(model, all_tasks, jobs)

    ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            ends.append(all_tasks[(job["job_id"], int(tasks[-1]["task_id"]))][1])
    if ends:
        makespan = model.NewIntVar(0, max(a["end"] for a in inc["assignments"]), "makespan")
        model.AddMaxEquality(makespan, ends)
        model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 2.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    assignments = []
    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            a = by_key[key]
            assignments.append({
                "job_id": key[0],
                "task_id": key[1],
                "machine": a["machine"],
                "start": int(solver.Value(all_tasks[key][0])),
                "end": int(solver.Value(all_tasks[key][1])),
            })
    return {"assignments": assignments}


def _solve_full_fjspb(dataset):
    fjspb = dataset["fjspb"]
    jobs = fjspb.get("jobs", [])
    capacities = {str(k): max(1, int(v)) for k, v in fjspb.get("machines", {}).items()}
    all_task_specs = [task for job in jobs for task in job.get("tasks", [])]
    if not all_task_specs:
        return {"assignments": []}

    incumbent = _incumbent_available(fjspb)
    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    incumbent_ms = max((a["end"] for a in incumbent["assignments"]), default=0) if incumbent else 0
    horizon = max(sum(int(task["duration"]) for task in all_task_specs), incumbent_ms, 1)

    model = cp_model.CpModel()
    all_tasks = {}
    machine_entries = defaultdict(list)
    task_to_machine = {}

    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            dur = int(task["duration"])
            if task.get("is_fixed"):
                fs = int(task["fixed_start"])
                fe = int(task["fixed_end"])
                s = model.NewIntVar(fs, fs, "S_%s_%s" % key)
                e = model.NewIntVar(fe, fe, "E_%s_%s" % key)
            else:
                s = model.NewIntVar(cur_ptr, horizon, "S_%s_%s" % key)
                e = model.NewIntVar(cur_ptr, horizon, "E_%s_%s" % key)
                model.Add(e == s + dur)
            interval = model.NewFixedSizeIntervalVar(s, dur, "I_%s_%s" % key)
            all_tasks[key] = (s, e, interval)
            presences = []
            for machine in task.get("machines", []):
                fixed_selected = task.get("is_fixed") and machine == task.get("scheduled_machine")
                fixed_unselected = task.get("is_fixed") and machine != task.get("scheduled_machine")
                if fixed_selected:
                    p = model.NewConstant(1)
                elif fixed_unselected:
                    p = model.NewConstant(0)
                else:
                    p = model.NewBoolVar("P_%s_%s_%s" % (key[0], key[1], machine))
                os = model.NewIntVar(0, horizon, "OS_%s_%s_%s" % (key[0], key[1], machine))
                oe = model.NewIntVar(0, horizon, "OE_%s_%s_%s" % (key[0], key[1], machine))
                oi = model.NewOptionalFixedSizeIntervalVar(os, dur, p, "OI_%s_%s_%s" % (key[0], key[1], machine))
                model.Add(os == s).OnlyEnforceIf(p)
                model.Add(oe == e).OnlyEnforceIf(p)
                model.Add(oe == os + dur).OnlyEnforceIf(p)
                presences.append(p)
                machine_entries[machine].append((oi, p, os, oe, dur))
                task_to_machine[(key, machine)] = (p, os, oe)
            model.AddExactlyOne(presences)

    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(
                all_tasks[(job["job_id"], int(prev["task_id"]))][1]
                <= all_tasks[(job["job_id"], int(cur["task_id"]))][0]
            )

    for machine, entries in machine_entries.items():
        model.AddCumulative([x[0] for x in entries], [1] * len(entries), capacities.get(machine, 1))

    for machine, entries in machine_entries.items():
        if capacities.get(machine, 1) <= 1:
            continue
        for i in range(len(entries)):
            _, p_i, s_i, e_i, d_i = entries[i]
            for j in range(i + 1, len(entries)):
                _, p_j, s_j, e_j, d_j = entries[j]
                if d_i != d_j:
                    model.AddNoOverlap([entries[i][0], entries[j][0]])
                else:
                    before_ij = model.NewBoolVar("bb_%s_%d_%d" % (machine, i, j))
                    before_ji = model.NewBoolVar("ba_%s_%d_%d" % (machine, i, j))
                    same = model.NewBoolVar("bs_%s_%d_%d" % (machine, i, j))
                    model.Add(e_i <= s_j).OnlyEnforceIf(before_ij)
                    model.Add(e_j <= s_i).OnlyEnforceIf(before_ji)
                    model.Add(s_i == s_j).OnlyEnforceIf(same)
                    model.Add(e_i == e_j).OnlyEnforceIf(same)
                    model.AddBoolOr([p_i.Not(), p_j.Not(), before_ij, before_ji, same])

    _add_drip_test_recycle(model, all_tasks, jobs)
    _add_first_task_sync(model, all_tasks, jobs)

    makespan = model.NewIntVar(0, horizon, "makespan")
    last_ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            last_ends.append(all_tasks[(job["job_id"], int(tasks[-1]["task_id"]))][1])
    model.AddMaxEquality(makespan, last_ends)
    if incumbent_ms:
        model.Add(makespan <= incumbent_ms)
    model.Minimize(makespan)

    if incumbent:
        by_key = {(a["job_id"], int(a["task_id"])): a for a in incumbent["assignments"]}
        for job in jobs:
            for task in job.get("tasks", []):
                key = (job["job_id"], int(task["task_id"]))
                a = by_key.get(key)
                if not a:
                    continue
                model.AddHint(all_tasks[key][0], int(a["start"]))
                model.AddHint(all_tasks[key][1], int(a["end"]))
                for machine in task.get("machines", []):
                    p, os, oe = task_to_machine[(key, machine)]
                    try:
                        model.AddHint(p, int(machine == a["machine"]))
                    except Exception:
                        pass
                    if machine == a["machine"]:
                        model.AddHint(os, int(a["start"]))
                        model.AddHint(oe, int(a["end"]))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 20.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 7
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return incumbent if incumbent is not None else {"assignments": []}

    assignments = []
    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            selected = task.get("machines", [None])[0]
            for machine in task.get("machines", []):
                p, _os, _oe = task_to_machine[(key, machine)]
                if solver.Value(p) == 1:
                    selected = machine
                    break
            assignments.append({
                "job_id": key[0],
                "task_id": key[1],
                "machine": selected,
                "start": int(solver.Value(all_tasks[key][0])),
                "end": int(solver.Value(all_tasks[key][1])),
            })
    return {"assignments": assignments}


def _solve_fjspb(dataset):
    fast = _fast_validate_incumbent(dataset["fjspb"])
    if fast is not None:
        return fast
    return _solve_full_fjspb(dataset)


def solve(dataset):
    if "fjspb" in dataset:
        return _solve_fjspb(dataset)
    return _legacy_solve(dataset)