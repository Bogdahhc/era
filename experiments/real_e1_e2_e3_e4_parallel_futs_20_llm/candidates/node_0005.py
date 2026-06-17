def _step_index(step):
    v = step.get("step_index", step.get("index", step.get("step", 0)))
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
        if f < 3 and step.get("time", None) is None:
            f = 3.0
        return int(f) if int(f) == f else f
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
        code = ws.get("code") or ws.get("name") or ws.get("id")
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


_SINGLE = {
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
    raw_tasks = dataset.get("task_list", [])
    for ti, task in enumerate(raw_tasks):
        steps = task.get("steps", task.get("step_list", []))
        steps = sorted(list(steps), key=_step_index)
        durs = [_duration(s) for s in steps]
        n = len(steps)
        rem = [0] * (n + 1)
        mx = [0] * (n + 1)
        bott = [0] * (n + 1)
        crit = [0] * (n + 1)
        muffle_rem = [0] * (n + 1)
        ecat_rem = [0] * (n + 1)
        xrd_rem = [0] * (n + 1)
        liquid_rem = [0] * (n + 1)
        long_rem = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            dur = durs[i]
            rem[i] = rem[i + 1] + dur
            mx[i] = max(mx[i + 1], dur)
            add = dur if ws in _SINGLE else 0
            bott[i] = bott[i + 1] + add
            crit[i] = crit[i + 1] + (dur if dur >= 20 or add else 0)
            muffle_rem[i] = muffle_rem[i + 1] + (dur if ws == "muffle_furnace" else 0)
            ecat_rem[i] = ecat_rem[i + 1] + (dur if "electrocatalysis" in ws else 0)
            xrd_rem[i] = xrd_rem[i + 1] + (dur if "xrd" in ws else 0)
            liquid_rem[i] = liquid_rem[i + 1] + (dur if ws == "liquid_dispensing" else 0)
            long_rem[i] = long_rem[i + 1] + (dur if dur >= 300 else 0)
        wss = [str(s.get("workstation")) for s in steps]
        has_muffle = 1 if "muffle_furnace" in wss else 0
        has_720 = 1 if any(d >= 700 for d in durs) else 0
        has_dryer = 1 if "dryer_workstation" in wss else 0
        has_solid = 1 if "solid_dispensing" in wss else 0
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "mx": mx,
            "bott": bott,
            "crit": crit,
            "muffle_rem": muffle_rem,
            "ecat_rem": ecat_rem,
            "xrd_rem": xrd_rem,
            "liquid_rem": liquid_rem,
            "long_rem": long_rem,
            "has_muffle": has_muffle,
            "has_720": has_720,
            "has_dryer": has_dryer,
            "has_solid": has_solid,
            "n": n,
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
    single = 1 if ws in _SINGLE else 0
    longop = 1 if dur >= 300 else 0
    verylong = 1 if dur >= 700 else 0
    muffle_now = 1 if ws == "muffle_furnace" else 0
    muffle_path = t["muffle_rem"][i]
    ecat = t["ecat_rem"][i]
    xrd = t["xrd_rem"][i]
    liquid = t["liquid_rem"][i]
    long_rem = t["long_rem"][i]
    has_muffle = t["has_muffle"]
    has_720 = t["has_720"]
    has_dryer = t["has_dryer"]
    pos = i

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
        return (-muffle_path, -muffle_now, -long_rem, -rem, ti)
    if mode == 11:
        return (-muffle_now, -muffle_path, -verylong, -rem, ti)
    if mode == 12:
        return (-has_muffle, -long_rem, -rem, -bott, ti)
    if mode == 13:
        return (-has_720, -verylong, -rem, -crit, ti)
    if mode == 14:
        return (-long_rem, -muffle_path, -rem, -crit, ti)
    if mode == 15:
        return (-muffle_path, -has_720, -long_rem, -rem, ti)
    if mode == 16:
        return (-has_720, -muffle_path, -long_rem, -rem, ti)
    if mode == 17:
        return (-has_dryer, -long_rem, -rem, -xrd, ti)
    if mode == 18:
        return (-liquid, -bott, -rem, -dur, ti)
    if mode == 19:
        return (-ecat, -xrd, -bott, -rem, ti)
    if mode == 20:
        return (-xrd, -ecat, -bott, -rem, ti)
    if mode == 21:
        return (pos, -rem, -dur, ti)
    if mode == 22:
        return (-dur, -rem, -bott, ti)
    if mode == 23:
        return (-longop, -muffle_path, -has_720, -rem, ti)
    if mode == 24:
        return (-crit, -muffle_path, -has_720, -rem, ti)
    if mode == 25:
        return (-has_muffle, -has_720, -long_rem, -bott, ti)
    if mode == 26:
        return (-has_720, -has_muffle, -long_rem, -bott, ti)
    if mode == 27:
        return (-muffle_path, -bott, -ecat, -xrd, -rem, ti)
    if mode == 28:
        return (-bott, -muffle_path, -long_rem, -rem, ti)
    if mode == 29:
        return (-rem, ti)
    return (-rem, -dur, ti)


def _schedule(dataset, tasks, robots, caps, mode, window, pair_mode=0):
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

            if pair_mode == 0:
                robot, slot_idx, st = _best_pair(robots, robot_available, slots, ready[ti])
            else:
                best = None
                for ri, r in enumerate(robots):
                    ra = robot_available[r]
                    base = ready[ti] if ready[ti] >= ra else ra
                    for si, sa in enumerate(slots):
                        st0 = base if base >= sa else sa
                        slack = abs(ra - sa)
                        if pair_mode == 1:
                            key = (st0, slack, ri, si)
                        elif pair_mode == 2:
                            key = (st0 + dur, st0, slack, ri, si)
                        else:
                            key = (st0, max(ra, sa), ri, si)
                        if best is None or key < best[0]:
                            best = (key, r, si, st0)
                robot, slot_idx, st = best[1], best[2], best[3]

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
            pr = _priority(t, i, dur, ws, mode)
            if mode == 8:
                key = (end, -t["rem"][i], -t["mx"][i], -dur, ti)
            elif mode == 9:
                key = (st, end, -t["rem"][i], -dur, ti)
            elif mode == 30:
                key = (end, pr)
            elif mode == 31:
                key = (st + max(0, 100 - t["rem"][i]) / 1000.0, pr)
            else:
                key = (st, pr)
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
        st_out = int(st) if int(st) == st else st
        end_out = int(end) if int(end) == end else end

        operations.append({
            "expr_no": task.get("expr_no"),
            "task_name": task.get("name"),
            "step_index": _step_index(step),
            "workstation": ws,
            "robot": robot,
            "start": st_out,
            "end": end_out,
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
    rlb = total / max(1, len(robots))
    wlb = 0
    for ws, load in ws_load.items():
        cap = max(1, int(caps.get(ws, 1)))
        val = load / cap
        if val > wlb:
            wlb = val
    lb = max(rlb, wlb, max_chain)
    return int(lb) if int(lb) == lb else int(lb) + 1


def _renumber_sort_key(op):
    return (op["start"], op["end"], str(op.get("robot")), str(op.get("expr_no")), int(op.get("step_index", 0)))


def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    tasks = _prepare(dataset)
    lb = _lower_bound(tasks, robots, caps)

    trials = []
    base_modes = [
        10, 11, 12, 15, 23, 24, 25, 27,
        0, 4, 2, 1, 3, 14, 16, 13, 26,
        5, 6, 7, 17, 18, 19, 20, 22, 28, 8, 9, 21, 29, 30, 31
    ]
    windows = [0, 1, 2, 3, 5, 8, 13, 21]
    for w in windows:
        for m in base_modes:
            trials.append((m, w, 0))
    for w in [0, 2, 5, 13]:
        for m in [10, 11, 12, 15, 23, 24, 0, 4, 14, 16, 13, 26, 28]:
            trials.append((m, w, 1))
    for w in [0, 3, 8]:
        for m in [10, 12, 0, 4, 2, 14, 23, 24]:
            trials.append((m, w, 2))

    best_schedule = None
    best_makespan = None
    seen = set()

    for mode, window, pair_mode in trials:
        key = (mode, window, pair_mode)
        if key in seen:
            continue
        seen.add(key)
        sched, ms = _schedule(dataset, tasks, robots, caps, mode, window, pair_mode)
        if best_makespan is None or ms < best_makespan:
            best_makespan = ms
            best_schedule = sched
            if ms <= lb:
                break

    if best_schedule is None:
        best_schedule, best_makespan = _schedule(dataset, tasks, robots, caps, 0, 0, 0)

    best_schedule["operations"].sort(key=_renumber_sort_key)
    return best_schedule