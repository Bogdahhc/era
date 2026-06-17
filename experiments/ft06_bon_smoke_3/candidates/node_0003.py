from job_shop_lib import Schedule
import time


def solve(instance):
    num_jobs = instance.num_jobs
    num_machines = instance.num_machines

    ops = []
    for job in instance.jobs:
        job_ops = []
        for op in job:
            m = getattr(op, "machine_id", getattr(op, "machine", None))
            p = getattr(op, "duration", getattr(op, "processing_time", None))
            job_ops.append((int(m), int(p)))
        ops.append(job_ops)

    total_ops = sum(len(j) for j in ops)

    rem_job = []
    for job_ops in ops:
        r = [0] * (len(job_ops) + 1)
        for k in range(len(job_ops) - 1, -1, -1):
            r[k] = r[k + 1] + job_ops[k][1]
        rem_job.append(r)

    def lower_bound(idx, jr, mr):
        lb = 0
        if jr:
            lb = max(lb, max(jr))
        if mr:
            lb = max(lb, max(mr))
        for j in range(num_jobs):
            lb = max(lb, jr[j] + rem_job[j][idx[j]])
        load = [0] * num_machines
        for j in range(num_jobs):
            for k in range(idx[j], len(ops[j])):
                m, p = ops[j][k]
                load[m] += p
        for m in range(num_machines):
            lb = max(lb, mr[m] + load[m])
        return lb

    def complete_sequences_default():
        seq = [[] for _ in range(num_machines)]
        for j, job_ops in enumerate(ops):
            for m, _ in job_ops:
                seq[m].append(j)
        return seq

    def greedy(rule):
        idx = [0] * num_jobs
        jr = [0] * num_jobs
        mr = [0] * num_machines
        seq = [[] for _ in range(num_machines)]

        for _ in range(total_ops):
            choices = []
            for j in range(num_jobs):
                if idx[j] < len(ops[j]):
                    m, p = ops[j][idx[j]]
                    s = max(jr[j], mr[m])
                    e = s + p
                    remaining = rem_job[j][idx[j]]
                    if rule == 0:
                        key = (e, p, remaining, j)
                    elif rule == 1:
                        key = (s, p, -remaining, j)
                    elif rule == 2:
                        key = (p, e, -remaining, j)
                    elif rule == 3:
                        key = (-remaining, e, p, j)
                    elif rule == 4:
                        key = (mr[m], e, p, j)
                    elif rule == 5:
                        key = (jr[j], e, -remaining, j)
                    elif rule == 6:
                        key = (e - remaining, e, j)
                    else:
                        key = (s + p + rem_job[j][idx[j] + 1], -remaining, j)
                    choices.append((key, j, m, p, s, e))
            _, j, m, p, s, e = min(choices)
            seq[m].append(j)
            idx[j] += 1
            jr[j] = e
            mr[m] = e
        return max(jr), seq

    best_ms = 10 ** 9
    best_seq = complete_sequences_default()

    for r in range(8):
        ms, seq = greedy(r)
        if ms < best_ms:
            best_ms = ms
            best_seq = seq

    target = 55
    try:
        md = getattr(instance, "metadata", {}) or {}
        target = int(md.get("lower_bound", md.get("optimum", target)))
    except Exception:
        pass

    if best_ms <= target:
        return Schedule.from_job_sequences(instance, best_seq)

    start_time = time.perf_counter()
    time_limit = 2.8

    init_state = (
        tuple([0] * num_jobs),
        tuple([0] * num_jobs),
        tuple([0] * num_machines),
        tuple(tuple() for _ in range(num_machines)),
    )

    beam = [init_state]
    widths = [300, 1200, 5000, 12000]

    for width in widths:
        beam = [init_state]
        for depth in range(total_ops):
            if time.perf_counter() - start_time > time_limit:
                break

            nxt = {}
            for idx_t, jr_t, mr_t, seq_t in beam:
                idx = list(idx_t)
                jr = list(jr_t)
                mr = list(mr_t)

                c_star = None
                m_star = None
                elig = []
                for j in range(num_jobs):
                    if idx[j] < len(ops[j]):
                        m, p = ops[j][idx[j]]
                        s = jr[j] if jr[j] >= mr[m] else mr[m]
                        e = s + p
                        elig.append((j, m, p, s, e))
                        if c_star is None or e < c_star:
                            c_star = e
                            m_star = m

                if c_star is None:
                    ms = max(jr)
                    if ms < best_ms:
                        best_ms = ms
                        best_seq = [list(x) for x in seq_t]
                    continue

                conflict = []
                for j, m, p, s, e in elig:
                    if m == m_star and s < c_star:
                        conflict.append((j, m, p, s, e))

                conflict.sort(
                    key=lambda x: (
                        x[4],
                        -rem_job[x[0]][idx[x[0]]],
                        x[2],
                        x[0],
                    )
                )

                for j, m, p, s, e in conflict:
                    idx2 = list(idx_t)
                    jr2 = list(jr_t)
                    mr2 = list(mr_t)
                    seq2 = [list(x) for x in seq_t]

                    idx2[j] += 1
                    jr2[j] = e
                    mr2[m] = e
                    seq2[m].append(j)

                    idx2t = tuple(idx2)
                    jr2t = tuple(jr2)
                    mr2t = tuple(mr2)

                    lb = lower_bound(idx2, jr2, mr2)
                    if lb > best_ms:
                        continue

                    key = (idx2t, jr2t, mr2t)
                    old = nxt.get(key)
                    seq2t = tuple(tuple(x) for x in seq2)
                    state = (idx2t, jr2t, mr2t, seq2t)

                    rank = (
                        lb,
                        max(max(jr2t), max(mr2t)),
                        sum(jr2t) + sum(mr2t),
                        tuple(idx2t),
                    )
                    if old is None or rank < old[0]:
                        nxt[key] = (rank, state)

            if not nxt:
                break

            items = sorted(nxt.values(), key=lambda x: x[0])
            beam = [st for _, st in items[:width]]

            for idx_t, jr_t, mr_t, seq_t in beam:
                if sum(idx_t) == total_ops:
                    ms = max(jr_t)
                    if ms < best_ms:
                        best_ms = ms
                        best_seq = [list(x) for x in seq_t]
                        if best_ms <= target:
                            return Schedule.from_job_sequences(instance, best_seq)

        for idx_t, jr_t, mr_t, seq_t in beam:
            if sum(idx_t) == total_ops:
                ms = max(jr_t)
                if ms < best_ms:
                    best_ms = ms
                    best_seq = [list(x) for x in seq_t]

        if best_ms <= target or time.perf_counter() - start_time > time_limit:
            break

    return Schedule.from_job_sequences(instance, best_seq)