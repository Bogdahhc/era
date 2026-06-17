"""Custom OR-Tools CP-SAT backend for structured exact job-shop specs."""

from __future__ import annotations

import time
from collections import defaultdict

from job_shop_lib import Schedule, ScheduledOperation
from ortools.sat.python import cp_model

from implementation.exact_job_shop_era.backends import ExactSolveResult
from implementation.exact_job_shop_era.spec import ExactSolverSpec


class CpSatJobShopSolver:
  """Builds and solves a JSSP CP-SAT model controlled by ExactSolverSpec."""

  def __init__(self, spec: ExactSolverSpec):
    self.spec = spec
    self.model = cp_model.CpModel()
    self.solver = cp_model.CpSolver()
    self._starts = {}
    self._ends = {}
    self._intervals_by_machine = defaultdict(list)
    self._makespan = None

  def solve(self, instance) -> ExactSolveResult:
    started = time.perf_counter()
    self._build_model(instance)
    status_code = self.solver.Solve(self.model)
    elapsed = time.perf_counter() - started
    status = self._status_name(status_code)

    result = ExactSolveResult(
        feasible=status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE),
        makespan=None,
        status=status,
        elapsed_seconds=elapsed,
        best_bound=self._safe_best_bound(status_code),
        branches=self.solver.NumBranches(),
        conflicts=self.solver.NumConflicts(),
    )
    if not result.feasible:
      return result

    assert self._makespan is not None
    makespan = int(self.solver.Value(self._makespan))
    schedule = self._create_schedule(instance, makespan, status, elapsed)
    return ExactSolveResult(
        feasible=True,
        makespan=makespan,
        status=status,
        elapsed_seconds=elapsed,
        best_bound=self._safe_best_bound(status_code),
        relative_gap=self._relative_gap(makespan),
        branches=self.solver.NumBranches(),
        conflicts=self.solver.NumConflicts(),
        schedule=schedule,
    )

  def _build_model(self, instance) -> None:
    self.model = cp_model.CpModel()
    self.solver = cp_model.CpSolver()
    self.solver.parameters.log_search_progress = self.spec.log_search_progress
    if self.spec.max_time_in_seconds is not None:
      self.solver.parameters.max_time_in_seconds = self.spec.max_time_in_seconds

    self._starts = {}
    self._ends = {}
    self._intervals_by_machine = defaultdict(list)
    horizon = int(instance.total_duration)

    for job in instance.jobs:
      for operation in job:
        start = self.model.NewIntVar(0, horizon, self._var_name("s", operation))
        end = self.model.NewIntVar(0, horizon, self._var_name("e", operation))
        interval = self.model.NewIntervalVar(
            start,
            int(operation.duration),
            end,
            self._var_name("i", operation),
        )
        self._starts[operation] = start
        self._ends[operation] = end
        self._intervals_by_machine[operation.machine_id].append((operation, interval))

    self._add_job_precedence(instance)
    self._add_machine_no_overlap(instance)
    self._set_objective(instance, horizon)
    self._add_redundant_bounds(instance)
    self._add_symmetry_breaking(instance)
    self._add_branching(instance)

  def _add_job_precedence(self, instance) -> None:
    for job in instance.jobs:
      for position in range(1, len(job)):
        self.model.Add(self._ends[job[position - 1]] <= self._starts[job[position]])

  def _add_machine_no_overlap(self, instance) -> None:
    for machine_id in range(instance.num_machines):
      intervals = [
          interval for _, interval in self._intervals_by_machine.get(machine_id, [])
      ]
      if intervals:
        self.model.AddNoOverlap(intervals)

  def _set_objective(self, instance, horizon: int) -> None:
    self._makespan = self.model.NewIntVar(0, horizon, "makespan")
    self.model.AddMaxEquality(self._makespan, list(self._ends.values()))
    self.model.Minimize(self._makespan)

  def _add_redundant_bounds(self, instance) -> None:
    if self._makespan is None:
      return
    if "job_chain_lb" in self.spec.redundant_bounds:
      for job in instance.jobs:
        self.model.Add(
            self._makespan >= sum(int(operation.duration) for operation in job)
        )
    if "machine_load_lb" in self.spec.redundant_bounds:
      for machine_ops in self._intervals_by_machine.values():
        self.model.Add(
            self._makespan >= sum(int(operation.duration) for operation, _ in machine_ops)
        )
    if "critical_path_lb" in self.spec.redundant_bounds:
      job_lb = max(
          (sum(int(operation.duration) for operation in job) for job in instance.jobs),
          default=0,
      )
      machine_lb = max(
          (
              sum(int(operation.duration) for operation, _ in machine_ops)
              for machine_ops in self._intervals_by_machine.values()
          ),
          default=0,
      )
      self.model.Add(self._makespan >= max(job_lb, machine_lb))

  def _add_symmetry_breaking(self, instance) -> None:
    if not self.spec.symmetry_breaking:
      return
    grouped_jobs = defaultdict(list)
    for job in instance.jobs:
      signature = tuple((op.machine_id, op.duration) for op in job)
      grouped_jobs[signature].append(job)
    for jobs in grouped_jobs.values():
      jobs = sorted(jobs, key=lambda job: job[0].job_id)
      for left, right in zip(jobs, jobs[1:]):
        self.model.Add(self._starts[left[0]] <= self._starts[right[0]])

  def _add_branching(self, instance) -> None:
    starts = list(self._starts.values())
    if not starts or self.spec.branching == "default":
      return

    if self.spec.branching == "earliest_start":
      variables = starts
    elif self.spec.branching == "min_slack_first":
      variables = sorted(
          starts,
          key=lambda var: self._duration_from_start_var_name(var.Name()),
          reverse=True,
      )
    elif self.spec.branching == "critical_machine_first":
      machine_loads = {
          machine_id: sum(int(operation.duration) for operation, _ in operations)
          for machine_id, operations in self._intervals_by_machine.items()
      }
      operations = [
          operation
          for machine_id, ops in sorted(
              self._intervals_by_machine.items(),
              key=lambda item: machine_loads[item[0]],
              reverse=True,
          )
          for operation, _ in ops
      ]
      variables = [self._starts[operation] for operation in operations]
    else:
      return

    self.model.AddDecisionStrategy(
        variables,
        cp_model.CHOOSE_LOWEST_MIN,
        cp_model.SELECT_MIN_VALUE,
    )

  def _create_schedule(self, instance, makespan: int, status: str, elapsed: float):
    machine_schedules = [[] for _ in range(instance.num_machines)]
    for job in instance.jobs:
      for operation in job:
        machine_schedules[operation.machine_id].append(
            ScheduledOperation(
                operation,
                int(self.solver.Value(self._starts[operation])),
                operation.machine_id,
            )
        )
    sorted_schedule = [
        sorted(machine_schedule, key=lambda scheduled: scheduled.start_time)
        for machine_schedule in machine_schedules
    ]
    return Schedule(
        instance=instance,
        schedule=sorted_schedule,
        status=status,
        elapsed_time=elapsed,
        makespan=makespan,
        best_bound=self._safe_best_bound(cp_model.OPTIMAL if status == "optimal" else cp_model.FEASIBLE),
        relative_gap=self._relative_gap(makespan),
        branches=self.solver.NumBranches(),
        conflicts=self.solver.NumConflicts(),
        solved_by="CpSatJobShopSolver",
    )

  def _safe_best_bound(self, status_code: int) -> float | None:
    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
      return None
    try:
      return float(self.solver.BestObjectiveBound())
    except RuntimeError:
      return None

  def _relative_gap(self, makespan: int) -> float | None:
    bound = self._safe_best_bound(cp_model.FEASIBLE)
    if bound is None or makespan <= 0:
      return None
    return max(0.0, (float(makespan) - bound) / float(makespan))

  @staticmethod
  def _status_name(status_code: int) -> str:
    return {
        cp_model.OPTIMAL: "optimal",
        cp_model.FEASIBLE: "feasible",
        cp_model.INFEASIBLE: "infeasible",
        cp_model.MODEL_INVALID: "model_invalid",
        cp_model.UNKNOWN: "unknown",
    }.get(status_code, f"status_{status_code}")

  @staticmethod
  def _var_name(prefix: str, operation) -> str:
    return (
        f"{prefix}_j{operation.job_id}_p{operation.position_in_job}"
        f"_m{operation.machine_id}_d{operation.duration}"
    )

  @staticmethod
  def _duration_from_start_var_name(name: str) -> int:
    try:
      return int(name.rsplit("_d", 1)[1])
    except (IndexError, ValueError):
      return 0
