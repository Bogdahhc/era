"""Conflict and deadlock monitor for flow_1160_era_v3 command schedules."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any


def monitor_schedule(dataset: dict, schedule: dict) -> dict:
  """Return structured v3 command-level diagnostics.

  This monitor is deliberately data-driven. It validates only fields exposed by
  the v3 IR or returned schedule; missing movement templates, travel times, or
  stable plate state remain warnings/data gaps instead of invented constraints.
  """
  fjspb = dataset.get("fjspb", {}) if isinstance(dataset, dict) else {}
  commands = _command_map(fjspb)
  assignments = _task_assignment_map(schedule)
  command_assignments = _command_assignment_rows(schedule)
  command_rows = _command_assignment_map(command_assignments)

  conflicts: list[dict] = []
  deadlocks: list[dict] = []
  warnings: list[dict] = []

  _check_command_shape(commands, command_assignments, command_rows, conflicts)
  _check_task_command_alignment(commands, assignments, command_rows, conflicts)
  _check_command_precedence(commands, assignments, command_rows, conflicts)
  _check_resource_calendars(fjspb, commands, command_assignments, conflicts)
  _check_position_calendars(fjspb, command_assignments, conflicts)
  _check_plate_calendars(fjspb, command_assignments, conflicts, warnings)
  _detect_wait_for_cycles(command_assignments, deadlocks)
  _detect_swap_deadlocks(fjspb, command_assignments, deadlocks, warnings)

  return {
      "ok": not conflicts and not deadlocks,
      "conflict_count": len(conflicts),
      "deadlock_count": len(deadlocks),
      "warning_count": len(warnings),
      "conflicts": conflicts,
      "deadlocks": deadlocks,
      "warnings": warnings,
      "counts": {
          "device_commands": len(commands),
          "command_assignments": len(command_assignments),
          "task_assignments": len(assignments),
      },
  }


def first_error(report: dict) -> str | None:
  for key in ("conflicts", "deadlocks"):
    rows = report.get(key) or []
    if rows:
      row = rows[0]
      return "%s: %s" % (row.get("type", key), row.get("message", row))
  return None


def _command_map(fjspb: dict) -> dict[str, dict]:
  return {
      str(command.get("command_id")): command
      for command in fjspb.get("device_commands") or []
      if isinstance(command, dict) and command.get("command_id") is not None
  }


def _task_assignment_map(schedule: dict) -> dict[int, dict]:
  result = {}
  if not isinstance(schedule, dict):
    return result
  for row in schedule.get("assignments") or []:
    if not isinstance(row, dict) or row.get("task_id") is None:
      continue
    result[int(row["task_id"])] = row
  return result


def _command_assignment_rows(schedule: dict) -> list[dict]:
  if not isinstance(schedule, dict):
    return []
  rows = schedule.get("command_assignments") or []
  return rows if isinstance(rows, list) else []


def _command_assignment_map(rows: list[dict]) -> dict[str, list[dict]]:
  result = defaultdict(list)
  for row in rows:
    if isinstance(row, dict) and row.get("command_id") is not None:
      result[str(row["command_id"])].append(row)
  return dict(result)


def _check_command_shape(
    commands: dict[str, dict],
    rows: list[dict],
    rows_by_command: dict[str, list[dict]],
    conflicts: list[dict],
) -> None:
  required = ("command_id", "start", "end", "resource_id")
  for index, row in enumerate(rows):
    if not isinstance(row, dict):
      _conflict(conflicts, "command_shape", "command assignment row %d is not a dict" % index)
      continue
    missing = [field for field in required if field not in row]
    if missing:
      _conflict(conflicts, "command_shape", "command %r missing fields %s" % (row.get("command_id"), missing))
      continue
    command_id = str(row["command_id"])
    if command_id not in commands:
      _conflict(conflicts, "unknown_command", "returned unknown command_id %s" % command_id)
    start, end = _time(row.get("start")), _time(row.get("end"))
    if start is None or end is None or start < 0 or end < start:
      _conflict(conflicts, "command_time", "command %s has invalid interval [%r, %r]" % (command_id, row.get("start"), row.get("end")))

  for command_id, command in commands.items():
    if command.get("kind") == "device_run" and command_id not in rows_by_command:
      _conflict(conflicts, "missing_command", "missing device_run command assignment %s" % command_id)
  for command_id, command_rows in rows_by_command.items():
    if len(command_rows) > 1:
      _conflict(conflicts, "duplicate_command", "duplicate command_assignment rows for %s" % command_id)


def _check_task_command_alignment(
    commands: dict[str, dict],
    task_assignments: dict[int, dict],
    command_rows: dict[str, list[dict]],
    conflicts: list[dict],
) -> None:
  for command_id, command in commands.items():
    if command.get("kind") != "device_run":
      continue
    task_id = command.get("task_id")
    if task_id is None:
      continue
    task_id = int(task_id)
    task_row = task_assignments.get(task_id)
    rows = command_rows.get(command_id) or []
    if task_row is None or not rows:
      continue
    row = rows[0]
    for field in ("start", "end"):
      if _time(row.get(field)) != _time(task_row.get(field)):
        _conflict(conflicts, "task_command_alignment", "%s %s=%s does not match task %s=%s" % (command_id, field, row.get(field), task_id, task_row.get(field)))
    command_resource = str(row.get("resource_id"))
    task_machine = str(task_row.get("machine"))
    if command_resource != task_machine:
      _conflict(conflicts, "task_command_alignment", "%s resource %s does not match task %s machine %s" % (command_id, command_resource, task_id, task_machine))


def _check_command_precedence(
    commands: dict[str, dict],
    task_assignments: dict[int, dict],
    command_rows: dict[str, list[dict]],
    conflicts: list[dict],
) -> None:
  for command_id, command in commands.items():
    rows = command_rows.get(command_id) or []
    if not rows:
      continue
    row = rows[0]
    start = _time(row.get("start"))
    if start is None:
      continue
    for pred_id in command.get("predecessor_command_ids") or []:
      pred_rows = command_rows.get(str(pred_id)) or []
      if pred_rows:
        pred_end = _time(pred_rows[0].get("end"))
        if pred_end is not None and start < pred_end:
          _conflict(conflicts, "command_precedence", "%s starts %s before predecessor command %s ends %s" % (command_id, start, pred_id, pred_end))
    for task_id in command.get("predecessor_task_ids") or []:
      task_row = task_assignments.get(int(task_id))
      if task_row:
        task_end = _time(task_row.get("end"))
        if task_end is not None and start < task_end:
          _conflict(conflicts, "command_precedence", "%s starts %s before predecessor task %s ends %s" % (command_id, start, task_id, task_end))
    end = _time(row.get("end"))
    if end is None:
      continue
    for task_id in command.get("successor_task_ids") or []:
      task_row = task_assignments.get(int(task_id))
      if task_row:
        task_start = _time(task_row.get("start"))
        if task_start is not None and task_start < end:
          _conflict(conflicts, "command_precedence", "successor task %s starts %s before %s ends %s" % (task_id, task_start, command_id, end))


def _check_resource_calendars(
    fjspb: dict,
    commands: dict[str, dict],
    rows: list[dict],
    conflicts: list[dict],
) -> None:
  capacities = _resource_capacities(fjspb)
  grouped = defaultdict(list)
  for row in rows:
    if not isinstance(row, dict):
      continue
    start, end = _time(row.get("start")), _time(row.get("end"))
    if start is None or end is None or end <= start:
      continue
    command = commands.get(str(row.get("command_id"))) or {}
    demand = _resource_demand(command, row)
    for resource_id in _row_resources(row):
      grouped[str(resource_id)].append((start, end, demand, row.get("command_id")))
  for resource_id, intervals in grouped.items():
    cap = max(1, int(capacities.get(resource_id, 1)))
    _check_cumulative_resource(resource_id, intervals, cap, "resource_conflict", conflicts)


def _check_position_calendars(fjspb: dict, rows: list[dict], conflicts: list[dict]) -> None:
  capacities = {
      str(position.get("position_id")): max(1, int(position.get("capacity") or 1))
      for position in fjspb.get("positions") or []
      if isinstance(position, dict) and position.get("position_id")
  }
  grouped = defaultdict(list)
  for row in rows:
    position_id = row.get("position_id") if isinstance(row, dict) else None
    if not position_id:
      continue
    start, end = _time(row.get("start")), _time(row.get("end"))
    if start is None or end is None or end <= start:
      continue
    grouped[str(position_id)].append((start, end, 1, row.get("command_id")))
  for position_id, intervals in grouped.items():
    _check_cumulative_resource(position_id, intervals, max(1, int(capacities.get(position_id, 1))), "position_conflict", conflicts)


def _check_plate_calendars(
    fjspb: dict,
    rows: list[dict],
    conflicts: list[dict],
    warnings: list[dict],
) -> None:
  stable_plate_ids = {
      str(row.get("plate_id"))
      for row in fjspb.get("plate_states") or []
      if isinstance(row, dict) and row.get("plate_id") and row.get("initial_position_id")
  }
  grouped = defaultdict(list)
  for row in rows:
    if not isinstance(row, dict) or not row.get("plate_id"):
      continue
    plate_id = str(row["plate_id"])
    start, end = _time(row.get("start")), _time(row.get("end"))
    if start is None or end is None or end <= start:
      continue
    grouped[plate_id].append((start, end, 1, row.get("command_id")))
  for plate_id, intervals in grouped.items():
    if plate_id not in stable_plate_ids:
      _warning(warnings, "plate_identity_audit_only", "plate %s lacks stable initial_position_id; overlap is audit-only" % plate_id)
      continue
    _check_cumulative_resource(plate_id, intervals, 1, "plate_conflict", conflicts)


def _detect_wait_for_cycles(rows: list[dict], deadlocks: list[dict]) -> None:
  graph = defaultdict(set)
  command_by_resource = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    command_id = row.get("command_id")
    if command_id is None:
      continue
    for resource_id in _row_resources(row):
      command_by_resource[str(resource_id)] = str(command_id)
  for row in rows:
    if not isinstance(row, dict) or row.get("command_id") is None:
      continue
    command_id = str(row["command_id"])
    for key in ("waits_for_resource_id", "waits_for_position_id"):
      waiting_for = row.get(key)
      if waiting_for is not None and str(waiting_for) in command_by_resource:
        graph[command_id].add(command_by_resource[str(waiting_for)])
  cycle = _find_cycle(graph)
  if cycle:
    _deadlock(deadlocks, "wait_for_cycle", "wait-for cycle detected: %s" % " -> ".join(cycle), cycle=cycle)


def _detect_swap_deadlocks(
    fjspb: dict,
    rows: list[dict],
    deadlocks: list[dict],
    warnings: list[dict],
) -> None:
  capacity = {
      str(position.get("position_id")): max(1, int(position.get("capacity") or 1))
      for position in fjspb.get("positions") or []
      if isinstance(position, dict) and position.get("position_id")
  }
  buffer_positions = {
      str(position.get("position_id"))
      for position in fjspb.get("positions") or []
      if isinstance(position, dict)
      and position.get("position_id")
      and str(position.get("kind")) in {"buffer_slot", "stack_slot"}
  }
  moves = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    src = row.get("from_position_id")
    dst = row.get("to_position_id")
    plate = row.get("plate_id")
    if not src or not dst or not plate:
      continue
    moves.append((str(src), str(dst), str(plate), row))
  if not moves:
    _warning(warnings, "deadlock_audit_limited", "no from_position_id/to_position_id/plate_id command rows; physical swap deadlock detection is limited")
    return
  for i, (src_a, dst_a, plate_a, row_a) in enumerate(moves):
    for src_b, dst_b, plate_b, row_b in moves[i + 1:]:
      if plate_a == plate_b:
        continue
      if src_a == dst_b and dst_a == src_b and capacity.get(src_a, 1) == 1 and capacity.get(dst_a, 1) == 1:
        usable_buffer = sorted(pos for pos in buffer_positions if pos not in {src_a, dst_a} and capacity.get(pos, 1) > 0)
        if not usable_buffer:
          _deadlock(
              deadlocks,
              "single_slot_swap_no_buffer",
              "commands %s and %s swap plates between single-capacity positions %s/%s without an available buffer"
              % (row_a.get("command_id"), row_b.get("command_id"), src_a, dst_a),
              commands=[row_a.get("command_id"), row_b.get("command_id")],
              positions=[src_a, dst_a],
          )


def _resource_capacities(fjspb: dict) -> dict[str, int]:
  capacities = {str(k): max(1, int(v)) for k, v in (fjspb.get("machines") or {}).items()}
  for row in fjspb.get("robot_resources") or []:
    if isinstance(row, dict) and row.get("resource_id"):
      capacities[str(row["resource_id"])] = max(1, int(row.get("capacity") or 1))
  for row in fjspb.get("logistics_resources") or []:
    if isinstance(row, dict) and row.get("id"):
      capacities[str(row["id"])] = max(1, int(row.get("capacity") or 1))
  for row in fjspb.get("buffers") or []:
    if isinstance(row, dict) and row.get("id"):
      capacities[str(row["id"])] = max(1, int(row.get("capacity") or 1))
  for row in fjspb.get("positions") or []:
    if isinstance(row, dict) and row.get("position_id"):
      capacities[str(row["position_id"])] = max(1, int(row.get("capacity") or 1))
  return capacities


def _row_resources(row: dict) -> list[str]:
  resources = []
  if row.get("resource_id") is not None:
    resources.append(str(row["resource_id"]))
  for resource_id in row.get("resource_ids") or []:
    resources.append(str(resource_id))
  if row.get("position_id") is not None:
    resources.append(str(row["position_id"]))
  return sorted(set(resources))


def _resource_demand(command: dict, row: dict) -> int:
  if row.get("required_capacity") is not None:
    return max(1, int(row.get("required_capacity") or 1))
  if command.get("required_capacity") is not None:
    return max(1, int(command.get("required_capacity") or 1))
  if command.get("kind") == "device_run" and command.get("task_id") is not None:
    return 1
  return 1


def _check_cumulative_resource(
    resource_id: str,
    intervals: list[tuple[float, float, int, Any]],
    capacity: int,
    conflict_type: str,
    conflicts: list[dict],
) -> None:
  events = []
  for start, end, demand, command_id in intervals:
    events.append((start, demand, command_id))
    events.append((end, -demand, command_id))
  active = 0
  active_ids = set()
  for time, delta, command_id in sorted(events, key=lambda item: (item[0], item[1])):
    if delta < 0:
      active += delta
      active_ids.discard(command_id)
    else:
      active += delta
      active_ids.add(command_id)
    if active > capacity:
      _conflict(
          conflicts,
          conflict_type,
          "%s capacity exceeded at %s: need %s > cap %s" % (resource_id, time, active, capacity),
          resource_id=resource_id,
          time=time,
          active_commands=sorted(str(item) for item in active_ids),
      )
      return


def _find_cycle(graph: dict[str, set[str]]) -> list[str] | None:
  seen = set()
  stack = []
  in_stack = set()

  def visit(node: str) -> list[str] | None:
    seen.add(node)
    stack.append(node)
    in_stack.add(node)
    for nxt in graph.get(node, ()):
      if nxt not in seen:
        found = visit(nxt)
        if found:
          return found
      elif nxt in in_stack:
        start = stack.index(nxt)
        return stack[start:] + [nxt]
    stack.pop()
    in_stack.remove(node)
    return None

  for node in list(graph):
    if node not in seen:
      found = visit(node)
      if found:
        return found
  return None


def _time(value: Any) -> float | None:
  try:
    result = float(value)
  except Exception:
    return None
  return result if math.isfinite(result) else None


def _conflict(conflicts: list[dict], typ: str, message: str, **extra) -> None:
  conflicts.append({"type": typ, "message": message, **extra})


def _deadlock(deadlocks: list[dict], typ: str, message: str, **extra) -> None:
  deadlocks.append({"type": typ, "message": message, **extra})


def _warning(warnings: list[dict], typ: str, message: str, **extra) -> None:
  warnings.append({"type": typ, "message": message, **extra})
