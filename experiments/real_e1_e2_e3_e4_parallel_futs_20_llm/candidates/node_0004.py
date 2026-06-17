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
        if f < 3 and step.get("time", None) is None:
            f = 3.0
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
        longcnt = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            dur = durs[i]
            rem[i] = rem[i + 1] + dur
            mx[i] = max(mx[i + 1], dur)
            add = dur if ws in _SINGLE_WS else 0
            bott[i] = bott[i + 1] + add
            crit[i] = crit[i + 1] + (dur if dur >= 20 or add else 0)
            longcnt[i] = longcnt[i + 1] + (1 if dur >= 300 else 0)
        workstations = [str(s.get("workstation")) for s in steps]
        total = rem[0]
        first_long = 999999
        for i, d in enumerate(durs):
            if d >= 300:
                first_long = i
                break
        tasks.append({
            "task": task,
            "task_index": ti,
            "steps": steps,
            "durs": durs,
            "rem": rem,
            "mx": mx,
            "bott": bott,
            "crit": crit,
            "longcnt": longcnt,
            "total": total,
            "first_long": first_long,
            "workstations": workstations,
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
    single = 1 if ws in _SINGLE_WS else 0
    longop = 1 if dur >= 300 else 0
    ecat = 1 if "electrocatalysis" in ws else 0
    xrd = 1 if "xrd" in ws else 0
    liquid = 1 if ws == "liquid_dispensing" else 0
    magnetic_long = 1 if ws == "magnetic_stirring" and dur >= 300 else 0
    furnace = 1 if ws == "muffle_furnace" else 0

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
        return (-magnetic_long, -rem, -dur, ti)
    if mode == 11:
        return (-furnace, -rem, -bott, -dur, ti)
    if mode == 12:
        return (-liquid, -bott, -rem, -dur, ti)
    if mode == 13:
        return (-t["longcnt"][i], -rem, -mx, -dur, ti)
    if mode == 14:
        return (-rem, t["first_long"], -bott, -dur, ti)
    return (-rem, -dur, ti)


def _schedule(dataset, tasks, robots, caps, mode, window, robot_bias=0):
    workstation_slots = {}
    for k, c in caps.items():
        workstation_slots[k] = [0] * max(1, int(c))

    robot_available = {r: 0 for r in robots}
    robot_load = {r: 0 for r in robots}
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

            best = None
            for ri, r in enumerate(robots):
                ra = robot_available[r]
                base = ready[ti] if ready[ti] >= ra else ra
                for si, sa in enumerate(slots):
                    st = base if base >= sa else sa
                    if robot_bias:
                        key = (st, robot_load[r], ra, sa, ri, si)
                    else:
                        key = (st, ra, sa, ri, si)
                    if best is None or key < best[0]:
                        best = (key, r, si, st)
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
            if mode == 8:
                key = (end, -t["rem"][i], -t["mx"][i], -dur, robot_load[robot], ti)
            elif mode == 9:
                key = (st, end, -t["rem"][i], -dur, robot_load[robot], ti)
            elif mode == 15:
                key = (robot_load[robot] + dur, st, -t["rem"][i], -dur, ti)
            elif mode == 16:
                key = (end, robot_load[robot] + dur, -t["crit"][i], -t["rem"][i], ti)
            else:
                key = (st, _priority(t, i, dur, ws, mode), robot_load[robot])
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
        robot_load[robot] += dur
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
    longest_chain = 0
    for t in tasks:
        if t["total"] > longest_chain:
            longest_chain = t["total"]
        for step, dur in zip(t["steps"], t["durs"]):
            total += dur
            ws = str(step.get("workstation"))
            ws_load[ws] = ws_load.get(ws, 0) + dur
    rlb = total / max(1, len(robots))
    wlb = 0
    for ws, load in ws_load.items():
        cap = max(1, int(caps.get(ws, 1)))
        val = load / cap
        if val > wlb:
            wlb = val
    lb = max(rlb, wlb, longest_chain)
    return int(lb) if int(lb) == lb else int(lb) + 1


def _task_orders(tasks):
    orders = []
    n = len(tasks)

    def add(seq):
        seen = set()
        out = []
        for t in seq:
            k = t["task_index"]
            if k not in seen:
                seen.add(k)
                out.append(t)
        if len(out) == n:
            sig = tuple(t["task_index"] for t in out)
            for old in orders:
                if tuple(x["task_index"] for x in old) == sig:
                    return
            orders.append(out)

    add(tasks)
    add(sorted(tasks, key=lambda t: (-t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (-t["mx"][0], -t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (-t["bott"][0], -t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (t["first_long"], -t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (-t["longcnt"][0], -t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (0 if any("muffle_furnace" == w for w in t["workstations"]) else 1, t["task_index"])))
    add(sorted(tasks, key=lambda t: (0 if any("electrocatalysis" in w for w in t["workstations"]) else 1, -t["total"], t["task_index"])))
    add(sorted(tasks, key=lambda t: (0 if any("xrd" in w for w in t["workstations"]) else 1, -t["total"], t["task_index"])))
    add(list(reversed(tasks)))
    return orders


def solve(dataset):
    robots = _robots(dataset)
    caps = _capacities(dataset)
    tasks = _prepare(dataset)
    lb = _lower_bound(tasks, robots, caps)

    trials = (
        (0, 0, 0), (4, 0, 0), (2, 0, 0), (1, 0, 0), (3, 0, 0), (5, 0, 0),
        (6, 0, 0), (7, 0, 0), (8, 0, 0), (9, 0, 0), (10, 0, 0), (11, 0, 0),
        (13, 0, 0), (14, 0, 0), (15, 0, 1), (16, 0, 1),
        (0, 1, 0), (4, 1, 0), (2, 1, 0), (1, 1, 0), (3, 1, 0), (7, 1, 0),
        (10, 1, 0), (13, 1, 0), (15, 1, 1), (16, 1, 1),
        (0, 2, 0), (4, 2, 0), (2, 2, 0), (1, 2, 0), (3, 2, 0), (10, 2, 0),
        (13, 2, 0), (15, 2, 1),
        (0, 3, 0), (4, 3, 0), (2, 3, 0), (1, 3, 0), (3, 3, 0), (5, 3, 0),
        (6, 3, 0), (10, 3, 0), (13, 3, 0), (15, 3, 1), (16, 3, 1),
        (0, 5, 0), (4, 5, 0), (2, 5, 0), (1, 5, 0), (3, 5, 0), (10, 5, 0),
        (13, 5, 0), (15, 5, 1),
        (0, 8, 0), (2, 8, 0), (1, 8, 0), (4, 8, 0), (13, 8, 0), (15, 8, 1),
        (0, 13, 0), (2, 13, 0), (4, 13, 0), (15, 13, 1),
    )

    best_schedule = None
    best_makespan = None

    orders = _task_orders(tasks)
    for oi, ordered_tasks in enumerate(orders):
        for mode, window, rb in trials:
            if oi > 0 and window not in (0, 1, 3, 8):
                continue
            sched, ms = _schedule(dataset, ordered_tasks, robots, caps, mode, window, rb)
            if best_makespan is None or ms < best_makespan:
                best_makespan = ms
                best_schedule = sched
                if ms <= lb:
                    return best_schedule

    return best_schedule