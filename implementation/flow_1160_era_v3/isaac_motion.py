"""Isaac-oriented robot motion layer for flow_1160_era_v3 schedules.

This module expands task-level plate transfers into conservative physical
robot actions. The generated action stream is usable by Isaac Sim and also by
the pure-Python monitor for fast collision/deadlock checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
import math
from typing import Any


@dataclass(frozen=True)
class MotionTiming:
  pick_seconds: int = 30
  move_seconds: int = 300
  place_seconds: int = 30
  drop_seconds: int = 10
  safety_gap_seconds: int = 10

  @property
  def transfer_seconds(self) -> int:
    return (
        int(self.pick_seconds)
        + int(self.move_seconds)
        + int(self.place_seconds)
        + int(self.drop_seconds)
        + int(self.safety_gap_seconds)
    )


def build_isaac_motion_events(
    dataset: dict,
    schedule: dict,
    *,
    timing: MotionTiming | None = None,
    robot_id: str = "robot:StackRobotA",
) -> dict:
  timing = timing or MotionTiming()
  fjspb = dataset.get("fjspb", {}) if isinstance(dataset, dict) else {}
  assignments = _assignments_by_task(schedule)
  transfers = _plate_transfers(fjspb, assignments, timing)
  robot_actions = _robot_actions(transfers, timing, robot_id)
  return {
      "timing": {
          "pick_seconds": timing.pick_seconds,
          "move_seconds": timing.move_seconds,
          "place_seconds": timing.place_seconds,
          "drop_seconds": timing.drop_seconds,
          "safety_gap_seconds": timing.safety_gap_seconds,
          "transfer_seconds": timing.transfer_seconds,
      },
      "robot_id": robot_id,
      "plate_transfers": transfers,
      "robot_actions": robot_actions,
      "motion_monitor": monitor_isaac_motion(fjspb, transfers, robot_actions),
  }


def monitor_isaac_motion(fjspb: dict, transfers: list[dict], robot_actions: list[dict]) -> dict:
  conflicts: list[dict] = []
  deadlocks: list[dict] = []
  warnings: list[dict] = []

  _check_arrival_windows(transfers, conflicts)
  _check_robot_calendar(robot_actions, conflicts)
  _check_device_port_calendar(robot_actions, conflicts)
  _check_plate_calendar(robot_actions, conflicts)
  _detect_motion_deadlocks(fjspb, transfers, deadlocks, warnings)

  return {
      "ok": not conflicts and not deadlocks,
      "conflict_count": len(conflicts),
      "deadlock_count": len(deadlocks),
      "warning_count": len(warnings),
      "conflicts": conflicts,
      "deadlocks": deadlocks,
      "warnings": warnings,
  }


def first_motion_error(report: dict) -> str | None:
  for key in ("conflicts", "deadlocks"):
    rows = report.get(key) or []
    if rows:
      row = rows[0]
      return "%s: %s" % (row.get("type", key), row.get("message", row))
  return None


def _assignments_by_task(schedule: dict) -> dict[int, dict]:
  result = {}
  if not isinstance(schedule, dict):
    return result
  for row in schedule.get("assignments") or []:
    if isinstance(row, dict) and row.get("task_id") is not None:
      result[int(row["task_id"])] = row
  return result


def _plate_transfers(fjspb: dict, assignments: dict[int, dict], timing: MotionTiming) -> list[dict]:
  transfers = []
  transfer_times = _device_transfer_time_lookup(fjspb)
  for edge in fjspb.get("material_edges") or []:
    src_task_id = edge.get("src_task_id")
    dst_task_id = edge.get("dst_task_id")
    if src_task_id is None or dst_task_id is None:
      continue
    src = assignments.get(int(src_task_id))
    dst = assignments.get(int(dst_task_id))
    if not src or not dst:
      continue
    ready_time = int(float(src.get("end")))
    need_by = int(float(dst.get("start")))
    from_device = src.get("machine")
    to_device = dst.get("machine")
    transfer_timing = _transfer_timing_for_devices(transfer_times, from_device, to_device, timing)
    transfer_id = "transfer:%s" % (edge.get("edge_id") or "%s_%s" % (src_task_id, dst_task_id))
    plate_id = _plate_id(edge)
    transfer_seconds = int(transfer_timing["transfer_seconds"])
    latest_start = need_by - transfer_seconds
    start = max(ready_time, latest_start)
    end = start + transfer_seconds
    transfers.append(
        {
            "transfer_id": transfer_id,
            "edge_id": edge.get("edge_id"),
            "src_task_id": int(src_task_id),
            "dst_task_id": int(dst_task_id),
            "plate_id": plate_id,
            "material_code": edge.get("material_code"),
            "plate_label": edge.get("plate_alias") or edge.get("plate_name") or edge.get("barcode_name"),
            "from_device": from_device,
            "to_device": to_device,
            "ready_time": ready_time,
            "need_by": need_by,
            "start": start,
            "end": end,
            "duration": transfer_seconds,
            "duration_source": transfer_timing.get("duration_source") or "isaac_motion_parameter_conservative",
            "motion_class": transfer_timing.get("motion_class"),
            "move_seconds": int(transfer_timing.get("move_seconds") or timing.move_seconds),
            "arrival_late": end > need_by,
        }
    )
  return sorted(transfers, key=lambda row: (row["start"], row["transfer_id"]))


def _robot_actions(transfers: list[dict], timing: MotionTiming, robot_id: str) -> list[dict]:
  actions = []
  cursor_by_robot = defaultdict(int)
  for transfer in transfers:
    start = max(int(transfer["start"]), cursor_by_robot[robot_id])
    segments = [
        ("pick", timing.pick_seconds, transfer["from_device"]),
        ("move", int(transfer.get("move_seconds") or timing.move_seconds), None),
        ("place", timing.place_seconds, transfer["to_device"]),
        ("drop", timing.drop_seconds + timing.safety_gap_seconds, transfer["to_device"]),
    ]
    t = start
    for kind, duration, device in segments:
      end = t + int(duration)
      actions.append(
          {
              "action_id": "%s:%s" % (transfer["transfer_id"], kind),
              "transfer_id": transfer["transfer_id"],
              "kind": kind,
              "robot_id": robot_id,
              "plate_id": transfer["plate_id"],
              "resource_id": robot_id,
              "device": device,
              "from_device": transfer["from_device"],
              "to_device": transfer["to_device"],
              "start": t,
              "end": end,
              "duration": int(duration),
              "duration_source": transfer["duration_source"],
          }
      )
      t = end
    cursor_by_robot[robot_id] = t
  return actions


def _device_transfer_time_lookup(fjspb: dict) -> dict[tuple[str, str], dict]:
  matrix = fjspb.get("device_transfer_times") or {}
  rows = matrix.get("rows") or []
  result = {}
  for row in rows:
    if not isinstance(row, dict):
      continue
    src = row.get("src_machine")
    dst = row.get("dst_machine")
    if src is None or dst is None:
      continue
    result[(str(src), str(dst))] = row
  return result


def _transfer_timing_for_devices(
    transfer_times: dict[tuple[str, str], dict],
    from_device: Any,
    to_device: Any,
    timing: MotionTiming,
) -> dict:
  row = transfer_times.get((str(from_device), str(to_device)))
  if row:
    return row
  return {
      "transfer_seconds": timing.transfer_seconds,
      "move_seconds": timing.move_seconds,
      "motion_class": "global_default",
      "duration_source": "isaac_motion_parameter_conservative",
  }


def _check_arrival_windows(transfers: list[dict], conflicts: list[dict]) -> None:
  for transfer in transfers:
    if int(transfer["end"]) > int(transfer["need_by"]):
      _conflict(
          conflicts,
          "robot_transfer_late",
          "%s arrives at %s after successor task %s starts at %s"
          % (transfer["transfer_id"], transfer["end"], transfer["dst_task_id"], transfer["need_by"]),
          transfer_id=transfer["transfer_id"],
          transfers=[transfer["transfer_id"]],
          task_ids=[transfer["src_task_id"], transfer["dst_task_id"]],
      )


def _check_robot_calendar(actions: list[dict], conflicts: list[dict]) -> None:
  grouped = defaultdict(list)
  for action in actions:
    grouped[action["robot_id"]].append(action)
  for robot_id, rows in grouped.items():
    _check_no_overlap(robot_id, rows, "robot_collision", conflicts)


def _check_device_port_calendar(actions: list[dict], conflicts: list[dict]) -> None:
  grouped = defaultdict(list)
  for action in actions:
    if action["kind"] in {"pick", "place", "drop"} and action.get("device"):
      grouped[str(action["device"])].append(action)
  for device, rows in grouped.items():
    _check_no_overlap(device, rows, "device_port_collision", conflicts)


def _check_plate_calendar(actions: list[dict], conflicts: list[dict]) -> None:
  grouped = defaultdict(list)
  for action in actions:
    grouped[str(action["plate_id"])].append(action)
  for plate_id, rows in grouped.items():
    _check_no_overlap(plate_id, rows, "plate_motion_collision", conflicts)


def _detect_motion_deadlocks(
    fjspb: dict,
    transfers: list[dict],
    deadlocks: list[dict],
    warnings: list[dict],
) -> None:
  buffer_count = sum(
      1
      for row in fjspb.get("positions") or []
      if isinstance(row, dict) and str(row.get("kind")) in {"buffer_slot", "stack_slot"}
  )
  by_pair = defaultdict(list)
  for transfer in transfers:
    by_pair[(transfer.get("from_device"), transfer.get("to_device"))].append(transfer)
  for (src, dst), rows in by_pair.items():
    reverse_rows = by_pair.get((dst, src)) or []
    if not reverse_rows:
      continue
    if src == dst:
      continue
    if buffer_count <= 0:
      _deadlock(
          deadlocks,
          "device_swap_no_buffer",
          "bidirectional plate exchange between %s and %s has no buffer position"
          % (src, dst),
          devices=[src, dst],
          transfers=[rows[0]["transfer_id"], reverse_rows[0]["transfer_id"]],
      )
      return
  if not any(t.get("from_device") and t.get("to_device") for t in transfers):
    _warning(warnings, "motion_deadlock_limited", "no concrete from/to devices in transfers")


def _check_no_overlap(resource_id: str, actions: list[dict], typ: str, conflicts: list[dict]) -> None:
  ordered = sorted(actions, key=lambda row: (row["start"], row["end"]))
  for prev, cur in zip(ordered, ordered[1:]):
    if int(cur["start"]) < int(prev["end"]):
      _conflict(
          conflicts,
          typ,
          "%s actions overlap: %s[%s,%s] and %s[%s,%s]"
          % (
              resource_id,
              prev["action_id"],
              prev["start"],
              prev["end"],
              cur["action_id"],
              cur["start"],
              cur["end"],
          ),
          resource_id=resource_id,
          actions=[prev["action_id"], cur["action_id"]],
          transfers=[prev.get("transfer_id"), cur.get("transfer_id")],
      )
      return


def _plate_id(edge: dict) -> str:
  parts = [
      edge.get("material_code") or "material",
      edge.get("barcode_type") or edge.get("barcode_name") or "barcode",
      edge.get("plate_alias") or edge.get("plate_name") or edge.get("edge_id") or "plate",
  ]
  return "plate:" + ":".join(_slug(part) for part in parts)


def _slug(value: Any) -> str:
  text = str(value).strip() if value is not None else "unknown"
  result = []
  for char in text:
    if char.isalnum():
      result.append(char)
    else:
      result.append("_")
  return ("".join(result).strip("_") or "unknown")[:80]


def _conflict(conflicts: list[dict], typ: str, message: str, **extra) -> None:
  conflicts.append({"type": typ, "message": message, **extra})


def _deadlock(deadlocks: list[dict], typ: str, message: str, **extra) -> None:
  deadlocks.append({"type": typ, "message": message, **extra})


def _warning(warnings: list[dict], typ: str, message: str, **extra) -> None:
  warnings.append({"type": typ, "message": message, **extra})
