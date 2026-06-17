from job_shop_lib import Schedule
import time
import random
import math


def solve(instance):
    n = instance.num_jobs
    m = instance.num_machines

    if n == 0 or m == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    machines = []
    durations = []
    for job in instance.jobs:
        mj = []
        dj = []
        for op in job:
            mj.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            dj.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(mj)
        durations.append(dj)

    op_count = [len(job) for job in instance.jobs]
    total_ops = sum(op_count)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(op_count) if op_count else m
    if width < m:
        width = m

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

    def node_id(j, k):
        return j * width + k

    num_nodes = n * width
    real_nodes = []
    for j in range(n):
        for k in range(op_count[j]):
            real_nodes.append(node_id(j, k))

    INF = 10 ** 12

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
            if len(seq[mach]) != n:
                return (INF, None, None, None) if need_info else INF
            seen = [False] * n
            last = None
            for j in seq[mach]:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if need_info else INF
                seen[j] = True
                k = op_of_machine[j][mach]
                if k < 0:
                    return (INF, None, None, None) if need_info else INF
                cur = node_id(j, k)
                if last is not None:
                    succ[last].append(cur)
                    indeg[cur] += 1
                last = cur

        q = [u for u in real_nodes if indeg[u] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        seen_count = 0

        while head < len(q):
            u = q[head]
            head += 1
            seen_count += 1
            ju = u // width
            ku = u % width
            finish_u = start[u] + durations[ju][ku]
            for v in succ[u]:
                if finish_u > start[v]:
                    start[v] = finish_u
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen_count != total_ops:
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

    def giffler_thompson(rule, rng=None, noise=0):
        job_ready = [0] * n
        mach_ready = [0] * m
        next_op = [0] * n
        seq = [[] for _ in range(m)]
        done = 0

        while done < total_ops:
            best_c = None
            target_m = None
            for j in range(n):
                k = next_op[j]
                if k < op_count[j]:
                    mach = machines[j][k]
                    p = durations[j][k]
                    c = max(job_ready[j], mach_ready[mach]) + p
                    if best_c is None or c < best_c:
                        best_c = c
                        target_m = mach

            conflict = []
            for j in range(n):
                k = next_op[j]
                if k < op_count[j] and machines[j][k] == target_m and job_ready[j] < best_c:
                    conflict.append(j)

            def key(j):
                k = next_op[j]
                p = durations[j][k]
                est = max(job_ready[j], mach_ready[target_m])
                ect = est + p
                rem = rem_work[j][k]
                tail = rem_work[j][k + 1]
                ops_left = op_count[j] - k
                slackish = ect + tail
                load = machine_load[target_m]
                if rule == 0:
                    val = (p, est, -rem, j)
                elif rule == 1:
                    val = (-p, est, -rem, j)
                elif rule == 2:
                    val = (-rem, est, -p, j)
                elif rule == 3:
                    val = (rem, est, p, j)
                elif rule == 4:
                    val = (-ops_left, -rem, est, j)
                elif rule == 5:
                    val = (ops_left, p, est, j)
                elif rule == 6:
                    val = (ect, -rem, j)
                elif rule == 7:
                    val = (est, -p, -rem, j)
                elif rule == 8:
                    val = (-tail, est, -p, j)
                elif rule == 9:
                    val = (tail, est, p, j)
                elif rule == 10:
                    val = (job_ready[j], -rem, -p, j)
                elif rule == 11:
                    val = (-job_ready[j], -p, -rem, j)
                elif rule == 12:
                    val = (slackish, -rem, j)
                elif rule == 13:
                    val = (ect - rem // 5, -p, j)
                elif rule == 14:
                    val = (ect + tail // 3, -total_work[j], j)
                elif rule == 15:
                    val = (est + p * 2 - rem // 4, -tail, j)
                elif rule == 16:
                    val = (-total_work[j], ect, j)
                elif rule == 17:
                    val = (ect + load // 20 - rem // 6, -p, j)
                else:
                    val = (est + p - tail // 7, -rem, j)
                if rng is not None and noise:
                    return val + (rng.randrange(noise),)
                return val

            chosen = min(conflict, key=key)
            k = next_op[chosen]
            mach = machines[chosen][k]
            p = durations[chosen][k]
            st = max(job_ready[chosen], mach_ready[mach])
            ft = st + p
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
            candidates = [j for j in range(n) if next_op[j] < op_count[j]]

            def key(j):
                k = next_op[j]
                mach = machines[j][k]
                p = durations[j][k]
                est = max(job_ready[j], mach_ready[mach])
                ect = est + p
                rem = rem_work[j][k]
                tail = rem_work[j][k + 1]
                ops_left = op_count[j] - k
                if rule == 0:
                    return (ect, -rem, j)
                if rule == 1:
                    return (est, -p, -rem, j)
                if rule == 2:
                    return (-rem, ect, j)
                if rule == 3:
                    return (p, est, j)
                if rule == 4:
                    return (-p, est, j)
                if rule == 5:
                    return (tail, ect, j)
                if rule == 6:
                    return (ect - rem // 8, -p, j)
                if rule == 7:
                    return (ect + tail, -rem, j)
                if rule == 8:
                    return (ops_left, ect, p, j)
                return (-total_work[j], ect, j)

            chosen = min(candidates, key=key)
            k = next_op[chosen]
            mach = machines[chosen][k]
            p = durations[chosen][k]
            st = max(job_ready[chosen], mach_ready[mach])
            ft = st + p
            seq[mach].append(chosen)
            job_ready[chosen] = ft
            mach_ready[mach] = ft
            next_op[chosen] += 1
            done += 1

        return seq

    rng = random.Random(21021021)
    best_seq = None
    best_val = INF

    for r in range(19):
        s = giffler_thompson(r)
        v = eval_sequence(s)
        if v < best_val:
            best_val = v
            best_seq = [a[:] for a in s]

    for r in range(10):
        s = list_dispatch(r)
        v = eval_sequence(s)
        if v < best_val:
            best_val = v
            best_seq = [a[:] for a in s]

    deadline = time.perf_counter() + 3.65

    while time.perf_counter() < deadline - 2.7:
        r = rng.randrange(19)
        s = giffler_thompson(r, rng, 17)
        v = eval_sequence(s)
        if v < best_val:
            best_val = v
            best_seq = [a[:] for a in s]

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

    def neighborhood(seq):
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
                    cand = []
                    cand.append(("swap", mach, b[0], b[0] + 1))
                    cand.append(("swap", mach, b[-1] - 1, b[-1]))
                    if len(b) >= 3:
                        cand.append(("insert", mach, b[0], b[-1] + 1))
                        cand.append(("insert", mach, b[-1], b[0]))
                    if len(b) >= 4:
                        cand.append(("swap", mach, b[1], b[1] + 1))
                        cand.append(("swap", mach, b[-2] - 1, b[-2]))
                    for mv in cand:
                        if mv not in added:
                            added.add(mv)
                            moves.append(mv)

            for i in range(len(arr) - 1):
                j1 = arr[i]
                j2 = arr[i + 1]
                if node_id(j1, op_of_machine[j1][mach]) in critical and node_id(j2, op_of_machine[j2][mach]) in critical:
                    mv = ("swap", mach, i, i + 1)
                    if mv not in added:
                        added.add(mv)
                        moves.append(mv)

        rng.shuffle(moves)
        return moves

    def apply_move_inplace(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo_move_inplace(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            if b > a:
                pos = b - 1
            else:
                pos = b
            x = arr.pop(pos)
            arr.insert(a, x)

    improved = True
    while time.perf_counter() < deadline - 1.15 and improved:
        improved = False
        moves = neighborhood(best_seq)
        local_best = best_val
        local_move = None

        for mv in moves:
            if time.perf_counter() >= deadline - 1.15:
                break
            apply_move_inplace(best_seq, mv)
            v = eval_sequence(best_seq)
            undo_move_inplace(best_seq, mv)
            if v < local_best:
                local_best = v
                local_move = mv

        if local_move is not None:
            apply_move_inplace(best_seq, local_move)
            best_val = local_best
            improved = True

    current = [a[:] for a in best_seq]
    current_val = best_val
    temp0 = max(25.0, best_val / 80.0)
    it = 0

    while time.perf_counter() < deadline:
        it += 1
        if it % 20 == 0:
            moves = neighborhood(current)
            if moves:
                mv = moves[0]
            else:
                mach = rng.randrange(m)
                i = rng.randrange(n - 1)
                mv = ("swap", mach, i, i + 1)
        else:
            mach = rng.randrange(m)
            if rng.random() < 0.80:
                i = rng.randrange(n - 1)
                mv = ("swap", mach, i, i + 1)
            else:
                a = rng.randrange(n)
                b = rng.randrange(n)
                if a == b:
                    continue
                mv = ("insert", mach, a, b)

        apply_move_inplace(current, mv)
        v = eval_sequence(current)

        if v < INF:
            if v <= current_val:
                accept = True
            else:
                elapsed_frac = max(0.0, min(1.0, (time.perf_counter() - (deadline - 3.65)) / 3.65))
                temp = temp0 * (1.0 - elapsed_frac) + 0.1
                accept = rng.random() < math.exp((current_val - v) / temp)

            if accept:
                current_val = v
                if v < best_val:
                    best_val = v
                    best_seq = [a[:] for a in current]
                    for _ in range(2):
                        if time.perf_counter() >= deadline:
                            break
                        nm = neighborhood(best_seq)
                        found = False
                        for lm in nm[:80]:
                            apply_move_inplace(best_seq, lm)
                            nv = eval_sequence(best_seq)
                            undo_move_inplace(best_seq, lm)
                            if nv < best_val:
                                apply_move_inplace(best_seq, lm)
                                best_val = nv
                                current = [a[:] for a in best_seq]
                                current_val = nv
                                found = True
                                break
                        if not found:
                            break
            else:
                undo_move_inplace(current, mv)
        else:
            undo_move_inplace(current, mv)

        if it % 250 == 0 and current_val > best_val + 60:
            current = [a[:] for a in best_seq]
            current_val = best_val

    return Schedule.from_job_sequences(instance, best_seq)