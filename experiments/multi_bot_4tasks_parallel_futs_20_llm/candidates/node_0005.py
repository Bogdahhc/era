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
    order = sorted(range(len(tasks)), key=lambda i: (-task_total(tasks[i]), i))

    robot_ready = {r: 0 for r in robots}
    operations = []

    for pos, ti in enumerate(order):
        task = tasks[ti]
        if pos < len(robots):
            robot = robots[pos]
        else:
            robot = min(robots, key=lambda r: (robot_ready[r], robots.index(r)))

        start_time = robot_ready[robot]
        expr_no = task.get("expr_no")
        task_name = task.get("name", task.get("task_name"))

        for step in get_steps(task):
            dur = get_duration(step)
            end_time = start_time + dur
            operations.append({
                "expr_no": expr_no,
                "task_name": task_name,
                "step_index": get_step_index(step),
                "workstation": step.get("workstation"),
                "robot": robot,
                "start": start_time,
                "end": end_time
            })
            start_time = end_time

        robot_ready[robot] = start_time

    return {"operations": operations}