from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random


def _greedy_active_schedule(instance, rule="mwkr", seed=0):
    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    next_op = [0] * num_jobs
    job_ready = [0] * num_jobs
    machine_ready = [0] * num_machines
    remaining_work = [sum(int(op.duration) for op in job) for job in jobs]
    remaining_ops = [len(job) for job in jobs]

    starts = {}
    ends = {}
    job_sequences = [[] for _ in range(num_machines)]
    total_ops = sum(len(job) for job in jobs)
    scheduled = 0

    rng = random.Random(seed)
    rand_priority = [rng.random() for _ in range(num_jobs)]

    while scheduled < total_ops:
        candidates = []
        for j in range(num_jobs):
            k = next_op[j]
            if k >= len(jobs[j]):
                continue
            op = jobs[j][k]
            m = int(op.machine_id)
            p = int(op.duration)
            est = max(job_ready[j], machine_ready[m])
            ect = est + p
            candidates.append((ect, est, j, k, m, p))

        min_ect = min(c[0] for c in candidates)
        target_machines = [c[4] for c in candidates if c[0] == min_ect]
        target_machine = min(target_machines)
        conflict_set = [
            c for c in candidates if c[4] == target_machine and c[1] < min_ect
        ]
        if not conflict_set:
            conflict_set = [c for c in candidates if c[4] == target_machine]

        def key(c):
            ect, est, j, k, m, p = c
            if rule == "spt":
                return (p, est, -remaining_work[j], j)
            if rule == "lpt":
                return (-p, est, -remaining_work[j], j)
            if rule == "mwkr":
                return (-remaining_work[j], est, p, j)
            if rule == "lwkr":
                return (remaining_work[j], est, p, j)
            if rule == "mopnr":
                return (-remaining_ops[j], est, p, j)
            if rule == "est_spt":
                return (est, p, -remaining_work[j], j)
            if rule == "ect":
                return (ect, est, p, j)
            if rule == "random":
                return (rand_priority[j], est, p, j)
            return (est, p, j)

        _, est, j, k, m, p = min(conflict_set, key=key)

        starts[(j, k)] = est
        end = est + p
        ends[(j, k)] = end
        job_sequences[m].append(j)

        next_op[j] += 1
        job_ready[j] = end
        machine_ready[m] = end
        remaining_work[j] -= p
        remaining_ops[j] -= 1
        scheduled += 1

    return max(machine_ready), job_sequences, starts, ends


def _best_greedy_schedule(instance):
    rules = ("mwkr", "mopnr", "spt", "lpt", "est_spt", "ect", "lwkr")
    best = None

    for rule in rules:
        candidate = _greedy_active_schedule(instance, rule=rule, seed=0)
        if best is None or candidate[0] < best[0]:
            best = candidate

    for seed in range(24):
        candidate = _greedy_active_schedule(instance, rule="random", seed=seed + 17)
        if candidate[0] < best[0]:
            best = candidate

    return best


def solve(instance):
    heuristic_makespan, fallback_job_sequences, hint_starts, hint_ends = (
        _best_greedy_schedule(instance)
    )

    model = cp_model.CpModel()
    upper_bound = int(heuristic_makespan)
    lower_bound = 0

    if hasattr(instance, "jobs"):
        job_totals = [sum(int(op.duration) for op in job) for job in instance.jobs]
        if job_totals:
            lower_bound = max(lower_bound, max(job_totals))

        machine_totals = [0] * instance.num_machines
        for job in instance.jobs:
            for op in job:
                machine_totals[int(op.machine_id)] += int(op.duration)
        if machine_totals:
            lower_bound = max(lower_bound, max(machine_totals))

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(instance.num_machines)}

    job_prefix = []
    job_suffix_after = []
    for job in instance.jobs:
        prefix = []
        t = 0
        for op in job:
            prefix.append(t)
            t += int(op.duration)
        suffix_after = [0] * len(job)
        s = 0
        for idx in range(len(job) - 1, -1, -1):
            suffix_after[idx] = s
            s += int(job[idx].duration)
        job_prefix.append(prefix)
        job_suffix_after.append(suffix_after)

    for job_id, job in enumerate(instance.jobs):
        for op_index, operation in enumerate(job):
            key = (job_id, op_index)
            duration = int(operation.duration)
            machine_id = int(operation.machine_id)

            start_lb = int(job_prefix[job_id][op_index])
            start_ub = int(upper_bound - duration - job_suffix_after[job_id][op_index])
            end_lb = start_lb + duration
            end_ub = int(upper_bound - job_suffix_after[job_id][op_index])

            if start_ub < start_lb:
                start_lb, start_ub = 0, upper_bound
            if end_ub < end_lb:
                end_lb, end_ub = 0, upper_bound

            start = model.NewIntVar(start_lb, start_ub, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(end_lb, end_ub, f"e_{job_id}_{op_index}")
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
        if machine_ops:
            model.AddNoOverlap([interval for _, _, interval in machine_ops])

    makespan = model.NewIntVar(lower_bound, upper_bound, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    model.Minimize(makespan)

    for key, var in starts.items():
        if key in hint_starts:
            model.AddHint(var, int(hint_starts[key]))
    for key, var in ends.items():
        if key in hint_ends:
            model.AddHint(var, int(hint_ends[key]))
    model.AddHint(makespan, upper_bound)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 295.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, fallback_job_sequences)

    job_sequences = [[] for _ in range(instance.num_machines)]
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