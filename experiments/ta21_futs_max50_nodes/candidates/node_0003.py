from job_shop_lib import Schedule
import time
import random
import math


def solve(instance):
    n = instance.num_jobs
    m = instance.num_machines
    if n <= 0 or m <= 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    machines, durations = [], []
    for job in instance.jobs:
        mj, dj = [], []
        for op in job:
            mj.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            dj.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(mj)
        durations.append(dj)

    op_count = [len(j) for j in instance.jobs]
    total_ops = sum(op_count)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(op_count), m)
    INF = 10 ** 12

    op_of_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, mach in enumerate(machines[j]):
            if 0 <= mach < m:
                op_of_machine[j][mach] = k

    rem_work = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem_work.append(r)

    total_work = [rem_work[j][0] for j in range(n)]
    machine_load = [0] * m
    for j in range(n):
        for k in range(op_count[j]):
            machine_load[machines[j][k]] += durations[j][k]

    num_nodes = n * width
    real_nodes = [j * width + k for j in range(n) for k in range(op_count[j])]

    def node_id(j, k):
        return j * width + k

    def eval_sequence(seq, need_info=False):
        indeg = [0] * num_nodes
        succ = [[] for _ in range(num_nodes)]

        for j in range(n):
            for k in range(op_count[j] - 1):
                a = node_id(j, k)
                b = node_id(j, k + 1)
                succ[a].append(b)
                indeg[b] += 1

        for mach in range(m):
            arr = seq[mach]
            if len(arr) != n:
                return (INF, None, None, None) if need_info else INF
            seen = [False] * n
            last = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if need_info else INF
                seen[j] = True
                k = op_of_machine[j][mach]
                if k < 0:
                    return (INF, None, None, None) if need_info else INF
                cur = node_id(j, k)
                if last >= 0:
                    succ[last].append(cur)
                    indeg[cur] += 1
                last = cur

        q = [u for u in real_nodes if indeg[u] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        cnt = 0

        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            ju = u // width
            ku = u % width
            finish = start[u] + durations[ju][ku]
            for v in succ[u]:
                if finish > start[v]:
                    start[v] = finish
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if cnt != total_ops:
            return (INF, None, None, None) if need_info else INF

        best = 0
        end_node = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = node_id(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end_node = u

        return (best, start, pred, end_node) if need_info else best

    def priority_value(rule, j, k, mach, job_ready, mach_ready):
        p = durations[j][k]
        est = max(job_ready[j], mach_ready[mach])
        ect = est + p
        rem = rem_work[j][k]
        tail = rem_work[j][k + 1]
        ops_left = op_count[j] - k
        if rule == 0:
            return p * 3 + est - rem * 0.20
        if rule == 1:
            return -p * 3 + est - rem * 0.15
        if rule == 2:
            return -rem + est * 0.20
        if rule == 3:
            return rem + est * 0.10
        if rule == 4:
            return -ops_left * 60 - rem * 0.25 + est
        if rule == 5:
            return ops_left * 70 + p + est * 0.20
        if rule == 6:
            return ect - rem * 0.18
        if rule == 7:
            return est - p * 1.5 - rem * 0.10
        if rule == 8:
            return -tail * 0.75 + est - p * 0.4
        if rule == 9:
            return tail * 0.7 + est + p * 0.2
        if rule == 10:
            return job_ready[j] - rem * 0.30 - p
        if rule == 11:
            return -job_ready[j] - p * 1.5 - rem * 0.10
        if rule == 12:
            return ect + tail * 0.35 - rem * 0.25
        if rule == 13:
            return ect - rem * 0.23 - p
        if rule == 14:
            return ect + tail * 0.45 - total_work[j] * 0.12
        if rule == 15:
            return est + p * 2.0 - rem * 0.18 - tail * 0.10
        if rule == 16:
            return -total_work[j] + ect * 0.55
        if rule == 17:
            return ect + machine_load[mach] * 0.03 - rem * 0.20 - p * 0.25
        if rule == 18:
            return est + p - tail * 0.18 - rem * 0.15
        if rule == 19:
            return ect + mach_ready[mach] * 0.15 - rem * 0.25
        if rule == 20:
            return est * 0.6 - p * 2.0 + tail * 0.15
        return ect - total_work[j] * 0.18 + ops_left * 15

    def giffler_thompson(rule, rng=None, noise=0.0, top_choice=False):
        job_ready = [0] * n
        mach_ready = [0] * m
        next_op = [0] * n
        seq = [[] for _ in range(m)]
        done = 0

        while done < total_ops:
            best_c = INF
            target_m = 0
            for j in range(n):
                k = next_op[j]
                if k < op_count[j]:
                    mach = machines[j][k]
                    c = max(job_ready[j], mach_ready[mach]) + durations[j][k]
                    if c < best_c:
                        best_c = c
                        target_m = mach

            conflict = []
            for j in range(n):
                k = next_op[j]
                if k < op_count[j] and machines[j][k] == target_m and job_ready[j] < best_c:
                    val = priority_value(rule, j, k, target_m, job_ready, mach_ready)
                    if rng is not None and noise > 0:
                        val += rng.uniform(-noise, noise)
                    conflict.append((val, j))

            if top_choice and rng is not None and len(conflict) > 1:
                conflict.sort()
                lim = min(len(conflict), 3)
                if rng.random() < 0.28:
                    chosen = conflict[rng.randrange(lim)][1]
                else:
                    chosen = conflict[0][1]
            else:
                chosen = min(conflict)[1]

            k = next_op[chosen]
            mach = machines[chosen][k]
            p = durations[chosen][k]
            ft = max(job_ready[chosen], mach_ready[mach]) + p
            seq[mach].append(chosen)
            job_ready[chosen] = ft
            mach_ready[mach] = ft
            next_op[chosen] += 1
            done += 1

        return seq

    def list_dispatch(rule):
        job_ready = [0] * n
        mach_ready = [0] * m
        next_op = [0] * n
        seq = [[] for _ in range(m)]
        done = 0

        while done < total_ops:
            best = None
            chosen = 0
            for j in range(n):
                k = next_op[j]
                if k >= op_count[j]:
                    continue
                mach = machines[j][k]
                p = durations[j][k]
                est = max(job_ready[j], mach_ready[mach])
                ect = est + p
                rem = rem_work[j][k]
                tail = rem_work[j][k + 1]
                ops = op_count[j] - k
                if rule == 0:
                    key = (ect, -rem, j)
                elif rule == 1:
                    key = (est, -p, -rem, j)
                elif rule == 2:
                    key = (-rem, ect, j)
                elif rule == 3:
                    key = (p, est, j)
                elif rule == 4:
                    key = (-p, est, j)
                elif rule == 5:
                    key = (tail, ect, j)
                elif rule == 6:
                    key = (ect - rem * 0.15, -p, j)
                elif rule == 7:
                    key = (ect + tail * 0.4, -rem, j)
                elif rule == 8:
                    key = (ops, ect, p, j)
                elif rule == 9:
                    key = (-total_work[j], ect, j)
                elif rule == 10:
                    key = (est + p * 1.6 - rem * 0.2, j)
                else:
                    key = (mach_ready[mach] + ect - tail * 0.12, j)
                if best is None or key < best:
                    best = key
                    chosen = j

            k = next_op[chosen]
            mach = machines[chosen][k]
            p = durations[chosen][k]
            ft = max(job_ready[chosen], mach_ready[mach]) + p
            seq[mach].append(chosen)
            job_ready[chosen] = ft
            mach_ready[mach] = ft
            next_op[chosen] += 1
            done += 1

        return seq

    rng = random.Random(21021021)
    start_time = time.perf_counter()
    deadline = start_time + 3.85

    best_seq = None
    best_val = INF

    def consider(seq):
        nonlocal best_seq, best_val
        v = eval_sequence(seq)
        if v < best_val:
            best_val = v
            best_seq = [a[:] for a in seq]
        return v

    for r in range(22):
        consider(giffler_thompson(r))
    for r in range(12):
        consider(list_dispatch(r))

    while time.perf_counter() < deadline - 2.85:
        r = rng.randrange(22)
        noise = rng.choice((8.0, 15.0, 25.0, 40.0, 65.0))
        consider(giffler_thompson(r, rng, noise, True))

    if best_seq is None:
        best_seq = giffler_thompson(0)
        best_val = eval_sequence(best_seq)

    def critical_data(seq):
        val, start, pred, end_node = eval_sequence(seq, True)
        if start is None:
            return val, set(), []
        path = []
        u = end_node
        while u != -1:
            path.append(u)
            u = pred[u]
        path.reverse()
        return val, set(path), path

    def neighborhood(seq, broad=False):
        val, critical, path = critical_data(seq)
        if not critical:
            return []
        moves = []
        added = set()

        for mach in range(m):
            arr = seq[mach]
            crit_pos = []
            for i, j in enumerate(arr):
                k = op_of_machine[j][mach]
                if node_id(j, k) in critical:
                    crit_pos.append(i)

            if len(crit_pos) >= 2:
                block = [crit_pos[0]]
                blocks = []
                for pos in crit_pos[1:]:
                    if pos == block[-1] + 1:
                        block.append(pos)
                    else:
                        if len(block) > 1:
                            blocks.append(block)
                        block = [pos]
                if len(block) > 1:
                    blocks.append(block)

                for b in blocks:
                    cand = [
                        ("swap", mach, b[0], b[0] + 1),
                        ("swap", mach, b[-1] - 1, b[-1]),
                    ]
                    if len(b) >= 3:
                        cand.append(("insert", mach, b[0], b[-1] + 1))
                        cand.append(("insert", mach, b[-1], b[0]))
                    if len(b) >= 4:
                        cand.append(("swap", mach, b[1], b[1] + 1))
                        cand.append(("swap", mach, b[-2] - 1, b[-2]))
                    if broad and len(b) >= 5:
                        cand.append(("insert", mach, b[1], b[-1] + 1))
                        cand.append(("insert", mach, b[-2], b[0]))
                    for mv in cand:
                        if mv not in added:
                            added.add(mv)
                            moves.append(mv)

            if broad:
                for idx in crit_pos:
                    for d in (-2, 2):
                        b = idx + d
                        if 0 <= b < n and b != idx:
                            mv = ("insert", mach, idx, b)
                            if mv not in added:
                                added.add(mv)
                                moves.append(mv)

        rng.shuffle(moves)
        return moves

    def apply_move(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo_move(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            pos = b - 1 if b > a else b
            x = arr.pop(pos)
            arr.insert(a, x)

    improved = True
    while improved and time.perf_counter() < deadline - 1.55:
        improved = False
        moves = neighborhood(best_seq, True)
        local_val = best_val
        local_mv = None
        for mv in moves:
            if time.perf_counter() >= deadline - 1.55:
                break
            apply_move(best_seq, mv)
            v = eval_sequence(best_seq)
            undo_move(best_seq, mv)
            if v < local_val:
                local_val = v
                local_mv = mv
        if local_mv is not None:
            apply_move(best_seq, local_mv)
            best_val = local_val
            improved = True

    current = [a[:] for a in best_seq]
    current_val = best_val
    temp0 = max(35.0, best_val / 65.0)
    it = 0

    while time.perf_counter() < deadline:
        it += 1
        if it % 17 == 0:
            nm = neighborhood(current, False)
            if nm:
                mv = nm[0]
            else:
                mach = rng.randrange(m)
                mv = ("swap", mach, rng.randrange(n - 1), rng.randrange(1, n))
                if mv[2] == mv[3]:
                    continue
        else:
            mach = rng.randrange(m)
            if rng.random() < 0.72:
                i = rng.randrange(n - 1)
                mv = ("swap", mach, i, i + 1)
            else:
                a = rng.randrange(n)
                b = rng.randrange(n)
                if a == b:
                    continue
                mv = ("insert", mach, a, b)

        apply_move(current, mv)
        v = eval_sequence(current)

        if v < INF:
            if v <= current_val:
                accept = True
            else:
                frac = (time.perf_counter() - start_time) / max(0.001, deadline - start_time)
                temp = temp0 * (1.0 - min(1.0, frac)) + 0.15
                accept = rng.random() < math.exp((current_val - v) / temp)

            if accept:
                current_val = v
                if v < best_val:
                    best_val = v
                    best_seq = [a[:] for a in current]
                    if time.perf_counter() < deadline - 0.08:
                        for lm in neighborhood(best_seq, False)[:90]:
                            apply_move(best_seq, lm)
                            nv = eval_sequence(best_seq)
                            undo_move(best_seq, lm)
                            if nv < best_val:
                                apply_move(best_seq, lm)
                                best_val = nv
                                current = [a[:] for a in best_seq]
                                current_val = nv
                                break
            else:
                undo_move(current, mv)
        else:
            undo_move(current, mv)

        if it % 300 == 0 and current_val > best_val + 80:
            current = [a[:] for a in best_seq]
            current_val = best_val

    return Schedule.from_job_sequences(instance, best_seq)