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
        return 3
    try:
        f = float(v)
        return int(f) if int(f) == f else f
    except Exception:
        return 3


def _robots(dataset):
    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, dict):
            code = r.get("code") or r.get("name") or r.get("id")
            if code and r.get("isRobot", True):
                robots.append(str(code))
        elif r is not None:
            robots.append(str(r))
    if not robots:
        robots = ["robot_0"]
    out = []
    seen = set()
    for r in robots:
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
        typ = ws.get("type") or ws.get("workstationType")
        cap = ws.get("bottleSlotCount", ws.get("capacity", 1))
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


_SINGLE_WS = {
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
        singles = [0] * (n + 1)
        ecat = [0] * (n + 1)
        xrd = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            dur = durs[i]
            single = 1 if ws in _SINGLE_WS else 0
            rem[i] = rem[i + 1] + dur
            mx[i] = mx[i + 1] if mx[i + 1] >= dur else dur
            bott[i] = bott[i + 1] + (dur if single else 0)
            crit[i] = crit[i + 1] + (dur if dur >= 20 or single else 0)
            singles[i] = singles[i + 1] + single
            ecat[i] = ecat[i + 1] + (dur if "electrocatalysis" in ws else 0)
            xrd[i] = xrd[i + 1] + (dur if "xrd" in ws else 0)
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "mx": mx,
            "bott": bott,
            "crit": crit,
            "singles": singles,
            "ecat": ecat,
            "xrd": xrd,
            "name": task.get("name"),
            "expr": task.get("expr_no"),
            "total": rem[0],
        })
    return tasks


def _lower_bound(tasks, robots, caps):
    total = 0
    chain = 0
    ws_load = {}
    for t in tasks:
        s = 0
        for step, dur in zip(t["steps"], t["durs"]):
            total += dur
            s += dur
            ws = str(step.get("workstation"))
            ws_load[ws] = ws_load.get(ws, 0) + dur
        if s > chain:
            chain = s
    lb = total / max(1, len(robots))
    if chain > lb:
        lb = chain
    for ws, load in ws_load.items():
        cap = max(1, int(caps.get(ws, 1)))
        val = load / cap
        if val > lb:
            lb = val
    return int(lb) if int(lb) == lb else int(lb) + 1


def _earliest_in_two(a, b, ready, dur):
    t = ready
    ia = 0
    ib = 0
    la = len(a)
    lb = len(b)
    while True:
        changed = False
        while ia < la and a[ia][1] <= t:
            ia += 1
        if ia < la and a[ia][0] < t + dur and a[ia][1] > t:
            t = a[ia][1]
            changed = True
            continue
        while ib < lb and b[ib][1] <= t:
            ib += 1
        if ib < lb and b[ib][0] < t + dur and b[ib][1] > t:
            t = b[ib][1]
            changed = True
            continue
        if not changed:
            return t


def _insert_interval(lst, st, en):
    i = len(lst)
    lst.append((st, en))
    while i > 0 and lst[i - 1][0] > st:
        lst[i] = lst[i - 1]
        i -= 1
    lst[i] = (st, en)


def _best_pair_calendar(robots, robot_cal, ws_slots, ready, dur, prefer_load=False):
    best = None
    best_key = None
    for ri, r in enumerate(robots):
        rc = robot_cal[r]
        rload = 0
        if prefer_load:
            for x, y in rc:
                rload += y - x
        for si, sc in enumerate(ws_slots):
            st = _earliest_in_two(rc, sc, ready, dur)
            key = (st, rload, ri, si) if prefer_load else (st, ri, si)
            if best_key is None or key < best_key:
                best_key = key
                best = (r, si, st)
    return best


def _priority(t, i, dur, ws, mode):
    ti = t["task_index"]
    rem = t["rem"][i]
    mx = t["mx"][i]
    bott = t["bott"][i]
    crit = t["crit"][i]
    single = 1 if ws in _SINGLE_WS else 0
    longop = 1 if dur >= 300 else 0
    ecat = t["ecat"][i]
    xrd = t["xrd"][i]
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
    if mode == 8:
        return (-dur, -rem, -bott, ti)
    if mode == 9:
        return (-longop, -rem, -dur, ti)
    if mode == 10:
        return (-t["total"], -rem, -dur, ti)
    if mode == 11:
        return (-t["singles"][i], -bott, -rem, -dur, ti)
    if mode == 12:
        return (-dur, -mx, -rem, -crit, ti)
    if mode == 13:
        return (-crit, -dur, -rem, -bott, ti)
    if mode == 14:
        return (-single, -crit, -rem, -mx, ti)
    if mode == 15:
        return (-ecat, -rem, -dur, ti)
    if mode == 16:
        return (-xrd, -rem, -dur, ti)
    return (-rem, -dur, ti)


def _slot_count(ws, caps, robot_count, task_count):
    c = caps.get(ws, 1)
    try:
        c = int(c)
    except Exception:
        c = 1
    if c < 1:
        c = 1
    m = robot_count
    if task_count < m:
        m = task_count
    return c if c < m else m


def _schedule_calendar(tasks, robots, caps, mode, window, prefer_load=False):
    robot_cal = {r: [] for r in robots}
    workstation_slots = {}
    ready = [0] * len(tasks)
    next_i = [0] * len(tasks)
    remaining = sum(len(t["steps"]) for t in tasks)
    operations = []
    rcount = len(robots)
    tcount = len(tasks)

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
                slots = [[] for _ in range(_slot_count(ws, caps, rcount, tcount))]
                workstation_slots[ws] = slots
            robot, slot_idx, st = _best_pair_calendar(robots, robot_cal, slots, ready[ti], dur, prefer_load)
            if min_st is None or st < min_st:
                min_st = st
            candidates.append((ti, i, step, ws, dur, robot, slot_idx, st))

        lim = min_st + window
        best = None
        best_key = None
        for cand in candidates:
            ti, i, step, ws, dur, robot, slot_idx, st = cand
            if st > lim:
                continue
            t = tasks[ti]
            end = st + dur
            if mode == 20:
                key = (end, -t["rem"][i], -t["mx"][i], -t["bott"][i], -dur, ti)
            elif mode == 21:
                key = (st, end, -dur, -t["rem"][i], ti)
            elif mode == 22:
                key = (st, -dur, -t["rem"][i], -t["bott"][i], ti)
            elif mode == 23:
                key = (end, -dur, -t["crit"][i], -t["rem"][i], ti)
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
        _insert_interval(robot_cal[robot], st, end)
        _insert_interval(workstation_slots[ws][slot_idx], st, end)
        ready[ti] = end
        next_i[ti] += 1
        remaining -= 1

        operations.append({
            "expr_no": t["expr"],
            "task_name": t["name"],
            "step_index": _step_index(step),
            "workstation": ws,
            "robot": robot,
            "start": int(st) if int(st) == st else st,
            "end": int(end) if int(end) == end else end,
        })

    makespan = max((op["end"] for op in operations), default=0)
    return {"operations": operations}, makespan


def _reordered_tasks(tasks, variant):
    if variant == 0:
        return tasks
    if variant == 1:
        return sorted(tasks, key=lambda t: (-t["rem"][0], -t["mx"][0], t["task_index"]))
    if variant == 2:
        return sorted(tasks, key=lambda t: (-t["mx"][0], -t["rem"][0], t["task_index"]))
    if variant == 3:
        return sorted(tasks, key=lambda t: (-t["bott"][0], -t["rem"][0], t["task_index"]))
    if variant == 4:
        return sorted(tasks, key=lambda t: (-t["crit"][0], -t["rem"][0], t["task_index"]))
    if variant == 5:
        return sorted(tasks, key=lambda t: (-t["singles"][0], -t["bott"][0], -t["rem"][0], t["task_index"]))
    if variant == 6:
        return sorted(tasks, key=lambda t: (str(t["steps"][0].get("workstation")), -t["rem"][0], t["task_index"]))
    if variant == 7:
        return sorted(tasks, key=lambda t: (t["task_index"] % 3, -t["rem"][0], t["task_index"]))
    if variant == 8:
        return sorted(tasks, key=lambda t: (t["task_index"] % 2, -t["rem"][0], t["task_index"]))
    if variant == 9:
        return sorted(tasks, key=lambda t: (-t["ecat"][0], -t["rem"][0], t["task_index"]))
    if variant == 10:
        return sorted(tasks, key=lambda t: (-t["xrd"][0], -t["rem"][0], t["task_index"]))
    if variant == 11:
        return sorted(tasks, key=lambda t: (-t["total"], t["task_index"]))
    if variant == 12:
        return sorted(tasks, key=lambda t: (len(t["steps"]), -t["rem"][0], t["task_index"]))
    return tasks


def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    base_tasks = _prepare(dataset)
    lb = _lower_bound(base_tasks, robots, caps)

    best_schedule = None
    best_makespan = None
    task_cache = {0: base_tasks}

    trials = []
    core_modes = [0, 4, 2, 1, 3, 9, 14, 13, 7, 8, 10, 11, 12, 15, 16, 20, 21, 22, 23]
    variants = [0, 1, 2, 3, 4, 5, 9, 10, 7, 8, 11, 12]
    windows = [0, 1, 2, 3, 5, 8, 13, 21, 34]

    for v in variants:
        for m in core_modes[:10]:
            trials.append((m, 0, v, False))
    for w in windows:
        for m in [0, 4, 2, 1, 3, 13, 14, 20, 21, 22, 23]:
            trials.append((m, w, 0, False))
    for v in [0, 1, 2, 3, 4, 5, 9, 10]:
        for w in [0, 3, 8, 21]:
            for m in [0, 4, 2, 13, 20, 22]:
                trials.append((m, w, v, False))
    for v in [0, 1, 3, 4, 5]:
        for w in [0, 5, 13]:
            for m in [0, 4, 2, 20, 22]:
                trials.append((m, w, v, True))

    seen = set()
    for mode, window, variant, prefer_load in trials:
        key = (mode, window, variant, prefer_load)
        if key in seen:
            continue
        seen.add(key)
        tasks = task_cache.get(variant)
        if tasks is None:
            tasks = _reordered_tasks(base_tasks, variant)
            task_cache[variant] = tasks
        schedule, makespan = _schedule_calendar(tasks, robots, caps, mode, window, prefer_load)
        if best_makespan is None or makespan < best_makespan:
            best_makespan = makespan
            best_schedule = schedule
            if makespan <= lb:
                break

    return best_schedule