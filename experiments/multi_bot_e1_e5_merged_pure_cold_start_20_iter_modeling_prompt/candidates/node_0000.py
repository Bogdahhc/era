from ortools.sat.python import cp_model


def solve(dataset):
    model = cp_model.CpModel()
    marker = model.NewBoolVar("cold_start_marker")
    model.Add(marker == 1)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 1.0
    solver.Solve(model)

    return {"assignments": []}