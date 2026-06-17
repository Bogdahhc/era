def solve(dataset):
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
            return int(v)
        except Exception:
            return 3

    def task_steps(task):
        return sorted(task.get("steps", []), key=step_index)

    def task_total(task):
        return sum(duration(s) for s in task_steps(task))

    robots = []
    for r in dataset.get("robot_list", []):
        if isinstance(r, str):
            robots.append(r)
        elif isinstance(r, dict):
            c = r.get("code") or r.get("name")
            if c:
                robots.append(c)
    if not robots:
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
                c = w.get("code")
                t = w.get("type") or w.get("workstationType")
                if c and (t == "robot" or w.get("isRobot")):
                    robots.append(c)
    if not robots:
        robots = ["robot_0"]

    capacities = {}
    for w in dataset.get("workstation_list", []):
        if not isinstance(w, dict):
            continue
        c = w.get("code")
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

    def feasible(intervals, cap, start, end):
        if end <= start:
            return True
        events = [(start, 1), (end, -1)]
        for s, e in intervals:
            events.append((s, 1))
            events.append((e, -1))
        events.sort(key=lambda x: (x[0], x[1]))
        active = 0
        for _, d in events:
            active += d
            if active > cap:
                return False
        return True

    def earliest(intervals, cap, ready, dur):
        ready = int(ready)
        dur = int(dur)
        candidates = [ready]
        for s, e in intervals:
            if e >= ready:
                candidates.append(e)
        candidates = sorted(set(candidates))
        for st in candidates:
            if feasible(intervals, cap, st, st + dur):
                return st
        st = candidates[-1] if candidates else ready
        while not feasible(intervals, cap, st, st + dur):
            nxt = None
            for s, e in intervals:
                if e > st and (nxt is None or e < nxt):
                    nxt = e
            if nxt is None:
                st += 1
            else:
                st = nxt
        return st

    def simulate(task, robot, robot_ready, ws_intervals):
        local = {k: v[:] for k, v in ws_intervals.items()}
        ready = robot_ready
        ops = []
        expr_no = task.get("expr_no")
        task_name = task.get("name")
        for step in task_steps(task):
            ws = step.get("workstation")
            dur = duration(step)
            cap = capacities.get(ws, 1)
            arr = local.setdefault(ws, [])
            st = earliest(arr, cap, ready, dur)
            en = st + dur
            arr.append((st, en))
            ready = en
            ops.append({
                "expr_no": expr_no,
                "task_name": task_name,
                "step_index": step_index(step),
                "workstation": ws,
                "robot": robot,
                "start": st,
                "end": en
            })
        return ready, ops, local

    tasks = list(dataset.get("task_list", []))
    order = sorted(range(len(tasks)), key=lambda i: (-task_total(tasks[i]), i))

    ws_intervals = {}
    robot_ready = {r: 0 for r in robots}
    operations = []

    for i in order:
        task = tasks[i]
        best = None
        for ri, r in enumerate(robots):
            finish, ops, local = simulate(task, r, robot_ready[r], ws_intervals)
            key = (finish, robot_ready[r], ri)
            if best is None or key < best[0]:
                best = (key, r, finish, ops, local)
        _, r, finish, ops, local = best
        robot_ready[r] = finish
        ws_intervals = local
        operations.extend(ops)

    return {"operations": operations}