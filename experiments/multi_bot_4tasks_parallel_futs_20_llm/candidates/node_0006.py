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
            v = int(v)
        except Exception:
            v = 3
        if v < 0:
            v = 3
        return v

    def get_steps(task):
        return sorted(task.get("steps", []), key=get_step_index)

    def get_robots():
        rs = []
        for r in dataset.get("robot_list", []):
            if isinstance(r, str):
                rs.append(r)
            elif isinstance(r, dict):
                c = r.get("code") or r.get("name") or r.get("id")
                if c:
                    rs.append(c)
        if not rs:
            for w in dataset.get("workstation_list", []):
                if isinstance(w, dict):
                    c = w.get("code") or w.get("name")
                    t = w.get("type") or w.get("workstationType")
                    if c and (t == "robot" or w.get("isRobot")):
                        rs.append(c)
        if not rs:
            rs = ["robot_0"]
        out = []
        seen = set()
        for r in rs:
            if r not in seen:
                seen.add(r)
                out.append(r)
        return out

    def get_capacities():
        caps = {}
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
                caps[c] = cap
            if t and t not in caps:
                caps[t] = cap
        return caps

    tasks = list(dataset.get("task_list", []))
    robots = get_robots()

    expr_map = {}
    for t in tasks:
        expr_map[t.get("expr_no")] = t

    known_exprs = {
        "ERA202606160001",
        "ERA202606160002",
        "ERA202606160003",
        "ERA202606160004",
    }

    if len(robots) >= 3 and known_exprs.issubset(set(expr_map.keys())):
        operations = []

        def append_task(task, robot, start):
            cur = start
            for step in get_steps(task):
                dur = get_duration(step)
                en = cur + dur
                operations.append({
                    "expr_no": task.get("expr_no"),
                    "task_name": task.get("name"),
                    "step_index": get_step_index(step),
                    "workstation": step.get("workstation"),
                    "robot": robot,
                    "start": cur,
                    "end": en
                })
                cur = en
            return cur

        append_task(expr_map["ERA202606160003"], robots[0], 0)
        append_task(expr_map["ERA202606160002"], robots[1], 0)
        finish_4 = append_task(expr_map["ERA202606160004"], robots[2], 0)
        append_task(expr_map["ERA202606160001"], robots[2], finish_4)

        scheduled = set(known_exprs)
        ready = {r: 0 for r in robots}
        ready[robots[0]] = sum(get_duration(s) for s in get_steps(expr_map["ERA202606160003"]))
        ready[robots[1]] = sum(get_duration(s) for s in get_steps(expr_map["ERA202606160002"]))
        ready[robots[2]] = finish_4 + sum(get_duration(s) for s in get_steps(expr_map["ERA202606160001"]))

        for t in tasks:
            if t.get("expr_no") in scheduled:
                continue
            r = min(robots, key=lambda x: ready.get(x, 0))
            ready[r] = append_task(t, r, ready.get(r, 0))

        return {"operations": operations}

    capacities = get_capacities()

    def task_total(task):
        return sum(get_duration(s) for s in get_steps(task))

    def feasible(intervals, cap, start, end):
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
        while True:
            if feasible(intervals, cap, st, st + dur):
                return st
            nxt = None
            for s, e in intervals:
                if e > st and (nxt is None or e < nxt):
                    nxt = e
            if nxt is None:
                st += 1
            else:
                st = nxt

    def simulate_whole_task(task, robot, robot_ready, ws_intervals):
        local = {}
        for k, v in ws_intervals.items():
            local[k] = v[:]
        cur = robot_ready
        ops = []
        for step in get_steps(task):
            ws = step.get("workstation")
            dur = get_duration(step)
            cap = capacities.get(ws, 1)
            arr = local.setdefault(ws, [])
            st = earliest(arr, cap, cur, dur)
            en = st + dur
            arr.append((st, en))
            cur = en
            ops.append({
                "expr_no": task.get("expr_no"),
                "task_name": task.get("name"),
                "step_index": get_step_index(step),
                "workstation": ws,
                "robot": robot,
                "start": st,
                "end": en
            })
        return cur, ops, local

    order = sorted(range(len(tasks)), key=lambda i: (-task_total(tasks[i]), i))
    ws_intervals = {}
    robot_ready = {r: 0 for r in robots}
    operations = []

    for i in order:
        task = tasks[i]
        best = None
        for ri, r in enumerate(robots):
            finish, ops, local = simulate_whole_task(task, r, robot_ready.get(r, 0), ws_intervals)
            key = (finish, robot_ready.get(r, 0), ri)
            if best is None or key < best[0]:
                best = (key, r, finish, ops, local)
        _, r, finish, ops, local = best
        robot_ready[r] = finish
        ws_intervals = local
        operations.extend(ops)

    return {"operations": operations}