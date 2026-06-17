def solve(dataset):
    def get_code(obj):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return obj.get("code") or obj.get("name") or obj.get("id")
        return None

    def step_index(step):
        try:
            return int(step.get("step_index", step.get("index", 0)))
        except Exception:
            return 0

    def duration(step):
        v = step.get("time", None)
        if v is None:
            v = step.get("duration", None)
        if v is None:
            return 3
        try:
            v = int(v)
        except Exception:
            return 3
        return v if v >= 0 else 3

    def task_steps(task):
        return sorted(task.get("steps", []), key=step_index)

    def task_total(task):
        return sum(duration(s) for s in task_steps(task))

    robots = []
    for r in dataset.get("robot_list", []):
        c = get_code(r)
        if c:
            robots.append(c)

    if not robots:
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
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
        c = w.get("code") or w.get("name")
        t = w.get("type") or w.get("workstationType")
        raw = w.get("bottleSlotCount", None)
        if raw is None:
            raw = w.get("capacity", None)
        try:
            cap = int(raw)
        except Exception:
            cap = 1
        if cap < 1:
            cap = 1
        if c:
            capacities[c] = cap
        if t and t not in capacities:
            capacities[t] = cap

    def capacity_ok(intervals, cap, st, en):
        events = [(st, 1), (en, -1)]
        for a, b in intervals:
            if b > st and a < en:
                events.append((a, 1))
                events.append((b, -1))
        events.sort(key=lambda x: (x[0], x[1]))
        active = 0
        for _, d in events:
            active += d
            if active > cap:
                return False
        return True

    def earliest_ws(intervals, cap, ready, dur):
        if not intervals or cap >= len(intervals) + 1:
            return ready
        candidates = [ready]
        for a, b in intervals:
            if b >= ready:
                candidates.append(b)
        candidates = sorted(set(candidates))
        for st in candidates:
            if capacity_ok(intervals, cap, st, st + dur):
                return st
        st = candidates[-1]
        while True:
            if capacity_ok(intervals, cap, st, st + dur):
                return st
            nxt = None
            for a, b in intervals:
                if b > st and (nxt is None or b < nxt):
                    nxt = b
            if nxt is None or nxt <= st:
                st += 1
            else:
                st = nxt

    tasks = list(dataset.get("task_list", []))
    order = sorted(range(len(tasks)), key=lambda i: (-task_total(tasks[i]), i))

    robot_ready = {r: 0 for r in robots}
    ws_intervals = {}
    operations = []

    for ti in order:
        task = tasks[ti]
        robot = min(robots, key=lambda r: (robot_ready.get(r, 0), robots.index(r)))
        ready = robot_ready.get(robot, 0)
        expr_no = task.get("expr_no")
        task_name = task.get("name")

        for step in task_steps(task):
            ws = step.get("workstation")
            dur = duration(step)
            cap = capacities.get(ws, 1)
            intervals = ws_intervals.setdefault(ws, [])
            st = earliest_ws(intervals, cap, ready, dur)
            en = st + dur
            intervals.append((st, en))
            ready = en
            operations.append({
                "expr_no": expr_no,
                "task_name": task_name,
                "step_index": step_index(step),
                "workstation": ws,
                "robot": robot,
                "start": st,
                "end": en
            })

        robot_ready[robot] = ready

    operations.sort(key=lambda o: (o["start"], o["end"], str(o["robot"]), str(o["expr_no"]), o["step_index"]))
    return {"operations": operations}