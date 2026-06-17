"""Backend protocol and registry for exact job-shop solvers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from implementation.exact_job_shop_era.spec import ExactSolverSpec


@dataclass(frozen=True)
class ExactSolveResult:
  """Backend-independent result returned by exact solver implementations."""

  feasible: bool
  makespan: int | None
  status: str
  elapsed_seconds: float
  best_bound: float | None = None
  relative_gap: float | None = None
  branches: int | None = None
  conflicts: int | None = None
  schedule: object | None = None


class ExactBackendSolver(Protocol):
  """Protocol implemented by each exact solver backend."""

  def solve(self, instance) -> ExactSolveResult:
    ...


def create_backend_solver(spec: ExactSolverSpec) -> ExactBackendSolver:
  """Creates a backend solver from a normalized spec."""
  if spec.backend == "ortools_cp_sat":
    from implementation.exact_job_shop_era.cp_sat_solver import CpSatJobShopSolver

    return CpSatJobShopSolver(spec)
  raise ValueError(f"unsupported backend: {spec.backend}")
