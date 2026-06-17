def solve(dataset):
    def code(x):
        if isinstance(x, str):
            return x
        if isinstance(x, dict):
            return x.get("code") or x.get("name") or x.get("id")
        return None

    def duration(step):
        v = step.get("time", None)
        if v is None:
            v = step.get("duration", 3)
        if v is None:
            return 3
        try:
            d = int(v)
        except Exception:
            try:
                d = int(float(v))
            except Exception:
                d = 3
        return max(0, d)

    def idx(step, default):
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return default

    capacities = {}
    for w in dataset.get("workstation_list", []) or []:
        if isinstance(w, dict):
            c = code(w)
            if c:
                try:
                    capacities[c] = max(1, int(w.get("bottleSlotCount", w.get("capacity", 1))))
                except Exception:
                    capacities[c] = 1

    robots = []
    for r in dataset.get("robot_list", []) or []:
        c = code(r)
        if c:
            robots.append(c)
    if not robots:
        for w in dataset.get("workstation_list", []) or []:
            if isinstance(w, dict):
                c = code(w)
                t = w.get("type") or w.get("workstationType")
                if c and (t == "robot" or w.get("isRobot")):
                    robots.append(c)
    if not robots:
        robots = ["robot_0"]

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", []) or []):
        steps_raw = list(task.get("steps", []) or [])
        steps_raw.sort(key=lambda s: idx(s, 0))
        steps = []
        total = 0
        for si, st in enumerate(steps_raw):
            d = duration(st)
            total += d
            steps.append((idx(st, si + 1), st.get("workstation"), d))
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": steps,
            "total": total
        })

    def insert(cal, s, e):
        i = 0
        n = len(cal)
        while i < n and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    def conflict_end(cal, s, e):
        for a, b in cal:
            if a >= e:
                return None
            if s < b and a < e:
                return b
        return None

    def earliest(rcal, wcal, ready, dur):
        t = ready
        while True:
            e = t + dur
            b = conflict_end(rcal, t, e)
            if b is not None:
                t = b
                continue
            b = conflict_end(wcal, t, e)
            if b is not None:
                t = b
                continue
            return t

    robot_cal = {r: [] for r in robots}
    ws_cal = {}
    operations = []

    order = sorted(range(len(tasks)), key=lambda i: (-tasks[i]["total"], i))

    for pos, ti in enumerate(order):
        task = tasks[ti]
        ready = 0
        preferred = robots[pos % len(robots)]

        for step_i, ws, dur in task["steps"]:
            cap = capacities.get(ws, 1)
            if ws not in ws_cal:
                ws_cal[ws] = [[] for _ in range(cap)]
            elif len(ws_cal[ws]) < cap:
                ws_cal[ws].extend([[] for _ in range(cap - len(ws_cal[ws]))])

            best = None
            for rp, r in enumerate(([preferred] + [x for x in robots if x != preferred])):
                rc = robot_cal.setdefault(r, [])
                for ui, wc in enumerate(ws_cal[ws]):
                    s = earliest(rc, wc, ready, dur)
                    cand = (s, rp, ui, r)
                    if best is None or cand < best:
                        best = cand

            s, _, ui, r = best
            e = s + dur
            insert(robot_cal[r], s, e)
            insert(ws_cal[ws][ui], s, e)
            ready = e
            operations.append({
                "expr_no": task["expr_no"],
                "task_name": task["name"],
                "step_index": step_i,
                "workstation": ws,
                "robot": r,
                "start": int(s),
                "end": int(e)
            })

    operations.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
    return {"operations": operations}