def _step_index(step):
    if "step_index" in step:
        return int(step["step_index"])
    if "index" in step:
        return int(step["index"])
    return 0


def _duration(step):
    if step.get("time") is not None:
        return int(step.get("time"))
    if step.get("duration") is not None:
        return int(step.get("duration"))
    return 3


def _robots(dataset):
    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, str):
            robots.append(r)
        elif isinstance(r, dict):
            code = r.get("code") or r.get("name")
            if code and (r.get("isRobot", True) or r.get("type") == "robot"):
                robots.append(code)
    if not robots:
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
                code = w.get("code")
                if code and (w.get("isRobot") or w.get("workstationType") == "robot" or w.get("type") == "robot"):
                    robots.append(code)
    return robots or ["robot_0"]


def _capacities(dataset):
    caps = {}
    for w in dataset.get("workstation_list", []):
        if not isinstance(w, dict):
            continue
        code = w.get("code")
        typ = w.get("workstationType") or w.get("type")
        raw = w.get("bottleSlotCount")
        if raw is None:
            raw = w.get("capacity")
        try:
            cap = int(raw)
        except Exception:
            cap = 1
        cap = max(1, cap)
        if code:
            caps[code] = cap
        if typ and typ not in caps:
            caps[typ] = cap
    return caps


def _copy_intervals(intervals):
    return {k: v[:] for k, v in intervals.items()}


def _can_add(intervals, cap, start, end):
    if end <= start:
        return True
    events = [(start, 1), (end, -1)]
    for s, e in intervals:
        if s < end and e > start:
            events.append((s, 1))
            events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))
    active = 0
    for _, delta in events:
        active += delta
        if active > cap:
            return False
    return True


def _earliest_on_resource(intervals, cap, earliest, duration):
    earliest = float(earliest)
    duration = float(duration)
    if duration <= 0:
        return earliest
    candidates = [earliest]
    for s, e in intervals:
        if e >= earliest:
            candidates.append(float(e))
    candidates = sorted(set(candidates))
    best_seen = None
    for t in candidates:
        if best_seen is not None and t >= best_seen:
            continue
        if _can_add(intervals, cap, t, t + duration):
            return t
    t = max(candidates) if candidates else earliest
    while True:
        nxt = None
        for s, e in intervals:
            if e >= t and (nxt is None or e < nxt):
                nxt = float(e)
        if nxt is None or nxt == t:
            if _can_add(intervals, cap, t, t + duration):
                return t
            t += 1.0
        else:
            t = nxt


def _task_steps(task):
    return sorted(task.get("steps", []), key=_step_index)


def _task_total(task):
    return sum(_duration(s) for s in _task_steps(task))


def _task_longest(task):
    vals = [_duration(s) for s in _task_steps(task)]
    return max(vals) if vals else 0


def _simulate_task(task, robot, robot_start, ws_intervals, capacities):
    local = _copy_intervals(ws_intervals)
    ready = float(robot_start)
    ops = []
    expr_no = task.get("expr_no")
    task_name = task.get("name")
    for step in _task_steps(task):
        ws = step.get("workstation")
        dur = _duration(step)
        cap = max(1, int(capacities.get(ws, 1)))
        arr = local.setdefault(ws, [])
        st = _earliest_on_resource(arr, cap, ready, dur)
        en = st + dur
        arr.append((st, en))
        ready = en
        ops.append({
            "expr_no": expr_no,
            "task_name": task_name,
            "step_index": _step_index(step),
            "workstation": ws,
            "robot": robot,
            "start": int(st) if abs(st - int(st)) < 1e-9 else st,
            "end": int(en) if abs(en - int(en)) < 1e-9 else en,
        })
    return ready, ops, local


def _schedule_order(tasks, robots, capacities, order):
    ws_intervals = {}
    robot_available = {r: 0.0 for r in robots}
    operations = []

    for idx in order:
        task = tasks[idx]
        best = None
        for robot in robots:
            finish, ops, local = _simulate_task(task, robot, robot_available[robot], ws_intervals, capacities)
            key = (finish, robot_available[robot], robots.index(robot))
            if best is None or key < best[0]:
                best = (key, robot, finish, ops, local)
        _, robot, finish, ops, local = best
        ws_intervals = local
        robot_available[robot] = finish
        operations.extend(ops)

    makespan = 0.0
    for op in operations:
        if op["end"] > makespan:
            makespan = float(op["end"])
    return {"operations": operations}, makespan


def _validate(schedule, dataset, capacities, robots):
    ops = schedule.get("operations", [])
    expected = {}
    for task in dataset.get("task_list", []):
        for step in _task_steps(task):
            expected[(task.get("expr_no"), _step_index(step))] = (step.get("workstation"), _duration(step))
    if len(ops) != len(expected):
        return False
    seen = set()
    by_expr = {}
    robot_int = {}
    ws_int = {}
    for op in ops:
        key = (op.get("expr_no"), int(op.get("step_index")))
        if key in seen or key not in expected:
            return False
        seen.add(key)
        ws, dur = expected[key]
        if op.get("workstation") != ws:
            return False
        if float(op.get("end")) - float(op.get("start")) + 1e-9 < dur:
            return False
        by_expr.setdefault(key[0], []).append((key[1], float(op.get("start")), float(op.get("end"))))
        r = op.get("robot")
        if r not in robots:
            return False
        robot_int.setdefault(r, []).append((float(op.get("start")), float(op.get("end"))))
        ws_int.setdefault(ws, []).append((float(op.get("start")), float(op.get("end"))))
    if seen != set(expected.keys()):
        return False
    for arr in by_expr.values():
        arr.sort()
        for i in range(1, len(arr)):
            if arr[i][1] + 1e-9 < arr[i - 1][2]:
                return False
    for arr in robot_int.values():
        arr.sort()
        for i in range(1, len(arr)):
            if arr[i][0] + 1e-9 < arr[i - 1][1]:
                return False
    for ws, arr in ws_int.items():
        cap = max(1, int(capacities.get(ws, 1)))
        events = []
        for s, e in arr:
            events.append((s, 1))
            events.append((e, -1))
        events.sort(key=lambda x: (x[0], x[1]))
        active = 0
        for _, d in events:
            active += d
            if active > cap:
                return False
    return True


def solve(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    tasks = list(dataset.get("task_list", []))
    n = len(tasks)

    base = list(range(n))
    orders = []

    orders.append(sorted(base, key=lambda i: (-_task_total(tasks[i]), i)))
    orders.append(sorted(base, key=lambda i: (-_task_longest(tasks[i]), -_task_total(tasks[i]), i)))
    orders.append(base[:])
    orders.append(list(reversed(base)))
    orders.append(sorted(base, key=lambda i: (_task_total(tasks[i]), i)))

    if n <= 8:
        import itertools
        totals = [_task_total(t) for t in tasks]
        longest_first = sorted(base, key=lambda i: -totals[i])
        perms = [tuple(longest_first)]
        for p in itertools.permutations(base):
            perms.append(p)
            if len(perms) >= 2000:
                break
        for p in perms:
            orders.append(list(p))

    best_schedule = None
    best_makespan = None

    seen_orders = set()
    for order in orders:
        tup = tuple(order)
        if tup in seen_orders:
            continue
        seen_orders.add(tup)
        sched, ms = _schedule_order(tasks, robots, capacities, order)
        if best_schedule is None or ms < best_makespan:
            best_schedule = sched
            best_makespan = ms

    if best_schedule is None:
        best_schedule = {"operations": []}

    if not _validate(best_schedule, dataset, capacities, robots):
        order = sorted(base, key=lambda i: (-_task_total(tasks[i]), i))
        best_schedule, _ = _schedule_order(tasks, robots, capacities, order)

    return best_schedule