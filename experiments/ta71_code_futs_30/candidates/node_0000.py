from job_shop_lib import Schedule
from ortools.sat.python import cp_model


def solve(instance):
  fallback_job_sequences = [[] for _ in range(instance.num_machines)]
  for job_id, job in enumerate(instance.jobs):
    for operation in job:
      fallback_job_sequences[int(operation.machine_id)].append(job_id)

  model = cp_model.CpModel()
  horizon = int(instance.total_duration)
  starts = {}
  ends = {}
  intervals_by_machine = {m: [] for m in range(instance.num_machines)}

  for job_id, job in enumerate(instance.jobs):
    for op_index, operation in enumerate(job):
      key = (job_id, op_index)
      duration = int(operation.duration)
      machine_id = int(operation.machine_id)
      start = model.NewIntVar(0, horizon, f"s_{job_id}_{op_index}")
      end = model.NewIntVar(0, horizon, f"e_{job_id}_{op_index}")
      interval = model.NewIntervalVar(
          start, duration, end, f"i_{job_id}_{op_index}"
      )
      starts[key] = start
      ends[key] = end
      intervals_by_machine[machine_id].append((job_id, op_index, interval))

  for job_id, job in enumerate(instance.jobs):
    for op_index in range(1, len(job)):
      model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

  for machine_ops in intervals_by_machine.values():
    intervals = [interval for _, _, interval in machine_ops]
    if intervals:
      model.AddNoOverlap(intervals)

  makespan = model.NewIntVar(0, horizon, "makespan")
  model.AddMaxEquality(makespan, list(ends.values()))
  model.Minimize(makespan)

  solver = cp_model.CpSolver()
  solver.parameters.max_time_in_seconds = 240.0
  status = solver.Solve(model)
  if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    return Schedule.from_job_sequences(instance, fallback_job_sequences)

  job_sequences = [[] for _ in range(instance.num_machines)]
  for machine_id, machine_ops in intervals_by_machine.items():
    ordered = sorted(
        machine_ops,
        key=lambda item: solver.Value(starts[(item[0], item[1])]),
    )
    job_sequences[machine_id] = [job_id for job_id, _, _ in ordered]
  return Schedule.from_job_sequences(instance, job_sequences)