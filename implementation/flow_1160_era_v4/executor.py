"""execute_fn implementation for flow_1160_era_v4 candidates."""

from __future__ import annotations

import time

from implementation.flow_1160_era.executor import (
    Evaluation,
    Flow1160Executor,
    WORST_SCORE,
    _disallowed_solver_shortcut,
    _uses_cp_sat,
)
from implementation.flow_1160_era.sandbox import run_candidate
from implementation.flow_1160_era.scorer import score_schedule
from implementation.flow_1160_era_v4.isaac_motion import build_isaac_motion_events, first_motion_error
from implementation.flow_1160_era_v4.schedule_monitor import first_error, monitor_schedule


ISAAC_MOTION_CONFLICT_PENALTY = 100_000.0
ISAAC_MOTION_DEADLOCK_PENALTY = 1_000_000.0
EXTERNAL_ISAAC_CONFLICT_PENALTY = 1_000_000.0
EXPLICIT_MOTION_CONFLICT_TYPES = {
    "robot_collision",
    "device_port_collision",
    "plate_motion_collision",
}
EXPLICIT_MOTION_DEADLOCK_TYPES = {
    "device_swap_no_buffer",
}


class Flow1160V4Executor(Flow1160Executor):
  """V4 executor keeps v1 scoring but requires v4/v3 constraints to be modeled."""

  def evaluate(self, problem, solution) -> Evaluation:
    started = time.perf_counter()
    self.last_schedule = None
    self.last_motion_report = None
    self.last_motion_feedback = None
    code = getattr(solution, "program", "") or ""
    if not _uses_cp_sat(code):
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          "candidate rejected: flow_1160_era_v4 requires OR-Tools CP-SAT",
      )
      self.last_evaluation = evaluation
      return evaluation
    shortcut_reason = _disallowed_solver_shortcut(code)
    if shortcut_reason:
      evaluation = Evaluation(WORST_SCORE, False, None, time.perf_counter() - started, shortcut_reason)
      self.last_evaluation = evaluation
      return evaluation
    v4_reason = _missing_v4_constraint_surface(code)
    if v4_reason:
      evaluation = Evaluation(WORST_SCORE, False, None, time.perf_counter() - started, v4_reason)
      self.last_evaluation = evaluation
      return evaluation

    result = run_candidate(code, problem.dataset, timeout_seconds=self.timeout_seconds)
    elapsed_seconds = time.perf_counter() - started
    if not result["ok"]:
      evaluation = Evaluation(WORST_SCORE, False, None, elapsed_seconds, result["error"])
      self.last_evaluation = evaluation
      return evaluation
    self.last_schedule = result["schedule"]
    schedule_reason = _invalid_v4_schedule(problem.dataset, result["schedule"])
    if schedule_reason:
      evaluation = Evaluation(WORST_SCORE, False, None, elapsed_seconds, schedule_reason)
      self.last_evaluation = evaluation
      return evaluation
    score, feasible, makespan, error = score_schedule(problem.dataset, result["schedule"], elapsed_seconds)
    if feasible:
      motion_error, motion, motion_feedback = _isaac_motion_blocking_error(problem.dataset, result["schedule"])
      self.last_motion_report = motion
      self.last_motion_feedback = motion_feedback
      if motion_error:
        evaluation = Evaluation(WORST_SCORE, False, makespan, elapsed_seconds, motion_error)
        self.last_evaluation = evaluation
        return evaluation
    evaluation = Evaluation(score, feasible, makespan, elapsed_seconds, error)
    self.last_evaluation = evaluation
    return evaluation


def _missing_v4_constraint_surface(code: str) -> str | None:
  required_tokens = [
      "seed_instance",
      "selected_task_ids",
      "disabled_task_reason",
      "material_traversals",
      "plate_instances",
      "required_initial_materials",
      "initial_device_loads",
      "initial_position_loads",
      "load_parameter_bindings",
      "load_compatibility_report",
      "flow_parallelism_hints",
      "hard_initial_inventory",
      "seed_realization_boundaries",
      "material_edges",
      "hard_precedence_candidate",
      "material_inventory_events",
      "material_conservation_model",
      "platform_realism_sources",
      "material_lineage_links",
      "constraint_realization_boundaries",
      "history_policy",
      "logistics_events",
      "buffers",
      "buffer_ids",
      "isaac_motion_timing",
      "transfer_seconds",
      "device_transfer_times",
      "existing_machine_occupancy",
      "rolling_state",
      "device_commands",
      "positions",
      "plate_states",
      "robot_resources",
      "command_templates",
      "command_realization_boundaries",
      "command_assignments",
  ]
  missing = [token for token in required_tokens if token not in code]
  if missing:
    return "candidate rejected: v4 solver must explicitly model/read %s" % ", ".join(missing)
  if "AddNoOverlap" not in code:
    return "candidate rejected: v4 device_commands/logistics_events require AddNoOverlap resource calendars"
  if "AddCumulative" not in code:
    return "candidate rejected: v4 solver must preserve cumulative machine/position calendars"
  if "AddReservoirConstraint" not in code:
    return "candidate rejected: v4 material_inventory_events require AddReservoirConstraint"
  if "status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)" in code and "cur_ptr + duration" in code:
    return "candidate rejected: v4 solver must not return unverified cur_ptr fallback assignments"
  if "historical_replay" in code and "strict_cold_start" not in code:
    return "candidate rejected: cold-start solver must not force historical_replay semantics"
  return None


def _isaac_motion_blocking_error(dataset: dict, schedule: dict) -> tuple[str | None, dict, dict]:
  motion = build_isaac_motion_events(dataset, schedule)
  report = motion.get("motion_monitor") or {}
  conflict_count = int(report.get("conflict_count") or 0)
  deadlock_count = int(report.get("deadlock_count") or 0)
  external_conflicts = _external_isaac_conflicts(schedule)
  feedback = _motion_feedback(motion, external_conflicts)
  if conflict_count <= 0 and deadlock_count <= 0 and not external_conflicts:
    return None, motion, feedback
  first = first_motion_error(report)
  if external_conflicts and not first:
    first = "external_isaac_conflict: %s" % external_conflicts[0]
  task_ids = _penalized_task_ids(motion, external_conflicts)
  return (
      "candidate rejected: Isaac/motion monitor found conflicts or deadlocks "
      "conflicts=%d deadlocks=%d external_isaac_conflicts=%d "
      "penalized_task_ids=%s first=%s"
      % (conflict_count, deadlock_count, len(external_conflicts), task_ids[:12], first)
  ), motion, feedback


def _motion_feedback(motion: dict, external_conflicts: list[dict]) -> dict:
  """Classify motion failures for FUTS feedback.

  Late arrivals are timing/gap evidence. Resource calendar collisions and
  deadlocks are explicit physical conflicts that the next solver should promote
  into hard CP-SAT resource constraints when the required fields are present.
  """

  report = motion.get("motion_monitor") or {}
  conflicts = [row for row in report.get("conflicts") or [] if isinstance(row, dict)]
  deadlocks = [row for row in report.get("deadlocks") or [] if isinstance(row, dict)]
  explicit_conflicts = [
      row for row in conflicts
      if str(row.get("type")) in EXPLICIT_MOTION_CONFLICT_TYPES
  ]
  explicit_deadlocks = [
      row for row in deadlocks
      if str(row.get("type")) in EXPLICIT_MOTION_DEADLOCK_TYPES
  ]
  timing_conflicts = [
      row for row in conflicts
      if str(row.get("type")) == "robot_transfer_late"
  ]
  return {
      "motion_ok": bool(report.get("ok")),
      "conflict_count": int(report.get("conflict_count") or 0),
      "deadlock_count": int(report.get("deadlock_count") or 0),
      "explicit_conflict_count": len(explicit_conflicts) + len(explicit_deadlocks),
      "timing_conflict_count": len(timing_conflicts),
      "external_isaac_conflict_count": len(external_conflicts),
      "explicit_conflicts": explicit_conflicts[:20],
      "explicit_deadlocks": explicit_deadlocks[:20],
      "timing_conflicts": timing_conflicts[:20],
      "external_isaac_conflicts": external_conflicts[:20],
      "policy": (
          "Promote explicit resource/deadlock conflicts to solver-side hard "
          "constraints; treat robot_transfer_late as transfer-time/slack evidence, "
          "not as a new resource conflict by itself. Do not convert "
          "robot_transfer_late into global transfer_safety_padding or pair_padding "
          "on every material edge; if used, target only the cited transfer_id, "
          "edge_id, task pair, or device pair, preferably as a secondary transfer-cost "
          "tie-break or local soft preference."
      ),
  }


def _external_isaac_conflicts(schedule: dict) -> list[dict]:
  if not isinstance(schedule, dict):
    return []
  rows = schedule.get("isaac_conflicts") or []
  return rows if isinstance(rows, list) else []


def _penalized_task_ids(motion: dict, external_conflicts: list[dict]) -> list[int]:
  transfer_to_tasks = {
      row.get("transfer_id"): [row.get("src_task_id"), row.get("dst_task_id")]
      for row in motion.get("plate_transfers") or []
      if isinstance(row, dict)
  }
  action_to_transfer = {
      row.get("action_id"): row.get("transfer_id")
      for row in motion.get("robot_actions") or []
      if isinstance(row, dict)
  }
  task_ids = set()
  report = motion.get("motion_monitor") or {}
  for section in ("conflicts", "deadlocks"):
    for row in report.get(section) or []:
      for transfer_id in row.get("transfers") or []:
        for task_id in transfer_to_tasks.get(transfer_id) or []:
          if task_id is not None:
            task_ids.add(int(task_id))
      if row.get("transfer_id") in transfer_to_tasks:
        for task_id in transfer_to_tasks[row.get("transfer_id")]:
          if task_id is not None:
            task_ids.add(int(task_id))
      for action_id in row.get("actions") or []:
        transfer_id = action_to_transfer.get(action_id)
        for task_id in transfer_to_tasks.get(transfer_id) or []:
          if task_id is not None:
            task_ids.add(int(task_id))
  for row in external_conflicts:
    if not isinstance(row, dict):
      continue
    for key in ("task_id", "src_task_id", "dst_task_id"):
      if row.get(key) is not None:
        task_ids.add(int(row[key]))
    for task_id in row.get("task_ids") or []:
      task_ids.add(int(task_id))
  return sorted(task_ids)


def _invalid_v4_schedule(dataset: dict, schedule: dict) -> str | None:
  fjspb = dataset.get("fjspb", {}) if isinstance(dataset, dict) else {}
  device_commands = fjspb.get("device_commands") or []
  if not device_commands:
    return None
  if not isinstance(schedule, dict):
    return "candidate rejected: v4 schedule must be a dict with assignments and command_assignments"
  command_assignments = schedule.get("command_assignments")
  if not isinstance(command_assignments, list) or not command_assignments:
    return "candidate rejected: v4 solver must return non-empty command_assignments, not task-only output"
  known_ids = {str(command.get("command_id")) for command in device_commands if isinstance(command, dict)}
  returned_ids = {
      str(row.get("command_id"))
      for row in command_assignments
      if isinstance(row, dict) and row.get("command_id") is not None
  }
  missing_task_runs = {command_id for command_id in known_ids if command_id.startswith("cmd:task:")} - returned_ids
  if missing_task_runs:
    sample = sorted(missing_task_runs)[:5]
    return "candidate rejected: v4 command_assignments missing task-run commands %s" % sample
  required_fields = ["command_id", "start", "end", "resource_id"]
  for row in command_assignments[:20]:
    if not isinstance(row, dict):
      return "candidate rejected: v4 command_assignments rows must be dicts"
    missing = [field for field in required_fields if field not in row]
    if missing:
      return "candidate rejected: v4 command_assignment missing fields %s" % missing
  report = monitor_schedule(dataset, schedule)
  error = first_error(report)
  if error:
    return "candidate rejected: v4 schedule monitor found %s" % error
  return None
