"""Reference CP-SAT candidate for flow_1160_era smoke tests.

This file follows the same public candidate contract used by FUTS-generated
code: expose solve(dataset) and return {"assignments": ...}. It is not used as
the cold-start root unless explicitly passed with --initial-code.
"""

from __future__ import annotations

import os

from ortools.sat.python import cp_model


def _task_param(task: dict, key: str):
  for entry in task.get("parameters") or []:
    param = entry.get("param") or {}
    if key in param:
      return param[key]
  return None


def solve(dataset):
  fjspb = dataset["fjspb"]
  jobs = fjspb.get("jobs", [])
  machines = {str(k): int(v) for k, v in fjspb.get("machines", {}).items()}
  tasks = []
  task_by_id = {}
  for job in jobs:
    for task in job.get("tasks", []):
      key = (job["job_id"], int(task["task_id"]))
      tasks.append((job, task, key))
      task_by_id[int(task["task_id"])] = task

  model = cp_model.CpModel()
  horizon = (
      sum(int(task["duration"]) for _job, task, _key in tasks)
      + sum(int(task.get("min_wait") or 0) for _job, task, _key in tasks)
      + int(fjspb.get("cur_ptr") or 0)
      + 10000
  )

  start_vars = {}
  end_vars = {}
  presence = {}
  optional_intervals = {}
  for _job, task, key in tasks:
    duration = int(task["duration"])
    start_vars[key] = model.NewIntVar(0, horizon, f"start_{key[0]}_{key[1]}")
    end_vars[key] = model.NewIntVar(0, horizon, f"end_{key[0]}_{key[1]}")
    model.Add(end_vars[key] == start_vars[key] + duration)
    if not task.get("is_fixed"):
      model.Add(start_vars[key] >= int(fjspb.get("cur_ptr") or 0))

    choices = []
    for machine_code in task.get("machines", []):
      chosen = model.NewBoolVar(f"assign_{key[0]}_{key[1]}_{machine_code}")
      presence[(key, machine_code)] = chosen
      choices.append(chosen)
      optional_intervals[(key, machine_code)] = model.NewOptionalIntervalVar(
          start_vars[key],
          duration,
          end_vars[key],
          chosen,
          f"interval_{key[0]}_{key[1]}_{machine_code}",
      )
    model.AddExactlyOne(choices)

    if task.get("is_fixed"):
      model.Add(start_vars[key] == int(task["fixed_start"]))
      model.Add(end_vars[key] == int(task["fixed_end"]))
      scheduled = task.get("scheduled_machine")
      for machine_code in task.get("machines", []):
        model.Add(presence[(key, machine_code)] == int(machine_code == scheduled))

  for machine_code, capacity in machines.items():
    intervals = []
    demands = []
    for _job, task, key in tasks:
      interval = optional_intervals.get((key, machine_code))
      if interval is None:
        continue
      intervals.append(interval)
      demands.append(max(1, int(task.get("required_capacity") or 1)))
    if intervals:
      model.AddCumulative(intervals, demands, max(1, int(capacity)))

  for a, b in fjspb.get("precedence_pairs") or []:
    pred_key = next(key for _job, _task, key in tasks if key[1] == int(a))
    succ_key = next(key for _job, _task, key in tasks if key[1] == int(b))
    pred_task = task_by_id[int(a)]
    model.Add(start_vars[succ_key] >= end_vars[pred_key] + int(pred_task.get("min_wait") or 0))

  for pair in fjspb.get("branch_priority_pairs") or []:
    higher_key = next(key for _job, _task, key in tasks if key[1] == int(pair["higher_task_id"]))
    lower_key = next(key for _job, _task, key in tasks if key[1] == int(pair["lower_task_id"]))
    model.Add(start_vars[higher_key] <= start_vars[lower_key])

  for machine_code in machines:
    temp_rows = [
        (task, key)
        for _job, task, key in tasks
        if (key, machine_code) in optional_intervals
        and _task_param(task, "temperature") is not None
    ]
    for i in range(len(temp_rows)):
      task_i, key_i = temp_rows[i]
      for j in range(i + 1, len(temp_rows)):
        task_j, key_j = temp_rows[j]
        if _task_param(task_i, "temperature") != _task_param(task_j, "temperature"):
          model.AddNoOverlap([
              optional_intervals[(key_i, machine_code)],
              optional_intervals[(key_j, machine_code)],
          ])

  machine_frequencies = fjspb.get("machine_frequencies") or {}
  for _job, task, key in tasks:
    required_frequency = _task_param(task, "frequency")
    if required_frequency is None:
      continue
    for machine_code in task.get("machines", []):
      frequency_range = machine_frequencies.get(machine_code)
      if frequency_range is None:
        continue
      lo, hi = frequency_range
      if lo is not None and hi is not None and not lo <= required_frequency <= hi:
        model.Add(presence[(key, machine_code)] == 0)

  makespan = model.NewIntVar(0, horizon, "makespan")
  model.AddMaxEquality(makespan, [end_vars[key] for _job, _task, key in tasks])
  model.Minimize(makespan)

  solver = cp_model.CpSolver()
  timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "30"))
  solver.parameters.max_time_in_seconds = max(1.0, timeout - 1.0)
  solver.parameters.num_search_workers = 8
  status = solver.Solve(model)
  if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    return {"assignments": []}

  assignments = []
  for job, task, key in tasks:
    chosen_machine = None
    for machine_code in task.get("machines", []):
      if solver.BooleanValue(presence[(key, machine_code)]):
        chosen_machine = machine_code
        break
    assignments.append(
        {
            "job_id": job["job_id"],
            "task_id": int(task["task_id"]),
            "machine": chosen_machine,
            "start": solver.Value(start_vars[key]),
            "end": solver.Value(end_vars[key]),
        }
    )
  return {"assignments": assignments}
