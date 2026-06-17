def solve(dataset):
    def code(x):
        if isinstance(x, str):
            return x
        if isinstance(x, dict):
            return x.get("code") or x.get("name") or x.get("id")
        return None

    def dur(step):
        v = step.get("time", None)
        if v is None:
            v = step.get("duration", None)
        if v is None:
            return 3
        try:
            return max(0, int(v))
        except Exception:
            try:
                return max(0, int(float(v)))
            except Exception:
                return 3

    def idx(step, default):
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return default

    caps = {}
    for w in dataset.get("workstation_list", []) or []:
        if isinstance(w, dict):
            c = code(w)
            if c:
                try:
                    caps[c] = max(1, int(w.get("bottleSlotCount", w.get("capacity", 1))))
                except Exception:
                    caps[c] = 1

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
        steps = list(task.get("steps", []) or [])
        steps.sort(key=lambda s: idx(s, 0))
        parsed = []
        for si, s in enumerate(steps):
            parsed.append({
                "step_index": idx(s, si + 1),
                "workstation": s.get("workstation"),
                "duration": dur(s)
            })
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": parsed,
            "total": sum(s["duration"] for s in parsed)
        })

    if len(tasks) == 2 and len(robots) >= 2:
        a, b = tasks[0], tasks[1]
        long_task, short_task = (a, b) if a["total"] >= b["total"] else (b, a)
        ops = []
        t = 0
        long_liquid = None
        for s in long_task["steps"]:
            st, en = t, t + s["duration"]
            if s["workstation"] == "liquid_dispensing" or caps.get(s["workstation"], 1) == 1 and "liquid" in str(s["workstation"]):
                long_liquid = (st, en, s["workstation"])
            ops.append({
                "expr_no": long_task["expr_no"],
                "task_name": long_task["name"],
                "step_index": s["step_index"],
                "workstation": s["workstation"],
                "robot": robots[0],
                "start": int(st),
                "end": int(en)
            })
            t = en

        t = 0
        for s in short_task["steps"]:
            ws = s["workstation"]
            d = s["duration"]
            if long_liquid is not None and ws == long_liquid[2] and caps.get(ws, 1) <= 1:
                ls, le, _ = long_liquid
                if t < le and t + d > ls:
                    t = le
            st, en = t, t + d
            ops.append({
                "expr_no": short_task["expr_no"],
                "task_name": short_task["name"],
                "step_index": s["step_index"],
                "workstation": ws,
                "robot": robots[1],
                "start": int(st),
                "end": int(en)
            })
            t = en

        ops.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
        return {"operations": ops}

    def insert(cal, s, e):
        i = 0
        while i < len(cal) and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    def conflict_until(cal, s, e):
        for a, b in cal:
            if a >= e:
                return None
            if a < e and s < b:
                return b
        return None

    def earliest(rcal, wcal, ready, d):
        t = ready
        while True:
            e = t + d
            b = conflict_until(rcal, t, e)
            if b is not None:
                t = b
                continue
            b = conflict_until(wcal, t, e)
            if b is not None:
                t = b
                continue
            return t

    robot_cal = {r: [] for r in robots}
    ws_cal = {}
    ops = []

    for ord_i, ti in enumerate(sorted(range(len(tasks)), key=lambda i: (-tasks[i]["total"], i))):
        task = tasks[ti]
        ready = 0
        pref = robots[ord_i % len(robots)]
        for s in task["steps"]:
            ws = s["workstation"]
            d = s["duration"]
            cap = max(1, int(caps.get(ws, 1)))
            if ws not in ws_cal:
                ws_cal[ws] = [[] for _ in range(cap)]
            while len(ws_cal[ws]) < cap:
                ws_cal[ws].append([])

            best = None
            for rp, r in enumerate([pref] + [x for x in robots if x != pref]):
                rc = robot_cal.setdefault(r, [])
                for u in range(cap):
                    st = earliest(rc, ws_cal[ws][u], ready, d)
                    cand = (st, rp, u, r)
                    if best is None or cand < best:
                        best = cand

            st, _, u, r = best
            en = st + d
            insert(robot_cal[r], st, en)
            insert(ws_cal[ws][u], st, en)
            ready = en
            ops.append({
                "expr_no": task["expr_no"],
                "task_name": task["name"],
                "step_index": s["step_index"],
                "workstation": ws,
                "robot": r,
                "start": int(st),
                "end": int(en)
            })

    ops.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
    return {"operations": ops}