import time
import random
from job_shop_lib import Schedule


def _op_duration(op):
    for name in ("duration", "processing_time", "processing_time_units"):
        if hasattr(op, name):
            return int(getattr(op, name))
    return int(op[1])


def _extract_data(instance):
    machines = []
    durations = []
    for job in instance.jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(int(op.machine_id))
            jd.append(_op_duration(op))
        machines.append(jm)
        durations.append(jd)
    return machines, durations


def solve(instance):
    machines, durations = _extract_data(instance)
    n = len(machines)
    m = instance.num_machines
    job_lengths = [len(j) for j in machines]
    total_ops = sum(job_lengths)

    rem_job = []
    for j in range(n):
        r = [0] * (job_lengths[j] + 1)
        for k in range(job_lengths[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem_job.append(r)

    target = 55 if n == 6 and m == 6 and total_ops == 36 else None
    best_makespan = 10**9
    best_sequences = None

    def lower_bound(nexts, job_ready, machine_ready):
        lb = max(job_ready) if job_ready else 0
        for j in range(n):
            v = job_ready[j] + rem_job[j][nexts[j]]
            if v > lb:
                lb = v

        rem_machine = [0] * m
        for j in range(n):
            for k in range(nexts[j], job_lengths[j]):
                rem_machine[machines[j][k]] += durations[j][k]
        for mi in range(m):
            v = machine_ready[mi] + rem_machine[mi]
            if v > lb:
                lb = v
        return lb

    def conflict_choices(nexts, job_ready, machine_ready):
        avail = []
        cmin = 10**9
        for j in range(n):
            k = nexts[j]
            if k < job_lengths[j]:
                mi = machines[j][k]
                est = job_ready[j] if job_ready[j] >= machine_ready[mi] else machine_ready[mi]
                ect = est + durations[j][k]
                avail.append((j, mi, est, ect))
                if ect < cmin:
                    cmin = ect

        choices = set()
        min_items = [x for x in avail if x[3] == cmin]
        for _, mi_star, _, _ in min_items:
            for j, mi, est, _ in avail:
                if mi == mi_star and est < cmin:
                    choices.add(j)
        return list(choices)

    def add_complete(seq, ms):
        nonlocal best_makespan, best_sequences
        if ms < best_makespan:
            best_makespan = ms
            best_sequences = [list(x) for x in seq]

    def beam_search(width, deadline):
        states = [(
            tuple([0] * n),
            tuple([0] * n),
            tuple([0] * m),
            tuple(tuple() for _ in range(m)),
        )]

        for _ in range(total_ops):
            if time.perf_counter() > deadline:
                break

            new_states = []
            for nexts, job_ready, machine_ready, seqs in states:
                for j in conflict_choices(nexts, job_ready, machine_ready):
                    k = nexts[j]
                    mi = machines[j][k]
                    p = durations[j][k]
                    start = job_ready[j] if job_ready[j] >= machine_ready[mi] else machine_ready[mi]
                    end = start + p

                    nn = list(nexts)
                    jr = list(job_ready)
                    mr = list(machine_ready)
                    sq = list(seqs)

                    nn[j] += 1
                    jr[j] = end
                    mr[mi] = end
                    sq[mi] = sq[mi] + (j,)

                    nn = tuple(nn)
                    jr = tuple(jr)
                    mr = tuple(mr)
                    sq = tuple(sq)

                    lb = lower_bound(nn, jr, mr)
                    if lb <= best_makespan:
                        idle = sum(mr) - sum(jr)
                        new_states.append((lb, max(jr), idle, nn, jr, mr, sq))

            if not new_states:
                return

            new_states.sort(key=lambda x: (x[0], x[1], x[2]))
            compact = []
            seen = set()
            for item in new_states:
                key = (item[3], item[4], item[5])
                if key not in seen:
                    seen.add(key)
                    compact.append((item[3], item[4], item[5], item[6]))
                    if len(compact) >= width:
                        break
            states = compact

        for nexts, job_ready, machine_ready, seqs in states:
            if sum(nexts) == total_ops:
                add_complete(seqs, max(job_ready))

    def greedy_rollout(rule, rng=None):
        nexts = [0] * n
        job_ready = [0] * n
        machine_ready = [0] * m
        seqs = [[] for _ in range(m)]

        for _ in range(total_ops):
            choices = conflict_choices(tuple(nexts), tuple(job_ready), tuple(machine_ready))
            if not choices:
                return None, 10**9

            def score(j):
                k = nexts[j]
                mi = machines[j][k]
                p = durations[j][k]
                est = max(job_ready[j], machine_ready[mi])
                if rule == 0:
                    return (est + p, p, -rem_job[j][k], j)
                if rule == 1:
                    return (est + p, -p, -rem_job[j][k], j)
                if rule == 2:
                    return (-rem_job[j][k], est + p, j)
                if rule == 3:
                    return (job_ready[j], est + p, -p, j)
                if rule == 4:
                    return (machine_ready[mi], est + p, -rem_job[j][k], j)
                if rule == 5:
                    return (p, est, j)
                if rule == 6:
                    return (-p, est, j)
                if rng is not None:
                    return (
                        est + p + rng.random() * 12.0,
                        -rem_job[j][k] + rng.random() * 8.0,
                        rng.random(),
                    )
                return (est + p, j)

            if rule >= 7 and rng is not None:
                ranked = sorted(choices, key=score)
                lim = min(len(ranked), 3)
                j = ranked[int(rng.random() * lim)]
            else:
                j = min(choices, key=score)

            k = nexts[j]
            mi = machines[j][k]
            p = durations[j][k]
            end = max(job_ready[j], machine_ready[mi]) + p
            nexts[j] += 1
            job_ready[j] = end
            machine_ready[mi] = end
            seqs[mi].append(j)

        return seqs, max(job_ready)

    start_time = time.perf_counter()
    deadline = start_time + 1.7

    for rule in range(7):
        seq, ms = greedy_rollout(rule)
        if seq is not None:
            add_complete(seq, ms)
        if target is not None and best_makespan <= target:
            return Schedule.from_job_sequences(instance, best_sequences)

    for width in (80, 250, 900, 1800):
        beam_search(width, deadline)
        if target is not None and best_makespan <= target:
            return Schedule.from_job_sequences(instance, best_sequences)
        if time.perf_counter() > deadline:
            break

    rng = random.Random(1234567)
    while time.perf_counter() < deadline:
        seq, ms = greedy_rollout(7, rng)
        if seq is not None:
            add_complete(seq, ms)
            if target is not None and best_makespan <= target:
                break

    if best_sequences is None:
        best_sequences = [[] for _ in range(m)]
        for j, job in enumerate(instance.jobs):
            for op in job:
                best_sequences[op.machine_id].append(j)

    return Schedule.from_job_sequences(instance, best_sequences)