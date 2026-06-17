from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time


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


def _suffix_durations(durations):
    suffix = []
    for j in range(len(durations)):
        s = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            s[k] = s[k + 1] + durations[j][k]
        suffix.append(s)
    return suffix


def _greedy_schedule(instance, rule="mwkr", seed=0):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(j) for j in machines)
    suffix = _suffix_durations(durations)

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


def _gt_schedule(instance, rule="mwkr", seed=0):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(j) for j in machines)
    suffix = _suffix_durations(durations)

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
        eligible = []
        best_ect = None
        best_machine = None
        best_est_for_tie = None

        for j in range(n_jobs):
            k = next_op[j]
            if k >= len(machines[j]):
                continue
            m = machines[j][k]
            d = durations[j][k]
            est = max(job_ready[j], machine_ready[m])
            ect = est + d
            eligible.append((j, k, m, d, est, ect))
            if best_ect is None or ect < best_ect or (ect == best_ect and est < best_est_for_tie):
                best_ect = ect
                best_machine = m
                best_est_for_tie = est

        conflict = [x for x in eligible if x[2] == best_machine and x[4] < best_ect]
        if not conflict:
            conflict = [min(eligible, key=lambda x: (x[5], x[4], x[0]))]

        best_key = None
        chosen = None
        for j, k, m, d, est, ect in conflict:
            rem = suffix[j][k]
            rem_after = suffix[j][k + 1]
            wait = max(machine_ready[m] - job_ready[j], 0)

            if rule == "spt":
                key = (d, est, -rem, job_priority[j], j)
            elif rule == "lpt":
                key = (-d, est, -rem, job_priority[j], j)
            elif rule == "ect":
                key = (ect, est, -rem, job_priority[j], j)
            elif rule == "mwkr":
                key = (-rem, est, d, job_priority[j], j)
            elif rule == "mor":
                key = (-(len(machines[j]) - k), -rem, est, d, job_priority[j], j)
            elif rule == "lookahead":
                key = (-rem_after, ect, est, d, job_priority[j], j)
            elif rule == "critical":
                key = (-(rem + wait), ect, -d, job_priority[j], j)
            elif rule == "random":
                key = (rng.random(), est, j)
            else:
                key = (job_priority[j], est, j)

            if best_key is None or key < best_key:
                best_key = key
                chosen = (j, k, m, d)

        j, k, m, d = chosen
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
    gt_rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "critical"]
    best = None

    for rule in rules:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for rule in gt_rules:
        cand = _gt_schedule(instance, rule=rule, seed=0)
        if cand[0] < best[0]:
            best = cand

    for seed in range(64):
        for rule in ("random", "mwkr", "critical"):
            cand = _greedy_schedule(instance, rule=rule, seed=seed * 17 + 19)
            if cand[0] < best[0]:
                best = cand

        for rule in ("random", "mwkr", "critical", "lookahead", "mor"):
            cand = _gt_schedule(instance, rule=rule, seed=seed * 31 + 7)
            if cand[0] < best[0]:
                best = cand

    return best


def _decode_job_sequences(instance, job_sequences):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    op_id = {}
    id_op = []
    dur = []
    for j in range(n_jobs):
        for k in range(len(machines[j])):
            op_id[(j, k)] = len(id_op)
            id_op.append((j, k))
            dur.append(durations[j][k])
    n_ops = len(id_op)

    by_job_machine = {}
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            by_job_machine.setdefault((j, m), []).append(k)

    machine_orders = [[] for _ in range(n_machines)]
    counters = {}
    for m in range(n_machines):
        for j in job_sequences[m]:
            key = (int(j), m)
            c = counters.get(key, 0)
            ops = by_job_machine.get(key)
            if ops is None or c >= len(ops):
                return None
            k = ops[c]
            counters[key] = c + 1
            machine_orders[m].append((int(j), k))

    if sum(len(x) for x in machine_orders) != n_ops:
        return None

    succ = [[] for _ in range(n_ops)]
    indeg = [0] * n_ops

    def add_arc(a, b):
        ia = op_id[a]
        ib = op_id[b]
        succ[ia].append(ib)
        indeg[ib] += 1

    for j in range(n_jobs):
        for k in range(len(machines[j]) - 1):
            add_arc((j, k), (j, k + 1))

    for m in range(n_machines):
        order = machine_orders[m]
        for p in range(len(order) - 1):
            add_arc(order[p], order[p + 1])

    ready = [i for i in range(n_ops) if indeg[i] == 0]
    head = 0
    starts = [0] * n_ops
    topo_count = 0
    while head < len(ready):
        u = ready[head]
        head += 1
        topo_count += 1
        end_u = starts[u] + dur[u]
        for v in succ[u]:
            if starts[v] < end_u:
                starts[v] = end_u
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)

    if topo_count != n_ops:
        return None

    start_map = {}
    end_map = {}
    makespan = 0
    for i, (j, k) in enumerate(id_op):
        start_map[(j, k)] = starts[i]
        end_map[(j, k)] = starts[i] + dur[i]
        if end_map[(j, k)] > makespan:
            makespan = end_map[(j, k)]

    return makespan, [list(x) for x in job_sequences], start_map, end_map


def _improve_sequences_by_adjacent_swaps(instance, initial, time_limit=3.5):
    decoded = _decode_job_sequences(instance, initial[1])
    if decoded is None:
        return initial
    best_ms, best_seq, best_starts, best_ends = decoded
    deadline = time.time() + time_limit
    rng = random.Random(9127)
    no_improve_rounds = 0

    while time.time() < deadline and no_improve_rounds < 4:
        improved = False
        moves = []
        for m, seq in enumerate(best_seq):
            for p in range(len(seq) - 1):
                moves.append((m, p))
        rng.shuffle(moves)

        for m, p in moves:
            if time.time() >= deadline:
                break
            cand_seq = [list(x) for x in best_seq]
            cand_seq[m][p], cand_seq[m][p + 1] = cand_seq[m][p + 1], cand_seq[m][p]
            decoded = _decode_job_sequences(instance, cand_seq)
            if decoded is not None and decoded[0] < best_ms:
                best_ms, best_seq, best_starts, best_ends = decoded
                improved = True
                break

        if improved:
            no_improve_rounds = 0
        else:
            no_improve_rounds += 1

    if best_ms < initial[0]:
        return best_ms, best_seq, best_starts, best_ends
    return initial


def solve(instance):
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        greedy = _best_greedy_schedule(instance)
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _improve_sequences_by_adjacent_swaps(
            instance, greedy, time_limit=3.0
        )
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
    order_lit_map = {}

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
                order_lit_map[(machine_id, j1, k1, j2, k2)] = lit

        for a_pos in range(len(ordered_hint_ops) - 2):
            j1, k1, _ = ordered_hint_ops[a_pos]
            j2, k2, _ = ordered_hint_ops[a_pos + 1]
            j3, k3, _ = ordered_hint_ops[a_pos + 2]
            lit12 = order_lit_map.get((machine_id, j1, k1, j2, k2))
            lit23 = order_lit_map.get((machine_id, j2, k2, j3, k3))
            lit13 = order_lit_map.get((machine_id, j1, k1, j3, k3))
            if lit12 is not None and lit23 is not None and lit13 is not None:
                model.AddBoolOr([lit12.Not(), lit23.Not(), lit13])

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
    solver.parameters.max_time_in_seconds = 270.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    solver.parameters.linearization_level = 1

    try:
        solver.parameters.repair_hint = True
        solver.parameters.hint_conflict_limit = 400
    except Exception:
        pass

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