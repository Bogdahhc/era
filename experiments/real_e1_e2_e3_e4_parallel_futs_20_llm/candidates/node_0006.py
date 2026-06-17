def _step_index(step):
    v = step.get("step_index", step.get("index", 0))
    try:
        return int(v)
    except Exception:
        return 0


def _duration(step):
    v = step.get("time", None)
    if v is None:
        v = step.get("duration", 3)
    if v is None:
        v = 3
    try:
        f = float(v)
        if int(f) == f:
            return int(f)
        return f
    except Exception:
        return 3


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
        code = ws.get("code") or ws.get("name")
        typ = ws.get("type") or ws.get("workstationType")
        cap = ws.get("bottleSlotCount", None)
        if cap is None:
            cap = ws.get("capacity", 1)
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            caps[str(code)] = cap
        if typ and str(typ) not in caps:
            caps[str(typ)] = cap
    return caps


def _prepare(dataset):
    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(list(task.get("steps", [])), key=_step_index)
        durs = [_duration(s) for s in steps]
        n = len(steps)
        rem = [0] * (n + 1)
        mx = [0] * (n + 1)
        bott = [0] * (n + 1)
        crit = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            dur = durs[i]
            rem[i] = rem[i + 1] + dur
            mx[i] = max(mx[i + 1], dur)
            add = dur if ws in (
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
            bott[i] = bott[i + 1] + add
            crit[i] = crit[i + 1] + (dur if dur >= 20 or add else 0)
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "mx": mx,
            "bott": bott,
            "crit": crit,
        })
    return tasks


def _best_pair(robots, robot_available, slots, ready):
    best_r = robots[0]
    best_s = 0
    best_st = None
    best_key = None
    for ri, r in enumerate(robots):
        ra = robot_available[r]
        base = ready if ready >= ra else ra
        for si, sa in enumerate(slots):
            st = base if base >= sa else sa
            key = (st, ra, sa, ri, si)
            if best_key is None or key < best_key:
                best_key = key
                best_r = r
                best_s = si
                best_st = st
    return best_r, best_s, best_st


def _priority(t, i, dur, ws, mode):
    ti = t["task_index"]
    rem = t["rem"][i]
    mx = t["mx"][i]
    bott = t["bott"][i]
    crit = t["crit"][i]
    single = 1 if ws in (
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
    longop = 1 if dur >= 300 else 0
    ecat = 1 if "electrocatalysis" in ws else 0
    xrd = 1 if "xrd" in ws else 0

    if mode == 0:
        return (-rem, -mx, -bott, -dur, ti)
    if mode == 1:
        return (-mx, -rem, -bott, -dur, ti)
    if mode == 2:
        return (-bott, -rem, -mx, -dur, ti)
    if mode == 3:
        return (-longop, -single, -rem, -mx, ti)
    if mode == 4:
        return (-crit, -rem, -bott, -mx, ti)
    if mode == 5:
        return (-rem, -ecat, -bott, -dur, ti)
    if mode == 6:
        return (-rem, -xrd, -bott, -dur, ti)
    if mode == 7:
        return (-single, -bott, -rem, -dur, ti)
    if mode == 10:
        return (-longop, -rem, -crit, -bott, ti)
    if mode == 11:
        return (-crit, -longop, -rem, -dur, ti)
    return (-rem, -dur, ti)


def _schedule(tasks, robots, caps, mode, window):
    workstation_slots = {k: [0] * max(1, int(c)) for k, c in caps.items()}
    robot_available = {r: 0 for r in robots}
    ready = [0] * len(tasks)
    next_i = [0] * len(tasks)
    remaining = sum(len(t["steps"]) for t in tasks)
    operations = []

    while remaining:
        candidates = []
        min_st = None

        for ti, t in enumerate(tasks):
            i = next_i[ti]
            if i >= len(t["steps"]):
                continue
            step = t["steps"][i]
            ws = str(step.get("workstation"))
            dur = t["durs"][i]
            slots = workstation_slots.get(ws)
            if slots is None:
                slots = [0] * max(1, int(caps.get(ws, 1)))
                workstation_slots[ws] = slots
            robot, slot_idx, st = _best_pair(robots, robot_available, slots, ready[ti])
            if min_st is None or st < min_st:
                min_st = st
            candidates.append((ti, i, step, ws, dur, robot, slot_idx, st))

        lim = min_st + window
        best_key = None
        best = None

        for cand in candidates:
            ti, i, step, ws, dur, robot, slot_idx, st = cand
            if st > lim:
                continue
            t = tasks[ti]
            end = st + dur
            if mode == 8:
                key = (end, -t["rem"][i], -t["mx"][i], -dur, ti)
            elif mode == 9:
                key = (st, end, -t["rem"][i], -dur, ti)
            elif mode == 12:
                key = (st, robot_available[robot], -t["rem"][i], -dur, ti)
            else:
                key = (st, _priority(t, i, dur, ws, mode))
            if best_key is None or key < best_key:
                best_key = key
                best = cand

        if best is None:
            best = min(candidates, key=lambda c: (c[7], c[0]))

        ti, i, step, ws, dur, robot, slot_idx, st = best
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


def _lower_bound(tasks, robots, caps):
    total = 0
    ws_load = {}
    max_chain = 0
    for t in tasks:
        chain = 0
        for step, dur in zip(t["steps"], t["durs"]):
            total += dur
            chain += dur
            ws = str(step.get("workstation"))
            ws_load[ws] = ws_load.get(ws, 0) + dur
        if chain > max_chain:
            max_chain = chain

    lb = total / max(1, len(robots))
    if max_chain > lb:
        lb = max_chain
    for ws, load in ws_load.items():
        cap = max(1, int(caps.get(ws, 1)))
        val = load / cap
        if val > lb:
            lb = val
    return int(lb) if int(lb) == lb else int(lb) + 1


def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    tasks = _prepare(dataset)
    lb = _lower_bound(tasks, robots, caps)

    trials = (
        (0, 0), (4, 0), (2, 0), (1, 0), (3, 0), (10, 0), (11, 0),
        (5, 0), (6, 0), (7, 0), (8, 0), (9, 0), (12, 0),
        (0, 1), (4, 1), (2, 1), (1, 1), (3, 1), (7, 1), (10, 1), (11, 1),
        (0, 2), (4, 2), (2, 2), (1, 2), (3, 2), (10, 2),
        (0, 3), (4, 3), (2, 3), (1, 3), (3, 3), (5, 3), (6, 3), (11, 3),
        (0, 5), (4, 5), (2, 5), (1, 5), (3, 5), (10, 5),
        (0, 8), (2, 8), (1, 8), (4, 8),
        (0, 13), (2, 13), (4, 13),
    )

    best_schedule = None
    best_makespan = None

    for mode, window in trials:
        sched, ms = _schedule(tasks, robots, caps, mode, window)
        if best_makespan is None or ms < best_makespan:
            best_makespan = ms
            best_schedule = sched
            if ms <= lb:
                break

    return best_schedule