"""execute_fn implementation for online multi-bot scheduling candidates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from implementation.multi_bot_online_era.sandbox import run_candidate
from implementation.multi_bot_online_era.scenario import build_online_scenario
from implementation.multi_bot_online_era.scorer import WORST_SCORE, score_dynamic_trace


@dataclass(frozen=True)
class Evaluation:
  score: float
  feasible: bool
  makespan: int | None
  elapsed_seconds: float
  error: str | None = None


class MultiBotOnlineExecutor:
  def __init__(
      self,
      timeout_seconds: int = 30,
      *,
      scenario_seed: int = 0,
      insertion_count: int = 1,
      inserted_jobs: int = 2,
      inserted_task_count: int = 4,
      insert_window_ratio: tuple[float, float] = (0.10, 0.60),
      insert_times: list[int] | None = None,
      enforce_even_centrifuge_inserts: bool = False,
  ):
    self.timeout_seconds = timeout_seconds
    self.scenario_seed = scenario_seed
    self.insertion_count = insertion_count
    self.inserted_jobs = inserted_jobs
    self.inserted_task_count = inserted_task_count
    self.insert_window_ratio = insert_window_ratio
    self.insert_times = insert_times
    self.enforce_even_centrifuge_inserts = enforce_even_centrifuge_inserts
    self.last_evaluation: Evaluation | None = None

  def evaluate(self, problem, solution) -> Evaluation:
    started = time.perf_counter()
    code = getattr(solution, "program", "") or ""
    if not _uses_online_interface(code):
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          "candidate rejected: dynamic scheduler must define "
          "class DynamicScheduler with handle_command(command)",
      )
      self.last_evaluation = evaluation
      return evaluation
    if not _uses_cp_sat(code):
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          "candidate rejected: multi_bot_online_era requires OR-Tools CP-SAT "
          "(`from ortools.sat.python import cp_model` and cp_model usage)",
      )
      self.last_evaluation = evaluation
      return evaluation
    shortcut_reason = _disallowed_solver_shortcut(code)
    if shortcut_reason:
      evaluation = Evaluation(
          WORST_SCORE,
          False,
          None,
          time.perf_counter() - started,
          shortcut_reason,
      )
      self.last_evaluation = evaluation
      return evaluation
    scenario = build_online_scenario(
        problem.dataset,
        scenario_seed=self.scenario_seed,
        insertion_count=self.insertion_count,
        inserted_jobs=self.inserted_jobs,
        inserted_task_count=self.inserted_task_count,
        insert_window_ratio=self.insert_window_ratio,
        insert_times=self.insert_times,
        enforce_even_centrifuge_inserts=self.enforce_even_centrifuge_inserts,
    )
    result = run_candidate(
        code,
        problem.dataset,
        scenario.commands,
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

    score, feasible, makespan, error = score_dynamic_trace(
        result["trace"], scenario.checks, elapsed_seconds
    )
    evaluation = Evaluation(score, feasible, makespan, elapsed_seconds, error)
    self.last_evaluation = evaluation
    return evaluation

  def __call__(self, problem, solution) -> float:
    return self.evaluate(problem, solution).score


def _uses_online_interface(code: str) -> bool:
  return "class DynamicScheduler" in code and "handle_command" in code


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


def _disallowed_solver_shortcut(code: str) -> str | None:
  compact = code.replace(" ", "").replace("'", '"')
  lower = code.lower()
  if "_build_greedy_schedule" in code:
    return (
        "candidate rejected: cold-start multi_bot_online_era must build the schedule "
        "inside CP-SAT, not precompute a full greedy schedule and wrap it"
    )
  if "_build_constructive_schedule" in code:
    return (
        "candidate rejected: cold-start multi_bot_online_era must not precompute a "
        "complete constructive schedule before CP-SAT"
    )
  if "raw_assignments" in code and (
      "NewIntVar(s0, s0" in code or "NewIntVar(e0, e0" in code
  ):
    return (
        "candidate rejected: CP-SAT start/end variables are fixed to "
        "precomputed raw_assignments instead of being solver decisions"
    )
  if 'return{"assignments":greedy}' in compact:
    return (
        "candidate rejected: returning a greedy schedule fallback bypasses "
        "the required CP-SAT-derived assignments"
    )
  if "model.add(s == int(ass[" in lower or "model.add(e == int(ass[" in lower:
    return (
        "candidate rejected: CP-SAT variables are fixed to a precomputed "
        "schedule instead of deciding start/end/machine values"
    )
  return None
