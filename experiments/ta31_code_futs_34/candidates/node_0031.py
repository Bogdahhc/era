from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
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


def _suffix_durations(durations):
    suffix = []
    for j in range(len(durations)):
        s = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            s[k] = s[k + 1] + durations[j][k]
        suffix.append(s)
    return suffix


def _decode_sequences(instance, sequences):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(job) for job in machines)
    if total_ops == 0:
        return 0, {}, {}

    machine_op_lists = [[] for _ in range(n_machines)]
    next_scan = [0] * n_jobs
    used = set()

    for m in range(n_machines):
        for j in sequences[m]:
            j = int(j)
            k = next_scan[j]
            while k < len(machines[j]) and (machines[j][k] != m or (j, k) in used):
                k += 1
            if k >= len(machines[j]):
                return int(instance.total_duration), {}, {}
            machine_op_lists[m].append((j, k))
            used.add((j, k))
            next_scan[j] = k + 1

    if len(used) != total_ops:
        return int(instance.total_duration), {}, {}

    succ = {op: [] for op in used}
    indeg = {op: 0 for op in used}

    for j in range(n_jobs):
        for k in range(1, len(machines[j])):
            a = (j, k - 1)
            b = (j, k)
            succ[a].append(b)
            indeg[b] += 1

    for ops in machine_op_lists:
        for p in range(1, len(ops)):
            a = ops[p - 1]
            b = ops[p]
            succ[a].append(b)
            indeg[b] += 1

    q = deque([op for op in used if indeg[op] == 0])
    starts = {op: 0 for op in used}
    seen = 0
    while q:
        op = q.popleft()
        seen += 1
        j, k = op
        finish = starts[op] + durations[j][k]
        for v in succ[op]:
            if starts[v] < finish:
                starts[v] = finish
            indeg[v] -= 1
            if indeg[v] == 0:
                q.append(v)

    if seen != total_ops:
        return int(instance.total_duration), {}, {}

    ends = {(j, k): starts[(j, k)] + durations[j][k] for j, k in used}
    return max(ends.values()) if ends else 0, starts, ends


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


def _backward_schedule(instance, rule="mwkr", seed=0):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(j) for j in machines)
    suffix = _suffix_durations(durations)
    total_duration = int(instance.total_duration)

    rng = random.Random(seed)
    prev_op = [len(machines[j]) - 1 for j in range(n_jobs)]
    job_tail = [total_duration] * n_jobs
    machine_tail = [total_duration] * n_machines
    latest_starts = {}
    seq_ops = [[] for _ in range(n_machines)]
    done = 0

    job_priority = list(range(n_jobs))
    rng.shuffle(job_priority)
    job_priority = {j: p for p, j in enumerate(job_priority)}

    while done < total_ops:
        best_key = None
        best = None
        for j in range(n_jobs):
            k = prev_op[j]
            if k < 0:
                continue
            m = machines[j][k]
            d = durations[j][k]
            lft = min(job_tail[j], machine_tail[m])
            lst = lft - d
            rem_before = suffix[j][0] - suffix[j][k]
            rem_from = suffix[j][k]
            if rule == "spt":
                key = (-lft, d, -rem_before, job_priority[j], j)
            elif rule == "lpt":
                key = (-lft, -d, -rem_before, job_priority[j], j)
            elif rule == "mwkr":
                key = (-lft, -rem_from, d, job_priority[j], j)
            elif rule == "mor":
                key = (-lft, -k, -rem_before, d, job_priority[j], j)
            elif rule == "critical":
                key = (-lft, -(rem_before + d), -d, job_priority[j], j)
            elif rule == "random":
                key = (-lft, rng.random(), j)
            else:
                key = (-lft, job_priority[j], j)
            if best_key is None or key < best_key:
                best_key = key
                best = (j, k, m, d, lst)

        j, k, m, d, lst = best
        latest_starts[(j, k)] = lst
        seq_ops[m].append((j, k))
        job_tail[j] = lst
        machine_tail[m] = lst
        prev_op[j] -= 1
        done += 1

    sequences = [[] for _ in range(n_machines)]
    for m in range(n_machines):
        ops = sorted(seq_ops[m], key=lambda op: (latest_starts[op], op[0], op[1]))
        sequences[m] = [j for j, _ in ops]

    makespan, starts, ends = _decode_sequences(instance, sequences)
    return makespan, sequences, starts, ends


def _best_greedy_schedule(instance):
    rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "critical", "dense"]
    gt_rules = ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "critical"]
    back_rules = ["mwkr", "spt", "lpt", "mor", "critical", "random"]
    best = None

    for rule in rules:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for rule in gt_rules:
        cand = _gt_schedule(instance, rule=rule, seed=0)
        if cand[0] < best[0]:
            best = cand

    for rule in back_rules:
        cand = _backward_schedule(instance, rule=rule, seed=0)
        if cand[0] < best[0]:
            best = cand

    for seed in range(56):
        for rule in ("random", "mwkr", "critical"):
            cand = _greedy_schedule(instance, rule=rule, seed=seed * 17 + 19)
            if cand[0] < best[0]:
                best = cand

        for rule in ("random", "mwkr", "critical", "lookahead", "mor"):
            cand = _gt_schedule(instance, rule=rule, seed=seed * 31 + 7)
            if cand[0] < best[0]:
                best = cand

        if seed < 28:
            for rule in ("random", "mwkr", "critical"):
                cand = _backward_schedule(instance, rule=rule, seed=seed * 43 + 11)
                if cand[0] < best[0]:
                    best = cand

    return best


def solve(instance):
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _best_greedy_schedule(instance)
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
    lower_bound = max(job_load_lb, max(machine_loads) if machine_loads else 0)
    model.Add(makespan >= lower_bound)

    for j in range(n_jobs):
        if durations[j]:
            model.Add(starts[(j, len(durations[j]) - 1)] + durations[j][-1] >= sum(durations[j]))

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
    solver.parameters.max_time_in_seconds = 282.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    solver.parameters.linearization_level = 1

    try:
        solver.parameters.repair_hint = True
        solver.parameters.hint_conflict_limit = 300
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