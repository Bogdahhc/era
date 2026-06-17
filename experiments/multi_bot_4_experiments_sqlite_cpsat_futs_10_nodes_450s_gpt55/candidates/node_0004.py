from ortools.sat.python import cp_model
import heapq
import math


def _duration(step):
    v = step.get("time", None)
    if v is None:
        v = step.get("duration", None)
    if v is None:
        return 3
    try:
        return max(1, int(v))
    except Exception:
        return 3


def _step_index(step, default):
    v = step.get("index", step.get("step_index", default))
    try:
        return int(v)
    except Exception:
        return int(default)


def _robots(dataset):
    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, str):
            robots.append(r)
        elif isinstance(r, dict):
            code = r.get("code") or r.get("name")
            if code and (r.get("isRobot", True) or r.get("type") == "robot" or r.get("workstationType") == "robot"):
                robots.append(code)
    if not robots:
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
                code = w.get("code")
                if code and (w.get("isRobot") or w.get("workstationType") == "robot" or w.get("type") == "robot"):
                    robots.append(code)
    seen = set()
    out = []
    for r in robots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out or ["robot_0"]


def _capacities(dataset):
    result = {}
    type_first = {}
    for ws in dataset.get("workstation_list", []):
        if not isinstance(ws, dict):
            continue
        code = ws.get("code")
        typ = ws.get("workstationType", ws.get("type"))
        try:
            cap = int(ws.get("bottleSlotCount", ws.get("capacity", 1)) or 1)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            result[code] = cap
        if typ:
            type_first.setdefault(typ, cap)
    for typ, cap in type_first.items():
        result.setdefault(typ, cap)
    return result


def _flatten_steps(dataset):
    jobs = []
    for task_pos, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(task.get("steps", []), key=lambda s: _step_index(s, 0))
        job = []
        for step_pos, step in enumerate(steps):
            idx = _step_index(step, step_pos + 1)
            job.append({
                "key": (task_pos, step_pos),
                "task_pos": task_pos,
                "step_pos": step_pos,
                "expr_no": task.get("expr_no", str(task_pos)),
                "task_name": task.get("name"),
                "step_index": idx,
                "workstation": step.get("workstation"),
                "duration": _duration(step),
            })
        jobs.append(job)
    return jobs


def _first_slot(slots, earliest):
    best_i = 0
    best_s = None
    for i, t in enumerate(slots):
        s = t if t > earliest else earliest
        if best_s is None or s < best_s:
            best_s = s
            best_i = i
    return best_i, best_s


def _critical_tails(jobs):
    tails = {}
    for job in jobs:
        acc = 0
        for step in reversed(job):
            acc += step["duration"]
            tails[step["key"]] = acc
    return tails


def _heads_and_tails(jobs):
    heads = {}
    tails_after = {}
    tails_incl = {}
    for job in jobs:
        acc = 0
        for step in job:
            heads[step["key"]] = acc
            acc += step["duration"]
        acc = 0
        for step in reversed(job):
            tails_after[step["key"]] = acc
            acc += step["duration"]
            tails_incl[step["key"]] = acc
    return heads, tails_after, tails_incl


def _list_schedule(jobs, robots, capacities, mode=0):
    tails = _critical_tails(jobs)
    ws_slots = {}
    for job in jobs:
        for st in job:
            ws = st["workstation"]
            if ws not in ws_slots:
                ws_slots[ws] = [0] * max(1, int(capacities.get(ws, 1)))
    robot_avail = {r: 0 for r in robots}
    job_next = [0] * len(jobs)
    job_ready = [0] * len(jobs)
    remaining = sum(len(j) for j in jobs)
    ops = []
    hint = {}

    while remaining:
        best = None
        for j, job in enumerate(jobs):
            p = job_next[j]
            if p >= len(job):
                continue
            st = job[p]
            dur = st["duration"]
            slots = ws_slots.setdefault(st["workstation"], [0] * max(1, int(capacities.get(st["workstation"], 1))))
            ws_i, ws_s = _first_slot(slots, job_ready[j])
            best_robot = None
            best_start = None
            for r in robots:
                s = max(ws_s, robot_avail[r], job_ready[j])
                if best_start is None or s < best_start or (s == best_start and r < best_robot):
                    best_start = s
                    best_robot = r
            if mode == 1:
                cand = (best_start, -dur, -tails[st["key"]], j, p, st, ws_i, best_robot)
            elif mode == 2:
                cand = (max(job_ready[j], ws_s), best_start, -tails[st["key"]], j, p, st, ws_i, best_robot)
            else:
                cand = (best_start, -tails[st["key"]], -dur, j, p, st, ws_i, best_robot)
            if best is None or cand < best:
                best = cand

        start, _, _, j, p, st, ws_i, robot = best
        if mode == 2:
            start = best[1]
        dur = st["duration"]
        end = start + dur
        ws_slots[st["workstation"]][ws_i] = end
        robot_avail[robot] = end
        job_ready[j] = end
        job_next[j] += 1
        remaining -= 1
        ops.append({
            "expr_no": st["expr_no"],
            "task_name": st["task_name"],
            "step_index": st["step_index"],
            "workstation": st["workstation"],
            "robot": robot,
            "start": int(start),
            "end": int(end),
        })
        hint[st["key"]] = (int(start), int(end), robot)

    ops.sort(key=lambda x: (x["start"], str(x["expr_no"]), x["step_index"], str(x["workstation"])))
    return {"operations": ops}, hint, max((o["end"] for o in ops), default=0)


def _sequential_schedule(jobs, robots, capacities):
    ws_slots = {}
    robot_avail = {r: 0 for r in robots}
    ops = []
    hint = {}
    for job in jobs:
        ready = 0
        for st in job:
            slots = ws_slots.setdefault(st["workstation"], [0] * max(1, int(capacities.get(st["workstation"], 1))))
            ws_i, ws_s = _first_slot(slots, ready)
            best_robot = min(robots, key=lambda r: (max(robot_avail[r], ws_s, ready), r))
            start = max(robot_avail[best_robot], ws_s, ready)
            end = start + st["duration"]
            slots[ws_i] = end
            robot_avail[best_robot] = end
            ready = end
            ops.append({
                "expr_no": st["expr_no"],
                "task_name": st["task_name"],
                "step_index": st["step_index"],
                "workstation": st["workstation"],
                "robot": best_robot,
                "start": int(start),
                "end": int(end),
            })
            hint[st["key"]] = (int(start), int(end), best_robot)
    ops.sort(key=lambda x: (x["start"], str(x["expr_no"]), x["step_index"], str(x["workstation"])))
    return {"operations": ops}, hint, max((o["end"] for o in ops), default=0)


def _lower_bound(jobs, all_steps, robots, capacities):
    lb = 0
    if jobs:
        lb = max(lb, max(sum(s["duration"] for s in j) for j in jobs))
    if robots:
        lb = max(lb, (sum(s["duration"] for s in all_steps) + len(robots) - 1) // len(robots))
    by_ws = {}
    for st in all_steps:
        by_ws[st["workstation"]] = by_ws.get(st["workstation"], 0) + st["duration"]
    for ws, load in by_ws.items():
        cap = max(1, int(capacities.get(ws, 1)))
        lb = max(lb, (load + cap - 1) // cap)
    return int(lb)


def solve(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    jobs = _flatten_steps(dataset)
    all_steps = [s for j in jobs for s in j]
    if not all_steps:
        return {"operations": []}

    candidates = []
    for mode in (0, 1, 2):
        candidates.append(_list_schedule(jobs, robots, capacities, mode))
    candidates.append(_sequential_schedule(jobs, robots, capacities))
    fallback, hint, greedy_ms = min(candidates, key=lambda x: x[2])

    total_duration = sum(s["duration"] for s in all_steps)
    max_job_duration = max(sum(s["duration"] for s in j) for j in jobs)
    horizon = max(greedy_ms, max_job_duration, 1)
    lb = _lower_bound(jobs, all_steps, robots, capacities)
    heads, tails_after, tails_incl = _heads_and_tails(jobs)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    intervals_by_workstation = {}
    all_intervals = []
    robot_optional_intervals = {r: [] for r in robots}
    robot_presence = {}

    for st in all_steps:
        key = st["key"]
        dur = st["duration"]
        hs = int(heads.get(key, 0))
        le = int(horizon - tails_after.get(key, 0))
        if le < hs + dur:
            hs = 0
            le = horizon
        s = model.NewIntVar(hs, max(hs, le - dur), "s_%d_%d" % key)
        e = model.NewIntVar(hs + dur, le, "e_%d_%d" % key)
        iv = model.NewIntervalVar(s, dur, e, "i_%d_%d" % key)
        starts[key] = s
        ends[key] = e
        all_intervals.append(iv)
        intervals_by_workstation.setdefault(st["workstation"], []).append(iv)

        pres = []
        for r_i, r in enumerate(robots):
            p = model.NewBoolVar("rp_%d_%d_%d" % (key[0], key[1], r_i))
            oiv = model.NewOptionalIntervalVar(s, dur, e, p, "ri_%d_%d_%d" % (key[0], key[1], r_i))
            robot_optional_intervals[r].append(oiv)
            robot_presence[(key, r)] = p
            pres.append(p)
        model.AddExactlyOne(pres)

    for job in jobs:
        for a, b in zip(job, job[1:]):
            model.Add(ends[a["key"]] <= starts[b["key"]])

    for ws, intervals in intervals_by_workstation.items():
        cap = max(1, int(capacities.get(ws, 1)))
        if cap == 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), cap)

    for r in robots:
        model.AddNoOverlap(robot_optional_intervals[r])

    if len(robots) > 1:
        model.AddCumulative(all_intervals, [1] * len(all_intervals), len(robots))

    makespan = model.NewIntVar(lb, horizon, "makespan")
    model.AddMaxEquality(makespan, [ends[s["key"]] for s in all_steps])
    model.Add(makespan <= int(greedy_ms))
    model.Add(makespan >= int(lb))

    loads = []
    for r_i, r in enumerate(robots):
        load = model.NewIntVar(0, total_duration, "load_%d" % r_i)
        model.Add(load == sum(st["duration"] * robot_presence[(st["key"], r)] for st in all_steps))
        loads.append(load)
    for i in range(len(loads) - 1):
        model.Add(loads[i] >= loads[i + 1])

    ordered_steps = sorted(all_steps, key=lambda st: (-tails_incl.get(st["key"], 0), hint.get(st["key"], (0, 0, ""))[0], st["key"]))
    model.AddDecisionStrategy([starts[st["key"]] for st in ordered_steps],
                              cp_model.CHOOSE_LOWEST_MIN,
                              cp_model.SELECT_MIN_VALUE)

    for st in all_steps:
        key = st["key"]
        if key in hint:
            hs, he, hr = hint[key]
            if hs <= horizon and he <= horizon:
                model.AddHint(starts[key], int(hs))
                model.AddHint(ends[key], int(he))
                for r in robots:
                    model.AddHint(robot_presence[(key, r)], 1 if r == hr else 0)
    model.AddHint(makespan, int(greedy_ms))

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 17
    solver.parameters.linearization_level = 2
    solver.parameters.cp_model_presolve = True
    solver.parameters.symmetry_level = 2
    try:
        solver.parameters.use_lns = True
    except Exception:
        pass

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return fallback

    operations = []
    for st in all_steps:
        key = st["key"]
        assigned = robots[0]
        for r in robots:
            if solver.BooleanValue(robot_presence[(key, r)]):
                assigned = r
                break
        operations.append({
            "expr_no": st["expr_no"],
            "task_name": st["task_name"],
            "step_index": int(st["step_index"]),
            "workstation": st["workstation"],
            "robot": assigned,
            "start": int(solver.Value(starts[key])),
            "end": int(solver.Value(ends[key])),
        })

    operations.sort(key=lambda op: (int(op["start"]), str(op["expr_no"]), int(op["step_index"]), str(op["workstation"])))
    return {"operations": operations}