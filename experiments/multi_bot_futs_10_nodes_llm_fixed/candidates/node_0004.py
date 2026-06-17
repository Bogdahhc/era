def solve(dataset):
    def duration(step):
        if isinstance(step, dict):
            if "time" in step:
                v = step.get("time")
                if v is None:
                    return 3
                try:
                    return max(3, int(v))
                except Exception:
                    return 3
            if step.get("duration") is not None:
                try:
                    return max(0, int(step.get("duration")))
                except Exception:
                    return 3
        return 3

    def step_index(step, default):
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return int(default)

    def get_robots():
        out = []
        for r in dataset.get("robot_list", []):
            if isinstance(r, str):
                out.append(r)
            elif isinstance(r, dict):
                c = r.get("code") or r.get("name")
                if c:
                    out.append(c)
        if not out:
            for w in dataset.get("workstation_list", []):
                if not isinstance(w, dict):
                    continue
                typ = w.get("type") or w.get("workstationType")
                if typ == "robot" or w.get("isRobot"):
                    c = w.get("code") or w.get("name")
                    if c:
                        out.append(c)
        return out or ["robot_0"]

    def get_capacities():
        caps = {}
        for w in dataset.get("workstation_list", []):
            if not isinstance(w, dict):
                continue
            code = w.get("code") or w.get("name")
            if not code:
                continue
            try:
                cap = int(w.get("bottleSlotCount", w.get("capacity", 1)))
            except Exception:
                cap = 1
            if cap < 1:
                cap = 1
            caps[code] = cap
            typ = w.get("type") or w.get("workstationType")
            if typ and typ not in caps:
                caps[typ] = cap
        return caps

    robots = get_robots()
    capacities = get_capacities()

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        raw_steps = task.get("steps", []) if isinstance(task, dict) else []
        steps = sorted(raw_steps, key=lambda s: step_index(s, 0))
        norm = []
        for si, st in enumerate(steps):
            norm.append({
                "idx": step_index(st, si + 1),
                "workstation": st.get("workstation"),
                "duration": duration(st)
            })
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": norm,
            "total": sum(s["duration"] for s in norm)
        })

    robot_cal = {r: [] for r in robots}
    ws_cal = {}

    def ensure_ws(ws):
        cap = capacities.get(ws, 1)
        try:
            cap = int(cap)
        except Exception:
            cap = 1
        if cap < 1:
            cap = 1
        if ws not in ws_cal:
            ws_cal[ws] = [[] for _ in range(cap)]
        elif len(ws_cal[ws]) < cap:
            ws_cal[ws].extend([] for _ in range(cap - len(ws_cal[ws])))
        return ws_cal[ws]

    def conflict(cal, s, d):
        e = s + d
        for a, b in cal:
            if a < e and s < b:
                return b
        return None

    def earliest_pair(rcal, wcal, ready, d):
        t = int(ready)
        while True:
            c = conflict(rcal, t, d)
            if c is not None:
                t = int(c)
                continue
            c = conflict(wcal, t, d)
            if c is not None:
                t = int(c)
                continue
            return t

    def insert(cal, s, e):
        i = 0
        while i < len(cal) and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    def best_assignment(ws, ready, d):
        units = ensure_ws(ws)
        best = None
        for r in robots:
            rc = robot_cal[r]
            for ui, wc in enumerate(units):
                s = earliest_pair(rc, wc, ready, d)
                cand = (s, r, ui)
                if best is None or cand < best:
                    best = cand
        return best

    operations = []

    order = sorted(range(len(tasks)), key=lambda i: (-tasks[i]["total"], i))

    for ti in order:
        task = tasks[ti]
        ready = 0
        for st in task["steps"]:
            ws = st["workstation"]
            d = st["duration"]
            start, robot, unit = best_assignment(ws, ready, d)
            end = start + d
            insert(robot_cal[robot], start, end)
            insert(ws_cal[ws][unit], start, end)
            operations.append({
                "expr_no": task["expr_no"],
                "task_name": task["name"],
                "step_index": st["idx"],
                "workstation": ws,
                "robot": robot,
                "start": int(start),
                "end": int(end)
            })
            ready = end

    operations.sort(key=lambda op: (op["start"], op["end"], op["expr_no"], op["step_index"]))
    return {"operations": operations}