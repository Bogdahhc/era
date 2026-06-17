from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time
import math


def _instance_data(instance):
    jobs = []
    for job in instance.jobs:
        jobs.append([(int(op.machine_id), int(op.duration)) for op in job])
    return jobs


def _evaluate_sequences(jobs, num_machines, sequences, need_times=False):
    num_jobs = len(jobs)
    op_count = sum(len(j) for j in jobs)
    if op_count == 0:
        return (0, {}, {}) if need_times else 0

    ops_by_machine_job = {}
    for j, job in enumerate(jobs):
        for k, (m, _) in enumerate(job):
            ops_by_machine_job.setdefault((m, j), []).append(k)

    used = {}
    machine_ops = [[] for _ in range(num_machines)]
    for m in range(num_machines):
        for j in sequences[m]:
            key = (m, j)
            idx = used.get(key, 0)
            lst = ops_by_machine_job.get(key)
            if lst is None or idx >= len(lst):
                return (math.inf, {}, {}) if need_times else math.inf
            machine_ops[m].append((j, lst[idx]))
            used[key] = idx + 1

    for key, lst in ops_by_machine_job.items():
        if used.get(key, 0) != len(lst):
            return (math.inf, {}, {}) if need_times else math.inf

    node_id = {}
    id_node = []
    durations = []
    t = 0
    for j, job in enumerate(jobs):
        for k, (_, p) in enumerate(job):
            node_id[(j, k)] = t
            id_node.append((j, k))
            durations.append(p)
            t += 1

    succ = [[] for _ in range(op_count)]
    indeg = [0] * op_count

    def add_arc(a, b):
        succ[a].append(b)
        indeg[b] += 1

    for j, job in enumerate(jobs):
        for k in range(len(job) - 1):
            add_arc(node_id[(j, k)], node_id[(j, k + 1)])

    for m in range(num_machines):
        seq = machine_ops[m]
        for a, b in zip(seq, seq[1:]):
            add_arc(node_id[a], node_id[b])

    ready = [i for i, d in enumerate(indeg) if d == 0]
    q_index = 0
    start = [0] * op_count
    seen = 0
    while q_index < len(ready):
        u = ready[q_index]
        q_index += 1
        seen += 1
        finish = start[u] + durations[u]
        for v in succ[u]:
            if start[v] < finish:
                start[v] = finish
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)

    if seen != op_count:
        return (math.inf, {}, {}) if need_times else math.inf

    makespan = max(start[i] + durations[i] for i in range(op_count))
    if not need_times:
        return makespan

    starts = {}
    ends = {}
    for i, (j, k) in enumerate(id_node):
        starts[(j, k)] = int(start[i])
        ends[(j, k)] = int(start[i] + durations[i])
    return int(makespan), starts, ends


def _greedy_schedule(instance, time_limit=2.0):
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

    def build(rule, rng=None):
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
                    key = (ect, -rem, machine_ready[m], p, j)
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (ect + int(16 * noise), est, p + int(10 * noise), -rem, noise, j)

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

    best_ms = None
    best_sequences = fallback_sequences
    best_starts = {}
    best_ends = {}
    start_time = time.monotonic()

    for rule in range(7):
        ms, seq, st, en = build(rule)
        if best_ms is None or ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    rng = random.Random(917371)
    tries = 0
    while tries < 180 and time.monotonic() - start_time < time_limit:
        ms, seq, st, en = build(7, rng)
        if ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en
        tries += 1

    return best_sequences, best_starts, best_ends, int(best_ms)


def _improve_sequences_by_swaps(jobs, num_machines, sequences, time_limit=3.0):
    start_time = time.monotonic()
    best_seq = [list(s) for s in sequences]
    best_ms, best_starts, best_ends = _evaluate_sequences(jobs, num_machines, best_seq, True)
    if not math.isfinite(best_ms):
        return sequences, {}, {}, 0

    improved = True
    rng = random.Random(271828)
    while improved and time.monotonic() - start_time < time_limit:
        improved = False

        machine_order = list(range(num_machines))
        rng.shuffle(machine_order)
        for m in machine_order:
            if time.monotonic() - start_time >= time_limit:
                break
            if len(best_seq[m]) < 2:
                continue

            positions = list(range(len(best_seq[m]) - 1))
            rng.shuffle(positions)
            local_best = None
            local_ms = best_ms

            for pos in positions:
                if best_seq[m][pos] == best_seq[m][pos + 1]:
                    continue
                cand = [list(s) for s in best_seq]
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                ms = _evaluate_sequences(jobs, num_machines, cand, False)
                if ms < local_ms:
                    local_ms = ms
                    local_best = cand
                    if best_ms - ms >= 3:
                        break

            if local_best is not None:
                best_seq = local_best
                best_ms, best_starts, best_ends = _evaluate_sequences(
                    jobs, num_machines, best_seq, True
                )
                improved = True

    return best_seq, best_starts, best_ends, int(best_ms)


def solve(instance):
    wall_start = time.monotonic()
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    heuristic_sequences, hint_starts, hint_ends, heuristic_makespan = _greedy_schedule(
        instance, time_limit=2.5
    )

    improved_sequences, improved_starts, improved_ends, improved_ms = _improve_sequences_by_swaps(
        jobs, num_machines, heuristic_sequences, time_limit=3.5
    )
    if improved_ms and (heuristic_makespan <= 0 or improved_ms <= heuristic_makespan):
        heuristic_sequences = improved_sequences
        hint_starts = improved_starts
        hint_ends = improved_ends
        heuristic_makespan = improved_ms

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

    makespan = model.NewIntVar(0, int(upper_bound), "makespan")
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

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    elapsed = time.monotonic() - wall_start
    solver.parameters.max_time_in_seconds = max(30.0, 294.0 - elapsed)
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 917371
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    solver.parameters.use_optimization_hints = True
    solver.parameters.randomize_search = True
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
    solver.parameters.symmetry_level = 2
    solver.parameters.probing_level = 2

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