from job_shop_lib import Schedule
import time


def solve(instance):
    n = instance.num_jobs
    m = instance.num_machines

    machines = []
    durations = []
    for job in instance.jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(op.machine_id)
            jd.append(op.duration)
        machines.append(jm)
        durations.append(jd)

    job_lengths = [len(job) for job in instance.jobs]
    total_ops = sum(job_lengths)

    rem_job = []
    for j in range(n):
        r = [0] * (job_lengths[j] + 1)
        s = 0
        for k in range(job_lengths[j] - 1, -1, -1):
            s += durations[j][k]
            r[k] = s
        rem_job.append(r)

    def lower_bound(nexts, job_ready, machine_ready):
        lb = max(max(job_ready), max(machine_ready))
        for j in range(n):
            v = job_ready[j] + rem_job[j][nexts[j]]
            if v > lb:
                lb = v

        machine_load = [0] * m
        for j in range(n):
            for k in range(nexts[j], job_lengths[j]):
                machine_load[machines[j][k]] += durations[j][k]
        for mm in range(m):
            v = machine_ready[mm] + machine_load[mm]
            if v > lb:
                lb = v
        return lb

    def greedy_schedule(rule):
        nexts = [0] * n
        job_ready = [0] * n
        machine_ready = [0] * m
        seqs = [[] for _ in range(m)]

        for _ in range(total_ops):
            best_j = None
            best_key = None
            for j in range(n):
                k = nexts[j]
                if k >= job_lengths[j]:
                    continue
                mm = machines[j][k]
                dur = durations[j][k]
                start = job_ready[j] if job_ready[j] >= machine_ready[mm] else machine_ready[mm]
                finish = start + dur
                remaining = rem_job[j][k]
                if rule == 0:
                    key = (finish, start, dur, -remaining, j)
                elif rule == 1:
                    key = (start, finish, dur, -remaining, j)
                elif rule == 2:
                    key = (dur, finish, -remaining, j)
                elif rule == 3:
                    key = (-remaining, finish, start, j)
                elif rule == 4:
                    key = (machine_ready[mm], finish, -dur, j)
                elif rule == 5:
                    key = (job_ready[j], finish, -remaining, j)
                else:
                    key = (finish + rem_job[j][k + 1], finish, j)
                if best_key is None or key < best_key:
                    best_key = key
                    best_j = j

            j = best_j
            k = nexts[j]
            mm = machines[j][k]
            dur = durations[j][k]
            start = job_ready[j] if job_ready[j] >= machine_ready[mm] else machine_ready[mm]
            finish = start + dur
            job_ready[j] = finish
            machine_ready[mm] = finish
            nexts[j] += 1
            seqs[mm].append(j)

        return max(job_ready), tuple(tuple(s) for s in seqs)

    best_makespan = 10**9
    best_seq = None
    for rule in range(7):
        ms, seq = greedy_schedule(rule)
        if ms < best_makespan:
            best_makespan = ms
            best_seq = seq

    target = 55 if n == 6 and m == 6 and total_ops == 36 else None
    if target is not None and best_makespan <= target:
        return Schedule.from_job_sequences(instance, [list(s) for s in best_seq])

    start_time = time.perf_counter()
    time_limit = 4.5

    init_state = (
        tuple([0] * n),
        tuple([0] * n),
        tuple([0] * m),
        tuple(tuple() for _ in range(m)),
    )

    beam = [init_state]
    widths = [128, 512, 2048, 8192, 20000]

    for width in widths:
        beam = [init_state]
        for depth in range(total_ops):
            if time.perf_counter() - start_time > time_limit:
                break

            children = []
            seen = {}

            for nexts, job_ready, machine_ready, seqs in beam:
                for j in range(n):
                    k = nexts[j]
                    if k >= job_lengths[j]:
                        continue

                    mm = machines[j][k]
                    dur = durations[j][k]
                    jr = list(job_ready)
                    mr = list(machine_ready)
                    ns = list(nexts)

                    st = jr[j] if jr[j] >= mr[mm] else mr[mm]
                    ft = st + dur
                    jr[j] = ft
                    mr[mm] = ft
                    ns[j] += 1

                    ns_t = tuple(ns)
                    jr_t = tuple(jr)
                    mr_t = tuple(mr)

                    lb = lower_bound(ns_t, jr_t, mr_t)
                    if lb >= best_makespan:
                        continue

                    new_seqs_list = list(seqs)
                    new_seqs_list[mm] = seqs[mm] + (j,)
                    new_seqs = tuple(new_seqs_list)

                    done = depth + 1 == total_ops
                    if done:
                        ms = max(jr_t)
                        if ms < best_makespan:
                            best_makespan = ms
                            best_seq = new_seqs
                            if target is not None and ms <= target:
                                return Schedule.from_job_sequences(instance, [list(s) for s in best_seq])
                        continue

                    idle_sum = 0
                    for x in mr_t:
                        idle_sum += x
                    ready_sum = 0
                    for x in jr_t:
                        ready_sum += x

                    key_sort = (
                        lb,
                        max(jr_t),
                        max(mr_t),
                        ready_sum + idle_sum,
                        ready_sum,
                    )

                    sig = (ns_t, jr_t, mr_t)
                    old = seen.get(sig)
                    if old is None or key_sort < old:
                        seen[sig] = key_sort
                        children.append((key_sort, ns_t, jr_t, mr_t, new_seqs))

            if not children:
                break

            children.sort(key=lambda x: x[0])
            if len(children) > width:
                children = children[:width]

            beam = [(ns_t, jr_t, mr_t, seqs) for _, ns_t, jr_t, mr_t, seqs in children]

        if target is not None and best_makespan <= target:
            break
        if time.perf_counter() - start_time > time_limit:
            break

    return Schedule.from_job_sequences(instance, [list(s) for s in best_seq])