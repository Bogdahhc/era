from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time


def _instance_data(instance):
    jobs = []
    for job in instance.jobs:
        jobs.append([(int(op.machine_id), int(op.duration)) for op in job])
    return jobs


def _greedy_schedule(instance, time_limit=3.0):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)
    total_ops = sum(len(job) for job in jobs)

    fallback_sequences = [[] for _ in range(num_machines)]
    for j, job in enumerate(jobs):
        for m, _ in job:
            fallback_sequences[m].append(j)

    if total_ops == 0:
        return fallback_sequences, {}, {}, 0

    remaining_work = []
    for job in jobs:
        rem = [0] * (len(job) + 1)
        for k in range(len(job) - 1, -1, -1):
            rem[k] = rem[k + 1] + job[k][1]
        remaining_work.append(rem)

    def build_serial(rule, rng=None):
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
                est = max(job_ready[j], machine_ready[m])
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
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (ect + int(14 * noise), est, p + int(9 * noise), -rem, noise, j)

                if best_key is None or key < best_key:
                    best_key = key
                    best_j = j

            j = best_j
            k = next_op[j]
            m, p = jobs[j][k]
            s = max(job_ready[j], machine_ready[m])
            e = s + p
            starts[(j, k)] = s
            ends[(j, k)] = e
            sequences[m].append(j)
            job_ready[j] = e
            machine_ready[m] = e
            next_op[j] += 1
            scheduled += 1

        return max(job_ready), sequences, starts, ends

    def build_giffler_thompson(rule, rng=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        sequences = [[] for _ in range(num_machines)]
        starts = {}
        ends = {}
        scheduled = 0

        while scheduled < total_ops:
            eligible = []
            min_ect = None
            bottleneck_machine = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                eligible.append((j, k, m, p, est, ect, remaining_work[j][k]))
                if min_ect is None or ect < min_ect:
                    min_ect = ect
                    bottleneck_machine = m

            conflict = [
                item for item in eligible
                if item[2] == bottleneck_machine and item[4] < min_ect
            ]
            if not conflict:
                conflict = [item for item in eligible if item[2] == bottleneck_machine]

            best_item = None
            best_key = None
            for item in conflict:
                j, k, m, p, est, ect, rem = item
                if rule == 0:
                    key = (p, -rem, est, ect, j)
                elif rule == 1:
                    key = (-rem, p, est, ect, j)
                elif rule == 2:
                    key = (ect, p, -rem, est, j)
                elif rule == 3:
                    key = (est, p, -rem, ect, j)
                elif rule == 4:
                    key = (-p, ect, -rem, est, j)
                elif rule == 5:
                    key = (remaining_work[j][k + 1] if k + 1 < len(remaining_work[j]) else 0, p, ect, j)
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (p + int(10 * noise), -rem, ect + int(10 * noise), noise, j)

                if best_key is None or key < best_key:
                    best_key = key
                    best_item = item

            j, k, m, p, est, ect, rem = best_item
            s = max(job_ready[j], machine_ready[m])
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

    def consider(result):
        nonlocal best_ms, best_sequences, best_starts, best_ends
        ms, seq, st, en = result
        if best_ms is None or ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    for rule in range(6):
        consider(build_serial(rule))
        consider(build_giffler_thompson(rule))

    rng = random.Random(917371)
    tries = 0
    while tries < 200 and time.monotonic() - start_time < time_limit:
        if tries & 1:
            consider(build_serial(6, rng))
        else:
            consider(build_giffler_thompson(6, rng))
        tries += 1

    return best_sequences, best_starts, best_ends, int(best_ms)


def solve(instance):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    heuristic_sequences, hint_starts, hint_ends, heuristic_makespan = _greedy_schedule(
        instance, time_limit=3.0
    )

    horizon = int(getattr(instance, "total_duration", 0))
    if horizon <= 0:
        horizon = sum(p for job in jobs for _, p in job)

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
            machine_workload[m] += p

    lower_bound = 0
    if job_prefix:
        lower_bound = max(lower_bound, max(prefix[-1] for prefix in job_prefix))
    if machine_workload:
        lower_bound = max(lower_bound, max(machine_workload))

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
                int(earliest_start), int(max(earliest_start, latest_start)),
                f"s_{job_id}_{op_index}"
            )
            end = model.NewIntVar(
                int(earliest_end), int(max(earliest_end, latest_end)),
                f"e_{job_id}_{op_index}"
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

    for job_id, job in enumerate(jobs):
        if job:
            model.Add(makespan >= int(job_prefix[job_id][-1]))

    for workload in machine_workload:
        if workload:
            model.Add(makespan >= int(workload))

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

    critical_start_vars = sorted(
        starts.items(),
        key=lambda kv: (
            -(job_suffix[kv[0][0]][kv[0][1]] + job_prefix[kv[0][0]][kv[0][1] + 1]),
            kv[0][1],
            kv[0][0],
        ),
    )
    if critical_start_vars:
        model.AddDecisionStrategy(
            [var for _, var in critical_start_vars],
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 285.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 917371
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    solver.parameters.use_optimization_hints = True

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