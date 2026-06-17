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
                else:
                    noise = rng.random() if rng is not None else 0.0
                    key = (ect + int(12 * noise), est, p + int(8 * noise), -rem, noise, j)

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
            star_est = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
                ect = est + p
                item = (j, k, m, p, est, ect)
                candidates.append(item)
                if min_ect is None or ect < min_ect or (ect == min_ect and (star_est is None or est < star_est)):
                    min_ect = ect
                    star_machine = m
                    star_est = est

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
    while tries < 160 and time.monotonic() - start_time < time_limit:
        if tries & 1:
            ms, seq, st, en = build_giffler_thompson(6, rng)
        else:
            ms, seq, st, en = build_serial(6, rng)
        if ms < best_ms:
            best_ms, best_sequences, best_starts, best_ends = ms, seq, st, en
        tries += 1

    return best_sequences, best_starts, best_ends, int(best_ms)


def _decode_fixed_sequences(jobs, num_machines, sequences):
    num_jobs = len(jobs)
    op_id = {}
    id_op = []
    durations = []
    machines = []
    for j, job in enumerate(jobs):
        for k, (m, p) in enumerate(job):
            op_id[(j, k)] = len(id_op)
            id_op.append((j, k))
            durations.append(int(p))
            machines.append(int(m))

    n = len(id_op)
    if n == 0:
        return 0, {}, {}, [], [], True

    by_job_machine = {}
    for j, job in enumerate(jobs):
        for k, (m, _) in enumerate(job):
            by_job_machine.setdefault((j, int(m)), []).append(k)

    succ = [[] for _ in range(n)]
    indeg = [0] * n

    for j, job in enumerate(jobs):
        for k in range(1, len(job)):
            u = op_id[(j, k - 1)]
            v = op_id[(j, k)]
            succ[u].append(v)
            indeg[v] += 1

    machine_ops = [[] for _ in range(num_machines)]
    node_pos = {}
    for m in range(num_machines):
        occ = {}
        for j in sequences[m]:
            j = int(j)
            c = occ.get(j, 0)
            occ[j] = c + 1
            ks = by_job_machine.get((j, m))
            if ks is None or c >= len(ks):
                return None, None, None, None, None, False
            node = op_id[(j, ks[c])]
            node_pos[node] = (m, len(machine_ops[m]))
            machine_ops[m].append(node)
        for pos in range(1, len(machine_ops[m])):
            u = machine_ops[m][pos - 1]
            v = machine_ops[m][pos]
            succ[u].append(v)
            indeg[v] += 1

    for node in range(n):
        if node not in node_pos:
            return None, None, None, None, None, False

    q = deque(i for i in range(n) if indeg[i] == 0)
    starts_arr = [0] * n
    pred = [-1] * n
    topo_count = 0

    while q:
        u = q.popleft()
        topo_count += 1
        eu = starts_arr[u] + durations[u]
        for v in succ[u]:
            if eu > starts_arr[v]:
                starts_arr[v] = eu
                pred[v] = u
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if topo_count != n:
        return None, None, None, None, None, False

    ends_arr = [starts_arr[i] + durations[i] for i in range(n)]
    makespan = max(ends_arr)
    starts = {}
    ends = {}
    for node, (j, k) in enumerate(id_op):
        starts[(j, k)] = starts_arr[node]
        ends[(j, k)] = ends_arr[node]

    return makespan, starts, ends, pred, node_pos, True


def _critical_path_local_search(jobs, num_machines, sequences, incumbent_ms, time_limit=1.2):
    t0 = time.monotonic()
    best_seq = [list(s) for s in sequences]
    decoded = _decode_fixed_sequences(jobs, num_machines, best_seq)
    if not decoded[-1]:
        return sequences, {}, {}, incumbent_ms
    best_ms, best_starts, best_ends, pred, node_pos, _ = decoded
    if incumbent_ms and incumbent_ms < best_ms:
        best_ms = incumbent_ms

    improved = True
    while improved and time.monotonic() - t0 < time_limit:
        improved = False
        decoded = _decode_fixed_sequences(jobs, num_machines, best_seq)
        if not decoded[-1]:
            break
        cur_ms, cur_starts, cur_ends, pred, node_pos, _ = decoded
        if cur_ms < best_ms:
            best_ms, best_starts, best_ends = cur_ms, cur_starts, cur_ends

        end_node = None
        max_end = -1
        for (j, k), e in cur_ends.items():
            if e > max_end:
                max_end = e
                end_node = sum(len(jobs[x]) for x in range(j)) + k

        path = []
        x = end_node
        while x is not None and x >= 0:
            path.append(x)
            x = pred[x]
        path.reverse()

        candidates = set()
        for a, b in zip(path, path[1:]):
            pa = node_pos.get(a)
            pb = node_pos.get(b)
            if pa is not None and pb is not None and pa[0] == pb[0] and abs(pa[1] - pb[1]) == 1:
                candidates.add((pa[0], min(pa[1], pb[1])))

        best_move = None
        best_move_ms = cur_ms
        for m, pos in candidates:
            if time.monotonic() - t0 >= time_limit:
                break
            cand_seq = [list(s) for s in best_seq]
            cand_seq[m][pos], cand_seq[m][pos + 1] = cand_seq[m][pos + 1], cand_seq[m][pos]
            ms, st, en, _, _, ok = _decode_fixed_sequences(jobs, num_machines, cand_seq)
            if ok and ms < best_move_ms:
                best_move_ms = ms
                best_move = (m, pos, st, en)

        if best_move is not None:
            m, pos, st, en = best_move
            best_seq[m][pos], best_seq[m][pos + 1] = best_seq[m][pos + 1], best_seq[m][pos]
            best_ms = best_move_ms
            best_starts = st
            best_ends = en
            improved = True

    return best_seq, best_starts, best_ends, int(best_ms)


def solve(instance):
    jobs = _instance_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    heuristic_sequences, hint_starts, hint_ends, heuristic_makespan = _greedy_schedule(
        instance, time_limit=2.5
    )

    ls_sequences, ls_starts, ls_ends, ls_makespan = _critical_path_local_search(
        jobs, num_machines, heuristic_sequences, heuristic_makespan, time_limit=1.2
    )
    if ls_makespan and (heuristic_makespan <= 0 or ls_makespan < heuristic_makespan):
        heuristic_sequences = ls_sequences
        hint_starts = ls_starts
        hint_ends = ls_ends
        heuristic_makespan = ls_makespan

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

    makespan = model.NewIntVar(0, int(upper_bound), "makespan")
    if ends:
        model.AddMaxEquality(makespan, list(ends.values()))
    else:
        model.Add(makespan == 0)

    for job_id, job in enumerate(jobs):
        if job:
            model.Add(makespan >= int(job_prefix[job_id][-1]))

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
            model.Add(makespan >= int(workload))
            model.Add(makespan >= int(workload + (min_release or 0) + (min_tail or 0)))

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
    solver.parameters.max_time_in_seconds = 285.0
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