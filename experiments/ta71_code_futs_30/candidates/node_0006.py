from job_shop_lib import Schedule
from ortools.sat.python import cp_model
import random
import time


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
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
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
                elif rule_id == 9:
                    key = (est + p + remaining_work[j][k + 1], p, j)
                else:
                    key = (est, -p, -remw, j)

                if best_key is None or key < best_key:
                    best_key = key
                    best_job = j

            j = best_job
            k = next_op[j]
            m, p = jobs[j][k]
            st = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
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
        candidate = run_rule(rule)
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best


def _active_dispatch_schedule(instance, time_limit=4.0):
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
        slack_proxy = est + p + rem_after

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
            key = (slack_proxy, p, j)
        elif rule == 9:
            key = (-(remw / max(1, p)), est, p, j)
        elif rule == 10:
            score = (
                0.020 * est
                + 0.030 * p
                - 0.018 * remw
                - 0.250 * rops
                - 0.004 * machine_total[m]
                + noise * rng.random()
            )
            key = (score, j)
        elif rule == 11:
            score = (
                0.030 * est
                - 0.035 * remw
                + 0.018 * p
                + 0.010 * slack_proxy
                - 0.006 * machine_total[m]
                + noise * rng.random()
            )
            key = (score, j)
        elif rule == 12:
            score = (
                0.045 * ect
                + 0.015 * rem_after
                - 0.020 * remw
                - 0.180 * rops
                + noise * rng.random()
            )
            key = (score, j)
        elif rule == 13:
            key = (est, slack_proxy, -remw, p, j)
        else:
            score = (
                rng.uniform(0.010, 0.050) * est
                + rng.uniform(-0.015, 0.040) * p
                - rng.uniform(0.010, 0.050) * remw
                - rng.uniform(0.020, 0.250) * rops
                - rng.uniform(0.000, 0.010) * machine_total[m]
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
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
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
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
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
            st = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
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
    for rule in range(14):
        cand = run(rule, 0.0)
        if best is None or cand[0] < best[0]:
            best = cand

    attempts = 0
    while time.monotonic() < deadline and attempts < 500:
        if attempts % 5 == 0:
            rule = 11
        elif attempts % 5 == 1:
            rule = 12
        elif attempts % 5 == 2:
            rule = 10
        else:
            rule = 14
        noise = 0.8 + 0.20 * (attempts % 23)
        cand = run(rule, noise)
        if cand[0] < best[0]:
            best = cand
        attempts += 1

    return best


def _build_greedy_schedule(instance):
    serial = _serial_dispatch_schedule(instance)
    active = _active_dispatch_schedule(instance)
    if serial is None:
        return active
    if active is None:
        return serial
    return active if active[0] < serial[0] else serial


def solve(instance):
    start_time = time.monotonic()
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

    start_vars_in_hint_order = sorted(
        starts.items(),
        key=lambda kv: (hint_starts.get(kv[0], 0), kv[0][1], kv[0][0]),
    )
    if start_vars_in_hint_order:
        model.AddDecisionStrategy(
            [var for _, var in start_vars_in_hint_order],
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )

    model.Minimize(makespan)

    solver = cp_model.CpSolver()
    elapsed = time.monotonic() - start_time
    solver.parameters.max_time_in_seconds = max(60.0, min(294.0, 297.0 - elapsed))
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 29
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.symmetry_level = 2

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