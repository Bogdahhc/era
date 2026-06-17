from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import os


def _construct_greedy(instance, rule):
    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    next_op = [0] * num_jobs
    job_ready = [0] * num_jobs
    machine_ready = [0] * num_machines
    remaining = [sum(int(op.duration) for op in job) for job in jobs]

    total_ops = sum(len(job) for job in jobs)
    starts = {}
    job_sequences = [[] for _ in range(num_machines)]

    for _ in range(total_ops):
        best_job = None
        best_key = None

        for job_id, job in enumerate(jobs):
            op_index = next_op[job_id]
            if op_index >= len(job):
                continue

            op = job[op_index]
            machine_id = int(op.machine_id)
            duration = int(op.duration)
            est = max(job_ready[job_id], machine_ready[machine_id])
            rem = remaining[job_id]

            if rule == 0:       # earliest start, shortest processing time
                key = (est, duration, -rem, job_id)
            elif rule == 1:     # earliest start, longest processing time
                key = (est, -duration, -rem, job_id)
            elif rule == 2:     # earliest start, most work remaining
                key = (est, -rem, duration, job_id)
            elif rule == 3:     # earliest start, least work remaining
                key = (est, rem, duration, job_id)
            elif rule == 4:     # most work remaining first
                key = (-rem, est, duration, job_id)
            elif rule == 5:     # shortest processing time first
                key = (duration, est, -rem, job_id)
            elif rule == 6:     # longest processing time first
                key = (-duration, est, -rem, job_id)
            else:               # balanced rule
                key = (est + duration, est, -rem, job_id)

            if best_key is None or key < best_key:
                best_key = key
                best_job = job_id

        job_id = best_job
        op_index = next_op[job_id]
        op = jobs[job_id][op_index]
        machine_id = int(op.machine_id)
        duration = int(op.duration)

        start = max(job_ready[job_id], machine_ready[machine_id])
        end = start + duration

        starts[(job_id, op_index)] = start
        job_sequences[machine_id].append(job_id)

        next_op[job_id] += 1
        job_ready[job_id] = end
        machine_ready[machine_id] = end
        remaining[job_id] -= duration

    return max(job_ready) if job_ready else 0, starts, job_sequences


def _best_greedy(instance):
    best = None
    for rule in range(8):
        candidate = _construct_greedy(instance, rule)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def solve(instance):
    heuristic_makespan, heuristic_starts, heuristic_sequences = _best_greedy(instance)

    model = cp_model.CpModel()
    total_duration = int(instance.total_duration)
    horizon = min(total_duration, int(heuristic_makespan)) if heuristic_makespan > 0 else total_duration

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(instance.num_machines)}

    job_prefix = []
    job_suffix_after = []
    for job in instance.jobs:
        prefix = []
        elapsed = 0
        for op in job:
            prefix.append(elapsed)
            elapsed += int(op.duration)

        suffix_after = [0] * len(job)
        rem = 0
        for idx in range(len(job) - 1, -1, -1):
            suffix_after[idx] = rem
            rem += int(job[idx].duration)

        job_prefix.append(prefix)
        job_suffix_after.append(suffix_after)

    for job_id, job in enumerate(instance.jobs):
        for op_index, operation in enumerate(job):
            key = (job_id, op_index)
            duration = int(operation.duration)
            machine_id = int(operation.machine_id)

            start_lb = int(job_prefix[job_id][op_index])
            end_lb = start_lb + duration
            end_ub = max(end_lb, horizon - int(job_suffix_after[job_id][op_index]))
            start_ub = max(start_lb, end_ub - duration)

            start = model.NewIntVar(start_lb, start_ub, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(end_lb, end_ub, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_index}")

            starts[key] = start
            ends[key] = end
            intervals_by_machine[machine_id].append((job_id, op_index, interval))

    for job_id, job in enumerate(instance.jobs):
        for op_index in range(1, len(job)):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    machine_load_lb = 0
    for machine_ops in intervals_by_machine.values():
        intervals = [interval for _, _, interval in machine_ops]
        if intervals:
            model.AddNoOverlap(intervals)
            load = 0
            for job_id, op_index, _ in machine_ops:
                load += int(instance.jobs[job_id][op_index].duration)
            machine_load_lb = max(machine_load_lb, load)

    job_load_lb = 0
    for job in instance.jobs:
        job_load_lb = max(job_load_lb, sum(int(op.duration) for op in job))

    makespan_lb = max(machine_load_lb, job_load_lb)
    makespan = model.NewIntVar(makespan_lb, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    model.Add(makespan <= horizon)
    model.Minimize(makespan)

    if heuristic_starts:
        for key, var in starts.items():
            value = int(heuristic_starts.get(key, 0))
            if value >= var.Proto().domain[0] and value <= var.Proto().domain[-1]:
                model.AddHint(var, value)
                model.AddHint(ends[key], value + int(instance.jobs[key[0]][key[1]].duration))
        model.AddHint(makespan, int(heuristic_makespan))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 285.0
    solver.parameters.num_search_workers = max(1, min(16, os.cpu_count() or 1))
    solver.parameters.random_seed = 13
    solver.parameters.randomize_search = True
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, heuristic_sequences)

    job_sequences = [[] for _ in range(instance.num_machines)]
    for machine_id, machine_ops in intervals_by_machine.items():
        ordered = sorted(
            machine_ops,
            key=lambda item: (solver.Value(starts[(item[0], item[1])]), item[0], item[1]),
        )
        job_sequences[machine_id] = [job_id for job_id, _, _ in ordered]

    return Schedule.from_job_sequences(instance, job_sequences)