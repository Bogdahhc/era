from ortools.sat.python import cp_model


def _duration(step):
    return int(step["time"]) if step.get("time") is not None else 3


def _robots(dataset):
    codes = [
        robot.get("code")
        for robot in dataset.get("robot_list", [])
        if robot.get("isRobot") and robot.get("code")
    ]
    return codes or ["robot_0"]


def _capacities(dataset):
    result = {}
    for ws in dataset.get("workstation_list", []):
        cap = max(1, int(ws.get("bottleSlotCount") or 1))
        result[ws.get("code")] = cap
        result.setdefault(ws.get("workstationType"), cap)
    return result


def _first_slot(slots, earliest, duration):
    best_index = 0
    best_start = None
    for index, available_at in enumerate(slots):
        start = max(earliest, available_at)
        if best_start is None or start < best_start:
            best_start = start
            best_index = index
    return best_index, best_start


def _flatten_steps(dataset):
    jobs = []
    for task_pos, task in enumerate(dataset.get("task_list", [])):
        expr_no = task["expr_no"]
        ordered_steps = sorted(task.get("steps", []), key=lambda item: item["index"])
        job = []
        for step_pos, step in enumerate(ordered_steps):
            job.append(
                {
                    "key": (task_pos, step_pos),
                    "expr_no": expr_no,
                    "task_name": task.get("name"),
                    "step_index": int(step["index"]),
                    "workstation": step["workstation"],
                    "duration": _duration(step),
                }
            )
        jobs.append(job)
    return jobs


def _greedy_fallback(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    workstation_slots = {
        code: [0] * cap
        for code, cap in capacities.items()
        if code is not None
    }
    robot_available = {robot: 0 for robot in robots}
    operations = []

    for task in dataset.get("task_list", []):
        expr_no = task["expr_no"]
        task_ready = 0
        for step in sorted(task.get("steps", []), key=lambda item: item["index"]):
            workstation = step["workstation"]
            duration = _duration(step)
            slots = workstation_slots.setdefault(
                workstation, [0] * max(1, capacities.get(workstation, 1))
            )
            ws_slot, ws_start = _first_slot(slots, task_ready, duration)
            robot = min(robots, key=lambda code: max(robot_available[code], ws_start))
            start = max(ws_start, robot_available[robot], task_ready)
            end = start + duration
            slots[ws_slot] = end
            robot_available[robot] = end
            task_ready = end
            operations.append(
                {
                    "expr_no": expr_no,
                    "task_name": task.get("name"),
                    "step_index": int(step["index"]),
                    "workstation": workstation,
                    "robot": robot,
                    "start": int(start),
                    "end": int(end),
                }
            )
    return {"operations": operations}


def solve(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    jobs = _flatten_steps(dataset)
    all_steps = [step for job in jobs for step in job]
    if not all_steps:
        return {"operations": []}

    horizon = sum(step["duration"] for step in all_steps)
    model = cp_model.CpModel()
    starts = {}
    ends = {}
    intervals_by_workstation = {}
    robot_optional_intervals = {robot: [] for robot in robots}
    robot_presence = {}

    for step in all_steps:
        key = step["key"]
        duration = step["duration"]
        start = model.NewIntVar(0, horizon, "s_%s_%s" % key)
        end = model.NewIntVar(0, horizon, "e_%s_%s" % key)
        interval = model.NewIntervalVar(start, duration, end, "i_%s_%s" % key)
        starts[key] = start
        ends[key] = end
        intervals_by_workstation.setdefault(step["workstation"], []).append(interval)

        presences = []
        for robot in robots:
            present = model.NewBoolVar("r_%s_%s_%s" % (robot, key[0], key[1]))
            optional = model.NewOptionalIntervalVar(
                start, duration, end, present, "ri_%s_%s_%s" % (robot, key[0], key[1])
            )
            robot_optional_intervals[robot].append(optional)
            robot_presence[(key, robot)] = present
            presences.append(present)
        model.AddExactlyOne(presences)

    for job in jobs:
        for prev, cur in zip(job, job[1:]):
            model.Add(ends[prev["key"]] <= starts[cur["key"]])

    for workstation, intervals in intervals_by_workstation.items():
        capacity = max(1, int(capacities.get(workstation, 1)))
        if capacity == 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), capacity)

    for intervals in robot_optional_intervals.values():
        model.AddNoOverlap(intervals)

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60.0
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _greedy_fallback(dataset)

    operations = []
    for step in all_steps:
        key = step["key"]
        assigned_robot = robots[0]
        for robot in robots:
            if solver.BooleanValue(robot_presence[(key, robot)]):
                assigned_robot = robot
                break
        operations.append(
            {
                "expr_no": step["expr_no"],
                "task_name": step["task_name"],
                "step_index": step["step_index"],
                "workstation": step["workstation"],
                "robot": assigned_robot,
                "start": int(solver.Value(starts[key])),
                "end": int(solver.Value(ends[key])),
            }
        )
    operations.sort(
        key=lambda op: (
            int(op["start"]),
            str(op["expr_no"]),
            int(op["step_index"]),
            str(op["workstation"]),
        )
    )
    return {"operations": operations}