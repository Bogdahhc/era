"""Minimal cold-start seed for multi_bot_era FUTS.

This seed intentionally contains only a CP-SAT skeleton. It should fail scoring
as a root node and force the first LLM mutation to build the reusable solver
from the prompt, dataset summary, and objective feedback.
"""

from ortools.sat.python import cp_model


def solve(dataset):
    model = cp_model.CpModel()
    marker = model.NewBoolVar("cold_start_marker")
    model.Add(marker == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    solver.Solve(model)

    return {"assignments": []}
