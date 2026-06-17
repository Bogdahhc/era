def _duration(step):
    value = step.get("time", step.get("duration"))
    if value is None:
        return 3
    try:
        return int(value)
    except Exception:
        return 3


def _step_index(step):
    value = step.get("index", step.get("step_index"))
    try:
        return int(value)
    except Exception:
        return 0


def _robots(dataset):
    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, dict):
            code = r.get("code") or r.get("name")
            typ = r.get("workstationType") or r.get("type")
            if code and (r.get("isRobot", True) or typ == "robot" or code.startswith("robot_") or code == "robot_platform"):
                robots.append(code)
        elif isinstance(r, str):
            robots.append(r)
    if not robots:
        for ws in dataset.get("workstation_list", []):
            code = ws.get("code")
            typ = ws.get("workstationType") or ws.get("type")
            if code and (ws.get("isRobot") or typ == "robot" or code.startswith("robot_") or code == "robot_platform"):
                robots.append(code)
    seen = set()
    ans = []
    for r in robots:
        if r not in seen:
            seen.add(r)
            ans.append(r)
    return ans or ["robot_0"]


def _capacities(dataset):
    result = {}
    type_caps = {}
    for ws in dataset.get("workstation_list", []):
        code = ws.get("code")
        typ = ws.get("workstationType") or ws.get("type")
        cap = ws.get("bottleSlotCount", ws.get("capacity", 1))
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            result[code] = cap
        if typ and typ not in type_caps:
            type_caps[typ] = cap
    for typ, cap in type_caps.items():
        result.setdefault(typ, cap)
    return result


def _prepare_tasks(dataset):
    tasks = []
    for pos, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(task.get("steps", []), key=_step_index)
        durs = [_duration(s) for s in steps]
        rem = [0] * (len(steps) + 1)
        bott = [0] * (len(steps) + 1)
        for i in range(len(steps) - 1, -1, -1):
            rem[i] = rem[i + 1] + durs[i]
        tasks.append(
            {
                "pos": pos,
                "name": task.get("name"),
                "expr_no": task.get("expr_no", task.get("name", str(pos))),
                "steps": steps,
                "durations": durs,
                "remaining": rem,
                "bott_tail": bott,
                "count": len(steps),
                "total": rem[0],
            }
        )
    return tasks


def _workstation_loads(tasks, capacities):
    loads = {}
    for t in tasks:
        for s, d in zip(t["steps"], t["durations"]):
            ws = s.get("workstation")
            loads[ws] = loads.get(ws, 0) + d
    pressure = {}
    for ws, load in loads.items():
        pressure[ws] = float(load) / max(1, capacities.get(ws, 1))
    for t in tasks:
        tail = 0.0
        bt = [0.0] * (t["count"] + 1)
        for i in range(t["count"] - 1, -1, -1):
            ws = t["steps"][i].get("workstation")
            tail += t["durations"][i] * pressure.get(ws, 0.0)
            bt[i] = tail
        t["bott_tail"] = bt
    return pressure, loads


def _lower_bound(tasks, robots, capacities, loads):
    total = 0
    cp = 0
    for t in tasks:
        total += t["remaining"][0]
        if t["remaining"][0] > cp:
            cp = t["remaining"][0]
    nrob = max(1, len(robots))
    lb = (total + nrob - 1) // nrob
    if cp > lb:
        lb = cp
    for ws, load in loads.items():
        cap = max(1, capacities.get(ws, 1))
        wlb = (load + cap - 1) // cap
        if wlb > lb:
            lb = wlb
    return lb


def _assignment(task_ready, ws_slots, robot_available, robots, duration, balance=False):
    best = None
    for si, sa in enumerate(ws_slots):
        base = task_ready if task_ready >= sa else sa
        for r in robots:
            ra = robot_available[r]
            st = base if base >= ra else ra
            en = st + duration
            if balance:
                item = (en, st, robot_available[r], si, r)
            else:
                item = (en, st, si, r)
            if best is None or item < best:
                best = item
    return best[1], best[0], best[-2], best[-1]


def _variant_key(mode, start, end, task, step_pos, duration, workstation, pressure, order_rank):
    remaining = task["remaining"][step_pos]
    tail = task["remaining"][step_pos + 1]
    bott_tail = task["bott_tail"][step_pos]
    bottleneck = pressure.get(workstation, 0.0)
    pos = task["pos"]
    rank = order_rank[pos]
    if mode == 0:
        return (start, -remaining, -bottleneck, -duration, rank)
    if mode == 1:
        return (start, -bottleneck, -remaining, -duration, rank)
    if mode == 2:
        return (start, end, -remaining, -bottleneck, rank)
    if mode == 3:
        return (start, -duration, -remaining, -bottleneck, rank)
    if mode == 4:
        return (start, -tail, -bottleneck, -duration, rank)
    if mode == 5:
        return (start, rank, -remaining, -bottleneck)
    if mode == 6:
        return (start, -bottleneck, -tail, end, rank)
    if mode == 7:
        return (start, -bott_tail, -remaining, -duration, rank)
    if mode == 8:
        return (end, start, -remaining, -bott_tail, rank)
    if mode == 9:
        return (start, -(remaining + int(bottleneck)), end, rank)
    return (start, -remaining, rank)


def _make_order(tasks, kind):
    indexed = list(range(len(tasks)))
    if kind == 0:
        indexed.sort(key=lambda i: tasks[i]["pos"])
    elif kind == 1:
        indexed.sort(key=lambda i: (-tasks[i]["remaining"][0], tasks[i]["pos"]))
    elif kind == 2:
        indexed.sort(key=lambda i: (tasks[i]["count"], -tasks[i]["remaining"][0], tasks[i]["pos"]))
    elif kind == 3:
        indexed.sort(key=lambda i: (-tasks[i]["count"], -tasks[i]["remaining"][0], tasks[i]["pos"]))
    elif kind == 4:
        indexed.sort(key=lambda i: (tasks[i]["expr_no"], tasks[i]["pos"]))
    elif kind == 5:
        indexed.sort(key=lambda i: (-tasks[i]["durations"][0] if tasks[i]["durations"] else 0, -tasks[i]["remaining"][0], tasks[i]["pos"]))
    else:
        indexed.sort(key=lambda i: (-tasks[i]["bott_tail"][0], -tasks[i]["remaining"][0], tasks[i]["pos"]))
    return {idx: rank for rank, idx in enumerate(indexed)}


def _schedule_once(tasks, robots, capacities, pressure, mode, order_kind, balance=False):
    order_rank = _make_order(tasks, order_kind)
    workstation_slots = {}
    for ws, cap in capacities.items():
        if ws is not None:
            workstation_slots[ws] = [0] * max(1, cap)
    robot_available = {r: 0 for r in robots}
    task_ready = [0] * len(tasks)
    next_step = [0] * len(tasks)
    operations = []
    total_steps = sum(t["count"] for t in tasks)

    while len(operations) < total_steps:
        best = None
        for ti, task in enumerate(tasks):
            sp = next_step[ti]
            if sp >= task["count"]:
                continue
            step = task["steps"][sp]
            ws = step.get("workstation")
            dur = task["durations"][sp]
            slots = workstation_slots.get(ws)
            if slots is None:
                slots = [0] * max(1, capacities.get(ws, 1))
                workstation_slots[ws] = slots
            st, en, slot_index, robot = _assignment(task_ready[ti], slots, robot_available, robots, dur, balance)
            key = _variant_key(mode, st, en, task, sp, dur, ws, pressure, order_rank)
            candidate = (key, ti, sp, st, en, slot_index, robot)
            if best is None or candidate < best:
                best = candidate

        if best is None:
            break

        _, ti, sp, st, en, slot_index, robot = best
        task = tasks[ti]
        step = task["steps"][sp]
        ws = step.get("workstation")
        workstation_slots[ws][slot_index] = en
        robot_available[robot] = en
        task_ready[ti] = en
        next_step[ti] += 1
        operations.append(
            {
                "expr_no": task["expr_no"],
                "task_name": task["name"],
                "step_index": _step_index(step),
                "workstation": ws,
                "robot": robot,
                "start": int(st),
                "end": int(en),
            }
        )

    makespan = 0
    for op in operations:
        if op["end"] > makespan:
            makespan = op["end"]
    return makespan, operations


def _left_shift_same_sequence(operations, tasks, robots, capacities, balance=False):
    dur_map = {}
    for t in tasks:
        expr = t["expr_no"]
        for s, d in zip(t["steps"], t["durations"]):
            dur_map[(expr, _step_index(s))] = d

    workstation_slots = {}
    for ws, cap in capacities.items():
        if ws is not None:
            workstation_slots[ws] = [0] * max(1, cap)
    robot_available = {r: 0 for r in robots}
    task_ready = {t["expr_no"]: 0 for t in tasks}
    shifted = []

    for op in sorted(operations, key=lambda x: (x["start"], x["end"], x["expr_no"], x["step_index"])):
        expr = op["expr_no"]
        ws = op["workstation"]
        idx = int(op["step_index"])
        dur = dur_map.get((expr, idx), max(3, int(op["end"] - op["start"])))
        slots = workstation_slots.get(ws)
        if slots is None:
            slots = [0] * max(1, capacities.get(ws, 1))
            workstation_slots[ws] = slots
        st, en, slot_index, robot = _assignment(task_ready.get(expr, 0), slots, robot_available, robots, dur, balance)
        slots[slot_index] = en
        robot_available[robot] = en
        task_ready[expr] = en
        newop = dict(op)
        newop["robot"] = robot
        newop["start"] = int(st)
        newop["end"] = int(en)
        shifted.append(newop)

    makespan = 0
    for op in shifted:
        if op["end"] > makespan:
            makespan = op["end"]
    return makespan, shifted


def solve(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    tasks = _prepare_tasks(dataset)
    pressure, loads = _workstation_loads(tasks, capacities)
    lower_bound = _lower_bound(tasks, robots, capacities, loads)

    best_makespan = None
    best_operations = None

    variants = []
    preferred = [(0, 1), (1, 1), (7, 1), (0, 2), (1, 2), (7, 2), (2, 1), (6, 1), (8, 1)]
    seen = set()
    for v in preferred:
        variants.append(v)
        seen.add(v)
    for mode in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9):
        for order_kind in (0, 1, 2, 3, 4, 5, 6):
            if (mode, order_kind) not in seen:
                variants.append((mode, order_kind))
                seen.add((mode, order_kind))

    for mode, order_kind in variants:
        for balance in (False, True) if mode in (0, 1, 7, 8) else (False,):
            makespan, operations = _schedule_once(tasks, robots, capacities, pressure, mode, order_kind, balance)
            if makespan > lower_bound:
                makespan2, operations2 = _left_shift_same_sequence(operations, tasks, robots, capacities, balance)
                if makespan2 <= makespan:
                    makespan, operations = makespan2, operations2
            if best_makespan is None or makespan < best_makespan:
                best_makespan = makespan
                best_operations = operations
                if best_makespan <= lower_bound:
                    best_operations.sort(key=lambda x: (x["start"], x["end"], x["expr_no"], x["step_index"]))
                    return {"operations": best_operations}

    best_operations.sort(key=lambda x: (x["start"], x["end"], x["expr_no"], x["step_index"]))
    return {"operations": best_operations}