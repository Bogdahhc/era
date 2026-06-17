def solve(dataset):
    def get_step_index(step):
        try:
            return int(step.get("step_index", step.get("index", 0)))
        except Exception:
            return 0

    def get_duration(step):
        v = step.get("time", None)
        if v is None:
            v = step.get("duration", None)
        if v is None:
            return 3
        try:
            d = int(v)
        except Exception:
            d = 3
        return d if d >= 0 else 3

    def get_steps(task):
        return sorted(task.get("steps", []), key=get_step_index)

    def task_total_duration(task):
        return sum(get_duration(s) for s in get_steps(task))

    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, str):
            robots.append(r)
        elif isinstance(r, dict):
            c = r.get("code") or r.get("name") or r.get("id")
            if c:
                robots.append(c)

    if not robots:
        for w in dataset.get("workstation_list", []):
            if not isinstance(w, dict):
                continue
            c = w.get("code") or w.get("name")
            t = w.get("type") or w.get("workstationType")
            if c and (t == "robot" or w.get("isRobot")):
                robots.append(c)

    if not robots:
        robots = ["robot_0"]

    capacities = {}
    for w in dataset.get("workstation_list", []):
        if not isinstance(w, dict):
            continue
        code = w.get("code") or w.get("name")
        typ = w.get("type") or w.get("workstationType")
        raw = w.get("bottleSlotCount", None)
        if raw is None:
            raw = w.get("capacity", None)
        try:
            cap = int(raw)
        except Exception:
            cap = 1
        if cap < 1:
            cap = 1
        if code:
            capacities[code] = cap
        if typ and typ not in capacities:
            capacities[typ] = cap

    def interval_feasible(intervals, cap, start, end):
        if end <= start:
            return True
        events = [(start, 1), (end, -1)]
        for s, e in intervals:
            if e > start and s < end:
                events.append((s, 1))
                events.append((e, -1))
        events.sort(key=lambda x: (x[0], x[1]))
        active = 0
        for _, delta in events:
            active += delta
            if active > cap:
                return False
        return True

    def earliest_start(robot_intervals, ws_intervals, ws_cap, ready, dur):
        ready = int(ready)
        dur = int(dur)
        candidates = {ready}
        for s, e in robot_intervals:
            if e >= ready:
                candidates.add(e)
        for s, e in ws_intervals:
            if e >= ready:
                candidates.add(e)

        candidates = sorted(candidates)
        for st in candidates:
            en = st + dur
            if interval_feasible(robot_intervals, 1, st, en) and interval_feasible(ws_intervals, ws_cap, st, en):
                return st

        st = candidates[-1] if candidates else ready
        while True:
            en = st + dur
            if interval_feasible(robot_intervals, 1, st, en) and interval_feasible(ws_intervals, ws_cap, st, en):
                return st
            nxt = None
            for s, e in robot_intervals:
                if e > st and (nxt is None or e < nxt):
                    nxt = e
            for s, e in ws_intervals:
                if e > st and (nxt is None or e < nxt):
                    nxt = e
            if nxt is None or nxt <= st:
                st += 1
            else:
                st = nxt

    def simulate_task_on_robot(task, robot, robot_intervals_all, ws_intervals_all):
        local_robot = {r: list(v) for r, v in robot_intervals_all.items()}
        local_ws = {w: list(v) for w, v in ws_intervals_all.items()}
        rints = local_robot.setdefault(robot, [])
        ready = 0
        ops = []
        expr_no = task.get("expr_no")
        task_name = task.get("name")
        for step in get_steps(task):
            ws = step.get("workstation")
            dur = get_duration(step)
            ws_cap = capacities.get(ws, 1)
            wints = local_ws.setdefault(ws, [])
            st = earliest_start(rints, wints, ws_cap, ready, dur)
            en = st + dur
            rints.append((st, en))
            wints.append((st, en))
            ready = en
            ops.append({
                "expr_no": expr_no,
                "task_name": task_name,
                "step_index": get_step_index(step),
                "workstation": ws,
                "robot": robot,
                "start": int(st),
                "end": int(en)
            })
        return ready, ops, local_robot, local_ws

    tasks = list(dataset.get("task_list", []))
    order = sorted(range(len(tasks)), key=lambda i: (-task_total_duration(tasks[i]), i))

    robot_intervals = {r: [] for r in robots}
    ws_intervals = {}
    operations = []

    for ti in order:
        task = tasks[ti]
        best = None
        for ri, robot in enumerate(robots):
            finish, ops, lr, lw = simulate_task_on_robot(task, robot, robot_intervals, ws_intervals)
            current_robot_load_end = max([0] + [e for _, e in robot_intervals.get(robot, [])])
            key = (finish, current_robot_load_end, ri)
            if best is None or key < best[0]:
                best = (key, finish, ops, lr, lw)
        _, _, ops, robot_intervals, ws_intervals = best
        operations.extend(ops)

    operations.sort(key=lambda o: (o["start"], o["end"], str(o["robot"]), str(o["expr_no"]), int(o["step_index"])))
    return {"operations": operations}