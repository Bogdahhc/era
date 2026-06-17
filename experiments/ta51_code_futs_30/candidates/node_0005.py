from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time


def _instance_data(instance):
    jobs = []
    for job in instance.jobs:
        jobs.append([(int(op.machine_id), int(op.duration)) for op in job])
    return jobs


def _fallback_sequences(jobs, num_machines):
    seq = [[] for _ in range(num_machines)]
    for j, job in enumerate(jobs):
        for m, _ in job:
            if 0 <= m < num_machines:
                seq[m].append(j)
    return seq


def _greedy_schedule(instance, time_limit=6.0):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)
    total_ops = sum(len(job) for job in jobs)

    fallback_sequences = _fallback_sequences(jobs, num_machines)
    if total_ops == 0:
        return fallback_sequences, {}, {}, 0

    remaining_work = []
    for job in jobs:
        rem = [0] * (len(job) + 1)
        for k in range(len(job) - 1, -1, -1):
            rem[k] = rem[k + 1] + job[k][1]
        remaining_work.append(rem)

    def serial_build(rule, rng=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        sequences = [[] for _ in range(num_machines)]
        starts = {}
        ends = {}
        scheduled = 0

        while scheduled < total_ops:
            best_j = None
            best_key = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
                ect = est + p
                rem = remaining_work[j][k]

                if rule == 0:
                    key = (ect, p, est, -rem, j)
                elif rule == 1:
                    key = (est, p, ect, -rem, j)
                elif rule == 2:
                    key = (-rem, ect, p, j)
                elif rule == 3:
                    key = (p, ect, -rem, j)
                elif rule == 4:
                    key = (-p, ect, -rem, j)
                elif rule == 5:
                    key = (machine_ready[m], ect, p, -rem, j)
                elif rule == 6:
                    key = (ect, -rem, -p, est, j)
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (ect + int(20 * noise), est, p + int(10 * noise), -rem, noise, j)

                if best_key is None or key < best_key:
                    best_key = key
                    best_j = j

            j = best_j
            k = next_op[j]
            m, p = jobs[j][k]
            s = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
            e = s + p
            starts[(j, k)] = s
            ends[(j, k)] = e
            sequences[m].append(j)
            job_ready[j] = e
            machine_ready[m] = e
            next_op[j] += 1
            scheduled += 1

        return max(job_ready), sequences, starts, ends

    def gt_build(rule, rng=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        sequences = [[] for _ in range(num_machines)]
        starts = {}
        ends = {}
        scheduled = 0

        while scheduled < total_ops:
            candidates = []
            min_ect = None
            chosen_machine = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
                ect = est + p
                candidates.append((j, k, m, p, est, ect))
                if min_ect is None or ect < min_ect:
                    min_ect = ect
                    chosen_machine = m

            conflict = [x for x in candidates if x[2] == chosen_machine and x[4] < min_ect]
            if not conflict:
                conflict = [x for x in candidates if x[2] == chosen_machine]

            def key_of(x):
                j, k, m, p, est, ect = x
                rem = remaining_work[j][k]
                if rule == 0:
                    return (p, ect, -rem, est, j)
                if rule == 1:
                    return (-p, ect, -rem, est, j)
                if rule == 2:
                    return (-rem, ect, p, est, j)
                if rule == 3:
                    return (ect, p, -rem, est, j)
                if rule == 4:
                    return (est, ect, p, -rem, j)
                if rule == 5:
                    return (-remaining_work[j][k + 1], ect, p, est, j)
                if rule == 6:
                    return (ect, -rem, -p, est, j)
                if rule == 7:
                    return (-rem / max(1, p), ect, p, est, j)
                noise = rng.random() if rng is not None else 0.0
                return (ect + int(25 * noise), -rem + int(40 * noise), p, noise, j)

            j, k, m, p, est, ect = min(conflict, key=key_of)
            s = est
            e = s + p
            starts[(j, k)] = s
            ends[(j, k)] = e
            sequences[m].append(j)
            job_ready[j] = e
            machine_ready[m] = e
            next_op[j] += 1
            scheduled += 1

        return max(job_ready), sequences, starts, ends

    best_ms = None
    best_sequences = fallback_sequences
    best_starts = {}
    best_ends = {}
    start_time = time.monotonic()

    for rule in range(7):
        ms, seq, st, en = serial_build(rule)
        if best_ms is None or ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    for rule in range(8):
        ms, seq, st, en = gt_build(rule)
        if ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    rng = random.Random(917371)
    tries = 0
    while time.monotonic() - start_time < time_limit:
        if tries & 1:
            ms, seq, st, en = gt_build(8, rng)
        else:
            ms, seq, st, en = serial_build(7, rng)
        if ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en
        tries += 1

    return best_sequences, best_starts, best_ends, int(best_ms)


def solve(instance):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    heuristic_sequences, hint_starts, hint_ends, heuristic_makespan = _greedy_schedule(
        instance, time_limit=6.0
    )

    horizon = int(getattr(instance, "total_duration", 0))
    if horizon <= 0:
        horizon = sum(p for job in jobs for _, p in job)

    if not jobs or horizon <= 0:
        return Schedule.from_job_sequences(instance, heuristic_sequences)

    upper_bound = heuristic_makespan if heuristic_makespan > 0 else horizon
    upper_bound = min(upper_bound, horizon)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(num_machines)}

    job_prefix = []
    job_suffix = []
    for job in jobs:
        prefix = [0] * (len(job) + 1)
        for k, (_, p) in enumerate(job):
            prefix[k + 1] = prefix[k] + p
        suffix = [0] * (len(job) + 1)
        for k in range(len(job) - 1, -1, -1):
            suffix[k] = suffix[k + 1] + job[k][1]
        job_prefix.append(prefix)
        job_suffix.append(suffix)

    machine_workload = [0] * num_machines
    for job in jobs:
        for m, p in job:
            if 0 <= m < num_machines:
                machine_workload[m] += p

    lower_bound = 0
    for j in range(num_jobs):
        if job_prefix[j][-1] > lower_bound:
            lower_bound = job_prefix[j][-1]
    for w in machine_workload:
        if w > lower_bound:
            lower_bound = w

    for job_id, job in enumerate(jobs):
        for op_index, (machine_id, duration) in enumerate(job):
            earliest_start = job_prefix[job_id][op_index]
            earliest_end = earliest_start + duration
            latest_start = upper_bound - job_suffix[job_id][op_index]
            latest_end = upper_bound - job_suffix[job_id][op_index + 1]

            if latest_start < earliest_start:
                earliest_start = 0
                earliest_end = duration
                latest_start = horizon - duration
                latest_end = horizon

            start = model.NewIntVar(
                int(earliest_start),
                int(max(earliest_start, latest_start)),
                f"s_{job_id}_{op_index}",
            )
            end = model.NewIntVar(
                int(earliest_end),
                int(max(earliest_end, latest_end)),
                f"e_{job_id}_{op_index}",
            )
            interval = model.NewIntervalVar(
                start, int(duration), end, f"i_{job_id}_{op_index}"
            )
            key = (job_id, op_index)
            starts[key] = start
            ends[key] = end
            intervals_by_machine[int(machine_id)].append((job_id, op_index, interval))

    for job_id, job in enumerate(jobs):
        for op_index in range(1, len(job)):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    for machine_id, machine_ops in intervals_by_machine.items():
        if machine_ops:
            model.AddNoOverlap([interval for _, _, interval in machine_ops])

    makespan = model.NewIntVar(int(lower_bound), int(upper_bound), "makespan")
    if ends:
        model.AddMaxEquality(makespan, list(ends.values()))
    else:
        model.Add(makespan == 0)

    if heuristic_makespan > 0:
        model.Add(makespan <= int(heuristic_makespan))

    for key, var in starts.items():
        if key in hint_starts:
            model.AddHint(var, int(hint_starts[key]))
    for key, var in ends.items():
        if key in hint_ends:
            model.AddHint(var, int(hint_ends[key]))
    if heuristic_makespan > 0:
        model.AddHint(makespan, int(heuristic_makespan))

    hinted_start_vars = []
    for key in sorted(starts, key=lambda x: hint_starts.get(x, horizon)):
        hinted_start_vars.append(starts[key])
    if hinted_start_vars:
        model.AddDecisionStrategy(
            hinted_start_vars,
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 279.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 917371
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    solver.parameters.use_optimization_hints = True
    solver.parameters.randomize_search = True
    solver.parameters.search_branching = cp_model.PORTFOLIO_WITH_QUICK_RESTART_SEARCH

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, heuristic_sequences)

    job_sequences = [[] for _ in range(num_machines)]
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