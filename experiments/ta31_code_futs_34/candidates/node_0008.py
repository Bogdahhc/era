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


def _best_greedy_schedule(instance):
    rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead"]
    best = None
    for rule in rules:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for seed in range(28):
        cand = _greedy_schedule(instance, rule="random", seed=seed + 17)
        if cand[0] < best[0]:
            best = cand
        cand = _greedy_schedule(instance, rule="mwkr", seed=seed + 101)
        if cand[0] < best[0]:
            best = cand

    return best


def _evaluate_sequences(instance, sequences, machines=None, durations=None):
    if machines is None or durations is None:
        machines, durations = _instance_arrays(instance)

    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    node_id = {}
    id_node = []
    dur = []
    for j in range(n_jobs):
        for k in range(len(machines[j])):
            node_id[(j, k)] = len(id_node)
            id_node.append((j, k))
            dur.append(durations[j][k])

    n = len(id_node)
    succ = [[] for _ in range(n)]
    indeg = [0] * n

    def add_arc(a, b):
        succ[a].append(b)
        indeg[b] += 1

    for j in range(n_jobs):
        for k in range(len(machines[j]) - 1):
            add_arc(node_id[(j, k)], node_id[(j, k + 1)])

    ops_by_machine_job = {}
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            ops_by_machine_job.setdefault((m, j), []).append(k)

    for m in range(n_machines):
        counters = {}
        prev = None
        for j in sequences[m]:
            key = (m, j)
            idx = counters.get(j, 0)
            lst = ops_by_machine_job.get(key)
            if not lst or idx >= len(lst):
                return None
            k = lst[idx]
            counters[j] = idx + 1
            cur = node_id[(j, k)]
            if prev is not None:
                add_arc(prev, cur)
            prev = cur

    est = [0] * n
    q = deque(i for i in range(n) if indeg[i] == 0)
    visited = 0
    while q:
        u = q.popleft()
        visited += 1
        end_u = est[u] + dur[u]
        for v in succ[u]:
            if est[v] < end_u:
                est[v] = end_u
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if visited != n:
        return None

    starts = {}
    ends = {}
    makespan = 0
    for i, (j, k) in enumerate(id_node):
        starts[(j, k)] = est[i]
        ends[(j, k)] = est[i] + dur[i]
        if ends[(j, k)] > makespan:
            makespan = ends[(j, k)]

    return makespan, starts, ends


def _local_search_sequences(instance, initial_sequences, time_limit=10.0, seed=73):
    start_time = time.monotonic()
    machines, durations = _instance_arrays(instance)
    n_machines = int(instance.num_machines)
    rng = random.Random(seed)

    current = [list(s) for s in initial_sequences]
    ev = _evaluate_sequences(instance, current, machines, durations)
    if ev is None:
        return None

    current_ms, current_starts, current_ends = ev
    best = [list(s) for s in current]
    best_ms = current_ms
    best_starts = dict(current_starts)
    best_ends = dict(current_ends)

    machine_order = list(range(n_machines))
    stagnant_rounds = 0

    while time.monotonic() - start_time < time_limit:
        improved = False
        rng.shuffle(machine_order)

        for m in machine_order:
            if time.monotonic() - start_time >= time_limit:
                break
            if len(current[m]) < 2:
                continue

            positions = list(range(len(current[m]) - 1))
            rng.shuffle(positions)
            for p in positions:
                if time.monotonic() - start_time >= time_limit:
                    break
                if current[m][p] == current[m][p + 1]:
                    continue

                current[m][p], current[m][p + 1] = current[m][p + 1], current[m][p]
                cand = _evaluate_sequences(instance, current, machines, durations)
                if cand is not None and cand[0] < current_ms:
                    current_ms, current_starts, current_ends = cand
                    improved = True
                    stagnant_rounds = 0
                    if current_ms < best_ms:
                        best_ms = current_ms
                        best = [list(s) for s in current]
                        best_starts = dict(current_starts)
                        best_ends = dict(current_ends)
                    break
                else:
                    current[m][p], current[m][p + 1] = current[m][p + 1], current[m][p]
            if improved:
                break

        if not improved:
            stagnant_rounds += 1
            current = [list(s) for s in best]
            swaps = 1 + min(5, stagnant_rounds // 2)
            for _ in range(swaps):
                m = rng.randrange(n_machines)
                if len(current[m]) >= 2:
                    p = rng.randrange(len(current[m]) - 1)
                    current[m][p], current[m][p + 1] = current[m][p + 1], current[m][p]
            cand = _evaluate_sequences(instance, current, machines, durations)
            if cand is None:
                current = [list(s) for s in best]
                current_ms = best_ms
            else:
                current_ms, current_starts, current_ends = cand
                if current_ms < best_ms:
                    best_ms = current_ms
                    best = [list(s) for s in current]
                    best_starts = dict(current_starts)
                    best_ends = dict(current_ends)

    return best_ms, best, best_starts, best_ends


def solve(instance):
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _best_greedy_schedule(instance)
        improved = _local_search_sequences(instance, heuristic_sequences, time_limit=12.0, seed=91)
        if improved is not None and improved[0] <= heuristic_makespan:
            heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = improved
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

    all_start_vars = [starts[key] for key in sorted(starts)]
    if all_start_vars:
        model.AddDecisionStrategy(
            all_start_vars,
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 258.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False

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