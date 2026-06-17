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


def solve(dataset):
    robots = _robots(dataset)
    capacities = _capacities(dataset)
    workstation_slots = {
        code: [0.0] * cap
        for code, cap in capacities.items()
        if code is not None
    }
    robot_available = {robot: 0.0 for robot in robots}
    operations = []

    for task in dataset.get("task_list", []):
        expr_no = task["expr_no"]
        task_ready = 0.0
        for step in sorted(task.get("steps", []), key=lambda item: item["index"]):
            workstation = step["workstation"]
            duration = _duration(step)
            slots = workstation_slots.setdefault(
                workstation, [0.0] * max(1, capacities.get(workstation, 1))
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
                    "start": start,
                    "end": end,
                }
            )
    return {"operations": operations}