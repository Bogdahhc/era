"""FUTS execute_fn implementation for job-shop candidates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from implementation.job_shop_era.scorer import (
    SCORE_RUNTIME_DIVISOR,
    WORST_SCORE,
    score_schedule,
)
from implementation.job_shop_era.sandbox import run_candidate


@dataclass(frozen=True)
class Evaluation:
  score: float
  feasible: bool
  makespan: int | None
  elapsed_seconds: float
  error: str | None = None


class JobShopExecutor:
  """Adapts sandboxed job-shop scoring into FUTS' execute_fn signature."""

  def __init__(self, timeout_seconds: int = 30):
    self.timeout_seconds = timeout_seconds
    self.last_evaluation: Evaluation | None = None

  def evaluate(self, problem, solution) -> Evaluation:
    started = time.time()
    result = run_candidate(
        solution.program,
        problem.instance_dict,
        timeout_seconds=self.timeout_seconds,
    )
    if not result["ok"]:
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.time() - started,
          result["error"],
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
      elapsed_seconds = time.time() - started
      if feasible and makespan is not None:
        score = -(float(makespan) + elapsed_seconds / SCORE_RUNTIME_DIVISOR)
    except Exception as exc:
      elapsed_seconds = time.time() - started
      score, feasible, makespan, error = WORST_SCORE, False, None, str(exc)

    evaluation = Evaluation(score, feasible, makespan, elapsed_seconds, error)
    self.last_evaluation = evaluation
    return evaluation

  def __call__(self, problem, solution) -> float:
    return self.evaluate(problem, solution).score
