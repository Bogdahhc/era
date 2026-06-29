"""Cold-start root candidate for flow_1160/FJSPB FUTS."""

from __future__ import annotations


def baseline_candidate_code() -> str:
  """Returns a minimal CP-SAT skeleton, not a usable scheduler.

  The flow_1160_era default root is intentionally weak. FUTS should grow a
  complete reusable OR-Tools model from the prompt, dataset IR, objective
  feedback, and failed-node diagnostics, rather than starting from a hand-built
  FJSPB solver.
  """
  return r'''
from ortools.sat.python import cp_model


def solve(dataset):
    model = cp_model.CpModel()
    marker = model.NewBoolVar("cold_start_marker")
    model.Add(marker == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    solver.Solve(model)

    return {"assignments": []}
'''.strip()
