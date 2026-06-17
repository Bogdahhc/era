from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random


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
            elif rule == "lookahead":
                key = (est, -rem_after, ect, d, job_priority[j], j)
            elif rule == "bottleneck":
                key = (est, -rem, -d, job_priority[j], j)
            elif rule == "random":
                key = (est, rng.random(), j)
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

    machine_loads = [0] * n_machines
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            machine_loads[m] += durations[j][k]

    rng = random.Random(seed)
    random_tie = list(range(n_jobs))
    rng.shuffle(random_tie)
    random_tie = {j: p for p, j in enumerate(random_tie)}

    next_op = [0] * n_jobs
    job_ready = [0] * n_jobs
    machine_ready = [0] * n_machines
    starts = {}
    ends = {}
    seq = [[] for _ in range(n_machines)]
    done = 0

    while done < total_ops:
        available = []
        best_ect = None
        best_m = None
        for j in range(n_jobs):
            k = next_op[j]
            if k >= len(machines[j]):
                continue
            m = machines[j][k]
            d = durations[j][k]
            est = max(job_ready[j], machine_ready[m])
            ect = est + d
            item = (j, k, m, d, est, ect)
            available.append(item)
            if best_ect is None or ect < best_ect or (ect == best_ect and machine_loads[m] > machine_loads[best_m]):
                best_ect = ect
                best_m = m

        conflict = [x for x in available if x[2] == best_m and x[4] < best_ect]
        if not conflict:
            conflict = [x for x in available if x[2] == best_m]

        def key_fn(x):
            j, k, m, d, est, ect = x
            rem = suffix[j][k]
            rem_after = suffix[j][k + 1]
            if rule == "spt":
                return (d, est, -rem, random_tie[j], j)
            if rule == "lpt":
                return (-d, est, -rem, random_tie[j], j)
            if rule == "mwkr":
                return (-rem, est, d, random_tie[j], j)
            if rule == "mor":
                return (-(len(machines[j]) - k), -rem, est, d, random_tie[j], j)
            if rule == "ect":
                return (ect, est, -rem, d, random_tie[j], j)
            if rule == "lookahead":
                return (-rem_after, ect, est, d, random_tie[j], j)
            if rule == "bottleneck":
                return (-machine_loads[m], -rem, est, d, random_tie[j], j)
            if rule == "random":
                return (rng.random(), j)
            return (-rem, est, d, random_tie[j], j)

        j, k, m, d, st, ect = min(conflict, key=key_fn)
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
    best = None

    for rule in ["mwkr", "ect", "spt", "lpt", "mor", "lookahead", "bottleneck"]:
        cand = _greedy_schedule(instance, rule=rule, seed=0)
        if best is None or cand[0] < best[0]:
            best = cand

    for rule in ["mwkr", "mor", "spt", "lpt", "ect", "lookahead", "bottleneck"]:
        for seed in range(10):
            cand = _gt_schedule(instance, rule=rule, seed=1009 + seed)
            if cand[0] < best[0]:
                best = cand

    for seed in range(24):
        cand = _greedy_schedule(instance, rule="random", seed=seed + 17)
        if cand[0] < best[0]:
            best = cand
        cand = _greedy_schedule(instance, rule="mwkr", seed=seed + 101)
        if cand[0] < best[0]:
            best = cand
        cand = _gt_schedule(instance, rule="random", seed=seed + 211)
        if cand[0] < best[0]:
            best = cand

    return best


def _set_param_if_exists(parameters, name, value):
    try:
        if hasattr(parameters, name):
            setattr(parameters, name, value)
    except Exception:
        pass


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
    total_machine_pairs = sum(len(v) * (len(v) - 1) // 2 for v in intervals_by_machine.values())
    if total_machine_pairs <= 20000:
        for machine_id, machine_ops in intervals_by_machine.items():
            ops = list(machine_ops)
            ops.sort(key=lambda item: (int(hint_starts.get((item[0], item[1]), 0)), item[0], item[1]))
            for a in range(len(ops)):
                j1, k1, _ = ops[a]
                key1 = (j1, k1)
                for b in range(a + 1, len(ops)):
                    j2, k2, _ = ops[b]
                    key2 = (j2, k2)
                    lit = model.NewBoolVar(f"ord_{machine_id}_{j1}_{k1}_{j2}_{k2}")
                    model.Add(ends[key1] <= starts[key2]).OnlyEnforceIf(lit)
                    model.Add(ends[key2] <= starts[key1]).OnlyEnforceIf(lit.Not())
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
    solver.parameters.max_time_in_seconds = 292.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    _set_param_if_exists(solver.parameters, "use_precedences_in_disjunctive_constraint", True)
    _set_param_if_exists(solver.parameters, "use_dynamic_precedence_in_disjunctive", True)
    _set_param_if_exists(solver.parameters, "use_strong_propagation_in_disjunctive", True)
    _set_param_if_exists(solver.parameters, "use_timetable_edge_finding_in_cumulative", True)

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