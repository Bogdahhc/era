"""Device-command IR builder for flow_1160_era_v3.

The v3 layer is intentionally conservative: it exposes command-level objects
only where project 1160 already has independently visible task/logistics/
position structure. Missing robot travel times, from/to route matrices, stable
plate identity, and initial stock bindings are recorded as blocked boundaries
instead of guessed as hard constraints.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def build_command_ir(project: dict, fjspb: dict, *, history_policy_mode: str) -> dict:
  positions = _positions(project)
  robot_resources = _robot_resources(fjspb, positions)
  plate_states = _plate_states(fjspb)
  task_commands = _task_run_commands(fjspb)
  logistics_commands = _logistics_commands(fjspb)
  device_commands = task_commands + logistics_commands
  command_templates = _command_templates(device_commands)
  boundaries = _command_realization_boundaries(
      device_commands,
      positions,
      plate_states,
      robot_resources,
      history_policy_mode=history_policy_mode,
  )
  return {
      "device_commands": device_commands,
      "positions": positions,
      "plate_states": plate_states,
      "robot_resources": robot_resources,
      "command_templates": command_templates,
      "command_realization_boundaries": boundaries,
  }


def _positions(project: dict) -> list[dict]:
  result = []
  seen = set()
  for index, row in enumerate(project.get("positions", []) or []):
    device_name = row.get("deviceName") or row.get("deviceCode") or "unknown_device"
    position_id = _position_id(row, index, device_name)
    if position_id in seen:
      continue
    seen.add(position_id)
    result.append(
        {
            "position_id": position_id,
            "device_name": device_name,
            "kind": _position_kind(row, device_name),
            "capacity": 1,
            "reachable_by_robot": _reachable_by_robot(device_name),
            "source": "devicePosition",
            "raw_id": row.get("id"),
            "raw_position_code": row.get("positionCode") or row.get("positionName"),
        }
    )
  return sorted(result, key=lambda item: item["position_id"])


def _position_id(row: dict, index: int, device_name: str) -> str:
  raw = row.get("id") or row.get("positionCode") or row.get("positionName") or row.get("level") or index
  return "pos:%s:%s" % (_slug(device_name), _slug(raw))


def _position_kind(row: dict, device_name: str) -> str:
  text = " ".join(str(row.get(key) or "") for key in ("positionName", "positionCode", "typeName", "remark"))
  if "Stack" in device_name or "堆栈" in device_name or "栈" in text:
    return "stack_slot"
  if "Buffer" in device_name or "缓存" in text:
    return "buffer_slot"
  if "进" in text or "入" in text:
    return "input_port"
  if "出" in text or "退" in text:
    return "output_port"
  return "device_slot"


def _reachable_by_robot(device_name: str) -> bool:
  return bool(device_name) and device_name != "unknown_device"


def _robot_resources(fjspb: dict, positions: list[dict]) -> list[dict]:
  reachable = [row["position_id"] for row in positions if row.get("reachable_by_robot")]
  resources = []
  for row in fjspb.get("logistics_resources") or []:
    if not isinstance(row, dict):
      continue
    resource_id = str(row.get("id") or "")
    resource_type = str(row.get("type") or "")
    if not resource_id:
      continue
    if resource_type in {"stacker", "transport", "loader", "port"} or "StackRobot" in resource_id:
      resources.append(
          {
              "resource_id": resource_id,
              "capacity": int(row.get("capacity") or 1),
              "reachable_positions": reachable,
              "source": row.get("source") or "logistics_resources",
          }
      )
  if not resources and reachable:
    resources.append(
        {
            "resource_id": "robot:StackRobotA",
            "capacity": 1,
            "reachable_positions": reachable,
            "source": "fallback_from_reachable_device_positions",
        }
    )
  return sorted(resources, key=lambda item: item["resource_id"])


def _plate_states(fjspb: dict) -> list[dict]:
  labels = []
  for link in fjspb.get("material_lineage_links") or []:
    if not isinstance(link, dict):
      continue
    for key in ("source_plate_label", "destination_plate_label", "plate_alias"):
      value = link.get(key)
      if value:
        labels.append(str(value))
  result = []
  for label in sorted(set(labels)):
    result.append(
        {
            "plate_id": "plate:%s" % _slug(label),
            "barcode_material": label,
            "initial_position_id": None,
            "source_confidence": "lineage_label_only_no_initial_position",
        }
    )
  return result


def _task_run_commands(fjspb: dict) -> list[dict]:
  commands = []
  for job in fjspb.get("jobs") or []:
    for task in job.get("tasks") or []:
      task_id = int(task.get("task_id"))
      command_id = "cmd:task:%s:run" % task_id
      commands.append(
          {
              "command_id": command_id,
              "task_id": task_id,
              "kind": "device_run",
              "resource_ids": [str(machine) for machine in task.get("machines") or []],
              "duration": int(task.get("duration") or 0),
              "duration_source": task.get("duration_source") or "task_duration_minutes_x60",
              "predecessor_command_ids": [],
              "predecessor_task_ids": [],
              "successor_task_ids": [],
              "from_position_id": None,
              "to_position_id": None,
              "plate_id": None,
              "effects": ["task_start_end_alignment", "machine_capacity_calendar"],
              "realization": "hard_ready_task_run_summary",
          }
      )
  return commands


def _logistics_commands(fjspb: dict) -> list[dict]:
  commands = []
  for event in fjspb.get("logistics_events") or []:
    if not isinstance(event, dict):
      continue
    command_id = "cmd:logistics:%s" % (event.get("id") or event.get("node_id"))
    resources = [str(item) for item in event.get("resources") or []]
    buffer_ids = [str(item) for item in event.get("buffer_ids") or []]
    commands.append(
        {
            "command_id": command_id,
            "task_id": None,
            "kind": "logistics_%s" % (event.get("kind") or "event"),
            "resource_ids": resources + buffer_ids,
            "duration": int(event.get("duration") or 0),
            "duration_source": event.get("duration_source") or "unknown",
            "predecessor_command_ids": [],
            "predecessor_task_ids": [int(x) for x in event.get("predecessor_task_ids") or []],
            "successor_task_ids": [int(x) for x in event.get("successor_task_ids") or []],
            "from_position_id": None,
            "to_position_id": None,
            "plate_id": None,
            "effects": _logistics_effects(event),
            "source_logistics_event_id": event.get("id"),
            "realization": "precedence_only" if int(event.get("duration") or 0) <= 0 else "resource_interval_candidate",
        }
    )
  return commands


def _logistics_effects(event: dict) -> list[str]:
  effects = ["task_predecessor_successor_precedence"]
  if event.get("resources"):
    effects.append("resource_calendar")
  if event.get("buffer_ids"):
    effects.append("position_capacity_calendar")
  if event.get("planning_duration_required"):
    effects.append("blocked_positive_duration_missing")
  return effects


def _command_templates(commands: list[dict]) -> list[dict]:
  counts = Counter(command.get("kind") for command in commands)
  return [
      {
          "template_id": "template:%s" % _slug(kind),
          "kind": kind,
          "count": count,
          "source": "derived_from_v2_task_or_logistics_event",
          "hard_model_rule": _template_rule(kind),
      }
      for kind, count in sorted(counts.items())
      if kind
  ]


def _template_rule(kind: str) -> str:
  if kind == "device_run":
    return "bind task start/end to this command and use machine cumulative capacity"
  return "model as command interval only when duration_source is explicit non-history and resource_ids are present; otherwise preserve precedence topology"


def _command_realization_boundaries(
    commands: list[dict],
    positions: list[dict],
    plate_states: list[dict],
    robot_resources: list[dict],
    *,
    history_policy_mode: str,
) -> dict:
  hard_ready = [
      {
          "name": "task_run_command_alignment",
          "count": sum(1 for command in commands if command.get("kind") == "device_run"),
          "required_fields": ["task_id", "duration", "resource_ids"],
          "allowed_cp_sat": ["task start/end equals device_run command start/end"],
      },
      {
          "name": "position_capacity_from_devicePosition",
          "count": len(positions),
          "required_fields": ["position_id", "capacity", "device_name"],
          "allowed_cp_sat": ["AddCumulative or AddNoOverlap when command from/to occupancy exists"],
      },
      {
          "name": "robot_resource_capacity",
          "count": len(robot_resources),
          "required_fields": ["resource_id", "capacity", "reachable_positions"],
          "allowed_cp_sat": ["AddNoOverlap for robot command intervals with explicit duration"],
      },
  ]
  audit_only = [
      {
          "name": "plate_identity_labels",
          "count": len(plate_states),
          "reason": "labels preserve lineage context but do not prove stable physical identity or initial position",
      },
      {
          "name": "zero_duration_logistics_topology",
          "count": sum(1 for command in commands if command.get("duration") == 0 and str(command.get("kind", "")).startswith("logistics_")),
          "reason": "strict cold-start hides historical spans; zero-duration commands keep topology only",
      },
  ]
  blocked_missing_fields = [
      {
          "name": "robot_move_duration_matrix",
          "missing_fields": ["from_position_id", "to_position_id", "moveDuration/transferDuration", "path distance/speed"],
          "upgrade_rule": "Only assign positive move durations when platform exports path/time data independent of history.",
      },
      {
          "name": "pick_place_duration_and_direction",
          "missing_fields": ["pickDuration", "placeDuration", "load/unload direction", "device port mapping"],
          "upgrade_rule": "Only split logistics commands into pick/move/place when explicit action templates exist.",
      },
      {
          "name": "stable_plate_position_state",
          "missing_fields": ["stable plate barcode across all edges", "initial_position_id", "command from/to positions"],
          "upgrade_rule": "Only enforce one-position-per-plate and deadlock checks when identity and positions are explicit.",
      },
      {
          "name": "online_replan_state",
          "missing_fields": ["rolling_state timestamp", "fixed in-flight command occupancy", "new experiment insertion contract"],
          "upgrade_rule": "Only score stability and <15s online replans when rolling state is exported.",
      },
  ]
  return {
      "interface": {
          "history_policy": history_policy_mode,
          "contract": "Hard-model only command fields with independent platform evidence; missing command semantics remain blocked data requirements.",
      },
      "state": {
          "required_hard_constraints": [_state_row(row, "required_hard", True) for row in hard_ready],
          "audit_controls": [_state_row(row, "audit_enabled", False) for row in audit_only],
          "blocked_controls": [_state_row(row, "blocked_missing_fields", False) for row in blocked_missing_fields],
      },
      "hard_ready": hard_ready,
      "audit_only": audit_only,
      "blocked_missing_fields": blocked_missing_fields,
  }


def _state_row(row: dict, status: str, hard_constraint: bool) -> dict:
  return {
      "name": row.get("name"),
      "status": status,
      "enabled": True,
      "hard_constraint": bool(hard_constraint),
  }


def _slug(value: Any) -> str:
  text = str(value).strip() if value is not None else "unknown"
  result = []
  for char in text:
    if char.isalnum():
      result.append(char)
    else:
      result.append("_")
  slug = "".join(result).strip("_")
  return slug or "unknown"
