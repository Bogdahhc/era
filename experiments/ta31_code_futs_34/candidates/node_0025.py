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
    seq = [[] for _ in range(instance.num_machines)]
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
            slack_proxy = max(machine_ready[m] - job_ready[j], 0)
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
            elif rule == "critical":
                key = (est, -(rem + slack_proxy), ect, -d, job_priority[j], j)
            elif rule == "dense":
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


def _best_greedy_schedule(instance):
    rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "critical", "dense"]
    best = None
    for rule in rules:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for seed in range(42):
        for rule, offset in (("random", 17), ("mwkr", 101), ("critical", 211), ("lookahead", 307)):
            cand = _greedy_schedule(instance, rule=rule, seed=seed + offset)
            if cand[0] < best[0]:
                best = cand

    return best


def _sequence_evaluator(machines, durations, n_machines):
    n_jobs = len(machines)
    op_to_id = {}
    id_to_op = []
    dur = []
    for j in range(n_jobs):
        for k in range(len(machines[j])):
            op_to_id[(j, k)] = len(id_to_op)
            id_to_op.append((j, k))
            dur.append(durations[j][k])
    n_ops = len(id_to_op)

    ops_for_machine_job = {}
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            ops_for_machine_job.setdefault((m, j), []).append(k)

    def evaluate(sequences, need_path=False):
        machine_ops = [[] for _ in range(n_machines)]
        used_count = {}
        try:
            for m in range(n_machines):
                for j in sequences[m]:
                    c = used_count.get((m, j), 0)
                    k = ops_for_machine_job[(m, j)][c]
                    used_count[(m, j)] = c + 1
                    machine_ops[m].append(op_to_id[(j, k)])
        except Exception:
            return None

        if sum(len(x) for x in machine_ops) != n_ops:
            return None

        succ = [[] for _ in range(n_ops)]
        indeg = [0] * n_ops

        for j in range(n_jobs):
            for k in range(1, len(machines[j])):
                u = op_to_id[(j, k - 1)]
                v = op_to_id[(j, k)]
                succ[u].append(v)
                indeg[v] += 1

        pos = {}
        op_machine = [0] * n_ops
        for m in range(n_machines):
            for p, oid in enumerate(machine_ops[m]):
                pos[oid] = p
                op_machine[oid] = m
                if p:
                    u = machine_ops[m][p - 1]
                    v = oid
                    succ[u].append(v)
                    indeg[v] += 1

        q = deque(i for i in range(n_ops) if indeg[i] == 0)
        start = [0] * n_ops
        pred = [-1] * n_ops
        seen = 0
        while q:
            u = q.popleft()
            seen += 1
            finish = start[u] + dur[u]
            for v in succ[u]:
                if finish > start[v]:
                    start[v] = finish
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != n_ops:
            return None

        makespan = 0
        last = -1
        for i in range(n_ops):
            e = start[i] + dur[i]
            if e > makespan:
                makespan = e
                last = i

        starts = {}
        ends = {}
        for oid, (j, k) in enumerate(id_to_op):
            starts[(j, k)] = start[oid]
            ends[(j, k)] = start[oid] + dur[oid]

        if not need_path:
            return makespan, starts, ends, None

        path = []
        x = last
        while x >= 0:
            path.append(x)
            x = pred[x]
        path.reverse()

        swaps = []
        for a, b in zip(path, path[1:]):
            ma = op_machine[a]
            if ma == op_machine[b] and pos.get(a, -99) + 1 == pos.get(b, -1):
                swaps.append((ma, pos[a]))

        return makespan, starts, ends, swaps

    return evaluate


def _local_search_sequences(instance, sequences, time_limit=7.0):
    machines, durations = _instance_arrays(instance)
    n_machines = int(instance.num_machines)
    evaluate = _sequence_evaluator(machines, durations, n_machines)

    best_seq = [list(s) for s in sequences]
    ev = evaluate(best_seq, need_path=True)
    if ev is None:
        return None
    best_ms, best_starts, best_ends, _ = ev
    current_seq = [list(s) for s in best_seq]
    current_ms = best_ms
    current_starts = best_starts
    current_ends = best_ends

    deadline = time.time() + float(time_limit)
    tabu = set()
    rng = random.Random(991)

    while time.time() < deadline:
        ev = evaluate(current_seq, need_path=True)
        if ev is None:
            break
        current_ms, current_starts, current_ends, swaps = ev
        if current_ms < best_ms:
            best_ms = current_ms
            best_seq = [list(s) for s in current_seq]
            best_starts = current_starts
            best_ends = current_ends
            tabu.clear()

        if not swaps:
            break

        rng.shuffle(swaps)
        improving = None
        improving_ev = None
        best_delta_ms = current_ms

        for m, p in swaps[:80]:
            if p < 0 or p + 1 >= len(current_seq[m]):
                continue
            key = (m, p, current_seq[m][p], current_seq[m][p + 1])
            if key in tabu:
                continue
            cand = [list(s) for s in current_seq]
            cand[m][p], cand[m][p + 1] = cand[m][p + 1], cand[m][p]
            cev = evaluate(cand, need_path=False)
            if cev is None:
                tabu.add(key)
                continue
            cms = cev[0]
            if cms < best_delta_ms:
                best_delta_ms = cms
                improving = cand
                improving_ev = cev
                if cms < current_ms:
                    break

        if improving is None:
            for m, p in swaps:
                tabu.add((m, p, current_seq[m][p], current_seq[m][p + 1]))
            if len(tabu) > 5000:
                tabu.clear()
            break

        current_seq = improving
        current_ms, current_starts, current_ends, _ = improving_ev

    return best_ms, best_seq, best_starts, best_ends


def solve(instance):
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _best_greedy_schedule(instance)
        improved = _local_search_sequences(instance, heuristic_sequences, time_limit=7.0)
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

    order_literals = []
    for machine_id, machine_ops in intervals_by_machine.items():
        if len(machine_ops) <= 1:
            continue

        def hint_key(item):
            j, k, _ = item
            return (int(hint_starts.get((j, k), job_prefix[j][k])), j, k)

        ordered_hint_ops = sorted(machine_ops, key=hint_key)
        for a_pos in range(len(ordered_hint_ops)):
            j1, k1, _ = ordered_hint_ops[a_pos]
            for b_pos in range(a_pos + 1, len(ordered_hint_ops)):
                j2, k2, _ = ordered_hint_ops[b_pos]
                lit = model.NewBoolVar(f"o_{machine_id}_{j1}_{k1}_before_{j2}_{k2}")
                model.Add(ends[(j1, k1)] <= starts[(j2, k2)]).OnlyEnforceIf(lit)
                model.Add(ends[(j2, k2)] <= starts[(j1, k1)]).OnlyEnforceIf(lit.Not())
                model.AddHint(lit, 1)
                order_literals.append(lit)

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

    if order_literals:
        model.AddDecisionStrategy(
            order_literals,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MAX_VALUE,
        )

    all_start_vars = [starts[key] for key in sorted(starts)]
    if all_start_vars:
        model.AddDecisionStrategy(
            all_start_vars,
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 284.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    solver.parameters.linearization_level = 1
    solver.parameters.randomize_search = True

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