from job_shop_lib import Schedule
from ortools.sat.python import cp_model


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


def _precompute(jobs, num_machines):
    num_jobs = len(jobs)
    remaining_work = []
    remaining_ops = []
    prefix_work = []
    tail_after = []
    machine_total = [0] * num_machines

    for job in jobs:
        n = len(job)
        rw = [0] * (n + 1)
        ro = [0] * (n + 1)
        pref = [0] * (n + 1)
        ta = [0] * n
        for i, (m, p) in enumerate(job):
            machine_total[m] += p
            pref[i + 1] = pref[i] + p
        for i in range(n - 1, -1, -1):
            rw[i] = rw[i + 1] + job[i][1]
            ro[i] = ro[i + 1] + 1
            ta[i] = rw[i + 1]
        remaining_work.append(rw)
        remaining_ops.append(ro)
        prefix_work.append(pref)
        tail_after.append(ta)

    max_job_load = max((sum(p for _, p in job) for job in jobs), default=0)
    lower_bound = max(max_job_load, max(machine_total) if machine_total else 0)
    return remaining_work, remaining_ops, prefix_work, tail_after, machine_total, lower_bound


def _build_greedy_schedule(instance):
    jobs, _ = _operation_data(instance)
    num_jobs = len(jobs)
    num_machines = int(instance.num_machines)
    remaining_work, remaining_ops, _, _, machine_total, _ = _precompute(jobs, num_machines)

    def run_serial_rule(rule_id):
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

    def priority_key(rule_id, j, k, est, ect):
        m, p = jobs[j][k]
        remw = remaining_work[j][k]
        remo = remaining_ops[j][k]
        mload = machine_total[m]
        if rule_id == 0:
            return (p, -remw, est, j)
        if rule_id == 1:
            return (-remw, p, est, j)
        if rule_id == 2:
            return (-remo, -remw, p, j)
        if rule_id == 3:
            return (est, p, -remw, j)
        if rule_id == 4:
            return (ect, -remw, p, j)
        if rule_id == 5:
            return (-mload, p, est, j)
        if rule_id == 6:
            return (-(remw / max(1, p)), est, p, j)
        if rule_id == 7:
            return (-p, -remw, est, j)
        if rule_id == 8:
            return (remaining_work[j][k + 1] if k + 1 < len(remaining_work[j]) else 0, p, j)
        return (j, p, est)

    def run_giffler_thompson(rule_id):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        starts = {}
        ends = {}
        sequences = [[] for _ in range(num_machines)]
        unscheduled = sum(len(job) for job in jobs)

        while unscheduled:
            min_ect = None
            selected_machine = None
            candidates_info = []
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(jobs[j]):
                    continue
                m, p = jobs[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                candidates_info.append((j, k, m, p, est, ect))
                if min_ect is None or ect < min_ect:
                    min_ect = ect
                    selected_machine = m

            conflict = [
                item for item in candidates_info
                if item[2] == selected_machine and item[4] < min_ect
            ]
            if not conflict:
                conflict = [item for item in candidates_info if item[2] == selected_machine]

            best_item = min(
                conflict,
                key=lambda item: priority_key(rule_id, item[0], item[1], item[4], item[5])
            )
            j, k, m, p, est, _ = best_item
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
        candidate = run_serial_rule(rule)
        if best is None or candidate[0] < best[0]:
            best = candidate
    for rule in range(10):
        candidate = run_giffler_thompson(rule)
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return 0, [[] for _ in range(num_machines)], {}, {}
    return best


def solve(instance):
    heuristic_makespan, fallback_job_sequences, hint_starts, hint_ends = _build_greedy_schedule(instance)

    jobs, total_duration = _operation_data(instance)
    num_machines = int(instance.num_machines)
    _, _, prefix_work, tail_after, machine_loads, lower_bound = _precompute(jobs, num_machines)

    model = cp_model.CpModel()
    horizon = int(total_duration)
    if heuristic_makespan and heuristic_makespan < horizon:
        horizon = int(heuristic_makespan)

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(num_machines)}
    all_ends = []

    for job_id, job in enumerate(jobs):
        for op_index, (machine_id, duration) in enumerate(job):
            key = (job_id, op_index)
            earliest_start = int(prefix_work[job_id][op_index])
            latest_start = int(horizon - duration - tail_after[job_id][op_index])
            if latest_start < earliest_start:
                latest_start = earliest_start
            earliest_end = earliest_start + duration
            latest_end = int(horizon - tail_after[job_id][op_index])
            if latest_end < earliest_end:
                latest_end = earliest_end

            start = model.NewIntVar(earliest_start, latest_start, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(earliest_end, latest_end, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_index}")
            starts[key] = start
            ends[key] = end
            all_ends.append(end)
            intervals_by_machine[machine_id].append((job_id, op_index, interval))

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
        if value is not None:
            lb = var.Proto().domain[0]
            ub = var.Proto().domain[-1]
            if lb <= value <= ub:
                model.AddHint(var, int(value))
    for key, var in ends.items():
        value = hint_ends.get(key)
        if value is not None:
            lb = var.Proto().domain[0]
            ub = var.Proto().domain[-1]
            if lb <= value <= ub:
                model.AddHint(var, int(value))
    if heuristic_makespan and lower_bound <= heuristic_makespan <= horizon:
        model.AddHint(makespan, int(heuristic_makespan))

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 285.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 17
    solver.parameters.log_search_progress = False
    solver.parameters.linearization_level = 0

    try:
        solver.parameters.use_optimization_hints = True
    except Exception:
        pass

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