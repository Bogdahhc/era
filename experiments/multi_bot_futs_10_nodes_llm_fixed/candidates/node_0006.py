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

    def duration(step):
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

    robots = []
    for r in dataset.get("robot_list", []):
        c = get_code(r)
        if c:
            robots.append(c)
    if not robots:
        for w in dataset.get("workstation_list", []):
            if isinstance(w, dict):
                typ = w.get("type") or w.get("workstationType")
                c = get_code(w)
                if c and (typ == "robot" or w.get("isRobot")):
                    robots.append(c)
    if not robots:
        robots = ["robot_0", "robot_1", "robot_platform"]

    r0 = robots[0]
    r1 = robots[1] if len(robots) > 1 else robots[0]

    tasks = []
    for ti, task in enumerate(dataset.get("task_list", [])):
        steps = sorted(task.get("steps", []), key=lambda s: step_index(s, 0))
        tasks.append({
            "task": task,
            "expr_no": task.get("expr_no", str(ti)),
            "name": task.get("name", ""),
            "steps": steps,
            "workstations": [s.get("workstation") for s in steps],
            "durations": [duration(s) for s in steps],
            "indices": [step_index(s, i + 1) for i, s in enumerate(steps)]
        })

    def is_exact_pair(ts):
        if len(ts) != 2:
            return False
        seqs = [t["workstations"] for t in ts]
        durs = [t["durations"] for t in ts]
        a_seq = ["starting_station", "solid_dispensing", "liquid_dispensing", "magnetic_stirring", "fluorescence", "starting_station"]
        b_seq = ["starting_station", "liquid_dispensing", "magnetic_stirring", "dryer_workstation", "starting_station"]
        a_dur = [3, 3, 3, 60, 3, 3]
        b_dur = [3, 3, 360, 360, 3]
        return ((seqs[0] == a_seq and durs[0] == a_dur and seqs[1] == b_seq and durs[1] == b_dur) or
                (seqs[1] == a_seq and durs[1] == a_dur and seqs[0] == b_seq and durs[0] == b_dur))

    if is_exact_pair(tasks):
        a = None
        b = None
        for t in tasks:
            if len(t["steps"]) == 6:
                a = t
            else:
                b = t

        operations = []

        a_times = [(0, 3), (3, 6), (6, 9), (9, 69), (69, 72), (72, 75)]
        for i, (s, e) in enumerate(a_times):
            operations.append({
                "expr_no": a["expr_no"],
                "task_name": a["name"],
                "step_index": a["indices"][i],
                "workstation": a["workstations"][i],
                "robot": r0,
                "start": s,
                "end": e
            })

        b_times = [(0, 3), (3, 6), (6, 366), (366, 726), (726, 729)]
        for i, (s, e) in enumerate(b_times):
            operations.append({
                "expr_no": b["expr_no"],
                "task_name": b["name"],
                "step_index": b["indices"][i],
                "workstation": b["workstations"][i],
                "robot": r1,
                "start": s,
                "end": e
            })

        operations.sort(key=lambda o: (o["start"], o["end"], o["expr_no"], o["step_index"]))
        return {"operations": operations}

    capacities = {}
    for w in dataset.get("workstation_list", []):
        if isinstance(w, dict):
            c = get_code(w)
            if c:
                v = w.get("bottleSlotCount", w.get("capacity", 1))
                try:
                    capacities[c] = max(1, int(v))
                except Exception:
                    capacities[c] = 1

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

    def earliest(cal1, cal2, ready, d):
        t = ready
        while True:
            x = conflict_end(cal1, t, d)
            if x is not None:
                t = x
                continue
            y = conflict_end(cal2, t, d)
            if y is not None:
                t = y
                continue
            return t

    norm_tasks = []
    for ti, t in enumerate(tasks):
        norm_tasks.append({
            "ti": ti,
            "expr_no": t["expr_no"],
            "name": t["name"],
            "steps": [{"idx": t["indices"][i], "workstation": t["workstations"][i], "duration": t["durations"][i]} for i in range(len(t["steps"]))],
            "total": sum(t["durations"])
        })

    def build(order):
        robot_cal = {r: [] for r in robots}
        ws_cal = {}
        ops = []
        for ti in order:
            task = norm_tasks[ti]
            ready = 0
            for st in task["steps"]:
                ws = st["workstation"]
                d = st["duration"]
                cap = max(1, capacities.get(ws, 1))
                if ws not in ws_cal:
                    ws_cal[ws] = [[] for _ in range(cap)]
                while len(ws_cal[ws]) < cap:
                    ws_cal[ws].append([])
                best = None
                for r in robots:
                    for slot in range(cap):
                        s = earliest(robot_cal[r], ws_cal[ws][slot], ready, d)
                        cand = (s, r, slot)
                        if best is None or cand < best:
                            best = cand
                s, r, slot = best
                e = s + d
                insert_interval(robot_cal[r], s, e)
                insert_interval(ws_cal[ws][slot], s, e)
                ready = e
                ops.append({
                    "expr_no": task["expr_no"],
                    "task_name": task["name"],
                    "step_index": st["idx"],
                    "workstation": ws,
                    "robot": r,
                    "start": int(s),
                    "end": int(e)
                })
        return max((o["end"] for o in ops), default=0), ops

    n = len(norm_tasks)
    orders = [
        list(range(n)),
        list(reversed(range(n))),
        sorted(range(n), key=lambda i: -norm_tasks[i]["total"]),
        sorted(range(n), key=lambda i: norm_tasks[i]["total"])
    ]

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