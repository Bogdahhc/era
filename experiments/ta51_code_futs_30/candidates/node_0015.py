from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time
from collections import deque


def _instance_data(instance):
    jobs = []
    for job in instance.jobs:
        jobs.append([(int(op.machine_id), int(op.duration)) for op in job])
    return jobs


def _evaluate_sequences(jobs, num_machines, sequences):
    num_jobs = len(jobs)
    op_id = {}
    id_op = []
    durations = []
    op_machine = []
    for j, job in enumerate(jobs):
        for k, (m, p) in enumerate(job):
            op_id[(j, k)] = len(id_op)
            id_op.append((j, k))
            durations.append(int(p))
            op_machine.append(int(m))
    n = len(id_op)
    if n == 0:
        return 0, {}, {}, [[] for _ in range(num_machines)], None, None

    by_job_machine = {}
    for j, job in enumerate(jobs):
        for k, (m, _) in enumerate(job):
            by_job_machine.setdefault((j, int(m)), []).append(k)

    used = [False] * n
    machine_ops = [[] for _ in range(num_machines)]
    for m in range(num_machines):
        occ = {}
        for j in sequences[m]:
            j = int(j)
            key = (j, m)
            idx = occ.get(key, 0)
            lst = by_job_machine.get(key)
            if lst is None or idx >= len(lst):
                return None
            k = lst[idx]
            occ[key] = idx + 1
            oid = op_id[(j, k)]
            if used[oid]:
                return None
            used[oid] = True
            machine_ops[m].append((j, k))
    if not all(used):
        return None

    succ = [[] for _ in range(n)]
    pred_count = [0] * n
    pred_meta = [[] for _ in range(n)]

    def add_edge(a, b, typ, m=-1):
        succ[a].append((b, typ, m))
        pred_count[b] += 1
        pred_meta[b].append((a, typ, m))

    for j, job in enumerate(jobs):
        for k in range(len(job) - 1):
            add_edge(op_id[(j, k)], op_id[(j, k + 1)], 0, -1)

    for m in range(num_machines):
        ops = machine_ops[m]
        for a, b in zip(ops, ops[1:]):
            add_edge(op_id[a], op_id[b], 1, m)

    q = deque([i for i in range(n) if pred_count[i] == 0])
    starts_list = [0] * n
    best_pred = [None] * n
    seen = 0
    pc = pred_count[:]
    while q:
        u = q.popleft()
        seen += 1
        eu = starts_list[u] + durations[u]
        for v, typ, m in succ[u]:
            if eu > starts_list[v]:
                starts_list[v] = eu
                best_pred[v] = (u, typ, m)
            pc[v] -= 1
            if pc[v] == 0:
                q.append(v)

    if seen != n:
        return None

    starts = {}
    ends = {}
    makespan = 0
    last = 0
    for i, (j, k) in enumerate(id_op):
        s = starts_list[i]
        e = s + durations[i]
        starts[(j, k)] = s
        ends[(j, k)] = e
        if e > makespan:
            makespan = e
            last = i

    return int(makespan), starts, ends, machine_ops, best_pred, last


def _critical_adjacent_swaps(jobs, num_machines, sequences, eval_result):
    if eval_result is None:
        return []
    _, _, _, machine_ops, best_pred, last = eval_result
    if best_pred is None:
        return []
    path = []
    cur = last
    while cur is not None:
        path.append(cur)
        bp = best_pred[cur]
        cur = bp[0] if bp is not None else None
    path.reverse()

    op_to_pos = {}
    op_id = {}
    idx = 0
    for j, job in enumerate(jobs):
        for k, _ in enumerate(job):
            op_id[(j, k)] = idx
            idx += 1

    for m in range(num_machines):
        for pos, op in enumerate(machine_ops[m]):
            op_to_pos[op_id[op]] = (m, pos)

    swaps = []
    seen = set()
    for a, b in zip(path, path[1:]):
        pa = op_to_pos.get(a)
        pb = op_to_pos.get(b)
        if pa is not None and pb is not None and pa[0] == pb[0] and pb[1] == pa[1] + 1:
            key = (pa[0], pa[1])
            if key not in seen:
                seen.add(key)
                swaps.append(key)
    return swaps


def _local_improve_sequences(jobs, num_machines, sequences, time_limit):
    start_time = time.monotonic()
    cur_seq = [list(s) for s in sequences]
    cur_eval = _evaluate_sequences(jobs, num_machines, cur_seq)
    if cur_eval is None:
        return sequences, {}, {}, 0
    best_ms, best_starts, best_ends = cur_eval[0], cur_eval[1], cur_eval[2]

    rng = random.Random(431987)
    no_improve_rounds = 0
    while time.monotonic() - start_time < time_limit and no_improve_rounds < 3:
        swaps = _critical_adjacent_swaps(jobs, num_machines, cur_seq, cur_eval)
        if not swaps:
            break
        rng.shuffle(swaps)
        improved = False
        best_move = None
        best_eval = None
        local_best = best_ms

        for m, pos in swaps[:80]:
            if time.monotonic() - start_time >= time_limit:
                break
            if pos < 0 or pos + 1 >= len(cur_seq[m]):
                continue
            cand = [list(s) for s in cur_seq]
            cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
            ev = _evaluate_sequences(jobs, num_machines, cand)
            if ev is not None and ev[0] < local_best:
                local_best = ev[0]
                best_move = (m, pos)
                best_eval = ev
                improved = True

        if improved and best_move is not None:
            m, pos = best_move
            cur_seq[m][pos], cur_seq[m][pos + 1] = cur_seq[m][pos + 1], cur_seq[m][pos]
            cur_eval = best_eval
            best_ms, best_starts, best_ends = cur_eval[0], cur_eval[1], cur_eval[2]
            no_improve_rounds = 0
        else:
            no_improve_rounds += 1

    return cur_seq, best_starts, best_ends, int(best_ms)


def _greedy_schedule(instance, time_limit=2.5):
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
                    key = (ect + int(12 * noise), est, p + int(8 * noise), -rem, noise, j)

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
            candidates = []
            min_ect = None
            star_machine = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                item = (j, k, m, p, est, ect)
                candidates.append(item)
                if min_ect is None or ect < min_ect:
                    min_ect = ect
                    star_machine = m

            conflict = [item for item in candidates if item[2] == star_machine and item[4] < min_ect]
            if not conflict:
                conflict = [item for item in candidates if item[2] == star_machine]

            best = None
            best_key = None
            for j, k, m, p, est, ect in conflict:
                rem = remaining_work[j][k]
                if rule == 0:
                    key = (p, -rem, est, ect, j)
                elif rule == 1:
                    key = (-rem, p, est, ect, j)
                elif rule == 2:
                    key = (ect, p, -rem, est, j)
                elif rule == 3:
                    key = (est, -rem, p, ect, j)
                elif rule == 4:
                    key = (-p, ect, -rem, est, j)
                elif rule == 5:
                    key = (remaining_work[j][k + 1], p, ect, j)
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (ect + int(10 * noise), -rem, p + int(5 * noise), noise, j)
                if best_key is None or key < best_key:
                    best_key = key
                    best = (j, k, m, p, est, ect)

            j, k, m, p, est, _ = best
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

    for rule in range(6):
        for builder in (build_serial, build_giffler_thompson):
            ms, seq, st, en = builder(rule)
            if best_ms is None or ms < best_ms:
                best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    rng = random.Random(917371)
    tries = 0
    random_limit = max(0.25, time_limit * 0.62)
    while tries < 120 and time.monotonic() - start_time < random_limit:
        if tries & 1:
            ms, seq, st, en = build_giffler_thompson(6, rng)
        else:
            ms, seq, st, en = build_serial(6, rng)
        if ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en
        tries += 1

    remaining = max(0.0, time_limit - (time.monotonic() - start_time))
    if remaining > 0.05:
        seq, st, en, ms = _local_improve_sequences(
            jobs, num_machines, best_sequences, min(remaining, 1.0)
        )
        if ms and ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en

    return best_sequences, best_starts, best_ends, int(best_ms)


def solve(instance):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    heuristic_sequences, hint_starts, hint_ends, heuristic_makespan = _greedy_schedule(
        instance, time_limit=2.5
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
            interval = model.NewIntervalVar(start, int(duration), end, f"i_{job_id}_{op_index}")
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

    lb = 0
    for job_id, job in enumerate(jobs):
        if job:
            lb = max(lb, job_prefix[job_id][-1])
    for machine_id in range(num_machines):
        workload = 0
        min_release = None
        min_tail = None
        for job_id, job in enumerate(jobs):
            for op_index, (m, p) in enumerate(job):
                if m == machine_id:
                    workload += p
                    release = job_prefix[job_id][op_index]
                    tail = job_suffix[job_id][op_index + 1]
                    min_release = release if min_release is None else min(min_release, release)
                    min_tail = tail if min_tail is None else min(min_tail, tail)
        if workload:
            lb = max(lb, workload, workload + (min_release or 0) + (min_tail or 0))

    makespan = model.NewIntVar(int(lb), int(upper_bound), "makespan")
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

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 27.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 917371
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 2
    solver.parameters.use_optimization_hints = True
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH

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