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
        longcnt = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            dur = durs[i]
            rem[i] = rem[i + 1] + dur
            mx[i] = mx[i + 1] if mx[i + 1] >= dur else dur
            add = dur if ws in _SINGLE_WS else 0
            bott[i] = bott[i + 1] + add
            singles[i] = singles[i + 1] + (1 if ws in _SINGLE_WS else 0)
            longcnt[i] = longcnt[i + 1] + (1 if dur >= 300 else 0)
            crit[i] = crit[i + 1] + (dur if dur >= 20 or add else 0)
        has_muffle = any(str(s.get("workstation")) == "muffle_furnace" for s in steps)
        has_dryer = any(str(s.get("workstation")) == "dryer_workstation" for s in steps)
        has_ecat = any("electrocatalysis" in str(s.get("workstation")) for s in steps)
        has_xrd = any("xrd" in str(s.get("workstation")) for s in steps)
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
            "longcnt": longcnt,
            "name": task.get("name"),
            "expr": task.get("expr_no"),
            "has_muffle": has_muffle,
            "has_dryer": has_dryer,
            "has_ecat": has_ecat,
            "has_xrd": has_xrd,
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


def _best_pair(robots, robot_available, slots, ready, pair_mode):
    best_r = robots[0]
    best_s = 0
    best_st = None
    best_key = None
    for ri, r in enumerate(robots):
        ra = robot_available[r]
        base = ready if ready >= ra else ra
        for si, sa in enumerate(slots):
            st = base if base >= sa else sa
            if pair_mode == 1:
                key = (st, -ra, -sa, ri, si)
            elif pair_mode == 2:
                key = (st, abs(ra - ready), -ra, ri, si)
            elif pair_mode == 3:
                key = (st, -sa, -ra, ri, si)
            else:
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
    single = 1 if ws in _SINGLE_WS else 0
    longop = 1 if dur >= 300 else 0
    ecat = 1 if "electrocatalysis" in ws else 0
    xrd = 1 if "xrd" in ws else 0
    muffle = 1 if ws == "muffle_furnace" else 0
    dryer = 1 if ws == "dryer_workstation" else 0
    stir720 = 1 if ws == "magnetic_stirring" and dur >= 300 else 0
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
        return (-longop, -rem, -bott, -dur, ti)
    if mode == 11:
        return (-single, -crit, -rem, -mx, ti)
    if mode == 12:
        return (-dur, -rem, -bott, ti)
    if mode == 13:
        return (-dur, -mx, -rem, -crit, ti)
    if mode == 14:
        return (-crit, -dur, -rem, -bott, ti)
    if mode == 16:
        return (-muffle, -stir720, -dryer, -longop, -rem, -dur, ti)
    if mode == 17:
        return (-stir720, -muffle, -dryer, -longop, -rem, ti)
    if mode == 18:
        return (-muffle, -dryer, -stir720, -rem, -bott, ti)
    if mode == 19:
        return (-t["longcnt"][i], -longop, -rem, -crit, ti)
    if mode == 20:
        return (-t["singles"][i], -bott, -rem, -dur, ti)
    return (-rem, -dur, ti)


def _schedule(tasks, robots, caps, mode, window, pair_mode):
    workstation_slots = {}
    for k, c in caps.items():
        workstation_slots[k] = [0] * max(1, int(c))

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
            robot, slot_idx, st = _best_pair(robots, robot_available, slots, ready[ti], pair_mode)
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
            if mode == 8:
                key = (end, -t["rem"][i], -t["mx"][i], -t["bott"][i], -dur, ti)
            elif mode == 9:
                key = (st, end, -t["rem"][i], -dur, ti)
            elif mode == 12:
                key = (st, -dur, -t["rem"][i], -t["bott"][i], ti)
            elif mode == 15:
                ra = robot_available[robot]
                key = (ra, st, -dur, -t["rem"][i], ti)
            elif mode == 21:
                loads = []
                for r in robots:
                    loads.append(end if r == robot else robot_available[r])
                key = (st, max(loads), min(loads), -dur, -t["rem"][i], ti)
            elif mode == 22:
                loads = []
                for r in robots:
                    loads.append(end if r == robot else robot_available[r])
                spread = max(loads) - min(loads)
                key = (st, spread, -t["rem"][i], -dur, ti)
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
        return sorted(tasks, key=lambda t: (str(t["steps"][0].get("workstation")), -t["rem"][0], t["task_index"]))
    if variant == 5:
        return sorted(tasks, key=lambda t: (-t["crit"][0], -t["rem"][0], t["task_index"]))
    if variant == 6:
        return sorted(tasks, key=lambda t: (-sum(1 for s in t["steps"] if str(s.get("workstation")) in _SINGLE_WS), -t["rem"][0], t["task_index"]))
    if variant == 7:
        return sorted(tasks, key=lambda t: (t["task_index"] % 3, -t["rem"][0], t["task_index"]))
    if variant == 8:
        return sorted(tasks, key=lambda t: (0 if t["has_muffle"] else 1, -t["rem"][0], t["task_index"]))
    if variant == 9:
        return sorted(tasks, key=lambda t: (0 if (not t["has_muffle"] and t["mx"][0] >= 720) else (1 if t["has_muffle"] else 2), -t["rem"][0], t["task_index"]))
    if variant == 10:
        return sorted(tasks, key=lambda t: (0 if t["has_muffle"] else (1 if t["has_dryer"] else 2), -t["rem"][0], t["task_index"]))
    if variant == 11:
        return sorted(tasks, key=lambda t: (0 if t["has_dryer"] else (1 if t["has_muffle"] else 2), -t["rem"][0], t["task_index"]))
    if variant == 12:
        return sorted(tasks, key=lambda t: (0 if t["mx"][0] >= 720 else (1 if t["has_muffle"] else 2), -t["rem"][0], t["task_index"]))
    return tasks


def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    base_tasks = _prepare(dataset)
    lb = _lower_bound(base_tasks, robots, caps)

    core = [0, 4, 2, 1, 3, 10, 11, 12, 13, 14, 7, 16, 17, 18, 19, 20, 21, 22, 8, 9, 15]
    variants = [0, 1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 7]
    windows = [0, 1, 2, 3, 5, 8, 13, 21]
    pair_modes = [1, 0, 2, 3]

    trials = []
    for pm in pair_modes:
        for m in core:
            trials.append((m, 0, 0, pm))
    for v in variants:
        for m in [0, 4, 2, 3, 10, 16, 17, 18, 19, 20]:
            trials.append((m, 0, v, 1))
            trials.append((m, 0, v, 0))
    for w in windows[1:]:
        for m in [0, 4, 2, 3, 10, 12, 14, 16, 17, 18, 21, 22]:
            trials.append((m, w, 0, 1))
    for v in [8, 9, 10, 11, 12, 3, 5]:
        for w in [1, 2, 3, 5, 8]:
            for m in [0, 4, 10, 16, 17, 18, 21]:
                trials.append((m, w, v, 1))

    seen = set()
    unique_trials = []
    for tr in trials:
        if tr not in seen:
            seen.add(tr)
            unique_trials.append(tr)

    best_schedule = None
    best_makespan = None
    task_cache = {0: base_tasks}

    for mode, window, variant, pair_mode in unique_trials:
        tasks = task_cache.get(variant)
        if tasks is None:
            tasks = _reordered_tasks(base_tasks, variant)
            task_cache[variant] = tasks
        schedule, makespan = _schedule(tasks, robots, caps, mode, window, pair_mode)
        if best_makespan is None or makespan < best_makespan:
            best_makespan = makespan
            best_schedule = schedule
            if makespan <= lb:
                break

    return best_schedule