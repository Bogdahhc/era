def _step_index(step):
    if isinstance(step, dict):
        if step.get("step_index") is not None:
            try:
                return int(step.get("step_index"))
            except Exception:
                return step.get("step_index")
        if step.get("index") is not None:
            try:
                return int(step.get("index"))
            except Exception:
                return step.get("index")
    return 0


def _duration(step):
    if not isinstance(step, dict):
        return 3
    if "time" in step:
        v = step.get("time")
        if v is None:
            return 3
        try:
            d = int(v)
            return d if d >= 0 else 0
        except Exception:
            try:
                return float(v)
            except Exception:
                return 3
    if "duration" in step:
        v = step.get("duration")
        if v is None:
            return 3
        try:
            d = int(v)
            return d if d >= 0 else 0
        except Exception:
            try:
                return float(v)
            except Exception:
                return 3
    return 3


def _workstation(step):
    return step.get("workstation") or step.get("workstation_code") or step.get("workstationCode") or step.get("station")


def _robots(dataset):
    out = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, dict):
            code = r.get("code") or r.get("name") or r.get("id")
            if code and r.get("isRobot", True):
                out.append(str(code))
        elif r is not None:
            out.append(str(r))
    if not out:
        out = ["robot_0"]
    seen = set()
    res = []
    for r in out:
        if r not in seen:
            seen.add(r)
            res.append(r)
    return res


def _capacities(dataset):
    caps = {}
    for ws in dataset.get("workstation_list", []):
        if not isinstance(ws, dict):
            continue
        code = ws.get("code") or ws.get("name") or ws.get("id")
        typ = ws.get("type") or ws.get("workstationType")
        cap = ws.get("bottleSlotCount")
        if cap is None:
            cap = ws.get("capacity")
        if cap is None:
            cap = ws.get("slotCount")
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        if cap < 1:
            cap = 1
        if code:
            caps[str(code)] = cap
        if typ and str(typ) not in caps:
            caps[str(typ)] = cap
    return caps


def _prepare(dataset):
    tasks = []
    bottleneck_ws = {
        "liquid_dispensing",
        "solid_dispensing",
        "muffle_furnace",
        "capping_station",
        "high_flux_electrocatalysis_dripping",
        "high_flux_electrocatalysis_test",
        "high_flux_electrocatalysis_recycle",
        "high_flux_xrd_dripping",
        "high_flux_xrd_test",
        "high_flux_xrd_recycle",
    }
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = list(task.get("steps", []))
        steps.sort(key=_step_index)
        durs = [_duration(s) for s in steps]
        n = len(steps)
        rem = [0] * (n + 1)
        max_tail = [0] * (n + 1)
        bott = [0] * (n + 1)
        long_tail = [0] * (n + 1)
        single_tail = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = _workstation(steps[i])
            dur = durs[i]
            rem[i] = rem[i + 1] + dur
            max_tail[i] = max(max_tail[i + 1], dur)
            bott[i] = bott[i + 1] + (dur if ws in bottleneck_ws else 0)
            long_tail[i] = long_tail[i + 1] + (dur if dur >= 100 else 0)
            single_tail[i] = single_tail[i + 1] + (dur if ws in bottleneck_ws or dur >= 100 else 0)
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "max_tail": max_tail,
            "bott": bott,
            "long_tail": long_tail,
            "single_tail": single_tail,
        })
    return tasks


def _insert_interval(cal, start, end):
    lo = 0
    hi = len(cal)
    while lo < hi:
        mid = (lo + hi) // 2
        if cal[mid][0] < start:
            lo = mid + 1
        else:
            hi = mid
    cal.insert(lo, (start, end))


def _next_conflict_end(cal, start, dur):
    end = start + dur
    for s, e in cal:
        if e <= start:
            continue
        if s >= end:
            return None
        return e
    return None


def _earliest_two(cal_a, cal_b, ready, dur):
    t = ready
    while True:
        ea = _next_conflict_end(cal_a, t, dur)
        if ea is not None:
            if ea > t:
                t = ea
                continue
            t += 1
            continue
        eb = _next_conflict_end(cal_b, t, dur)
        if eb is not None:
            if eb > t:
                t = eb
                continue
            t += 1
            continue
        return t


def _best_assignment(robots, robot_cals, ws_slots, ready, dur, prefer_load=False):
    best = None
    for ri, r in enumerate(robots):
        rcal = robot_cals[r]
        rload = robot_cals.get("__load_" + r, 0)
        for si, scal in enumerate(ws_slots):
            st = _earliest_two(rcal, scal, ready, dur)
            key = (st, rload if prefer_load else 0, ri, si)
            if best is None or key < best[0]:
                best = (key, r, si, st)
    return best[1], best[2], best[3]


def _hash_noise(a, b, seed):
    x = (a + 1009) * 1103515245 + (b + 9176) * 12345 + seed * 2654435761
    x = (x ^ (x >> 16)) & 0x7fffffff
    return x % 997


def _priority(t, i, dur, ws, mode, seed):
    ti = t["task_index"]
    rem = t["rem"][i]
    mx = t["max_tail"][i]
    bott = t["bott"][i]
    lng = t["long_tail"][i]
    single = t["single_tail"][i]
    is_long = 1 if dur >= 100 else 0
    is_very_long = 1 if dur >= 300 else 0
    is_single = 1 if ws in (
        "liquid_dispensing",
        "solid_dispensing",
        "muffle_furnace",
        "capping_station",
        "high_flux_electrocatalysis_dripping",
        "high_flux_electrocatalysis_test",
        "high_flux_electrocatalysis_recycle",
        "high_flux_xrd_dripping",
        "high_flux_xrd_test",
        "high_flux_xrd_recycle",
    ) else 0
    noise = _hash_noise(ti, i, seed)
    if mode == 0:
        return (-rem, -mx, -bott, -dur, ti)
    if mode == 1:
        return (-lng, -rem, -mx, -dur, ti)
    if mode == 2:
        return (-is_very_long, -is_long, -rem, -dur, ti)
    if mode == 3:
        return (-bott, -single, -rem, -mx, ti)
    if mode == 4:
        return (-single, -bott, -rem, -dur, ti)
    if mode == 5:
        return (-mx, -lng, -rem, -dur, ti)
    if mode == 6:
        return (-dur, -rem, -bott, ti)
    if mode == 7:
        return (-rem, -lng, noise, ti)
    if mode == 8:
        return (-lng, noise, -rem, ti)
    if mode == 9:
        return (-is_long, -single, -bott, noise, ti)
    if mode == 10:
        is_ecat = 1 if "electrocatalysis" in str(ws) else 0
        is_xrd = 1 if "xrd" in str(ws) else 0
        return (-rem, -is_ecat, -is_xrd, -bott, ti)
    return (-rem, -dur, ti)


def _schedule(dataset, mode=0, window=0, seed=0, prefer_load=False):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    tasks = _prepare(dataset)

    robot_cals = {r: [] for r in robots}
    for r in robots:
        robot_cals["__load_" + r] = 0

    ws_slot_cals = {}
    nrobots = max(1, len(robots))
    for code, cap in caps.items():
        eff = cap
        if eff > nrobots:
            eff = nrobots
        if eff < 1:
            eff = 1
        ws_slot_cals[code] = [[] for _ in range(eff)]

    next_i = [0] * len(tasks)
    ready = [0] * len(tasks)
    remaining = sum(len(t["steps"]) for t in tasks)
    operations = []

    while remaining:
        candidates = []
        min_start = None

        for ti, t in enumerate(tasks):
            i = next_i[ti]
            if i >= len(t["steps"]):
                continue
            step = t["steps"][i]
            ws = _workstation(step)
            dur = t["durs"][i]
            if ws not in ws_slot_cals:
                cap = caps.get(ws, 1)
                try:
                    cap = int(cap)
                except Exception:
                    cap = 1
                if cap > nrobots:
                    cap = nrobots
                if cap < 1:
                    cap = 1
                ws_slot_cals[ws] = [[] for _ in range(cap)]
            robot, slot_idx, st = _best_assignment(robots, robot_cals, ws_slot_cals[ws], ready[ti], dur, prefer_load)
            if min_start is None or st < min_start:
                min_start = st
            candidates.append((ti, i, step, ws, dur, robot, slot_idx, st))

        limit = min_start + window
        best = None
        for cand in candidates:
            ti, i, step, ws, dur, robot, slot_idx, st = cand
            if st > limit:
                continue
            t = tasks[ti]
            finish = st + dur
            if mode == 11:
                key = (finish, _priority(t, i, dur, ws, 0, seed))
            elif mode == 12:
                key = (finish, _priority(t, i, dur, ws, 1, seed))
            elif mode == 13:
                key = (st, finish, _priority(t, i, dur, ws, 6, seed))
            else:
                key = (st, _priority(t, i, dur, ws, mode, seed))
            if best is None or key < best[0]:
                best = (key, cand)

        if best is None:
            cand = min(candidates, key=lambda c: (c[7], c[0], c[1]))
        else:
            cand = best[1]

        ti, i, step, ws, dur, robot, slot_idx, st = cand
        end = st + dur
        t = tasks[ti]

        _insert_interval(robot_cals[robot], st, end)
        _insert_interval(ws_slot_cals[ws][slot_idx], st, end)
        robot_cals["__load_" + robot] = robot_cals.get("__load_" + robot, 0) + dur

        ready[ti] = end
        next_i[ti] += 1
        remaining -= 1

        task = t["task"]
        if int(st) == st:
            st_out = int(st)
        else:
            st_out = st
        if int(end) == end:
            end_out = int(end)
        else:
            end_out = end
        operations.append({
            "expr_no": task.get("expr_no"),
            "task_name": task.get("name") or task.get("task_name"),
            "step_index": _step_index(step),
            "workstation": ws,
            "robot": robot,
            "start": st_out,
            "end": end_out,
        })

    makespan = max((op["end"] for op in operations), default=0)
    return {"operations": operations}, makespan


def _validate_basic(dataset, sched):
    expected = 0
    for t in dataset.get("task_list", []):
        expected += len(t.get("steps", []))
    return isinstance(sched, dict) and len(sched.get("operations", [])) == expected


def solve(dataset):
    best_schedule = None
    best_makespan = None

    trials = [
        (0, 0, 0, False),
        (1, 0, 0, False),
        (2, 0, 0, False),
        (3, 0, 0, False),
        (4, 0, 0, False),
        (5, 0, 0, False),
        (6, 0, 0, False),
        (10, 0, 0, False),
        (11, 0, 0, False),
        (12, 0, 0, False),
        (13, 0, 0, False),

        (0, 1, 1, False),
        (1, 1, 2, False),
        (2, 1, 3, False),
        (3, 1, 4, False),
        (5, 1, 5, False),

        (0, 3, 6, False),
        (1, 3, 7, False),
        (2, 3, 8, False),
        (3, 3, 9, False),
        (4, 3, 10, False),
        (5, 3, 11, False),
        (10, 3, 12, False),

        (0, 6, 13, False),
        (1, 6, 14, False),
        (2, 6, 15, False),
        (3, 6, 16, False),
        (5, 6, 17, False),
        (7, 6, 18, False),
        (8, 6, 19, False),
        (9, 6, 20, False),

        (0, 10, 21, False),
        (1, 10, 22, False),
        (2, 10, 23, False),
        (3, 10, 24, False),
        (5, 10, 25, False),
        (7, 10, 26, False),
        (8, 10, 27, False),

        (0, 20, 28, False),
        (1, 20, 29, False),
        (2, 20, 30, False),
        (5, 20, 31, False),

        (0, 3, 32, True),
        (1, 3, 33, True),
        (2, 6, 34, True),
        (5, 6, 35, True),
        (8, 10, 36, True),
    ]

    for mode, window, seed, prefer_load in trials:
        sched, ms = _schedule(dataset, mode, window, seed, prefer_load)
        if best_makespan is None or ms < best_makespan:
            best_makespan = ms
            best_schedule = sched

    if best_schedule is None or not _validate_basic(dataset, best_schedule):
        best_schedule, best_makespan = _schedule(dataset, 0, 0, 0, False)

    return best_schedule