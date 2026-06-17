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
        capacities[ws.get("code")] = cap
    ws_slots = {code: [0] * cap for code, cap in capacities.items() if code}
    robot_available = {robot: 0 for robot in robots}
    operations = []
    for task in dataset.get("task_list", []):
        ready = 0
        for step in sorted(task.get("steps", []), key=lambda item: item["index"]):
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


def _temperature(task):
    vals = []
    for p in task.get("parameters", []) or []:
        param = p.get("param") if isinstance(p, dict) else None
        if isinstance(param, dict) and param.get("temperature") is not None:
            vals.append(str(param.get("temperature")))
    return "|".join(vals) if vals else None


def _hot_machine(machine):
    m = str(machine)
    return "dryer" in m or "muffle" in m or "furnace" in m


def _add_optional_disj(model, p_i, s_i, e_i, p_j, s_j, e_j, name):
    before_ij = model.NewBoolVar(name + "_b1")
    before_ji = model.NewBoolVar(name + "_b2")
    model.Add(e_i <= s_j).OnlyEnforceIf(before_ij)
    model.Add(e_j <= s_i).OnlyEnforceIf(before_ji)
    model.AddBoolOr([p_i.Not(), p_j.Not(), before_ij, before_ji])


def _add_batch_sync(model, machine_entries, capacities):
    for machine, entries in machine_entries.items():
        if capacities.get(machine, 1) <= 1:
            continue
        hot = _hot_machine(machine)
        n = len(entries)
        for i in range(n):
            _, p_i, s_i, e_i, d_i, task_i = entries[i]
            temp_i = _temperature(task_i)
            for j in range(i + 1, n):
                _, p_j, s_j, e_j, d_j, task_j = entries[j]
                temp_j = _temperature(task_j)
                temp_limited = hot and temp_i is not None and temp_j is not None and temp_i != temp_j
                if d_i != d_j or temp_limited:
                    _add_optional_disj(model, p_i, s_i, e_i, p_j, s_j, e_j, "batch_no_%s_%d_%d" % (machine, i, j))
                else:
                    before_ij = model.NewBoolVar("batch_before_%s_%d_%d" % (machine, i, j))
                    before_ji = model.NewBoolVar("batch_after_%s_%d_%d" % (machine, i, j))
                    same = model.NewBoolVar("batch_same_%s_%d_%d" % (machine, i, j))
                    model.Add(e_i <= s_j).OnlyEnforceIf(before_ij)
                    model.Add(e_j <= s_i).OnlyEnforceIf(before_ji)
                    model.Add(s_i == s_j).OnlyEnforceIf(same)
                    model.Add(e_i == e_j).OnlyEnforceIf(same)
                    model.AddBoolOr([p_i.Not(), p_j.Not(), before_ij, before_ji, same])


def _add_drip_test_recycle(model, all_tasks, jobs):
    group_flags = [
        ("electronic_dripping", "electronic_test", "electronic_recycle"),
        ("xrd_dripping", "xrd_test", "xrd_recycle"),
    ]
    for flags in group_flags:
        intervals = []
        for job in jobs:
            for task in job.get("tasks", []):
                if any(_task_flag(task, flag) for flag in flags):
                    intervals.append(all_tasks[(job["job_id"], int(task["task_id"]))][2])
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)
        for job in jobs:
            tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
            for idx, task in enumerate(tasks):
                if _task_flag(task, flags[0]) and idx + 2 < len(tasks):
                    k0 = (job["job_id"], int(task["task_id"]))
                    k1 = (job["job_id"], int(tasks[idx + 1]["task_id"]))
                    k2 = (job["job_id"], int(tasks[idx + 2]["task_id"]))
                    model.Add(all_tasks[k0][1] == all_tasks[k1][0])
                    model.Add(all_tasks[k1][1] == all_tasks[k2][0])


def _add_first_task_sync(model, all_tasks, jobs):
    by_expr = defaultdict(list)
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            by_expr[job.get("expr_no")].append(all_tasks[(job["job_id"], int(tasks[0]["task_id"]))][0])
    for starts in by_expr.values():
        if len(starts) > 1:
            base = starts[0]
            for start in starts[1:]:
                model.Add(start == base)


def _add_odd_centrifuge_pair_sync(model, all_tasks, jobs):
    groups = defaultdict(list)
    for job in jobs:
        for task in job.get("tasks", []):
            if task.get("is_fixed"):
                continue
            machines = [str(machine) for machine in task.get("machines", [])]
            flags = task.get("flags") or {}
            if any("centrifug" in machine for machine in machines) or flags.get("odd"):
                groups[(job.get("expr_no"), int(task["task_id"]), int(task.get("duration", 0)))].append(
                    (job["job_id"], int(task["task_id"]))
                )
    for keys in groups.values():
        keys.sort()
        for i in range(0, len(keys) - 1, 2):
            first = keys[i]
            second = keys[i + 1]
            model.Add(all_tasks[first][0] == all_tasks[second][0])
            model.Add(all_tasks[first][1] == all_tasks[second][1])


def _slot_start_for_machine(machine_state, cap, dur, temp, ready, machine):
    if cap > 1:
        best_existing = None
        for idx, b in enumerate(machine_state.setdefault(machine, [])):
            bs, be, bd, bt, used = b
            temp_ok = (bt == temp) or (not _hot_machine(machine))
            if bd == dur and used < cap and bs >= ready and temp_ok:
                cand = (bs, idx)
                if best_existing is None or cand < best_existing:
                    best_existing = cand
        if best_existing is not None:
            return best_existing[0], best_existing[1], True
        t = ready
        while True:
            conflict_end = None
            used_same = 0
            for bs, be, bd, bt, used in machine_state.setdefault(machine, []):
                if be <= t or bs >= t + dur:
                    continue
                same_temp = (bt == temp) or (not _hot_machine(machine))
                if bd == dur and bs == t and same_temp:
                    used_same += used
                else:
                    conflict_end = max(conflict_end or 0, be)
            if conflict_end is None and used_same < cap:
                return t, None, False
            t = conflict_end if conflict_end is not None else t + 1
    else:
        avail = machine_state.setdefault(machine, [0])[0]
        return max(avail, ready), 0, False


def _reserve_machine(machine_state, capacities, machine, start, dur, temp, idx=None, existing=False):
    cap = max(1, int(capacities.get(machine, 1)))
    end = start + dur
    if cap > 1:
        batches = machine_state.setdefault(machine, [])
        if existing and idx is not None and idx < len(batches):
            bs, be, bd, bt, used = batches[idx]
            batches[idx] = (bs, be, bd, bt, used + 1)
        else:
            batches.append((start, end, dur, temp, 1))
            batches.sort()
    else:
        machine_state.setdefault(machine, [0])[0] = end


def _greedy_hints(jobs, capacities, cur_ptr):
    machine_state = {}
    for m, c in capacities.items():
        if int(c) <= 1:
            machine_state[str(m)] = [cur_ptr]
        else:
            machine_state[str(m)] = []
    hint = {}
    expr_first_start = {}

    ordered_jobs = sorted(jobs, key=lambda j: (str(j.get("expr_no")), str(j.get("job_id"))))
    for job in ordered_jobs:
        job_id = job["job_id"]
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        ready = cur_ptr
        for idx, task in enumerate(tasks):
            key = (job_id, int(task["task_id"]))
            dur = int(task["duration"])
            temp = _temperature(task)
            if task.get("is_fixed"):
                mach = str(task.get("scheduled_machine") or (task.get("machines") or [""])[0])
                st = int(task["fixed_start"])
                en = int(task["fixed_end"])
                if mach in capacities:
                    _reserve_machine(machine_state, capacities, mach, st, dur, temp)
                hint[key] = (mach, st, en)
                ready = en
                continue

            best = None
            for mach0 in task.get("machines", []):
                mach = str(mach0)
                req_ready = max(ready, cur_ptr)
                if idx == 0 and job.get("expr_no") in expr_first_start:
                    req_ready = max(req_ready, expr_first_start[job.get("expr_no")])
                st, slot_idx, existing = _slot_start_for_machine(
                    machine_state, max(1, int(capacities.get(mach, 1))), dur, temp, req_ready, mach
                )
                cand = (st + dur, st, 0 if existing else 1, mach, slot_idx, existing)
                if best is None or cand < best:
                    best = cand
            if best is None:
                continue
            en, st, _, mach, slot_idx, existing = best
            if idx == 0:
                old = expr_first_start.get(job.get("expr_no"))
                if old is None:
                    expr_first_start[job.get("expr_no")] = st
                else:
                    st = max(st, old)
                    en = st + dur
            _reserve_machine(machine_state, capacities, mach, st, dur, temp, slot_idx, existing)
            hint[key] = (mach, st, en)
            ready = en
    return hint


def _add_simple_lower_bounds(model, all_tasks, jobs, cur_ptr):
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        acc = 0
        for task in tasks:
            key = (job["job_id"], int(task["task_id"]))
            if not task.get("is_fixed"):
                model.Add(all_tasks[key][0] >= cur_ptr + acc)
            acc += int(task.get("duration", 0))


def _critical_path_lb(jobs, cur_ptr):
    lb = 0
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        t = cur_ptr
        for task in tasks:
            dur = int(task.get("duration", 0))
            if task.get("is_fixed"):
                fs = int(task.get("fixed_start", t))
                fe = int(task.get("fixed_end", fs + dur))
                t = max(t, fs) + dur
                if t < fe:
                    t = fe
            else:
                t += dur
        lb = max(lb, t)
    return int(lb)


class _StopAtBound(cp_model.CpSolverSolutionCallback):
    def __init__(self, obj_var, target):
        cp_model.CpSolverSolutionCallback.__init__(self)
        self._obj = obj_var
        self._target = int(target)
        self.best = None

    def OnSolutionCallback(self):
        val = int(self.Value(self._obj))
        self.best = val if self.best is None else min(self.best, val)
        if val <= self._target:
            self.StopSearch()


def _solve_fjspb(dataset):
    fjspb = dataset["fjspb"]
    jobs = fjspb.get("jobs", [])
    capacities = {str(k): max(1, int(v)) for k, v in fjspb.get("machines", {}).items()}
    all_task_specs = [task for job in jobs for task in job.get("tasks", [])]
    if not all_task_specs:
        return {"assignments": []}

    cur_ptr = int(fjspb.get("cur_ptr") or 0)
    fixed_latest = max((int(task["fixed_end"]) for task in all_task_specs if task.get("fixed_end") is not None), default=0)
    horizon = max(cur_ptr + sum(int(task["duration"]) for task in all_task_specs), fixed_latest, 1)

    model = cp_model.CpModel()
    all_tasks = {}
    machine_entries = defaultdict(list)
    task_to_machine = {}
    presence_vars = []
    start_vars = []

    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            dur = int(task["duration"])
            machines = [str(m) for m in (task.get("machines") or [])]
            if task.get("is_fixed") and task.get("scheduled_machine") is not None:
                sm = str(task.get("scheduled_machine"))
                if sm not in machines:
                    machines.append(sm)
            if not machines:
                machines = [str(task.get("scheduled_machine") or "machine_0")]

            if task.get("is_fixed"):
                s = model.NewConstant(int(task["fixed_start"]))
                e = model.NewConstant(int(task["fixed_end"]))
                interval = model.NewFixedSizeIntervalVar(s, dur, "I_%s_%s" % key)
            else:
                s = model.NewIntVar(cur_ptr, horizon, "S_%s_%s" % key)
                e = model.NewIntVar(cur_ptr, horizon, "E_%s_%s" % key)
                model.Add(e == s + dur)
                interval = model.NewFixedSizeIntervalVar(s, dur, "I_%s_%s" % key)
                start_vars.append(s)
            all_tasks[key] = (s, e, interval)
            presences = []
            for machine in machines:
                if task.get("is_fixed") and machine == str(task.get("scheduled_machine")):
                    p = model.NewConstant(1)
                elif task.get("is_fixed"):
                    p = model.NewConstant(0)
                else:
                    p = model.NewBoolVar("P_%s_%s_%s" % (key[0], key[1], machine))
                    presence_vars.append(p)
                os = model.NewIntVar(0, horizon, "OS_%s_%s_%s" % (key[0], key[1], machine))
                oe = model.NewIntVar(0, horizon, "OE_%s_%s_%s" % (key[0], key[1], machine))
                oi = model.NewOptionalFixedSizeIntervalVar(os, dur, p, "OI_%s_%s_%s" % (key[0], key[1], machine))
                model.Add(os == s).OnlyEnforceIf(p)
                model.Add(oe == e).OnlyEnforceIf(p)
                model.Add(oe == os + dur).OnlyEnforceIf(p)
                presences.append(p)
                machine_entries[machine].append((oi, p, os, oe, dur, task))
                task_to_machine[(key, machine)] = (p, os, oe)
            model.AddExactlyOne(presences)

    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        for prev, cur in zip(tasks, tasks[1:]):
            model.Add(
                all_tasks[(job["job_id"], int(prev["task_id"]))][1]
                <= all_tasks[(job["job_id"], int(cur["task_id"]))][0]
            )

    _add_simple_lower_bounds(model, all_tasks, jobs, cur_ptr)
    _add_batch_sync(model, machine_entries, capacities)

    for machine, entries in machine_entries.items():
        intervals = [entry[0] for entry in entries]
        if capacities.get(machine, 1) <= 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), capacities.get(machine, 1))

    _add_drip_test_recycle(model, all_tasks, jobs)
    _add_first_task_sync(model, all_tasks, jobs)
    _add_odd_centrifuge_pair_sync(model, all_tasks, jobs)

    makespan = model.NewIntVar(0, horizon, "makespan")
    last_ends = []
    for job in jobs:
        tasks = sorted(job.get("tasks", []), key=lambda t: int(t["task_id"]))
        if tasks:
            last_ends.append(all_tasks[(job["job_id"], int(tasks[-1]["task_id"]))][1])
    model.AddMaxEquality(makespan, last_ends)
    cp_lb = _critical_path_lb(jobs, cur_ptr)
    if cp_lb > 0:
        model.Add(makespan >= cp_lb)
    model.Minimize(makespan)

    hints = _greedy_hints(jobs, capacities, cur_ptr)
    hint_ms = 0
    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            if key not in hints:
                continue
            mach, st, en = hints[key]
            hint_ms = max(hint_ms, int(en))
            try:
                if not task.get("is_fixed"):
                    model.AddHint(all_tasks[key][0], int(st))
                    model.AddHint(all_tasks[key][1], int(en))
                for m0 in task.get("machines", []):
                    m = str(m0)
                    if (key, m) in task_to_machine:
                        p, _, _ = task_to_machine[(key, m)]
                        if not task.get("is_fixed"):
                            model.AddHint(p, 1 if m == mach else 0)
            except Exception:
                pass
    if hint_ms > 0:
        try:
            model.AddHint(makespan, int(max(hint_ms, fixed_latest)))
        except Exception:
            pass

    if presence_vars:
        model.AddDecisionStrategy(presence_vars, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)
    if start_vars:
        model.AddDecisionStrategy(start_vars, cp_model.CHOOSE_LOWEST_MIN, cp_model.SELECT_MIN_VALUE)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 44.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 29
    solver.parameters.randomize_search = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.symmetry_level = 2
    try:
        solver.parameters.use_lns = True
    except Exception:
        pass
    try:
        solver.parameters.optimize_with_core = False
    except Exception:
        pass
    try:
        solver.parameters.use_objective_lb_search = True
    except Exception:
        pass

    cb = _StopAtBound(makespan, cp_lb)
    status = solver.SolveWithSolutionCallback(model, cb)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solver.parameters.max_time_in_seconds = 120.0
        status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"assignments": []}

    assignments = []
    for job in jobs:
        for task in job.get("tasks", []):
            key = (job["job_id"], int(task["task_id"]))
            selected = str(task.get("scheduled_machine")) if task.get("is_fixed") and task.get("scheduled_machine") is not None else None
            if selected is None:
                selected = str((task.get("machines") or [None])[0])
            for machine0 in task.get("machines", []):
                machine = str(machine0)
                if (key, machine) not in task_to_machine:
                    continue
                p, _, _ = task_to_machine[(key, machine)]
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


def solve(dataset):
    if "fjspb" in dataset:
        return _solve_fjspb(dataset)
    return _legacy_solve(dataset)