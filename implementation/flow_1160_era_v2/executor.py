"""execute_fn implementation for flow_1160_era_v2 candidates."""

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


class Flow1160V2Executor(Flow1160Executor):
  """V2 executor keeps v1 scoring but requires v2 constraints to be modeled."""

  def evaluate(self, problem, solution) -> Evaluation:
    started = time.perf_counter()
    code = getattr(solution, "program", "") or ""
    if not _uses_cp_sat(code):
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          "candidate rejected: flow_1160_era_v2 requires OR-Tools CP-SAT",
      )
      self.last_evaluation = evaluation
      return evaluation
    shortcut_reason = _disallowed_solver_shortcut(code)
    if shortcut_reason:
      evaluation = Evaluation(WORST_SCORE, False, None, time.perf_counter() - started, shortcut_reason)
      self.last_evaluation = evaluation
      return evaluation
    v2_reason = _missing_v2_constraint_surface(code)
    if v2_reason:
      evaluation = Evaluation(WORST_SCORE, False, None, time.perf_counter() - started, v2_reason)
      self.last_evaluation = evaluation
      return evaluation

    result = run_candidate(code, problem.dataset, timeout_seconds=self.timeout_seconds)
    elapsed_seconds = time.perf_counter() - started
    if not result["ok"]:
      evaluation = Evaluation(WORST_SCORE, False, None, elapsed_seconds, result["error"])
      self.last_evaluation = evaluation
      return evaluation
    score, feasible, makespan, error = score_schedule(problem.dataset, result["schedule"], elapsed_seconds)
    evaluation = Evaluation(score, feasible, makespan, elapsed_seconds, error)
    self.last_evaluation = evaluation
    return evaluation


def _missing_v2_constraint_surface(code: str) -> str | None:
  required_tokens = [
      "material_edges",
      "hard_precedence_candidate",
      "material_inventory_events",
      "material_lineage_links",
      "constraint_realization_boundaries",
      "history_policy",
      "logistics_events",
      "buffers",
      "buffer_ids",
      "existing_machine_occupancy",
      "rolling_state",
  ]
  missing = [token for token in required_tokens if token not in code]
  if missing:
    return "candidate rejected: v2 solver must explicitly model/read %s" % ", ".join(missing)
  if "AddNoOverlap" not in code:
    return "candidate rejected: v2 logistics_events require AddNoOverlap resource calendars"
  if "AddCumulative" not in code:
    return "candidate rejected: v2 solver must preserve cumulative machine calendars"
  if "AddReservoirConstraint" not in code:
    return "candidate rejected: v2 material_inventory_events require AddReservoirConstraint"
  if "status not in (cp_model.OPTIMAL, cp_model.FEASIBLE)" in code and "cur_ptr + duration" in code:
    return "candidate rejected: v2 solver must not return unverified cur_ptr fallback assignments"
  if "historical_replay" in code and "strict_cold_start" not in code:
    return "candidate rejected: cold-start solver must not force historical_replay semantics"
  return None
