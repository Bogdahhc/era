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


def _build_greedy_schedule(instance):
    jobs, total_duration = _operation_data(instance)
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
    for rule in range(10):
        candidate = run_rule(rule)
        if best is None or candidate[0] < best[0]:
            best = candidate

    if best is None:
        return 0, [[] for _ in range(num_machines)], {}, {}
    return best


def solve(instance):
    heuristic_makespan, fallback_job_sequences, hint_starts, hint_ends = _build_greedy_schedule(instance)

    model = cp_model.CpModel()
    total_duration = int(instance.total_duration)
    horizon = total_duration
    if heuristic_makespan and heuristic_makespan < horizon:
        horizon = int(heuristic_makespan)

    starts = {}
    ends = {}
    intervals_by_machine = {m: [] for m in range(instance.num_machines)}
    all_ends = []

    machine_loads = [0] * int(instance.num_machines)
    max_job_load = 0
    for job in instance.jobs:
        job_load = 0
        for operation in job:
            duration = int(operation.duration)
            machine_id = int(operation.machine_id)
            machine_loads[machine_id] += duration
            job_load += duration
        if job_load > max_job_load:
            max_job_load = job_load
    lower_bound = max(max_job_load, max(machine_loads) if machine_loads else 0)

    for job_id, job in enumerate(instance.jobs):
        for op_index, operation in enumerate(job):
            key = (job_id, op_index)
            duration = int(operation.duration)
            machine_id = int(operation.machine_id)
            latest_start = max(0, horizon - duration)
            start = model.NewIntVar(0, latest_start, f"s_{job_id}_{op_index}")
            end = model.NewIntVar(duration, horizon, f"e_{job_id}_{op_index}")
            interval = model.NewIntervalVar(start, duration, end, f"i_{job_id}_{op_index}")
            starts[key] = start
            ends[key] = end
            all_ends.append(end)
            intervals_by_machine[machine_id].append((job_id, op_index, interval))

    for job_id, job in enumerate(instance.jobs):
        for op_index in range(1, len(job)):
            model.Add(ends[(job_id, op_index - 1)] <= starts[(job_id, op_index)])

    for machine_ops in intervals_by_machine.values():
        if machine_ops:
            model.AddNoOverlap([interval for _, _, interval in machine_ops])

    makespan = model.NewIntVar(lower_bound, horizon, "makespan")
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
    solver.parameters.max_time_in_seconds = 285.0
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 13
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Schedule.from_job_sequences(instance, fallback_job_sequences)

    job_sequences = [[] for _ in range(instance.num_machines)]
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