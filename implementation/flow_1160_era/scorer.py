"""Validation and scoring for flow_1160 schedules."""

from __future__ import annotations

from collections import defaultdict
import json
import math


WORST_SCORE = float("-inf")
SCORE_RUNTIME_DIVISOR = 100.0


def step_duration(step: dict) -> int:
  return int(step["time"]) if step.get("time") is not None else 3


def workstation_capacities(dataset: dict) -> dict[str, int]:
  capacities = {}
  for ws in dataset.get("workstation_list", []):
    capacity = int(ws.get("bottleSlotCount") or 1)
    capacities[ws.get("code")] = max(1, capacity)
    capacities.setdefault(ws.get("workstationType"), max(1, capacity))
  return capacities


def robot_codes(dataset: dict) -> list[str]:
  codes = [
      robot.get("code")
      for robot in dataset.get("robot_list", [])
      if robot.get("isRobot") and robot.get("code")
  ]
  return codes or ["robot_0"]


def expected_operations(dataset: dict) -> dict[tuple[str, int], dict]:
  expected = {}
  for task in dataset.get("task_list", []):
    expr_no = task["expr_no"]
    for step in task.get("steps", []):
      expected[(expr_no, int(step["index"]))] = {
          "expr_no": expr_no,
          "task_name": task.get("name"),
          "step_index": int(step["index"]),
          "workstation": step["workstation"],
          "duration": step_duration(step),
      }
  return expected


def _operations(schedule) -> list[dict]:
  if isinstance(schedule, dict):
    operations = schedule.get("operations")
  else:
    operations = schedule
  if not isinstance(operations, list):
    raise TypeError("schedule must be a list or a dict with an operations list")
  return operations


def _over_capacity(intervals: list[tuple[float, float]], capacity: int) -> bool:
  events = []
  for start, end in intervals:
    events.append((start, 1))
    events.append((end, -1))
  active = 0
  for _, delta in sorted(events, key=lambda item: (item[0], item[1])):
    active += delta
    if active > capacity:
      return True
  return False


def validate_schedule(dataset: dict, schedule) -> tuple[bool, int | None, str | None]:
  if "fjspb" in dataset:
    return validate_fjspb_schedule(dataset["fjspb"], schedule)
  expected = expected_operations(dataset)
  capacities = workstation_capacities(dataset)
  robots = set(robot_codes(dataset))
  seen = {}
  by_task = defaultdict(list)
  by_workstation = defaultdict(list)
  by_robot = defaultdict(list)
  makespan = 0.0

  for op in _operations(schedule):
    expr_no = op.get("expr_no")
    step_index = int(op.get("step_index"))
    key = (expr_no, step_index)
    if key not in expected:
      return False, None, f"unexpected operation {key}"
    if key in seen:
      return False, None, f"duplicate operation {key}"
    spec = expected[key]
    workstation = op.get("workstation")
    if workstation != spec["workstation"]:
      return (
          False,
          None,
          f"operation {key} uses {workstation}, expected {spec['workstation']}",
      )
    start = float(op.get("start"))
    end = float(op.get("end"))
    if not math.isfinite(start) or not math.isfinite(end) or start < 0:
      return False, None, f"invalid time for operation {key}"
    if end - start + 1e-9 < spec["duration"]:
      return False, None, f"operation {key} shorter than duration {spec['duration']}"
    robot = op.get("robot")
    if robot is not None and robot not in robots:
      return False, None, f"unknown robot {robot} for operation {key}"
    seen[key] = op
    by_task[expr_no].append((step_index, start, end))
    by_workstation[workstation].append((start, end))
    if robot is not None:
      by_robot[robot].append((start, end))
    makespan = max(makespan, end)

  missing = sorted(set(expected) - set(seen))
  if missing:
    return False, None, f"missing operations: {missing[:5]}"

  for expr_no, ops in by_task.items():
    ordered = sorted(ops)
    for (_, _, prev_end), (step_index, start, _) in zip(ordered, ordered[1:]):
      if start + 1e-9 < prev_end:
        return False, None, f"task {expr_no} step {step_index} starts before predecessor ends"

  for workstation, intervals in by_workstation.items():
    if _over_capacity(intervals, capacities.get(workstation, 1)):
      return False, None, f"workstation capacity exceeded: {workstation}"

  for robot, intervals in by_robot.items():
    if _over_capacity(intervals, 1):
      return False, None, f"robot overlap: {robot}"

  return True, int(math.ceil(makespan)), None


def _assignments(schedule) -> list[dict]:
  if not isinstance(schedule, dict):
    raise TypeError("FJSPB schedule must be a dict with assignments")
  assignments = schedule.get("assignments")
  if assignments is None:
    assignments = _legacy_operations_to_assignments(schedule)
  if not isinstance(assignments, list):
    raise TypeError("FJSPB schedule must contain an assignments list")
  return assignments


def _legacy_operations_to_assignments(schedule: dict) -> list[dict]:
  operations = schedule.get("operations")
  if not isinstance(operations, list):
    raise TypeError("schedule must contain assignments or operations")
  result = []
  for op in operations:
    step_index = int(op.get("step_index"))
    result.append(
        {
            "job_id": op.get("job_id") or op.get("expr_no"),
            "task_id": int(op.get("task_id", step_index - 1)),
            "machine": op.get("machine") or op.get("workstation"),
            "start": op.get("start"),
            "end": op.get("end"),
        }
    )
  return result


def _fjspb_expected(fjspb: dict) -> dict[tuple[str, int], dict]:
  expected = {}
  for job in fjspb.get("jobs", []):
    for task in job.get("tasks", []):
      key = (job["job_id"], int(task["task_id"]))
      expected[key] = {"job": job, "task": task}
  return expected


def _intervals_overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
  return a[0] < b[1] and b[0] < a[1]


def _temperature(task: dict):
  params = task.get("parameters") or []
  for entry in params:
    if not isinstance(entry, dict):
      continue
    param = entry.get("param") or {}
    if "temperature" in param:
      raw = param["temperature"]
      parsed = _loads_json(raw)
      return parsed if parsed is not None else raw
    if "custom_param" in param:
      parsed = _loads_json(param["custom_param"])
      if isinstance(parsed, dict) and "temperature" in parsed:
        return parsed["temperature"]
  return None


def _frequency(task: dict):
  params = task.get("parameters") or []
  for entry in params:
    if not isinstance(entry, dict):
      continue
    param = entry.get("param") or {}
    if "frequency" in param:
      return param["frequency"]
  return None


def _loads_json(value):
  if not isinstance(value, str):
    return value
  try:
    return json.loads(value)
  except Exception:
    return None


def _over_capacity_fjspb(intervals: list[tuple[float, float]], capacity: int) -> bool:
  return _over_capacity(intervals, capacity)


def validate_fjspb_schedule(fjspb: dict, schedule) -> tuple[bool, int | None, str | None]:
  expected = _fjspb_expected(fjspb)
  machines = {str(k): int(v) for k, v in fjspb.get("machines", {}).items()}
  cur_ptr = int(fjspb.get("cur_ptr") or 0)
  seen = {}
  by_job = defaultdict(list)
  by_machine = defaultdict(list)
  task_info_by_key = {}
  makespan = 0.0

  for assignment in _assignments(schedule):
    job_id = assignment.get("job_id")
    task_id = int(assignment.get("task_id"))
    key = (job_id, task_id)
    if key not in expected:
      return False, None, f"unexpected assignment {key}"
    if key in seen:
      return False, None, f"duplicate assignment {key}"
    task = expected[key]["task"]
    machine = assignment.get("machine")
    if machine not in task.get("machines", []):
      return False, None, f"assignment {key} uses {machine}, candidates={task.get('machines')}"
    start = float(assignment.get("start"))
    end = float(assignment.get("end"))
    duration = int(task["duration"])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0:
      return False, None, f"invalid time for assignment {key}"
    if abs((end - start) - duration) > 1e-9:
      return False, None, f"assignment {key} duration {end - start} != {duration}"
    if task.get("is_fixed"):
      if (
          int(start) != int(task["fixed_start"])
          or int(end) != int(task["fixed_end"])
          or machine != task.get("scheduled_machine")
      ):
        return False, None, f"fixed assignment {key} changed"
    elif start + 1e-9 < cur_ptr:
      return False, None, f"non-fixed assignment {key} starts before cur_ptr={cur_ptr}"
    seen[key] = assignment
    by_job[job_id].append((task_id, start, end, machine))
    by_machine[machine].append((start, end, duration, key, task))
    task_info_by_key[key] = (start, end, machine, task)
    makespan = max(makespan, end)

  missing = sorted(set(expected) - set(seen))
  if missing:
    return False, None, f"missing assignments: {missing[:5]}"

  # ⚠ 不再强制「job 内 task_id 相邻不重叠」——那是 multi_bot_era 的串行工艺假设，
  # 对 flow_1160 的并行 DAG 会把所有 task 锁成全序链（makespan 恒=串行上界）。
  # job 内顺序由 precedence_pairs（显式边）+ cumulative（设备容量）共同保证，
  # 在下方 _validate_explicit_precedence 统一校验。

  for machine, rows in by_machine.items():
    cap = max(1, machines.get(machine, 1))
    # ⭐ cumulative scheduling：同设备任意时刻重叠 task 的 required_capacity 之和 <= cap。
    #    多板并行——一个 task 占 instance_count 个位（required_capacity）。
    #    端点按 (time, delta) 排序，end(-rc) 在 start(+rc) 前，临界点先释放再占用不假溢出。
    events = []
    for (start, end, _dur, _key, task) in rows:
      rc = max(1, int(task.get("required_capacity") or 1))
      events.append((start, rc))
      events.append((end, -rc))
    cur = 0
    for _, delta in sorted(events, key=lambda it: (it[0], it[1])):
      cur += delta
      if cur > cap:
        return False, None, f"machine capacity exceeded (cumulative): {machine}, need {cur} > cap {cap}"

  ok, error = _validate_drip_test_recycle(fjspb, task_info_by_key)
  if not ok:
    return False, None, error
  ok, error = _validate_temperature_mutex(by_machine)
  if not ok:
    return False, None, error
  ok, error = _validate_frequency_match(fjspb, task_info_by_key)
  if not ok:
    return False, None, error
  ok, error = _validate_centrifuge_even(by_machine)
  if not ok:
    return False, None, error
  ok, error = _validate_first_task_sync(fjspb, task_info_by_key)
  if not ok:
    return False, None, error
  ok, error = _validate_explicit_precedence(fjspb, task_info_by_key)
  if not ok:
    return False, None, error
  ok, error = _validate_branch_priority(fjspb, task_info_by_key)
  if not ok:
    return False, None, error

  return True, int(math.ceil(makespan)), None


def _validate_explicit_precedence(fjspb: dict, task_info_by_key: dict) -> tuple[bool, str | None]:
  """显式 precedence_pairs：每对 [a,b] 要求 assignment(a).end <= assignment(b).start。

  解决拓扑 task_id 序对并行兄弟表达弱的问题：即使 task_id 序允许，
  真实前后边（来自 flowData 连线传递闭包）也必须被尊重。
  """
  pairs = fjspb.get("precedence_pairs") or []
  if not pairs:
    return True, None
  by_tid = {}
  for (_jid, tid), info in task_info_by_key.items():
    by_tid.setdefault(int(tid), info)  # 单 job 下 tid 全局唯一
  errs = []
  for pair in pairs:
    a, b = int(pair[0]), int(pair[1])
    if a in by_tid and b in by_tid:
      a_end = by_tid[a][1]
      b_start = by_tid[b][0]
      a_task = by_tid[a][3]
      if a_end > b_start + 1e-9:
        errs.append("precedence %d->%d violated: end %s > start %s" % (a, b, a_end, b_start))
      # min_wait 硬约束：后继须在前驱 end + min_wait 之后才开始（静置/稳定要求）
      minw = int(a_task.get("min_wait") or 0)
      if minw and b_start < a_end + minw - 1e-9:
        errs.append("min_wait %d->%d violated: need %ds after end, gap %.0fs" % (a, b, minw, b_start - a_end))
  return (False, "; ".join(errs)) if errs else (True, None)


def _validate_branch_priority(fjspb: dict, task_info_by_key: dict) -> tuple[bool, str | None]:
  """UI P1/P2/P3 route priority: higher-priority branch starts first.

  This is not mutual exclusion. It only restores the start-order semantics of
  task-bearing branches shown in the flow graph.
  """
  pairs = fjspb.get("branch_priority_pairs") or []
  if not pairs:
    return True, None
  by_tid = {}
  for (_jid, tid), info in task_info_by_key.items():
    by_tid.setdefault(int(tid), info)
  errs = []
  for pair in pairs:
    hi = int(pair["higher_task_id"])
    lo = int(pair["lower_task_id"])
    if hi not in by_tid or lo not in by_tid:
      continue
    hi_start = by_tid[hi][0]
    lo_start = by_tid[lo][0]
    if hi_start > lo_start + 1e-9:
      errs.append(
          "branch priority from node %s violated: P%s task %d starts %s after P%s task %d starts %s"
          % (
              pair.get("from_node_id"),
              pair.get("higher_priority"),
              hi,
              hi_start,
              pair.get("lower_priority"),
              lo,
              lo_start,
          )
      )
  return (False, "; ".join(errs)) if errs else (True, None)


def _validate_drip_test_recycle(fjspb: dict, task_info_by_key: dict) -> tuple[bool, str | None]:
  groups = [
      ("electronic_dripping", "electronic_test", "electronic_recycle"),
      ("xrd_dripping", "xrd_test", "xrd_recycle"),
  ]
  for flags in groups:
    intervals = []
    for key, (start, end, _machine, task) in task_info_by_key.items():
      if any(task.get("flags", {}).get(flag) for flag in flags):
        intervals.append((start, end, key, task))
    for i in range(len(intervals)):
      for j in range(i + 1, len(intervals)):
        if _intervals_overlap(intervals[i][:2], intervals[j][:2]):
          return False, f"{flags} intervals overlap: {intervals[i][2]}, {intervals[j][2]}"
  for job in fjspb.get("jobs", []):
    tasks = job.get("tasks", [])
    for idx, task in enumerate(tasks):
      task_flags = task.get("flags", {})
      if not (task_flags.get("electronic_dripping") or task_flags.get("xrd_dripping")):
        continue
      if idx + 2 >= len(tasks):
        continue
      key0 = (job["job_id"], int(task["task_id"]))
      key1 = (job["job_id"], int(tasks[idx + 1]["task_id"]))
      key2 = (job["job_id"], int(tasks[idx + 2]["task_id"]))
      if key0 in task_info_by_key and key1 in task_info_by_key:
        if task_info_by_key[key0][1] != task_info_by_key[key1][0]:
          return False, f"dripping/test not back-to-back for {key0}"
      if key1 in task_info_by_key and key2 in task_info_by_key:
        if task_info_by_key[key1][1] != task_info_by_key[key2][0]:
          return False, f"test/recycle not back-to-back for {key1}"
  return True, None


def _validate_temperature_mutex(by_machine: dict) -> tuple[bool, str | None]:
  # 通用化：任一机器上两个带温度的 task，温度不同且时间重叠 -> 冲突。
  # （原 multi_bot_era 仅限 muffle_furnace/dryer_workstation；flow_1160 的培养箱/温控同样适用）
  for machine, rows in by_machine.items():
    for i in range(len(rows)):
      si, ei, _di, key_i, task_i = rows[i]
      temp_i = _temperature(task_i)
      if temp_i is None:
        continue
      for j in range(i + 1, len(rows)):
        sj, ej, _dj, key_j, task_j = rows[j]
        temp_j = _temperature(task_j)
        if temp_j is None:
          continue
        if temp_i != temp_j and _intervals_overlap((si, ei), (sj, ej)):
          return False, f"temperature conflict on {machine}: {key_i}({temp_i}C) vs {key_j}({temp_j}C)"
  return True, None


def _validate_frequency_match(fjspb: dict, task_info_by_key: dict) -> tuple[bool, str | None]:
  """频率匹配：task 有 frequency 需求时，分配机器的频率范围(machine_frequencies)须包含它。"""
  freqs = fjspb.get("machine_frequencies") or {}
  if not freqs:
    return True, None
  for (_jid, tid), info in task_info_by_key.items():
    task = info[3]
    f = _frequency(task)
    if f is None:
      continue
    machine = info[2]
    rng = freqs.get(machine)
    if rng is None:
      continue  # 该机器无频率能力信息，跳过
    lo, hi = rng
    if lo is not None and hi is not None and not (lo <= f <= hi):
      return False, f"frequency mismatch: task {tid} needs {f}rpm, machine {machine} range [{lo},{hi}]"
  return True, None


def _validate_centrifuge_even(by_machine: dict) -> tuple[bool, str | None]:
  for machine, rows in by_machine.items():
    if "centrifugation" not in machine:
      continue
    events = sorted({time for start, end, *_ in rows for time in (start, end)})
    for time in events:
      active = sum(1 for start, end, *_ in rows if start <= time < end)
      if active % 2 != 0:
        return False, f"centrifuge active count is odd on {machine} at {time}: {active}"
  return True, None


def _validate_first_task_sync(fjspb: dict, task_info_by_key: dict) -> tuple[bool, str | None]:
  by_expr = defaultdict(list)
  for job in fjspb.get("jobs", []):
    tasks = job.get("tasks", [])
    if not tasks:
      continue
    key = (job["job_id"], int(tasks[0]["task_id"]))
    if key in task_info_by_key:
      by_expr[job.get("expr_no")].append((key, task_info_by_key[key][0]))
  for expr_no, rows in by_expr.items():
    starts = {start for _, start in rows}
    if len(starts) > 1:
      return False, f"first task sync violated for expr_no={expr_no}: {rows[:5]}"
  return True, None


def score_schedule(dataset: dict, schedule, elapsed_seconds: float) -> tuple[float, bool, int | None, str | None]:
  try:
    feasible, makespan, error = validate_schedule(dataset, schedule)
  except Exception as exc:
    return WORST_SCORE, False, None, str(exc)
  if not feasible or makespan is None:
    return WORST_SCORE, False, None, error
  return (
      -(float(makespan) + elapsed_seconds / SCORE_RUNTIME_DIVISOR),
      True,
      makespan,
      None,
  )
