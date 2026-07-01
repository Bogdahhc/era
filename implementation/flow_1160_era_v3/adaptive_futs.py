"""Adaptive logistics-gap tightening for flow_1160_era_v3 FUTS runs."""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from implementation.flow_1160_era.executor import Evaluation
from implementation.flow_1160_era_v3.adaptive_logistics_gap import _events_from_schedule


class AdaptiveLogisticsTightener:
  """Tighten transfer caps after feasible motion-safe candidate evaluations."""

  def __init__(
      self,
      problem,
      *,
      enabled: bool,
      min_gap: int | None = None,
      step: int | None = None,
      isaac_headless: bool = False,
      artifact_dir: Path | None = None,
      isaac_python: str = "/home/hehaochen/anaconda3/envs/isaacsim/bin/python",
      isaac_speed: int = 1200,
      isaac_timeout_seconds: int = 240,
  ):
    self.enabled = bool(enabled)
    self.isaac_headless = bool(isaac_headless)
    self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
    self.isaac_python = str(isaac_python)
    self.isaac_speed = int(isaac_speed)
    self.isaac_timeout_seconds = int(isaac_timeout_seconds)
    timing = problem.dataset["fjspb"].get("isaac_motion_timing") or {}
    self.max_gap = int(timing.get("transfer_seconds") or 0)
    self.min_gap = int(min_gap if min_gap is not None else timing.get("min_transfer_seconds") or 0)
    self.step = max(1, int(step if step is not None else timing.get("tightening_step_seconds") or 60))
    self.current_gap = self.max_gap
    self.rows: list[dict[str, Any]] = []
    self.process_summaries: list[dict[str, Any]] = []
    apply_transfer_cap(problem.dataset, self.current_gap, enabled=self.enabled)
    self._publish(problem)

  def evaluate(self, problem, solution, executor, *, node_id: int, parent_id: int | None = None) -> Evaluation:
    if not self.enabled:
      apply_transfer_cap(problem.dataset, self.current_gap, enabled=False)
      self._publish(problem)
      evaluation = executor.evaluate(problem, solution)
      self.rows.append(self._row(node_id, parent_id, self.current_gap, evaluation, "fixed"))
      return evaluation

    accepted_gap = self.current_gap
    apply_transfer_cap(problem.dataset, accepted_gap, enabled=True)
    self._publish(problem)
    accepted = executor.evaluate(problem, solution)
    total_elapsed = accepted.elapsed_seconds
    safe, sim_info = self._candidate_safe(problem, executor, accepted, node_id, accepted_gap)
    self.rows.append(self._row(node_id, parent_id, accepted_gap, accepted, "current", sim_info))

    if not safe:
      return self._with_sim_error(accepted, sim_info)

    gap = accepted_gap - self.step
    while gap >= self.min_gap:
      apply_transfer_cap(problem.dataset, gap, enabled=True)
      self._publish(problem)
      trial = executor.evaluate(problem, solution)
      total_elapsed += trial.elapsed_seconds
      safe, sim_info = self._candidate_safe(problem, executor, trial, node_id, gap)
      if safe:
        accepted_gap = gap
        accepted = trial
        self.current_gap = accepted_gap
        self.rows.append(self._row(node_id, parent_id, gap, trial, "accepted_tighter", sim_info))
        gap -= self.step
        continue

      self.rows.append(self._row(node_id, parent_id, gap, trial, "rejected_tighter", sim_info))
      break

    apply_transfer_cap(problem.dataset, accepted_gap, enabled=True)
    self._publish(problem)
    self.current_gap = accepted_gap
    return self._with_total_elapsed(accepted, total_elapsed)

  def write_report(self, path: Path) -> None:
    payload = {
        "enabled": self.enabled,
        "current_gap": self.current_gap,
        "min_gap": self.min_gap,
        "max_gap": self.max_gap,
        "step": self.step,
        "isaac_headless": self.isaac_headless,
        "isaac_python": self.isaac_python,
        "isaac_speed": self.isaac_speed,
        "isaac_timeout_seconds": self.isaac_timeout_seconds,
        "rows": self.rows,
        "recent_process_summaries": self.recent_process_summaries(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

  def state(self) -> dict[str, Any]:
    return {
        "enabled": self.enabled,
        "current_gap": self.current_gap,
        "min_gap": self.min_gap,
        "max_gap": self.max_gap,
        "step": self.step,
        "isaac_headless": self.isaac_headless,
        "policy": (
            "tighten_after_isaac_headless_safe_node"
            if self.enabled and self.isaac_headless
            else "tighten_after_motion_safe_node"
            if self.enabled
            else "fixed_default"
        ),
    }

  def recent_process_summaries(self, limit: int = 5) -> list[dict[str, Any]]:
    return self.process_summaries[-max(0, int(limit)):]

  def _publish(self, problem) -> None:
    state = self.state()
    problem.dataset["fjspb"]["adaptive_logistics_state"] = state
    if isinstance(problem.prompt_dataset, dict):
      problem.prompt_dataset["adaptive_logistics_state"] = state

  @staticmethod
  def _is_motion_safe(evaluation: Evaluation) -> bool:
    if not evaluation.feasible:
      return False
    return "isaac_motion_penalty" not in str(evaluation.error or "")

  def _candidate_safe(self, problem, executor, evaluation: Evaluation, node_id: int, gap: int) -> tuple[bool, dict[str, Any]]:
    info: dict[str, Any] = {
        "motion_safe": self._is_motion_safe(evaluation),
        "isaac_headless": self.isaac_headless,
    }
    if not info["motion_safe"]:
      return False, info
    if not self.isaac_headless:
      return True, info

    schedule = getattr(executor, "last_schedule", None)
    if not isinstance(schedule, dict):
      info.update({"isaac_ok": False, "isaac_error": "missing executor.last_schedule"})
      return False, info
    if self.artifact_dir is None:
      info.update({"isaac_ok": False, "isaac_error": "missing artifact_dir"})
      return False, info

    trial_dir = self.artifact_dir / "isaac_trials"
    trial_dir.mkdir(parents=True, exist_ok=True)
    stem = "node_%04d_gap_%04d" % (int(node_id), int(gap))
    events_path = trial_dir / ("%s_events.json" % stem)
    screenshot_path = trial_dir / ("%s_headless.png" % stem)
    report_path = trial_dir / ("%s_report.json" % stem)
    stdout_path = trial_dir / ("%s_stdout.log" % stem)
    stderr_path = trial_dir / ("%s_stderr.log" % stem)

    events = _events_from_schedule("1160", problem.dataset, schedule, int(gap))
    events_path.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    process_summary = _summarize_logistics_process(events, int(gap))

    cmd = [
        self.isaac_python,
        "/home/era/implementation/flow_1160_era_v3/isaac_twin.py",
        str(events_path),
        "--headless",
        "--speed",
        str(self.isaac_speed),
        "--screenshot",
        str(screenshot_path),
        "--report-json",
        str(report_path),
    ]
    started = time.perf_counter()
    try:
      completed = subprocess.run(
          cmd,
          text=True,
          capture_output=True,
          timeout=self.isaac_timeout_seconds,
          check=False,
      )
      stdout_path.write_text(_as_text(completed.stdout), encoding="utf-8")
      stderr_path.write_text(_as_text(completed.stderr), encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
      stdout_path.write_text(_as_text(exc.stdout), encoding="utf-8")
      stderr_path.write_text(_as_text(exc.stderr), encoding="utf-8")
      report = _read_json(report_path)
      if bool(report.get("ok")):
        info.update(
            {
                "isaac_ok": True,
                "isaac_returncode": "timeout_after_report",
                "isaac_elapsed_seconds": time.perf_counter() - started,
                "isaac_events": str(events_path),
                "isaac_report": str(report_path),
                "isaac_screenshot": str(screenshot_path),
                "isaac_stdout": str(stdout_path),
                "isaac_stderr": str(stderr_path),
                "isaac_conflict_count": int(((report.get("motion_monitor") or {}).get("conflict_count") or 0)),
                "isaac_deadlock_count": int(((report.get("motion_monitor") or {}).get("deadlock_count") or 0)),
                "isaac_first_conflict": (report.get("motion_monitor") or {}).get("first_conflict"),
                "isaac_first_deadlock": (report.get("motion_monitor") or {}).get("first_deadlock"),
                "isaac_note": "process timed out after writing ok report",
                "logistics_process": process_summary,
            }
        )
        self.process_summaries.append(process_summary | {"node_id": int(node_id), "gap_seconds": int(gap), "isaac_ok": True})
        return True, info
      info.update(
          {
              "isaac_ok": False,
              "isaac_error": "timeout after %ss" % self.isaac_timeout_seconds,
              "isaac_elapsed_seconds": time.perf_counter() - started,
              "isaac_events": str(events_path),
              "isaac_report": str(report_path),
              "isaac_stdout": str(stdout_path),
              "isaac_stderr": str(stderr_path),
              "logistics_process": process_summary,
          }
      )
      self.process_summaries.append(process_summary | {"node_id": int(node_id), "gap_seconds": int(gap), "isaac_ok": False})
      return False, info

    report = _read_json(report_path)
    isaac_ok = bool(report.get("ok")) and completed.returncode == 0
    info.update(
        {
            "isaac_ok": isaac_ok,
            "isaac_returncode": completed.returncode,
            "isaac_elapsed_seconds": time.perf_counter() - started,
            "isaac_events": str(events_path),
            "isaac_report": str(report_path),
            "isaac_screenshot": str(screenshot_path),
            "isaac_stdout": str(stdout_path),
            "isaac_stderr": str(stderr_path),
            "isaac_conflict_count": int(((report.get("motion_monitor") or {}).get("conflict_count") or 0)),
            "isaac_deadlock_count": int(((report.get("motion_monitor") or {}).get("deadlock_count") or 0)),
            "isaac_first_conflict": (report.get("motion_monitor") or {}).get("first_conflict"),
            "isaac_first_deadlock": (report.get("motion_monitor") or {}).get("first_deadlock"),
            "logistics_process": process_summary,
        }
    )
    self.process_summaries.append(process_summary | {"node_id": int(node_id), "gap_seconds": int(gap), "isaac_ok": isaac_ok})
    return isaac_ok, info

  @staticmethod
  def _with_total_elapsed(evaluation: Evaluation, total_elapsed: float) -> Evaluation:
    if total_elapsed <= evaluation.elapsed_seconds:
      return evaluation
    extra_elapsed = total_elapsed - evaluation.elapsed_seconds
    return Evaluation(
        evaluation.score - extra_elapsed / 100.0,
        evaluation.feasible,
        evaluation.makespan,
        total_elapsed,
        evaluation.error,
    )

  @staticmethod
  def _with_sim_error(evaluation: Evaluation, sim_info: dict[str, Any]) -> Evaluation:
    if sim_info.get("isaac_ok") is not False:
      return evaluation
    error = evaluation.error
    sim_error = sim_info.get("isaac_error")
    if not sim_error and sim_info.get("isaac_ok") is False:
      sim_error = "isaac_headless_rejected"
    if not sim_error:
      return evaluation
    return Evaluation(
        evaluation.score - 1_000_000.0,
        evaluation.feasible,
        evaluation.makespan,
        evaluation.elapsed_seconds,
        (error + "; " if error else "") + sim_error,
    )

  @staticmethod
  def _row(
      node_id: int,
      parent_id: int | None,
      gap: int,
      evaluation: Evaluation,
      decision: str,
      sim_info: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    row = {
        "node_id": node_id,
        "parent_id": parent_id,
        "gap_seconds": int(gap),
        "decision": decision,
        "score": evaluation.score,
        "feasible": evaluation.feasible,
        "makespan": evaluation.makespan,
        "elapsed_seconds": evaluation.elapsed_seconds,
        "error": evaluation.error,
    }
    if sim_info:
      row.update(sim_info)
    return row


def apply_transfer_cap(dataset: dict, gap_seconds: int, *, enabled: bool = True) -> None:
  """Publish adaptive state without flattening graph-distance transfer times."""

  fjspb = dataset["fjspb"]
  timing = fjspb.setdefault("isaac_motion_timing", {})
  if "_adaptive_original_transfer_seconds" not in timing:
    timing["_adaptive_original_transfer_seconds"] = int(timing.get("transfer_seconds") or gap_seconds)
  original_global = int(timing.get("_adaptive_original_transfer_seconds") or gap_seconds)
  timing["transfer_seconds"] = original_global
  timing["gap_policy"] = "adaptive_validate_graph_distance" if enabled else "graph_distance_fixed"
  timing["adaptive_validation_gap_seconds"] = int(gap_seconds)

  pick = int(timing.get("pick_seconds") or 0)
  place = int(timing.get("place_seconds") or 0)
  drop = int(timing.get("drop_seconds") or 0)
  safety = int(timing.get("safety_gap_seconds") or 0)
  fixed_segments = pick + place + drop + safety
  matrix = fjspb.get("device_transfer_times") or {}
  for row in matrix.get("rows") or []:
    if not isinstance(row, dict):
      continue
    if "_adaptive_original_transfer_seconds" not in row:
      row["_adaptive_original_transfer_seconds"] = int(row.get("transfer_seconds") or original_global)
    original = int(row.get("_adaptive_original_transfer_seconds") or original_global)
    row["transfer_seconds"] = max(fixed_segments, original)
    row["move_seconds"] = max(0, int(row["transfer_seconds"]) - fixed_segments)
    row["adaptive_validation_gap_seconds"] = int(gap_seconds)
    row["adaptive_policy"] = "preserve_graph_distance_no_cap"


def _as_text(value) -> str:
  if value is None:
    return ""
  if isinstance(value, bytes):
    return value.decode("utf-8", errors="replace")
  return str(value)


def _read_json(path: Path) -> dict:
  if not path.exists():
    return {}
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception as exc:
    return {"ok": False, "parse_error": str(exc)}


def _summarize_logistics_process(events: dict, gap_seconds: int) -> dict[str, Any]:
  transfers = [row for row in events.get("plate_transfers") or [] if isinstance(row, dict)]
  robot_actions = [row for row in events.get("robot_actions") or [] if isinstance(row, dict)]
  motion = events.get("motion_monitor") or {}
  timeline = events.get("timeline_meta") or {}

  pair_counts = Counter()
  pair_durations = defaultdict(list)
  pair_slacks = defaultdict(list)
  motion_class_counts = Counter()
  tight_transfers = []
  late_transfers = []
  longest_transfers = []
  for row in transfers:
    pair = "%s->%s" % (row.get("from_device"), row.get("to_device"))
    duration = int(row.get("duration") or 0)
    ready = int(row.get("ready_time") or 0)
    need_by = int(row.get("need_by") or 0)
    slack = need_by - ready - duration
    pair_counts[pair] += 1
    pair_durations[pair].append(duration)
    pair_slacks[pair].append(slack)
    motion_class_counts[str(row.get("motion_class"))] += 1
    item = {
        "transfer_id": row.get("transfer_id"),
        "edge_id": row.get("edge_id"),
        "src_task_id": row.get("src_task_id"),
        "dst_task_id": row.get("dst_task_id"),
        "from_device": row.get("from_device"),
        "to_device": row.get("to_device"),
        "duration": duration,
        "ready_time": ready,
        "need_by": need_by,
        "slack": slack,
        "motion_class": row.get("motion_class"),
        "plate_id": row.get("plate_id"),
    }
    if slack <= 300:
      tight_transfers.append(item)
    if row.get("arrival_late") or slack < 0:
      late_transfers.append(item)
    longest_transfers.append(item)

  busiest_pairs = []
  for pair, count in pair_counts.most_common(12):
    durations = pair_durations[pair]
    slacks = pair_slacks[pair]
    busiest_pairs.append(
        {
            "pair": pair,
            "count": count,
            "max_duration": max(durations) if durations else 0,
            "min_slack": min(slacks) if slacks else None,
            "avg_slack": round(sum(slacks) / len(slacks), 2) if slacks else None,
        }
    )

  robot_busy = Counter()
  for action in robot_actions:
    robot_busy[str(action.get("kind"))] += max(0, int(action.get("duration") or 0))

  conflict_task_ids = set()
  for section in ("conflicts", "deadlocks"):
    for row in motion.get(section) or []:
      for task_id in row.get("task_ids") or []:
        if task_id is not None:
          conflict_task_ids.add(int(task_id))

  return {
      "gap_seconds": int(gap_seconds),
      "makespan_seconds": timeline.get("makespan_seconds"),
      "motion_ok": motion.get("ok"),
      "conflict_count": int(motion.get("conflict_count") or 0),
      "deadlock_count": int(motion.get("deadlock_count") or 0),
      "first_conflict": (motion.get("conflicts") or [None])[0],
      "first_deadlock": (motion.get("deadlocks") or [None])[0],
      "transfer_count": len(transfers),
      "robot_action_count": len(robot_actions),
      "motion_class_counts": dict(motion_class_counts),
      "busiest_device_pairs": busiest_pairs,
      "tightest_transfers": sorted(tight_transfers, key=lambda row: row["slack"])[:20],
      "late_transfers": late_transfers[:20],
      "longest_transfers": sorted(longest_transfers, key=lambda row: row["duration"], reverse=True)[:20],
      "robot_busy_seconds_by_action": dict(robot_busy),
      "conflict_task_ids": sorted(conflict_task_ids),
  }
