def solve(dataset):
    def duration(step):
        v = step.get("time", None)
        if v is None:
            v = step.get("duration", None)
        if v is None:
            return 3
        try:
            return max(3 if step.get("time", None) is None and step.get("duration", None) is None else 0, int(v))
        except Exception:
            return 3

    def idx(step, default):
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return default

    def get_robots():
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
                    typ = w.get("type") or w.get("workstationType")
                    c = w.get("code") or w.get("name")
                    if c and (typ == "robot" or w.get("isRobot")):
                        robots.append(c)
        return robots or ["robot_0"]

    def get_capacities():
        caps = {}
        for w in dataset.get("workstation_list", []):
            if not isinstance(w, dict):
                continue
            c = w.get("code") or w.get("name")
            if not c:
                continue
            v = w.get("bottleSlotCount", w.get("capacity", 1))
            try:
                cap = int(v)
            except Exception:
                cap = 1
            caps[c] = max(1, cap)
        return caps

    robots = get_robots()
    capacities = get_capacities()

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        raw_steps = sorted(task.get("steps", []), key=lambda s: idx(s, 0))
        steps = []
        for si, st in enumerate(raw_steps):
            steps.append({
                "idx": idx(st, si + 1),
                "workstation": st.get("workstation"),
                "duration": duration(st),
            })
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": steps,
            "total": sum(s["duration"] for s in steps),
        })

    def insert_interval(cal, s, e):
        i = 0
        while i < len(cal) and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    def conflict_end(cal, s, d):
        e = s + d
        for a, b in cal:
            if a < e and s < b:
                return b
            if a >= e:
                break
        return None

    def earliest_two(cal_a, cal_b, ready, d):
        t = int(ready)
        while True:
            x = conflict_end(cal_a, t, d)
            if x is not None:
                t = x
                continue
            y = conflict_end(cal_b, t, d)
            if y is not None:
                t = y
                continue
            return t

    def build(order):
        robot_cal = {r: [] for r in robots}
        ws_cal = {}
        ops = []

        for ti in order:
            task = tasks[ti]
            ready = 0
            for st in task["steps"]:
                ws = st["workstation"]
                d = st["duration"]
                cap = max(1, int(capacities.get(ws, 1)))
                if ws not in ws_cal:
                    ws_cal[ws] = [[] for _ in range(cap)]
                while len(ws_cal[ws]) < cap:
                    ws_cal[ws].append([])

                best = None
                for r in robots:
                    rc = robot_cal[r]
                    for ui in range(cap):
                        s = earliest_two(rc, ws_cal[ws][ui], ready, d)
                        cand = (s, r, ui)
                        if best is None or cand < best:
                            best = cand

                s, r, ui = best
                e = s + d
                insert_interval(robot_cal[r], s, e)
                insert_interval(ws_cal[ws][ui], s, e)
                ready = e
                ops.append({
                    "expr_no": task["expr_no"],
                    "task_name": task["name"],
                    "step_index": st["idx"],
                    "workstation": ws,
                    "robot": r,
                    "start": int(s),
                    "end": int(e),
                })

        return max((o["end"] for o in ops), default=0), ops

    n = len(tasks)
    orders = []
    orders.append(sorted(range(n), key=lambda i: (-tasks[i]["total"], i)))
    orders.append(sorted(range(n), key=lambda i: (tasks[i]["total"], i)))
    orders.append(list(range(n)))
    orders.append(list(reversed(range(n))))

    best_ms = None
    best_ops = None
    seen = set()
    for order in orders:
        key = tuple(order)
        if key in seen:
            continue
        seen.add(key)
        ms, ops = build(order)
        if best_ms is None or ms < best_ms:
            best_ms = ms
            best_ops = ops

    best_ops.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
    return {"operations": best_ops}