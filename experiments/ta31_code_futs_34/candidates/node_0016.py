from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time
from collections import deque


def _instance_arrays(instance):
    machines = []
    durations = []
    for job in instance.jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(int(op.machine_id))
            jd.append(int(op.duration))
        machines.append(jm)
        durations.append(jd)
    return machines, durations


def _fallback_sequences(instance):
    seq = [[] for _ in range(int(instance.num_machines))]
    for j, job in enumerate(instance.jobs):
        for op in job:
            seq[int(op.machine_id)].append(j)
    return seq


def _greedy_schedule(instance, rule="mwkr", seed=0):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(j) for j in machines)

    suffix = []
    for j in range(n_jobs):
        s = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            s[k] = s[k + 1] + durations[j][k]
        suffix.append(s)

    rng = random.Random(seed)
    next_op = [0] * n_jobs
    job_ready = [0] * n_jobs
    machine_ready = [0] * n_machines
    starts = {}
    ends = {}
    seq = [[] for _ in range(n_machines)]
    done = 0

    job_priority = list(range(n_jobs))
    rng.shuffle(job_priority)
    job_priority = {j: p for p, j in enumerate(job_priority)}

    while done < total_ops:
        best_key = None
        best_job = None
        for j in range(n_jobs):
            k = next_op[j]
            if k >= len(machines[j]):
                continue
            m = machines[j][k]
            d = durations[j][k]
            est = max(job_ready[j], machine_ready[m])
            ect = est + d
            rem = suffix[j][k]
            rem_after = suffix[j][k + 1]
            if rule == "spt":
                key = (est, d, -rem, job_priority[j], j)
            elif rule == "lpt":
                key = (est, -d, -rem, job_priority[j], j)
            elif rule == "ect":
                key = (ect, est, -rem, job_priority[j], j)
            elif rule == "mwkr":
                key = (est, -rem, d, job_priority[j], j)
            elif rule == "mor":
                key = (est, -(len(machines[j]) - k), -rem, d, job_priority[j], j)
            elif rule == "random":
                key = (est, rng.random(), j)
            elif rule == "lookahead":
                key = (est, -rem_after, ect, d, job_priority[j], j)
            elif rule == "machine_slack":
                key = (machine_ready[m], est, -rem, d, job_priority[j], j)
            else:
                key = (est, job_priority[j], j)

            if best_key is None or key < best_key:
                best_key = key
                best_job = j

        j = best_job
        k = next_op[j]
        m = machines[j][k]
        d = durations[j][k]
        st = max(job_ready[j], machine_ready[m])
        en = st + d
        starts[(j, k)] = st
        ends[(j, k)] = en
        seq[m].append(j)
        job_ready[j] = en
        machine_ready[m] = en
        next_op[j] += 1
        done += 1

    return max(job_ready) if job_ready else 0, seq, starts, ends


def _decode_sequences(instance, job_sequences):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    nodes = []
    node_id = {}
    for j in range(n_jobs):
        for k in range(len(machines[j])):
            node_id[(j, k)] = len(nodes)
            nodes.append((j, k))

    n = len(nodes)
    if n == 0:
        return 0, {}, {}, [], []

    ops_by_jm = {}
    machine_counts = [0] * n_machines
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            ops_by_jm.setdefault((j, m), deque()).append(k)
            machine_counts[m] += 1

    if len(job_sequences) != n_machines:
        return None

    machine_ops = [[] for _ in range(n_machines)]
    for m in range(n_machines):
        if len(job_sequences[m]) != machine_counts[m]:
            return None
        local = {key: deque(val) for key, val in ops_by_jm.items() if key[1] == m}
        for j in job_sequences[m]:
            key = (int(j), m)
            if key not in local or not local[key]:
                return None
            k = local[key].popleft()
            machine_ops[m].append((int(j), k))

    succ = [[] for _ in range(n)]
    indeg = [0] * n

    def add_arc(a, b):
        aid = node_id[a]
        bid = node_id[b]
        succ[aid].append(bid)
        indeg[bid] += 1

    for j in range(n_jobs):
        for k in range(len(machines[j]) - 1):
            add_arc((j, k), (j, k + 1))

    for m in range(n_machines):
        ops = machine_ops[m]
        for p in range(len(ops) - 1):
            add_arc(ops[p], ops[p + 1])

    q = deque([i for i in range(n) if indeg[i] == 0])
    topo = []
    indeg_work = indeg[:]
    while q:
        u = q.popleft()
        topo.append(u)
        for v in succ[u]:
            indeg_work[v] -= 1
            if indeg_work[v] == 0:
                q.append(v)

    if len(topo) != n:
        return None

    start_vals = [0] * n
    pred = [-1] * n
    for u in topo:
        j, k = nodes[u]
        finish = start_vals[u] + durations[j][k]
        for v in succ[u]:
            if finish > start_vals[v]:
                start_vals[v] = finish
                pred[v] = u

    starts = {}
    ends = {}
    best_end = -1
    best_node = -1
    for i, (j, k) in enumerate(nodes):
        starts[(j, k)] = start_vals[i]
        ends[(j, k)] = start_vals[i] + durations[j][k]
        if ends[(j, k)] > best_end:
            best_end = ends[(j, k)]
            best_node = i

    critical_path = []
    cur = best_node
    while cur != -1:
        critical_path.append(nodes[cur])
        cur = pred[cur]
    critical_path.reverse()

    return best_end, starts, ends, machine_ops, critical_path


def _best_greedy_schedule(instance):
    rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "machine_slack"]
    best = None
    for rule in rules:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for seed in range(32):
        cand = _greedy_schedule(instance, rule="random", seed=seed + 17)
        if cand[0] < best[0]:
            best = cand
        cand = _greedy_schedule(instance, rule="mwkr", seed=seed + 101)
        if cand[0] < best[0]:
            best = cand
        cand = _greedy_schedule(instance, rule="machine_slack", seed=seed + 211)
        if cand[0] < best[0]:
            best = cand

    return best


def _critical_adjacent_local_search(instance, initial_sequences, time_limit=12.0):
    start_time = time.time()
    decoded = _decode_sequences(instance, initial_sequences)
    if decoded is None:
        return None
    best_ms, best_starts, best_ends, _, best_cp = decoded
    best_seq = [list(s) for s in initial_sequences]

    machines, _ = _instance_arrays(instance)
    n_machines = int(instance.num_machines)

    op_to_machine = {}
    for j, job_machines in enumerate(machines):
        for k, m in enumerate(job_machines):
            op_to_machine[(j, k)] = m

    improved = True
    iterations = 0
    while improved and time.time() - start_time < time_limit:
        improved = False
        iterations += 1
        candidate_swaps = []
        for a, b in zip(best_cp, best_cp[1:]):
            ma = op_to_machine.get(a)
            if ma is not None and ma == op_to_machine.get(b):
                candidate_swaps.append((ma, a[0], b[0]))

        seen = set()
        ordered_swaps = []
        for item in candidate_swaps:
            if item not in seen:
                seen.add(item)
                ordered_swaps.append(item)

        local_best = None
        for m, ja, jb in ordered_swaps:
            if time.time() - start_time >= time_limit:
                break
            seq_m = best_seq[m]
            positions = [i for i, x in enumerate(seq_m) if x == ja]
            pos_b_set = {i for i, x in enumerate(seq_m) if x == jb}
            swap_pos = None
            for p in positions:
                if p + 1 in pos_b_set:
                    swap_pos = p
                    break
            if swap_pos is None:
                continue

            new_seq = [list(s) for s in best_seq]
            new_seq[m][swap_pos], new_seq[m][swap_pos + 1] = new_seq[m][swap_pos + 1], new_seq[m][swap_pos]
            dec = _decode_sequences(instance, new_seq)
            if dec is None:
                continue
            ms = dec[0]
            if ms < best_ms and (local_best is None or ms < local_best[0]):
                local_best = (ms, new_seq, dec)

        if local_best is not None:
            best_ms = local_best[0]
            best_seq = local_best[1]
            best_starts = local_best[2][1]
            best_ends = local_best[2][2]
            best_cp = local_best[2][4]
            improved = True

        if iterations >= 200:
            break

    return best_ms, best_seq, best_starts, best_ends


def solve(instance):
    solve_start_time = time.time()
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _best_greedy_schedule(instance)
        ls = _critical_adjacent_local_search(instance, heuristic_sequences, time_limit=14.0)
        if ls is not None and ls[0] <= heuristic_makespan:
            heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = ls
    except Exception:
        heuristic_makespan = int(instance.total_duration)
        heuristic_sequences = fallback_job_sequences
        hint_starts = {}
        hint_ends = {}

    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_duration = int(instance.total_duration)
    horizon = max(1, min(total_duration, int(heuristic_makespan)))

    job_prefix = []
    job_suffix = []
    for j in range(n_jobs):
        pref = [0] * (len(durations[j]) + 1)
        for k, d in enumerate(durations[j]):
            pref[k + 1] = pref[k] + d
        suff = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            suff[k] = suff[k + 1] + durations[j][k]
        job_prefix.append(pref)
        job_suffix.append(suff)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(n_machines)}

    for job_id in range(n_jobs):
        for op_index in range(len(machines[job_id])):
            duration = durations[job_id][op_index]
            machine_id = machines[job_id][op_index]
            start_lb = job_prefix[job_id][op_index]
            end_lb = start_lb + duration
            start_ub = horizon - duration - job_suffix[job_id][op_index + 1]
            end_ub = horizon - job_suffix[job_id][op_index + 1]
            if start_ub < start_lb:
                start_ub = horizon
            if end_ub < end_lb:
                end_ub = horizon

            start = model.NewIntVar(start_lb, start_ub, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(end_lb, end_ub, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_index}")
            starts[(job_id, op_index)] = start
            ends[(job_id, op_index)] = end
            intervals_by_machine[machine_id].append((job_id, op_index, interval))

    for job_id in range(n_jobs):
        for op_index in range(1, len(machines[job_id])):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    for machine_ops in intervals_by_machine.values():
        if machine_ops:
            model.AddNoOverlap([interval for _, _, interval in machine_ops])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))

    job_load_lb = max((sum(durations[j]) for j in range(n_jobs)), default=0)
    machine_loads = [0] * n_machines
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            machine_loads[m] += durations[j][k]
    model.Add(makespan >= max(job_load_lb, max(machine_loads) if machine_loads else 0))
    if heuristic_makespan < total_duration:
        model.Add(makespan <= int(heuristic_makespan))

    for key, var in starts.items():
        if key in hint_starts:
            model.AddHint(var, int(hint_starts[key]))
    for key, var in ends.items():
        if key in hint_ends:
            model.AddHint(var, int(hint_ends[key]))
    if heuristic_makespan < total_duration:
        model.AddHint(makespan, int(heuristic_makespan))

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    elapsed = time.time() - solve_start_time
    solver.parameters.max_time_in_seconds = max(60.0, min(282.0, 286.0 - elapsed))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    solver.parameters.randomize_search = True
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, heuristic_sequences)

    job_sequences = [[] for _ in range(n_machines)]
    for machine_id, machine_ops in intervals_by_machine.items():
        ordered = sorted(
            machine_ops,
            key=lambda item: (solver.Value(starts[(item[0], item[1])]), item[0], item[1]),
        )
        job_sequences[machine_id] = [job_id for job_id, _, _ in ordered]

    return Schedule.from_job_sequences(instance, job_sequences)