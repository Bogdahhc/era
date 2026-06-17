from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time
from collections import deque


def _operation_data(instance):
    jobs = []
    total_duration = 0
    for job in instance.jobs:
        ops = []
        for op in job:
            machine = int(op.machine_id)
            duration = int(op.duration)
            ops.append((machine, duration))
            total_duration += duration
        jobs.append(ops)
    return jobs, total_duration


def _serial_dispatch_schedule(instance):
    jobs, _ = _operation_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)

    remaining_work = []
    remaining_ops = []
    for job in jobs:
        rw = [0] * (len(job) + 1)
        ro = [0] * (len(job) + 1)
        for i in range(len(job) - 1, -1, -1):
            rw[i] = rw[i + 1] + job[i][1]
            ro[i] = ro[i + 1] + 1
        remaining_work.append(rw)
        remaining_ops.append(ro)

    machine_total = [0] * num_machines
    for job in jobs:
        for machine, duration in job:
            machine_total[machine] += duration

    def run_rule(rule_id):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        starts = {}
        ends = {}
        sequences = [[] for _ in range(num_machines)]
        unscheduled = sum(len(job) for job in jobs)

        while unscheduled:
            best_key = None
            best_job = None
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = max(job_ready[j], machine_ready[m])
                remw = remaining_work[j][k]
                remo = remaining_ops[j][k]
                mload = machine_total[m]

                if rule_id == 0:
                    key = (est, p, -remw, j)
                elif rule_id == 1:
                    key = (est, -remw, p, j)
                elif rule_id == 2:
                    key = (est, -remo, -remw, p, j)
                elif rule_id == 3:
                    key = (est + p, -remw, p, j)
                elif rule_id == 4:
                    key = (-remw, est, p, j)
                elif rule_id == 5:
                    key = (-mload, est, p, j)
                elif rule_id == 6:
                    key = (job_ready[j], est, p, -remw, j)
                elif rule_id == 7:
                    key = (machine_ready[m], est, -remw, p, j)
                elif rule_id == 8:
                    key = (est, -(remw / max(1, p)), p, j)
                else:
                    key = (est, -p, -remw, j)

                if best_key is None or key < best_key:
                    best_key = key
                    best_job = j

            j = best_job
            k = next_op[j]
            m, p = jobs[j][k]
            st = max(job_ready[j], machine_ready[m])
            en = st + p
            starts[(j, k)] = st
            ends[(j, k)] = en
            job_ready[j] = en
            machine_ready[m] = en
            next_op[j] += 1
            sequences[m].append(j)
            unscheduled -= 1

        return max(job_ready) if job_ready else 0, sequences, starts, ends

    best = None
    for rule in range(10):
        candidate = run_rule(rule)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def _active_dispatch_schedule(instance, time_limit=2.0):
    jobs, _ = _operation_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)
    deadline = time.monotonic() + max(0.05, float(time_limit))

    remaining_work = []
    remaining_ops = []
    for job in jobs:
        rw = [0] * (len(job) + 1)
        ro = [0] * (len(job) + 1)
        for i in range(len(job) - 1, -1, -1):
            rw[i] = rw[i + 1] + job[i][1]
            ro[i] = ro[i + 1] + 1
        remaining_work.append(rw)
        remaining_ops.append(ro)

    machine_total = [0] * num_machines
    for job in jobs:
        for m, p in job:
            machine_total[m] += p

    rng = random.Random(9173)

    def priority_key(j, k, est, ect, rule, noise):
        m, p = jobs[j][k]
        remw = remaining_work[j][k]
        rem_after = remaining_work[j][k + 1]
        rops = remaining_ops[j][k]
        if rule == 0:
            key = (p, -remw, est, j)
        elif rule == 1:
            key = (-p, -remw, est, j)
        elif rule == 2:
            key = (-remw, p, est, j)
        elif rule == 3:
            key = (remw, p, est, j)
        elif rule == 4:
            key = (-rops, -remw, p, j)
        elif rule == 5:
            key = (ect + rem_after, -remw, p, j)
        elif rule == 6:
            key = (-machine_total[m], est, p, j)
        elif rule == 7:
            key = (est, p, -remw, j)
        elif rule == 8:
            key = (est + p + rem_after, p, j)
        elif rule == 9:
            key = (-(remw / max(1, p)), est, p, j)
        else:
            score = (
                0.020 * est
                + 0.030 * p
                - 0.018 * remw
                - 0.25 * rops
                - 0.004 * machine_total[m]
                + noise * rng.random()
            )
            key = (score, j)
        return key

    def run(rule, noise=0.0):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        starts = {}
        ends = {}
        sequences = [[] for _ in range(num_machines)]
        unscheduled = sum(len(job) for job in jobs)

        while unscheduled:
            best_ect = None
            critical_machine = None
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                if best_ect is None or ect < best_ect:
                    best_ect = ect
                    critical_machine = m

            chosen = None
            chosen_key = None
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                if m != critical_machine:
                    continue
                est = max(job_ready[j], machine_ready[m])
                if est >= best_ect:
                    continue
                ect = est + p
                key = priority_key(j, k, est, ect, rule, noise)
                if chosen_key is None or key < chosen_key:
                    chosen_key = key
                    chosen = j

            if chosen is None:
                for j in range(num_jobs):
                    k = next_op[j]
                    if k < len(jobs[j]):
                        chosen = j
                        break

            j = chosen
            k = next_op[j]
            m, p = jobs[j][k]
            st = max(job_ready[j], machine_ready[m])
            en = st + p
            starts[(j, k)] = st
            ends[(j, k)] = en
            job_ready[j] = en
            machine_ready[m] = en
            next_op[j] += 1
            sequences[m].append(j)
            unscheduled -= 1

        return max(job_ready) if job_ready else 0, sequences, starts, ends

    best = None
    for rule in range(11):
        cand = run(rule, 0.0)
        if best is None or cand[0] < best[0]:
            best = cand

    attempts = 0
    while time.monotonic() < deadline and attempts < 180:
        rule = 10
        noise = 1.2 + 0.22 * (attempts % 19)
        cand = run(rule, noise)
        if cand[0] < best[0]:
            best = cand
        attempts += 1

    return best


def _op_sequences_from_starts(jobs, num_machines, starts, ends):
    seq = [[] for _ in range(num_machines)]
    for j, job in enumerate(jobs):
        for k, (m, _) in enumerate(job):
            seq[m].append((j, k))
    for m in range(num_machines):
        seq[m].sort(key=lambda op: (starts.get(op, 0), ends.get(op, starts.get(op, 0)), op[0], op[1]))
    return seq


def _evaluate_op_sequences(jobs, op_sequences):
    num_jobs = len(jobs)
    ops = [(j, k) for j, job in enumerate(jobs) for k in range(len(job))]
    succ = {op: [] for op in ops}
    indeg = {op: 0 for op in ops}

    for j, job in enumerate(jobs):
        for k in range(1, len(job)):
            a = (j, k - 1)
            b = (j, k)
            succ[a].append(b)
            indeg[b] += 1

    machine_prev = {}
    machine_next = {}
    for seq in op_sequences:
        for i in range(1, len(seq)):
            a = seq[i - 1]
            b = seq[i]
            succ[a].append(b)
            indeg[b] += 1
            machine_prev[b] = a
            machine_next[a] = b

    starts = {op: 0 for op in ops}
    q = deque([op for op in ops if indeg[op] == 0])
    processed = 0
    topo = []
    while q:
        op = q.popleft()
        topo.append(op)
        processed += 1
        j, k = op
        en = starts[op] + jobs[j][k][1]
        for nb in succ[op]:
            if starts[nb] < en:
                starts[nb] = en
            indeg[nb] -= 1
            if indeg[nb] == 0:
                q.append(nb)

    if processed != len(ops):
        return None

    ends = {}
    makespan = 0
    for op in topo:
        j, k = op
        en = starts[op] + jobs[j][k][1]
        ends[op] = en
        if en > makespan:
            makespan = en

    return makespan, starts, ends, machine_prev, machine_next


def _critical_path(jobs, starts, ends, machine_prev):
    if not ends:
        return []
    cur = max(ends, key=lambda op: (ends[op], op[0], op[1]))
    path = [cur]
    while True:
        j, k = cur
        st = starts[cur]
        preds = []
        if k > 0:
            jp = (j, k - 1)
            if ends.get(jp) == st:
                preds.append(jp)
        mp = machine_prev.get(cur)
        if mp is not None and ends.get(mp) == st:
            preds.append(mp)
        if not preds:
            break
        mp = machine_prev.get(cur)
        if mp in preds:
            cur = mp
        else:
            cur = preds[0]
        path.append(cur)
    path.reverse()
    return path


def _critical_swap_improvement(instance, base_makespan, base_starts, base_ends, time_limit=4.5):
    jobs, _ = _operation_data(instance)
    num_machines = int(instance.num_machines)
    deadline = time.monotonic() + max(0.0, float(time_limit))

    current_seq = _op_sequences_from_starts(jobs, num_machines, base_starts, base_ends)
    ev = _evaluate_op_sequences(jobs, current_seq)
    if ev is None:
        return base_makespan, [[op[0] for op in s] for s in current_seq], base_starts, base_ends

    current_mk, current_starts, current_ends, machine_prev, _ = ev
    best_seq = [list(s) for s in current_seq]
    best_mk = current_mk
    best_starts = current_starts
    best_ends = current_ends

    rng = random.Random(40729)
    idle_rounds = 0

    while time.monotonic() < deadline:
        pos = {}
        op_machine = {}
        for m, seq in enumerate(current_seq):
            for i, op in enumerate(seq):
                pos[op] = i
                op_machine[op] = m

        path = _critical_path(jobs, current_starts, current_ends, machine_prev)
        candidates = []
        seen = set()
        for a, b in zip(path, path[1:]):
            ma = op_machine.get(a)
            if ma is not None and ma == op_machine.get(b) and abs(pos[a] - pos[b]) == 1:
                i = min(pos[a], pos[b])
                key = (ma, i)
                if key not in seen:
                    seen.add(key)
                    candidates.append(key)

        if idle_rounds > 0:
            critical_machines = list({op_machine[op] for op in path if op in op_machine})
            rng.shuffle(critical_machines)
            for m in critical_machines[:4]:
                if len(current_seq[m]) > 1:
                    i = rng.randrange(len(current_seq[m]) - 1)
                    key = (m, i)
                    if key not in seen:
                        seen.add(key)
                        candidates.append(key)

        if not candidates:
            break

        improved = False
        rng.shuffle(candidates)
        for m, i in candidates:
            if time.monotonic() >= deadline:
                break
            trial_seq = [list(s) for s in current_seq]
            trial_seq[m][i], trial_seq[m][i + 1] = trial_seq[m][i + 1], trial_seq[m][i]
            ev2 = _evaluate_op_sequences(jobs, trial_seq)
            if ev2 is None:
                continue
            mk2, st2, en2, mp2, _ = ev2
            if mk2 < current_mk:
                current_seq = trial_seq
                current_mk = mk2
                current_starts = st2
                current_ends = en2
                machine_prev = mp2
                idle_rounds = 0
                improved = True
                if mk2 < best_mk:
                    best_mk = mk2
                    best_seq = [list(s) for s in trial_seq]
                    best_starts = st2
                    best_ends = en2
                break

        if not improved:
            idle_rounds += 1
            if idle_rounds >= 3:
                break

    return best_mk, [[op[0] for op in s] for s in best_seq], best_starts, best_ends


def _build_greedy_schedule(instance):
    serial = _serial_dispatch_schedule(instance)
    active = _active_dispatch_schedule(instance)
    if serial is None:
        best = active
    elif active is None:
        best = serial
    else:
        best = active if active[0] < serial[0] else serial

    improved = _critical_swap_improvement(instance, best[0], best[2], best[3])
    if improved[0] < best[0]:
        return improved
    return best


def solve(instance):
    heuristic_makespan, fallback_job_sequences, hint_starts, hint_ends = _build_greedy_schedule(instance)

    model = cp_model.CpModel()
    jobs, total_duration = _operation_data(instance)
    num_machines = int(instance.num_machines)
    horizon = int(total_duration)
    if heuristic_makespan and heuristic_makespan < horizon:
        horizon = int(heuristic_makespan)

    machine_loads = [0] * num_machines
    max_job_load = 0
    job_prefix = []
    job_suffix = []
    for job in jobs:
        pref = [0] * len(job)
        acc = 0
        for i, (_, p) in enumerate(job):
            pref[i] = acc
            acc += p
        max_job_load = max(max_job_load, acc)
        suff = [0] * len(job)
        acc2 = 0
        for i in range(len(job) - 1, -1, -1):
            acc2 += job[i][1]
            suff[i] = acc2
        job_prefix.append(pref)
        job_suffix.append(suff)
        for m, p in job:
            machine_loads[m] += p

    lower_bound = max(max_job_load, max(machine_loads) if machine_loads else 0)

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(num_machines)}
    all_ends = []

    for job_id, job in enumerate(jobs):
        for op_index, (machine_id, duration) in enumerate(job):
            key = (job_id, op_index)
            start_lb = int(job_prefix[job_id][op_index])
            start_ub = int(max(start_lb, horizon - job_suffix[job_id][op_index]))
            end_lb = int(start_lb + duration)
            end_ub = int(horizon - (job_suffix[job_id][op_index] - duration))
            end_ub = max(end_lb, end_ub)
            start = model.NewIntVar(start_lb, start_ub, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(end_lb, end_ub, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, int(duration), end, f"i_{job_id}_{op_index}")
            starts[key] = start
            ends[key] = end
            all_ends.append(end)
            intervals_by_machine[int(machine_id)].append((job_id, op_index, interval))

    for job_id, job in enumerate(jobs):
        for op_index in range(1, len(job)):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    for machine_ops in intervals_by_machine.values():
        if machine_ops:
            model.AddNoOverlap([interval for _, _, interval in machine_ops])

    makespan = model.NewIntVar(int(lower_bound), int(horizon), "makespan")
    model.AddMaxEquality(makespan, all_ends)
    if heuristic_makespan:
        model.Add(makespan <= int(heuristic_makespan))

    for key, var in starts.items():
        value = hint_starts.get(key)
        if value is not None and 0 <= value <= horizon:
            model.AddHint(var, int(value))
    for key, var in ends.items():
        value = hint_ends.get(key)
        if value is not None and 0 <= value <= horizon:
            model.AddHint(var, int(value))
    if heuristic_makespan and lower_bound <= heuristic_makespan <= horizon:
        model.AddHint(makespan, int(heuristic_makespan))

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 286.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 23
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.symmetry_level = 2
    solver.parameters.linearization_level = 2
    solver.parameters.randomize_search = True

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, fallback_job_sequences)

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