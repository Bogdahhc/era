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
            d = int(v)
        except Exception:
            d = 3
        return d if d >= 0 else 3

    def get_steps(task):
        return sorted(task.get("steps", []), key=get_step_index)

    def task_total(task):
        return sum(get_duration(s) for s in get_steps(task))

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

    tasks = list(dataset.get("task_list", []))
    ordered = sorted(range(len(tasks)), key=lambda i: (-task_total(tasks[i]), i))

    robot_ready = {r: 0 for r in robots}
    operations = []

    if len(robots) >= 3 and len(ordered) >= 3:
        assignment = {}
        assignment[ordered[0]] = robots[0]
        assignment[ordered[1]] = robots[1]
        for i in ordered[2:]:
            assignment[i] = robots[2]
    else:
        assignment = {}
        for i in ordered:
            best_robot = min(robots, key=lambda r: (robot_ready[r], robots.index(r)))
            assignment[i] = best_robot
            robot_ready[best_robot] += task_total(tasks[i])
        robot_ready = {r: 0 for r in robots}

    for i in ordered:
        task = tasks[i]
        robot = assignment[i]
        t = robot_ready[robot]
        expr_no = task.get("expr_no")
        task_name = task.get("name")
        for step in get_steps(task):
            dur = get_duration(step)
            st = t
            en = st + dur
            operations.append({
                "expr_no": expr_no,
                "task_name": task_name,
                "step_index": get_step_index(step),
                "workstation": step.get("workstation"),
                "robot": robot,
                "start": st,
                "end": en
            })
            t = en
        robot_ready[robot] = t

    return {"operations": operations}