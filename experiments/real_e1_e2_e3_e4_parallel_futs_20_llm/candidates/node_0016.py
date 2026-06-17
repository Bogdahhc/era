import heapq

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
            rem[i] = rem[i + 1] + dur
            mx[i] = mx[i + 1] if mx[i + 1] >= dur else dur
            add = dur if ws in _SINGLE_WS else 0
            bott[i] = bott[i + 1] + add
            singles[i] = singles[i + 1] + (1 if ws in _SINGLE_WS else 0)
            crit[i] = crit[i + 1] + (dur if dur >= 20 or add else 0)
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
        v = load / cap
        if v > lb:
            lb = v
    return int(lb) if int(lb) == lb else int(lb) + 1

def _best_robot(robots, robot_available, slot_avail, ready):
    best_r = robots[0]
    best_st = None
    best_key = None
    for ri, r in enumerate(robots):
        ra = robot_available[r]
        st = ready
        if ra > st:
            st = ra
        if slot_avail > st:
            st = slot_avail
        key = (st, ra, ri)
        if best_key is None or key < best_key:
            best_key = key
            best_r = r
            best_st = st
    return best_r, best_st

def _priority(t, i, dur, ws, mode):
    ti = t["task_index"]
    single = 1 if ws in _SINGLE_WS else 0
    longop = 1 if dur >= 300 else 0
    if mode == 0:
        return (-t["rem"][i], -t["mx"][i], -t["bott"][i], -dur, ti)
    if mode == 1:
        return (-t["mx"][i], -t["rem"][i], -t["bott"][i], -dur, ti)
    if mode == 2:
        return (-t["bott"][i], -t["rem"][i], -t["mx"][i], -dur, ti)
    if mode == 3:
        return (-longop, -single, -t["rem"][i], -t["mx"][i], ti)
    if mode == 4:
        return (-t["crit"][i], -t["rem"][i], -t["bott"][i], -t["mx"][i], ti)
    if mode == 5:
        return (-t["singles"][i], -t["bott"][i], -t["rem"][i], -dur, ti)
    if mode == 6:
        return (-t["ecat"][i], -t["rem"][i], -t["bott"][i], -dur, ti)
    if mode == 7:
        return (-t["xrd"][i], -t["rem"][i], -t["bott"][i], -dur, ti)
    if mode == 8:
        return (-longop, -t["singles"][i], -t["crit"][i], -t["rem"][i], ti)
    if mode == 9:
        return (-dur, -t["rem"][i], -t["bott"][i], ti)
    if mode == 10:
        return (-t["ecat"][i] - t["xrd"][i], -t["crit"][i], -t["rem"][i], -dur, ti)
    if mode == 11:
        return (-t["bott"][i], -longop, -dur, -t["rem"][i], ti)
    return (-t["rem"][i], -dur, ti)

def _schedule(tasks, robots, caps, mode=0, window=0):
    workstation_heaps = {}
    for k, c in caps.items():
        workstation_heaps[k] = [0] * max(1, int(c))

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
            hp = workstation_heaps.get(ws)
            if hp is None:
                hp = [0] * max(1, int(caps.get(ws, 1)))
                workstation_heaps[ws] = hp
            robot, st = _best_robot(robots, robot_available, hp[0], ready[ti])
            if min_st is None or st < min_st:
                min_st = st
            candidates.append((ti, i, step, ws, dur, robot, st))

        lim = min_st + window
        best = None
        best_key = None

        for ti, i, step, ws, dur, robot, st in candidates:
            if st > lim:
                continue
            t = tasks[ti]
            end = st + dur
            if mode == 12:
                key = (end, -t["rem"][i], -t["mx"][i], -t["bott"][i], -dur, ti)
            elif mode == 13:
                key = (st, end, -t["rem"][i], -dur, ti)
            elif mode == 14:
                key = (robot_available[robot], st, -t["crit"][i], -t["rem"][i], -dur, ti)
            elif mode == 15:
                key = (st, -t["singles"][i], -t["crit"][i], -t["rem"][i], ti)
            elif mode == 16:
                key = (st, -t["ecat"][i] - t["xrd"][i], -t["rem"][i], -dur, ti)
            else:
                key = (st, _priority(t, i, dur, ws, mode))
            if best_key is None or key < best_key:
                best_key = key
                best = (ti, i, step, ws, dur, robot, st)

        if best is None:
            best = min(candidates, key=lambda c: (c[6], c[0]))

        ti, i, step, ws, dur, robot, st = best
        end = st + dur
        t = tasks[ti]

        heapq.heapreplace(workstation_heaps[ws], end)
        robot_available[robot] = end
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
        return sorted(tasks, key=lambda t: (-t["singles"][0], -t["crit"][0], -t["rem"][0], t["task_index"]))
    if variant == 6:
        return sorted(tasks, key=lambda t: (-t["ecat"][0], -t["rem"][0], t["task_index"]))
    if variant == 7:
        return sorted(tasks, key=lambda t: (-t["xrd"][0], -t["rem"][0], t["task_index"]))
    if variant == 8:
        return sorted(tasks, key=lambda t: (-t["ecat"][0] - t["xrd"][0], -t["crit"][0], -t["rem"][0], t["task_index"]))
    if variant == 9:
        return sorted(tasks, key=lambda t: (-sum(t["durs"]), -t["crit"][0], t["task_index"]))
    if variant == 10:
        return sorted(tasks, key=lambda t: (-t["mx"][0], -t["singles"][0], -t["crit"][0], t["task_index"]))
    if variant == 11:
        return sorted(tasks, key=lambda t: (t["task_index"] % 3, -t["rem"][0], t["task_index"]))
    return tasks

def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    base_tasks = _prepare(dataset)
    lb = _lower_bound(base_tasks, robots, caps)

    trials = (
        (0, 0, 0), (4, 0, 0), (2, 0, 0), (1, 0, 0), (3, 0, 0),
        (5, 0, 0), (8, 0, 0), (11, 0, 0), (14, 0, 0),
        (0, 1, 0), (4, 1, 0), (2, 1, 0), (15, 1, 0),
        (0, 2, 0), (4, 2, 0), (2, 2, 0), (14, 2, 0),
        (0, 3, 0), (4, 3, 0), (2, 3, 0),
        (12, 0, 0), (13, 0, 0), (16, 0, 0),
        (0, 0, 1), (4, 0, 1), (2, 0, 1),
        (0, 0, 2), (4, 0, 2), (2, 0, 2),
        (0, 0, 3), (4, 0, 3), (2, 0, 3), (11, 0, 3),
        (0, 0, 4), (4, 0, 4), (2, 0, 4), (14, 0, 4),
        (0, 0, 5), (5, 0, 5), (8, 0, 5),
        (6, 0, 6), (7, 0, 7), (10, 0, 8),
        (0, 0, 9), (4, 0, 9), (8, 0, 9),
        (0, 0, 10), (4, 0, 10),
        (0, 5, 0), (4, 5, 0), (2, 5, 0), (14, 5, 0),
        (0, 8, 0), (4, 8, 0), (2, 8, 0),
        (0, 0, 11), (4, 0, 11), (2, 0, 11),
    )

    best_schedule = None
    best_makespan = None
    cache = {0: base_tasks}

    for mode, window, variant in trials:
        tasks = cache.get(variant)
        if tasks is None:
            tasks = _reordered_tasks(base_tasks, variant)
            cache[variant] = tasks
        schedule, makespan = _schedule(tasks, robots, caps, mode, window)
        if best_makespan is None or makespan < best_makespan:
            best_makespan = makespan
            best_schedule = schedule
            if makespan <= lb:
                break

    return best_schedule