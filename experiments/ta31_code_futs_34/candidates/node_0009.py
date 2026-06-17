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


def _gt_schedule(instance, rule="mwkr", seed=0):
    machines, durations = _instance_arrays(instance)
    n_jobs = len(machines)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(j) for j in machines)
    rng = random.Random(seed)

    suffix = []
    for j in range(n_jobs):
        s = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            s[k] = s[k + 1] + durations[j][k]
        suffix.append(s)

    job_priority = list(range(n_jobs))
    rng.shuffle(job_priority)
    job_priority = {j: p for p, j in enumerate(job_priority)}

    next_op = [0] * n_jobs
    job_ready = [0] * n_jobs
    machine_ready = [0] * n_machines
    starts = {}
    ends = {}
    seq = [[] for _ in range(n_machines)]
    done = 0

    while done < total_ops:
        candidates = []
        min_ect = None
        conflict_machine = None

        for j in range(n_jobs):
            k = next_op[j]
            if k >= len(machines[j]):
                continue
            m = machines[j][k]
            d = durations[j][k]
            est = max(job_ready[j], machine_ready[m])
            ect = est + d
            if min_ect is None or ect < min_ect or ((ect == min_ect and candidates) and est < candidates[0][3]):
                min_ect = ect
                conflict_machine = m
            candidates.append((j, k, m, est, ect, d))

        conflict = [x for x in candidates if x[2] == conflict_machine and x[3] < min_ect]
        if not conflict:
            conflict = [x for x in candidates if x[2] == conflict_machine]

        best_key = None
        best = None
        for j, k, m, est, ect, d in conflict:
            rem = suffix[j][k]
            rem_after = suffix[j][k + 1]
            if rule == "spt":
                key = (d, est, -rem, job_priority[j], j)
            elif rule == "lpt":
                key = (-d, est, -rem, job_priority[j], j)
            elif rule == "mwkr":
                key = (-rem, est, d, job_priority[j], j)
            elif rule == "mor":
                key = (-(len(machines[j]) - k), -rem, est, d, job_priority[j], j)
            elif rule == "ect":
                key = (ect, est, -rem, job_priority[j], j)
            elif rule == "lookahead":
                key = (-rem_after, ect, est, d, job_priority[j], j)
            elif rule == "random":
                key = (rng.random(), j)
            else:
                key = (job_priority[j], j)
            if best_key is None or key < best_key:
                best_key = key
                best = (j, k, m, est, d)

        j, k, m, est, d = best
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
        for builder in (_greedy_schedule, _gt_schedule):
            cand = builder(instance, rule=rule, seed=0)
            if best is None or cand[0] < best[0]:
                best = cand

    for seed in range(32):
        for rule in ("random", "mwkr", "mor", "lookahead"):
            cand = _gt_schedule(instance, rule=rule, seed=seed + 37)
            if cand[0] < best[0]:
                best = cand

        cand = _greedy_schedule(instance, rule="random", seed=seed + 17)
        if cand[0] < best[0]:
            best = cand
        cand = _greedy_schedule(instance, rule="mwkr", seed=seed + 101)
        if cand[0] < best[0]:
            best = cand

    return best


def _ops_by_machine_from_starts(machines, starts, n_machines):
    seq_ops = [[] for _ in range(n_machines)]
    for j, job_machines in enumerate(machines):
        for k, m in enumerate(job_machines):
            seq_ops[m].append((j, k))
    for m in range(n_machines):
        seq_ops[m].sort(key=lambda op: (starts.get(op, 0), op[0], op[1]))
    return seq_ops


def _evaluate_fixed_sequences(machines, durations, seq_ops):
    n_jobs = len(machines)
    n_machines = len(seq_ops)
    total_ops = sum(len(x) for x in machines)
    succ = {op: [] for j in range(n_jobs) for op in [(j, k) for k in range(len(machines[j]))]}
    indeg = {op: 0 for j in range(n_jobs) for op in [(j, k) for k in range(len(machines[j]))]}

    def add_arc(a, b):
        succ[a].append(b)
        indeg[b] += 1

    for j in range(n_jobs):
        for k in range(len(machines[j]) - 1):
            add_arc((j, k), (j, k + 1))

    seen = set()
    for m in range(n_machines):
        prev = None
        for op in seq_ops[m]:
            if op in seen:
                return None
            seen.add(op)
            if prev is not None:
                add_arc(prev, op)
            prev = op

    if len(seen) != total_ops:
        return None

    q = deque([op for op, deg in indeg.items() if deg == 0])
    starts = {op: 0 for op in indeg}
    order_count = 0

    while q:
        op = q.popleft()
        order_count += 1
        j, k = op
        finish = starts[op] + durations[j][k]
        for nb in succ[op]:
            if starts[nb] < finish:
                starts[nb] = finish
            indeg[nb] -= 1
            if indeg[nb] == 0:
                q.append(nb)

    if order_count != total_ops:
        return None

    ends = {}
    makespan = 0
    for op, st in starts.items():
        j, k = op
        en = st + durations[j][k]
        ends[op] = en
        if en > makespan:
            makespan = en
    return makespan, starts, ends


def _local_search_sequences(instance, base_makespan, base_starts, max_seconds=7.5, seed=9127):
    machines, durations = _instance_arrays(instance)
    n_machines = int(instance.num_machines)
    total_ops = sum(len(x) for x in machines)
    if total_ops == 0:
        return base_makespan, [[] for _ in range(n_machines)], {}, {}
    if total_ops > 900:
        return base_makespan, _ops_by_machine_from_starts(machines, base_starts, n_machines), base_starts, {
            op: base_starts[op] + durations[op[0]][op[1]] for op in base_starts
        }

    deadline = time.time() + max_seconds
    rng = random.Random(seed)
    best_seq = _ops_by_machine_from_starts(machines, base_starts, n_machines)
    ev = _evaluate_fixed_sequences(machines, durations, best_seq)
    if ev is None:
        return base_makespan, best_seq, base_starts, {op: base_starts[op] + durations[op[0]][op[1]] for op in base_starts}
    best_ms, best_starts, best_ends = ev
    if base_makespan and base_makespan < best_ms:
        best_ms = base_makespan

    no_improve_passes = 0
    while time.time() < deadline and no_improve_passes < 3:
        moves = []
        for m, seq in enumerate(best_seq):
            for i in range(len(seq) - 1):
                moves.append((m, i))
        rng.shuffle(moves)
        improved = False
        for m, i in moves:
            if time.time() >= deadline:
                break
            a = best_seq[m][i]
            b = best_seq[m][i + 1]
            if a[0] == b[0]:
                continue
            cand_seq = [list(s) for s in best_seq]
            cand_seq[m][i], cand_seq[m][i + 1] = cand_seq[m][i + 1], cand_seq[m][i]
            ev = _evaluate_fixed_sequences(machines, durations, cand_seq)
            if ev is None:
                continue
            ms, st, en = ev
            if ms < best_ms:
                best_ms = ms
                best_seq = cand_seq
                best_starts = st
                best_ends = en
                improved = True
                break
        if improved:
            no_improve_passes = 0
        else:
            no_improve_passes += 1

    return best_ms, best_seq, best_starts, best_ends


def solve(instance):
    start_wall = time.time()
    fallback_job_sequences = _fallback_sequences(instance)
    try:
        heuristic_makespan, heuristic_sequences, hint_starts, hint_ends = _best_greedy_schedule(instance)
        ls_ms, ls_seq_ops, ls_starts, ls_ends = _local_search_sequences(
            instance, heuristic_makespan, hint_starts, max_seconds=7.0
        )
        if ls_ms < heuristic_makespan:
            heuristic_makespan = ls_ms
            hint_starts = ls_starts
            hint_ends = ls_ends
            heuristic_sequences = [[op[0] for op in machine_seq] for machine_seq in ls_seq_ops]
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
            machine_intervals = [interval for _, _, interval in machine_ops]
            model.AddNoOverlap(machine_intervals)
            model.AddCumulative(machine_intervals, [1] * len(machine_intervals), 1)

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))

    job_load_lb = max((sum(durations[j]) for j in range(n_jobs)), default=0)
    machine_loads = [0] * n_machines
    for j in range(n_jobs):
        for k, m in enumerate(machines[j]):
            machine_loads[m] += durations[j][k]
    lower_bound = max(job_load_lb, max(machine_loads) if machine_loads else 0)
    model.Add(makespan >= lower_bound)
    if heuristic_makespan < total_duration:
        model.Add(makespan <= int(heuristic_makespan))

    for key, var in starts.items():
        if key in hint_starts:
            val = int(hint_starts[key])
            if val >= 0:
                model.AddHint(var, val)
    for key, var in ends.items():
        if key in hint_ends:
            val = int(hint_ends[key])
            if val >= 0:
                model.AddHint(var, val)
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
    elapsed = time.time() - start_wall
    solver.parameters.max_time_in_seconds = max(20.0, min(286.0, 296.0 - elapsed))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 17
    solver.parameters.use_optimization_hints = True
    solver.parameters.cp_model_presolve = True
    solver.parameters.log_search_progress = False
    solver.parameters.linearization_level = 2
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