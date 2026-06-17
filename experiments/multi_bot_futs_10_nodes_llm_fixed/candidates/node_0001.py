def solve(dataset):
    def duration(step):
        if step.get("time") is not None:
            try:
                return int(step.get("time"))
            except Exception:
                return 3
        if step.get("duration") is not None:
            try:
                return int(step.get("duration"))
            except Exception:
                return 3
        return 3

    def step_index(step, default):
        v = step.get("step_index", step.get("index", default))
        try:
            return int(v)
        except Exception:
            return int(default)

    def get_robots():
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
                if isinstance(w, dict) and (w.get("isRobot") or w.get("workstationType") == "robot" or w.get("type") == "robot"):
                    code = w.get("code")
                    if code:
                        robots.append(code)
        return robots or ["robot_0"]

    def get_capacities():
        caps = {}
        for w in dataset.get("workstation_list", []):
            if not isinstance(w, dict):
                continue
            code = w.get("code")
            if not code:
                continue
            cap = w.get("bottleSlotCount", w.get("capacity", 1))
            try:
                cap = int(cap)
            except Exception:
                cap = 1
            cap = max(1, cap)
            caps[code] = cap
            typ = w.get("workstationType") or w.get("type")
            if typ and typ not in caps:
                caps[typ] = cap
        return caps

    robots = get_robots()
    capacities = get_capacities()

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(task.get("steps", []), key=lambda s: step_index(s, 0))
        norm_steps = []
        for si, st in enumerate(steps):
            norm_steps.append({
                "raw": st,
                "idx": step_index(st, si + 1),
                "workstation": st.get("workstation"),
                "duration": duration(st)
            })
        tasks.append({
            "task_i": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name"),
            "steps": norm_steps
        })

    def conflict(cal, t, d):
        end = t + d
        for a, b in cal:
            if a < end and t < b:
                return b
        return None

    def earliest_common(cal1, cal2, ready, d):
        t = int(ready)
        while True:
            c1 = conflict(cal1, t, d)
            if c1 is not None:
                t = int(c1)
                continue
            c2 = conflict(cal2, t, d)
            if c2 is not None:
                t = int(c2)
                continue
            return t

    def insert_interval(cal, s, e):
        i = 0
        while i < len(cal) and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    def build_schedule(rule):
        robot_cal = {r: [] for r in robots}
        ws_cal = {}
        next_step = [0] * len(tasks)
        ready_time = [0] * len(tasks)
        operations = []
        total_steps = sum(len(t["steps"]) for t in tasks)

        rem = []
        for t in tasks:
            ds = [s["duration"] for s in t["steps"]]
            suffix = [0] * (len(ds) + 1)
            for i in range(len(ds) - 1, -1, -1):
                suffix[i] = suffix[i + 1] + ds[i]
            rem.append(suffix)

        def best_assignment(ws, ready, d):
            cap = max(1, int(capacities.get(ws, 1)))
            units = ws_cal.setdefault(ws, [[] for _ in range(cap)])
            if len(units) < cap:
                units.extend([] for _ in range(cap - len(units)))
            best = None
            for r in robots:
                rc = robot_cal[r]
                for ui, uc in enumerate(units):
                    s = earliest_common(rc, uc, ready, d)
                    cand = (s, r, ui)
                    if best is None or cand[0] < best[0] or (cand[0] == best[0] and cand[1] < best[1]):
                        best = cand
            return best

        while len(operations) < total_steps:
            candidates = []
            for ti, t in enumerate(tasks):
                si = next_step[ti]
                if si >= len(t["steps"]):
                    continue
                st = t["steps"][si]
                s, r, ui = best_assignment(st["workstation"], ready_time[ti], st["duration"])
                if rule == 0:
                    key = (-rem[ti][si], s, ready_time[ti], -st["duration"], ti)
                elif rule == 1:
                    key = (s, -rem[ti][si], ready_time[ti], ti)
                elif rule == 2:
                    key = (ready_time[ti], -rem[ti][si], s, ti)
                elif rule == 3:
                    key = (-st["duration"], s, -rem[ti][si], ti)
                elif rule == 4:
                    key = (ti, s)
                else:
                    key = (-ti, s)
                candidates.append((key, ti, si, st, s, r, ui))

            candidates.sort(key=lambda x: x[0])
            _, ti, si, st, start, robot, unit = candidates[0]
            end = start + st["duration"]
            ws = st["workstation"]

            insert_interval(robot_cal[robot], start, end)
            insert_interval(ws_cal[ws][unit], start, end)
            ready_time[ti] = end
            next_step[ti] += 1

            operations.append({
                "expr_no": tasks[ti]["expr_no"],
                "task_name": tasks[ti]["name"],
                "step_index": st["idx"],
                "workstation": ws,
                "robot": robot,
                "start": int(start),
                "end": int(end)
            })

        makespan = max((op["end"] for op in operations), default=0)
        return makespan, operations

    best_makespan = None
    best_ops = None
    for rule in range(6):
        ms, ops = build_schedule(rule)
        if best_makespan is None or ms < best_makespan:
            best_makespan = ms
            best_ops = ops

    best_ops.sort(key=lambda op: (op["start"], op["end"], op["expr_no"], op["step_index"]))
    return {"operations": best_ops}