import heapq
import time

_SINGLE_WS = {
    "liquid_dispensing", "solid_dispensing", "muffle_furnace", "capping_station",
    "high_flux_electrocatalysis_dripping", "high_flux_electrocatalysis_test",
    "high_flux_electrocatalysis_recycle", "high_flux_xrd_dripping",
    "high_flux_xrd_test", "high_flux_xrd_recycle",
}

def _idx(step):
    try:
        return int(step.get("step_index", step.get("index", 0)))
    except Exception:
        return 0

def _dur(step):
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
    rs = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, dict):
            c = r.get("code") or r.get("name") or r.get("id")
            if c and r.get("isRobot", True):
                rs.append(str(c))
        elif r is not None:
            rs.append(str(r))
    if not rs:
        rs = ["robot_0"]
    out, seen = [], set()
    for r in rs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out

def _caps(dataset):
    c = {}
    for w in dataset.get("workstation_list", []):
        if not isinstance(w, dict):
            continue
        code = w.get("code") or w.get("name")
        typ = w.get("type") or w.get("workstationType")
        cap = w.get("bottleSlotCount", w.get("capacity", 1))
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            c[str(code)] = cap
        if typ and str(typ) not in c:
            c[str(typ)] = cap
    return c

def _prepare(dataset):
    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(list(task.get("steps", [])), key=_idx)
        durs = [_dur(s) for s in steps]
        n = len(steps)
        rem = [0] * (n + 1)
        mx = [0] * (n + 1)
        bott = [0] * (n + 1)
        crit = [0] * (n + 1)
        singles = [0] * (n + 1)
        ecat = [0] * (n + 1)
        xrd = [0] * (n + 1)
        l720 = [0] * (n + 1)
        furnace = [0] * (n + 1)
        for i in range(n - 1, -1, -1):
            ws = str(steps[i].get("workstation"))
            d = durs[i]
            rem[i] = rem[i + 1] + d
            mx[i] = max(mx[i + 1], d)
            is_single = ws in _SINGLE_WS
            bott[i] = bott[i + 1] + (d if is_single else 0)
            crit[i] = crit[i + 1] + (d if d >= 20 or is_single else 0)
            singles[i] = singles[i + 1] + (1 if is_single else 0)
            ecat[i] = ecat[i + 1] + (d if "electrocatalysis" in ws else 0)
            xrd[i] = xrd[i + 1] + (d if "xrd" in ws else 0)
            l720[i] = l720[i + 1] + (d if d >= 700 else 0)
            furnace[i] = furnace[i + 1] + (d if ws == "muffle_furnace" else 0)
        tasks.append({
            "task": task, "task_index": ti, "steps": steps, "durs": durs,
            "rem": rem, "mx": mx, "bott": bott, "crit": crit, "singles": singles,
            "ecat": ecat, "xrd": xrd, "l720": l720, "furnace": furnace,
            "name": task.get("name"), "expr": task.get("expr_no"), "total": rem[0],
        })
    return tasks

def _lb(tasks, robots, caps):
    total = 0
    chain = 0
    load = {}
    for t in tasks:
        s = 0
        for st, d in zip(t["steps"], t["durs"]):
            total += d
            s += d
            ws = str(st.get("workstation"))
            load[ws] = load.get(ws, 0) + d
        chain = max(chain, s)
    b = max(chain, total / max(1, len(robots)))
    for ws, l in load.items():
        b = max(b, l / max(1, int(caps.get(ws, 1))))
    return int(b) if int(b) == b else int(b) + 1

def _reorder(tasks, v):
    if v == 0:
        return tasks
    if v == 1:
        return sorted(tasks, key=lambda t: (-t["rem"][0], -t["mx"][0], t["task_index"]))
    if v == 2:
        return sorted(tasks, key=lambda t: (-t["mx"][0], -t["rem"][0], t["task_index"]))
    if v == 3:
        return sorted(tasks, key=lambda t: (-t["bott"][0], -t["rem"][0], t["task_index"]))
    if v == 4:
        return sorted(tasks, key=lambda t: (-t["crit"][0], -t["rem"][0], t["task_index"]))
    if v == 5:
        return sorted(tasks, key=lambda t: (-t["singles"][0], -t["crit"][0], -t["rem"][0], t["task_index"]))
    if v == 6:
        return sorted(tasks, key=lambda t: (-t["ecat"][0], -t["rem"][0], t["task_index"]))
    if v == 7:
        return sorted(tasks, key=lambda t: (-t["xrd"][0], -t["rem"][0], t["task_index"]))
    if v == 8:
        return sorted(tasks, key=lambda t: (-(t["ecat"][0] + t["xrd"][0]), -t["crit"][0], -t["rem"][0], t["task_index"]))
    if v == 9:
        return sorted(tasks, key=lambda t: (-t["total"], -t["crit"][0], t["task_index"]))
    if v == 10:
        return sorted(tasks, key=lambda t: (-t["mx"][0], -t["singles"][0], -t["crit"][0], t["task_index"]))
    if v == 11:
        return sorted(tasks, key=lambda t: (t["task_index"] % 3, -t["rem"][0], t["task_index"]))
    if v == 12:
        return sorted(tasks, key=lambda t: (-t["l720"][0], -t["furnace"][0], -t["rem"][0], t["task_index"]))
    if v == 13:
        return sorted(tasks, key=lambda t: (-t["furnace"][0], -t["l720"][0], -t["rem"][0], t["task_index"]))
    if v == 14:
        return sorted(tasks, key=lambda t: (-(t["l720"][0] + t["furnace"][0]), -t["mx"][0], t["task_index"]))
    if v == 15:
        return sorted(tasks, key=lambda t: (0 if t["l720"][0] else (1 if t["furnace"][0] else 2), -t["rem"][0], t["task_index"]))
    if v == 16:
        return sorted(tasks, key=lambda t: (0 if t["furnace"][0] else (1 if t["l720"][0] else 2), -t["rem"][0], t["task_index"]))
    if v == 17:
        return sorted(tasks, key=lambda t: (t["task_index"] % 2, -t["mx"][0], -t["rem"][0], t["task_index"]))
    if v == 18:
        return sorted(tasks, key=lambda t: (t["task_index"] % 4, -t["rem"][0], t["task_index"]))
    if v == 19:
        return sorted(tasks, key=lambda t: ((t["task_index"] * 7) % 19, -t["rem"][0], t["task_index"]))
    return sorted(tasks, key=lambda t: ((t["task_index"] * 11) % 23, -t["mx"][0], t["task_index"]))

def _prio(t, i, d, ws, m):
    ti = t["task_index"]
    single = 1 if ws in _SINGLE_WS else 0
    longop = 1 if d >= 300 else 0
    verylong = 1 if d >= 600 else 0
    if m == 0:
        return (-t["rem"][i], -t["mx"][i], -t["bott"][i], -d, ti)
    if m == 1:
        return (-t["mx"][i], -t["rem"][i], -t["bott"][i], -d, ti)
    if m == 2:
        return (-t["bott"][i], -t["rem"][i], -t["mx"][i], -d, ti)
    if m == 3:
        return (-longop, -single, -t["rem"][i], -t["mx"][i], ti)
    if m == 4:
        return (-t["crit"][i], -t["rem"][i], -t["bott"][i], -t["mx"][i], ti)
    if m == 5:
        return (-t["singles"][i], -t["bott"][i], -t["rem"][i], -d, ti)
    if m == 6:
        return (-t["ecat"][i], -t["rem"][i], -t["bott"][i], -d, ti)
    if m == 7:
        return (-t["xrd"][i], -t["rem"][i], -t["bott"][i], -d, ti)
    if m == 8:
        return (-longop, -t["singles"][i], -t["crit"][i], -t["rem"][i], ti)
    if m == 9:
        return (-d, -t["rem"][i], -t["bott"][i], ti)
    if m == 10:
        return (-(t["ecat"][i] + t["xrd"][i]), -t["crit"][i], -t["rem"][i], -d, ti)
    if m == 11:
        return (-t["bott"][i], -longop, -d, -t["rem"][i], ti)
    if m == 17:
        return (-t["l720"][i], -t["furnace"][i], -t["rem"][i], -d, ti)
    if m == 18:
        return (-t["furnace"][i], -t["l720"][i], -t["rem"][i], -d, ti)
    if m == 19:
        return (-verylong, -d, -t["rem"][i], -t["crit"][i], ti)
    if m == 20:
        return (-single, -t["bott"][i], -t["crit"][i], -t["rem"][i], ti)
    if m == 21:
        return (-(t["l720"][i] + t["furnace"][i]), -t["mx"][i], -t["rem"][i], ti)
    if m == 22:
        return (-t["total"], -t["rem"][i], -d, ti)
    if m == 23:
        return (ti % 3, -t["rem"][i], -d, ti)
    if m == 24:
        return (-(d >= 20), -d, -t["rem"][i], ti)
    return (-t["rem"][i], -d, ti)

def _best_robot(robots, rav, slot, ready, rmode):
    br = robots[0]
    bst = None
    bk = None
    for ri, r in enumerate(robots):
        ra = rav[r]
        st = ready
        if ra > st:
            st = ra
        if slot > st:
            st = slot
        if rmode == 1:
            k = (st, -ra, ri)
        elif rmode == 2:
            k = (st, abs(ra - ready), ri)
        else:
            k = (st, ra, ri)
        if bk is None or k < bk:
            bk = k
            br = r
            bst = st
    return br, bst

def _schedule(tasks, robots, caps, mode, window, rmode):
    wh = {k: [0] * max(1, int(v)) for k, v in caps.items()}
    rav = {r: 0 for r in robots}
    ready = [0] * len(tasks)
    nxt = [0] * len(tasks)
    left = sum(len(t["steps"]) for t in tasks)
    ops = []
    while left:
        cand = []
        mn = None
        for ti, t in enumerate(tasks):
            i = nxt[ti]
            if i >= len(t["steps"]):
                continue
            step = t["steps"][i]
            ws = str(step.get("workstation"))
            d = t["durs"][i]
            h = wh.get(ws)
            if h is None:
                h = [0] * max(1, int(caps.get(ws, 1)))
                wh[ws] = h
            rb, st = _best_robot(robots, rav, h[0], ready[ti], rmode)
            if mn is None or st < mn:
                mn = st
            cand.append((ti, i, step, ws, d, rb, st))
        lim = mn + window
        best = None
        bk = None
        for ti, i, step, ws, d, rb, st in cand:
            if st > lim:
                continue
            t = tasks[ti]
            e = st + d
            if mode == 12:
                k = (e, -t["rem"][i], -t["mx"][i], -t["bott"][i], -d, ti)
            elif mode == 13:
                k = (st, e, -t["rem"][i], -d, ti)
            elif mode == 14:
                k = (rav[rb], st, -t["crit"][i], -t["rem"][i], -d, ti)
            elif mode == 15:
                k = (st, -t["singles"][i], -t["crit"][i], -t["rem"][i], ti)
            elif mode == 16:
                k = (st, -(t["ecat"][i] + t["xrd"][i]), -t["rem"][i], -d, ti)
            elif mode == 25:
                k = (st + max(0, 30 - d), -t["l720"][i], -t["furnace"][i], -t["rem"][i], ti)
            else:
                k = (st, _prio(t, i, d, ws, mode))
            if bk is None or k < bk:
                bk = k
                best = (ti, i, step, ws, d, rb, st)
        if best is None:
            best = min(cand, key=lambda x: (x[6], x[0]))
        ti, i, step, ws, d, rb, st = best
        e = st + d
        t = tasks[ti]
        heapq.heapreplace(wh[ws], e)
        rav[rb] = e
        ready[ti] = e
        nxt[ti] += 1
        left -= 1
        ops.append({
            "expr_no": t["expr"],
            "task_name": t["name"],
            "step_index": _idx(step),
            "workstation": ws,
            "robot": rb,
            "start": int(st) if int(st) == st else st,
            "end": int(e) if int(e) == e else e,
        })
    return {"operations": ops}, max((o["end"] for o in ops), default=0)

def solve(dataset):
    t0 = time.time()
    robots = _robots(dataset)
    caps = _caps(dataset)
    base = _prepare(dataset)
    lower = _lb(base, robots, caps)
    best_s = None
    best_m = None
    cache = {0: base}

    trials = [
        (17, 0, 0, 0), (21, 0, 0, 0), (4, 0, 0, 0), (0, 0, 0, 0),
        (17, 5, 15, 1), (21, 8, 14, 2), (14, 3, 13, 0), (2, 2, 12, 0),
        (18, 0, 0, 0), (19, 0, 0, 0), (25, 0, 0, 0), (12, 0, 0, 0),
        (13, 0, 0, 0), (16, 0, 0, 0), (20, 0, 0, 0), (22, 0, 0, 0),
        (0, 1, 0, 0), (4, 1, 0, 0), (17, 1, 0, 0), (21, 1, 0, 0),
        (0, 2, 0, 0), (4, 2, 0, 0), (17, 2, 0, 0), (21, 2, 0, 0),
        (0, 3, 0, 0), (4, 3, 0, 0), (17, 3, 0, 0), (21, 3, 0, 0),
        (0, 5, 0, 0), (4, 5, 0, 0), (17, 5, 0, 0), (21, 5, 0, 0),
    ]

    for v in range(1, 21):
        trials.append((0, 0, v, 0))
        trials.append((4, 0, v, 0))
        trials.append((17, 0, v, 0))
        trials.append((21, 0, v, 0))
        if v in (1, 2, 4, 9, 12, 13, 14, 15, 16):
            trials.append((2, 2, v, 0))
            trials.append((14, 3, v, 0))
            trials.append((17, 5, v, 1))
            trials.append((21, 8, v, 2))

    seen = set()
    for mode, window, variant, rmode in trials:
        key = (mode, window, variant, rmode)
        if key in seen:
            continue
        seen.add(key)
        tasks = cache.get(variant)
        if tasks is None:
            tasks = _reorder(base, variant)
            cache[variant] = tasks
        s, m = _schedule(tasks, robots, caps, mode, window, rmode)
        if best_m is None or m < best_m:
            best_s, best_m = s, m
            if m <= lower:
                return best_s
        if time.time() - t0 > 1.6:
            return best_s

    modes = list(range(26))
    windows = [0, 1, 2, 3, 5, 8, 13, 21, 34]
    for a in range(700):
        if time.time() - t0 > 1.6:
            break
        mode = modes[(a * 7 + 3) % 26]
        window = windows[(a * 5 + a // 7) % len(windows)]
        variant = (a * 11 + 5) % 21
        rmode = (a // 13) % 3
        key = (mode, window, variant, rmode)
        if key in seen:
            continue
        seen.add(key)
        tasks = cache.get(variant)
        if tasks is None:
            tasks = _reorder(base, variant)
            cache[variant] = tasks
        s, m = _schedule(tasks, robots, caps, mode, window, rmode)
        if m < best_m:
            best_s, best_m = s, m
            if m <= lower:
                break
    return best_s