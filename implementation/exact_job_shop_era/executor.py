"""execute_fn for CP-SAT Python job-shop candidates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from implementation.job_shop_era.sandbox import run_candidate
from implementation.job_shop_era.scorer import (
    SCORE_RUNTIME_DIVISOR,
    WORST_SCORE,
    score_schedule,
)


@dataclass(frozen=True)
class ExactEvaluation:
  score: float
  feasible: bool
  makespan: int | None
  status: str | None
  elapsed_seconds: float
  best_bound: float | None = None
  relative_gap: float | None = None
  branches: int | None = None
  conflicts: int | None = None
  error: str | None = None


class ExactJobShopExecutor:
  """Runs generated CP-SAT Python candidates in a subprocess sandbox."""

  def __init__(self, timeout_seconds: int = 30):
    self.timeout_seconds = timeout_seconds
    self.last_evaluation: ExactEvaluation | None = None

  def evaluate(self, problem, solution) -> ExactEvaluation:
    started = time.perf_counter()
    result = run_candidate(
        solution.program,
        problem.instance_dict,
        timeout_seconds=self.timeout_seconds,
    )
    if not result["ok"]:
      evaluation = ExactEvaluation(
          WORST_SCORE,
          False,
          None,
          None,
          time.perf_counter() - started,
          error=result["error"],
      )
      self.last_evaluation = evaluation
      return evaluation

    try:
      from job_shop_lib import Schedule

      schedule_data = result["schedule_dict"]
      schedule = Schedule.from_dict(
          schedule_data["instance"],
          schedule_data["job_sequences"],
          metadata=schedule_data.get("metadata"),
      )
      score, feasible, makespan, error = score_schedule(schedule)
      elapsed_seconds = time.perf_counter() - started
      if feasible and makespan is not None:
        score = -(float(makespan) + elapsed_seconds / SCORE_RUNTIME_DIVISOR)
    except Exception as exc:
      elapsed_seconds = time.perf_counter() - started
      score, feasible, makespan, error = WORST_SCORE, False, None, str(exc)

    evaluation = ExactEvaluation(
        score=score,
        feasible=feasible,
        makespan=makespan,
        status="feasible" if feasible else None,
        elapsed_seconds=elapsed_seconds,
        error=error,
    )
    self.last_evaluation = evaluation
    return evaluation

  def __call__(self, problem, solution) -> float:
    return self.evaluate(problem, solution).score
