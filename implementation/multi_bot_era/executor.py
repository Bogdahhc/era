"""execute_fn implementation for multi-bot scheduling candidates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from implementation.multi_bot_era.sandbox import run_candidate
from implementation.multi_bot_era.scorer import WORST_SCORE, score_schedule


@dataclass(frozen=True)
class Evaluation:
  score: float
  feasible: bool
  makespan: int | None
  elapsed_seconds: float
  error: str | None = None


class MultiBotExecutor:
  def __init__(self, timeout_seconds: int = 30):
    self.timeout_seconds = timeout_seconds
    self.last_evaluation: Evaluation | None = None

  def evaluate(self, problem, solution) -> Evaluation:
    started = time.perf_counter()
    code = getattr(solution, "program", "") or ""
    if not _uses_cp_sat(code):
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          "candidate rejected: multi_bot_era requires OR-Tools CP-SAT "
          "(`from ortools.sat.python import cp_model` and cp_model usage)",
      )
      self.last_evaluation = evaluation
      return evaluation
    result = run_candidate(
        code,
        problem.dataset,
        timeout_seconds=self.timeout_seconds,
    )
    elapsed_seconds = time.perf_counter() - started
    if not result["ok"]:
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          elapsed_seconds,
          result["error"],
      )
      self.last_evaluation = evaluation
      return evaluation

    score, feasible, makespan, error = score_schedule(
        problem.dataset, result["schedule"], elapsed_seconds
    )
    evaluation = Evaluation(score, feasible, makespan, elapsed_seconds, error)
    self.last_evaluation = evaluation
    return evaluation

  def __call__(self, problem, solution) -> float:
    return self.evaluate(problem, solution).score


def _uses_cp_sat(code: str) -> bool:
  compact = code.replace(" ", "")
  return (
      "ortools.sat.python" in code
      and "cp_model" in code
      and "CpModel(" in code
      and "CpSolver(" in code
      and ("fromortools.sat.pythonimportcp_model" in compact
           or "importcp_model" in compact)
  )
