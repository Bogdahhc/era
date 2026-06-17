from job_shop_lib import Schedule
from ortools.sat.python import cp_model


def _dispatch_heuristic(instance, rule):
    num_jobs = len(instance.jobs)
    num_machines = int(instance.num_machines)
    next_op = [0] * num_jobs
    job_ready = [0] * num_jobs
    machine_ready = [0] * num_machines
    sequences = [[] for _ in range(num_machines)]
    starts = {}
    ends = {}

    tails = []
    for job in instance.jobs:
        durations = [int(op.duration) for op in job]
        tail = [0] * (len(durations) + 1)
        for i in range(len(durations) - 1, -1, -1):
            tail[i] = tail[i + 1] + durations[i]
        tails.append(tail)

    total_ops = sum(len(job) for job in instance.jobs)
    for _ in range(total_ops):
        best_key = None
        best = None
        for j, job in enumerate(instance.jobs):
            i = next_op[j]
            if i >= len(job):
                continue
            op = job[i]
            m = int(op.machine_id)
            d = int(op.duration)
            est = max(job_ready[j], machine_ready[m])
            ect = est + d
            rem = tails[j][i]
            slack_like = est + rem

            if rule == 0:
                key = (ect, est, d, -rem, j)
            elif rule == 1:
                key = (est, d, -rem, machine_ready[m], j)
            elif rule == 2:
                key = (est, -d, -rem, machine_ready[m], j)
            elif rule == 3:
                key = (est, -rem, d, machine_ready[m], j)
            elif rule == 4:
                key = (slack_like, est, d, j)
            elif rule == 5:
                key = (machine_ready[m], est, d, -rem, j)
            elif rule == 6:
                key = (est, machine_ready[m], -rem, -d, j)
            else:
                key = (ect, -rem, d, j)

            if best_key is None or key < best_key:
                best_key = key
                best = (j, i, m, d, est)

        j, i, m, d, start = best
        end = start + d
        starts[(j, i)] = start
        ends[(j, i)] = end
        sequences[m].append(j)
        next_op[j] += 1
        job_ready[j] = end
        machine_ready[m] = end

    return max(job_ready) if job_ready else 0, sequences, starts, ends


def _initial_solution(instance):
    best = None
    for rule in range(8):
        candidate = _dispatch_heuristic(instance, rule)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def solve(instance):
    heuristic_makespan, heuristic_sequences, heuristic_starts, heuristic_ends = _initial_solution(instance)

    model = cp_model.CpModel()
    total_duration = int(instance.total_duration)
    horizon = max(heuristic_makespan, 0)
    if horizon <= 0:
        horizon = total_duration

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(int(instance.num_machines))}

    job_prefix = []
    job_tail_after = []
    for job in instance.jobs:
        durations = [int(op.duration) for op in job]
        prefix = [0] * len(durations)
        acc = 0
        for i, d in enumerate(durations):
            prefix[i] = acc
            acc += d
        tail_after = [0] * len(durations)
        acc = 0
        for i in range(len(durations) - 1, -1, -1):
            tail_after[i] = acc
            acc += durations[i]
        job_prefix.append(prefix)
        job_tail_after.append(tail_after)

    for job_id, job in enumerate(instance.jobs):
        for op_index, operation in enumerate(job):
            duration = int(operation.duration)
            machine_id = int(operation.machine_id)
            est = int(job_prefix[job_id][op_index])
            latest_start = int(horizon - duration - job_tail_after[job_id][op_index])
            latest_end = int(horizon - job_tail_after[job_id][op_index])
            if latest_start < est:
                latest_start = horizon
            if latest_end < est + duration:
                latest_end = horizon
            start = model.NewIntVar(est, latest_start, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(est + duration, latest_end, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_index}")
            key = (job_id, op_index)
            starts[key] = start
            ends[key] = end
            intervals_by_machine[machine_id].append((job_id, op_index, interval))

    for job_id, job in enumerate(instance.jobs):
        for op_index in range(1, len(job)):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    machine_loads = []
    for machine_id, machine_ops in intervals_by_machine.items():
        intervals = [interval for _, _, interval in machine_ops]
        if intervals:
            model.AddNoOverlap(intervals)
            load = 0
            for job_id, op_index, _ in machine_ops:
                load += int(instance.jobs[job_id][op_index].duration)
            machine_loads.append(load)

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    if heuristic_makespan > 0:
        model.Add(makespan <= int(heuristic_makespan))

    for job in instance.jobs:
        model.Add(makespan >= sum(int(op.duration) for op in job))
    for load in machine_loads:
        model.Add(makespan >= int(load))

    for key, var in starts.items():
        if key in heuristic_starts:
            model.AddHint(var, int(heuristic_starts[key]))
    for key, var in ends.items():
        if key in heuristic_ends:
            model.AddHint(var, int(heuristic_ends[key]))
    if heuristic_makespan > 0:
        model.AddHint(makespan, int(heuristic_makespan))

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 275.0
    solver.parameters.random_seed = 17
    solver.parameters.num_search_workers = 0

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, heuristic_sequences)

    job_sequences = [[] for _ in range(int(instance.num_machines))]
    for machine_id, machine_ops in intervals_by_machine.items():
        ordered = sorted(
            machine_ops,
            key=lambda item: (
                solver.Value(starts[(item[0], item[1])]),
                solver.Value(ends[(item[0], item[1])]),
                item[0],
                item[1],
            ),
        )
        job_sequences[machine_id] = [job_id for job_id, _, _ in ordered]

    return Schedule.from_job_sequences(instance, job_sequences)