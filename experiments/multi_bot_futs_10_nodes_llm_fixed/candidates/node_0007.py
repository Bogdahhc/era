def solve(dataset):
    def get_code(obj):
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return obj.get("code") or obj.get("name") or obj.get("id")
        return None

    def step_index(step, default):
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return default

    def step_duration(step):
        if step.get("time", None) is not None:
            v = step.get("time")
        elif step.get("duration", None) is not None:
            v = step.get("duration")
        else:
            return 3
        try:
            d = int(v)
        except Exception:
            try:
                d = int(float(v))
            except Exception:
                return 3
        return max(0, d)

    def capacities_from_dataset():
        caps = {}
        for w in dataset.get("workstation_list", []) or []:
            if not isinstance(w, dict):
                continue
            c = get_code(w)
            if not c:
                continue
            v = w.get("bottleSlotCount", w.get("capacity", 1))
            try:
                caps[c] = max(1, int(v))
            except Exception:
                caps[c] = 1
        return caps

    def robots_from_dataset():
        rs = []
        for r in dataset.get("robot_list", []) or []:
            c = get_code(r)
            if c:
                rs.append(c)
        if not rs:
            for w in dataset.get("workstation_list", []) or []:
                if isinstance(w, dict):
                    typ = w.get("type") or w.get("workstationType")
                    c = get_code(w)
                    if c and (typ == "robot" or w.get("isRobot")):
                        rs.append(c)
        return rs or ["robot_0"]

    def insert_interval(cal, s, e):
        lo = 0
        hi = len(cal)
        while lo < hi:
            mid = (lo + hi) // 2
            if cal[mid][0] <= s:
                lo = mid + 1
            else:
                hi = mid
        cal.insert(lo, (s, e))

    def blocked_until(cal, s, e):
        for a, b in cal:
            if a >= e:
                return None
            if a < e and s < b:
                return b
        return None

    def earliest_pair(robot_cal, unit_cal, ready, dur):
        t = int(ready)
        while True:
            e = t + dur
            b = blocked_until(robot_cal, t, e)
            if b is not None:
                t = b
                continue
            b = blocked_until(unit_cal, t, e)
            if b is not None:
                t = b
                continue
            return t

    capacities = capacities_from_dataset()
    robots = robots_from_dataset()

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", []) or []):
        raw_steps = list(task.get("steps", []) or [])
        raw_steps.sort(key=lambda st: step_index(st, 0))
        steps = []
        for si, st in enumerate(raw_steps):
            steps.append({
                "idx": step_index(st, si + 1),
                "workstation": st.get("workstation"),
                "duration": step_duration(st),
            })
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": steps,
            "total": sum(x["duration"] for x in steps),
        })

    robot_cal = {r: [] for r in robots}
    ws_cal = {}
    operations = []

    order = sorted(range(len(tasks)), key=lambda i: (-tasks[i]["total"], i))

    for ti in order:
        task = tasks[ti]
        ready = 0
        preferred_robot = robots[ti % len(robots)] if robots else "robot_0"

        for st in task["steps"]:
            ws = st["workstation"]
            dur = st["duration"]
            cap = max(1, int(capacities.get(ws, 1)))

            if ws not in ws_cal:
                ws_cal[ws] = [[] for _ in range(cap)]
            while len(ws_cal[ws]) < cap:
                ws_cal[ws].append([])

            best = None

            robot_order = [preferred_robot] + [r for r in robots if r != preferred_robot]
            for r in robot_order:
                rc = robot_cal.setdefault(r, [])
                units = ws_cal[ws]
                for ui in range(cap):
                    s = earliest_pair(rc, units[ui], ready, dur)
                    cand = (s, 0 if r == preferred_robot else 1, ui, r)
                    if best is None or cand < best:
                        best = cand

            s, _, ui, r = best
            e = s + dur
            insert_interval(robot_cal[r], s, e)
            insert_interval(ws_cal[ws][ui], s, e)
            ready = e

            operations.append({
                "expr_no": task["expr_no"],
                "task_name": task["name"],
                "step_index": st["idx"],
                "workstation": ws,
                "robot": r,
                "start": int(s),
                "end": int(e),
            })

    operations.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
    return {"operations": operations}