def _step_index(step):
    if "index" in step and step.get("index") is not None:
        return int(step.get("index"))
    if "step_index" in step and step.get("step_index") is not None:
        return int(step.get("step_index"))
    return 0


def _duration(step):
    for key in ("time", "duration"):
        if key in step and step.get(key) is not None:
            try:
                return int(step.get(key))
            except Exception:
                return float(step.get(key))
    return 3


def _robots(dataset):
    result = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, dict):
            code = r.get("code") or r.get("name")
            if code and r.get("isRobot", True):
                result.append(code)
        elif r:
            result.append(str(r))
    if not result:
        result = ["robot_0"]
    seen = set()
    out = []
    for r in result:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _capacities(dataset):
    caps = {}
    for ws in dataset.get("workstation_list", []):
        if not isinstance(ws, dict):
            continue
        code = ws.get("code") or ws.get("name")
        typ = ws.get("workstationType") or ws.get("type")
        cap = ws.get("bottleSlotCount")
        if cap is None:
            cap = ws.get("capacity")
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            caps[code] = cap
        if typ and typ not in caps:
            caps[typ] = cap
    return caps


def _best_pair(robots, robot_available, slots, ready):
    best = None
    for ri, r in enumerate(robots):
        ra = robot_available[r]
        for si, sa in enumerate(slots):
            st = ready
            if ra > st:
                st = ra
            if sa > st:
                st = sa
            key = (st, ra, sa, ri, si)
            if best is None or key < best[0]:
                best = (key, r, si, st)
    return best[1], best[2], best[3]


def _prepare(dataset):
    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        raw_steps = task.get("steps", [])
        steps = sorted(raw_steps, key=_step_index)
        durs = [_duration(s) for s in steps]
        rem = [0] * (len(steps) + 1)
        mx = [0] * (len(steps) + 1)
        bott = [0] * (len(steps) + 1)
        for i in range(len(steps) - 1, -1, -1):
            dur = durs[i]
            ws = steps[i].get("workstation")
            rem[i] = rem[i + 1] + dur
            mx[i] = max(mx[i + 1], dur)
            add = dur if ws in (
                "liquid_dispensing",
                "solid_dispensing",
                "muffle_furnace",
                "high_flux_electrocatalysis_dripping",
                "high_flux_electrocatalysis_test",
                "high_flux_electrocatalysis_recycle",
                "high_flux_xrd_dripping",
                "high_flux_xrd_test",
                "high_flux_xrd_recycle",
                "capping_station",
            ) else 0
            bott[i] = bott[i + 1] + add
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "mx": mx,
            "bott": bott,
        })
    return tasks


def _priority_key(t, i, dur, ws, mode):
    rem = t["rem"][i]
    mx = t["mx"][i]
    bott = t["bott"][i]
    ti = t["task_index"]
    if mode == 0:
        return (-rem, -mx, -bott, -dur, ti)
    if mode == 1:
        return (-mx, -rem, -bott, -dur, ti)
    if mode == 2:
        return (-bott, -rem, -mx, -dur, ti)
    if mode == 3:
        is_long = 1 if dur >= 300 else 0
        is_single = 1 if ws in ("muffle_furnace", "liquid_dispensing", "solid_dispensing") else 0
        return (-is_long, -is_single, -rem, -mx, ti)
    if mode == 4:
        is_ecat = 1 if "electrocatalysis" in str(ws) else 0
        return (-rem, -is_ecat, -bott, -mx, ti)
    return (-rem, -dur, ti)


def _schedule(dataset, mode=0, window=0):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    tasks = _prepare(dataset)

    workstation_slots = {}
    for code, cap in caps.items():
        if code is not None:
            workstation_slots[code] = [0] * max(1, int(cap))

    robot_available = {r: 0 for r in robots}
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
            ws = step.get("workstation")
            dur = t["durs"][i]
            slots = workstation_slots.get(ws)
            if slots is None:
                slots = [0] * max(1, int(caps.get(ws, 1)))
                workstation_slots[ws] = slots
            robot, slot_idx, st = _best_pair(robots, robot_available, slots, ready[ti])
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
            if mode == 5:
                key = (finish, -t["rem"][i], -t["mx"][i], ti)
            elif mode == 6:
                key = (st, finish, -t["rem"][i], -dur, ti)
            else:
                key = (st, _priority_key(t, i, dur, ws, mode))
            if best is None or key < best[0]:
                best = (key, cand)

        if best is None:
            cand = min(candidates, key=lambda c: (c[7], c[0]))
        else:
            cand = best[1]

        ti, i, step, ws, dur, robot, slot_idx, st = cand
        end = st + dur
        t = tasks[ti]
        workstation_slots[ws][slot_idx] = end
        robot_available[robot] = end
        ready[ti] = end
        next_i[ti] += 1
        remaining -= 1

        task = t["task"]
        operations.append({
            "expr_no": task.get("expr_no"),
            "task_name": task.get("name"),
            "step_index": _step_index(step),
            "workstation": ws,
            "robot": robot,
            "start": int(st) if int(st) == st else st,
            "end": int(end) if int(end) == end else end,
        })

    makespan = max((op["end"] for op in operations), default=0)
    return {"operations": operations}, makespan


def solve(dataset):
    best_schedule = None
    best_makespan = None

    trials = [
        (0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0),
        (0, 1), (1, 1), (2, 1), (3, 1),
        (0, 3), (1, 3), (2, 3), (3, 3), (4, 3),
        (0, 6), (1, 6), (2, 6), (3, 6),
        (0, 10), (1, 10), (2, 10),
    ]

    for mode, window in trials:
        sched, ms = _schedule(dataset, mode, window)
        if best_makespan is None or ms < best_makespan:
            best_makespan = ms
            best_schedule = sched

    return best_schedule