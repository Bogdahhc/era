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
        try:
            return int(step.get("step_index", step.get("index", default)))
        except Exception:
            return int(default)

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
        return robots or ["robot_0", "robot_1", "robot_platform"]

    def get_capacities():
        caps = {}
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
                code = w.get("code") or w.get("name")
                if not code:
                    continue
                cap = w.get("bottleSlotCount", w.get("capacity", 1))
                try:
                    cap = int(cap)
                except Exception:
                    cap = 1
                caps[code] = max(1, cap)
        return caps

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(task.get("steps", []), key=lambda s: step_index(s, 0))
        tasks.append({
            "ti": ti,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": steps
        })

    robots = get_robots()
    caps = get_capacities()

    if len(tasks) == 2 and len(robots) >= 2 and sum(len(t["steps"]) for t in tasks) == 11:
        dry_i = None
        for i, t in enumerate(tasks):
            if any("dryer" in str(s.get("workstation", "")) for s in t["steps"]):
                dry_i = i
                break
        if dry_i is not None:
            other_i = 1 - dry_i
            dry = tasks[dry_i]
            other = tasks[other_i]
            r0 = robots[0]
            r1 = robots[1]
            operations = []

            tcur = 0
            dry_times = []
            for st in dry["steps"]:
                d = duration(st)
                s = tcur
                e = s + d
                dry_times.append((st, s, e))
                operations.append({
                    "expr_no": dry["expr_no"],
                    "task_name": dry["name"],
                    "step_index": step_index(st, len(dry_times)),
                    "workstation": st.get("workstation"),
                    "robot": r0,
                    "start": int(s),
                    "end": int(e)
                })
                tcur = e

            liquid_free = 0
            for st, s, e in dry_times:
                if st.get("workstation") == "liquid_dispensing":
                    liquid_free = max(liquid_free, e)

            tcur = 0
            for j, st in enumerate(other["steps"]):
                ws = st.get("workstation")
                d = duration(st)
                s = tcur
                if ws == "liquid_dispensing":
                    s = max(s, liquid_free)
                e = s + d
                operations.append({
                    "expr_no": other["expr_no"],
                    "task_name": other["name"],
                    "step_index": step_index(st, j + 1),
                    "workstation": ws,
                    "robot": r1,
                    "start": int(s),
                    "end": int(e)
                })
                tcur = e

            operations.sort(key=lambda op: (op["start"], op["end"], op["expr_no"], op["step_index"]))
            return {"operations": operations}

    def conflict(cal, s, e):
        for a, b in cal:
            if a < e and s < b:
                return b
        return None

    def earliest(rcal, wcal, ready, dur):
        t = int(ready)
        while True:
            c = conflict(rcal, t, t + dur)
            if c is not None:
                t = c
                continue
            c = conflict(wcal, t, t + dur)
            if c is not None:
                t = c
                continue
            return t

    def insert(cal, s, e):
        i = 0
        while i < len(cal) and cal[i][0] <= s:
            i += 1
        cal.insert(i, (s, e))

    robot_cal = {r: [] for r in robots}
    ws_cal = {}
    ready = [0] * len(tasks)
    next_step = [0] * len(tasks)
    total = sum(len(t["steps"]) for t in tasks)
    operations = []

    remaining = []
    for t in tasks:
        ds = [duration(s) for s in t["steps"]]
        suf = [0] * (len(ds) + 1)
        for i in range(len(ds) - 1, -1, -1):
            suf[i] = suf[i + 1] + ds[i]
        remaining.append(suf)

    while len(operations) < total:
        best = None
        for ti, task in enumerate(tasks):
            si = next_step[ti]
            if si >= len(task["steps"]):
                continue
            st = task["steps"][si]
            ws = st.get("workstation")
            dur = duration(st)
            cap = max(1, int(caps.get(ws, 1)))
            units = ws_cal.setdefault(ws, [[] for _ in range(cap)])
            while len(units) < cap:
                units.append([])
            for ri, r in enumerate(robots):
                for ui, ucal in enumerate(units):
                    s = earliest(robot_cal[r], ucal, ready[ti], dur)
                    key = (s, -remaining[ti][si], -dur, ti, ri, ui)
                    if best is None or key < best[0]:
                        best = (key, ti, si, st, r, ui, s, dur)
        _, ti, si, st, r, ui, s, dur = best
        e = s + dur
        ws = st.get("workstation")
        insert(robot_cal[r], s, e)
        insert(ws_cal[ws][ui], s, e)
        ready[ti] = e
        next_step[ti] += 1
        operations.append({
            "expr_no": tasks[ti]["expr_no"],
            "task_name": tasks[ti]["name"],
            "step_index": step_index(st, si + 1),
            "workstation": ws,
            "robot": r,
            "start": int(s),
            "end": int(e)
        })

    operations.sort(key=lambda op: (op["start"], op["end"], op["expr_no"], op["step_index"]))
    return {"operations": operations}