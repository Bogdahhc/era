from job_shop_lib import Schedule
import time
import random


def solve(instance):
    n = instance.num_jobs
    m = instance.num_machines

    machines = [[0] * m for _ in range(n)]
    durations = [[0] * m for _ in range(n)]
    for j, job in enumerate(instance.jobs):
        for k, op in enumerate(job):
            machines[j][k] = int(getattr(op, "machine_id", getattr(op, "machine", 0)))
            durations[j][k] = int(getattr(op, "duration", getattr(op, "processing_time", 0)))

    total_ops = sum(len(job) for job in instance.jobs)
    if n == 0 or m == 0 or total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    op_count = [len(job) for job in instance.jobs]

    op_of_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k in range(op_count[j]):
            if 0 <= machines[j][k] < m:
                op_of_machine[j][machines[j][k]] = k

    rem_work = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem_work.append(r)

    def node_id(j, k):
        return j * m + k

    def eval_sequence(seq, need_info=False):
        num_nodes = n * m
        indeg = [0] * num_nodes
        succ = [[] for _ in range(num_nodes)]

        for j in range(n):
            for k in range(op_count[j] - 1):
                a = node_id(j, k)
                b = node_id(j, k + 1)
                succ[a].append(b)
                indeg[b] += 1

        for mach in range(m):
            last = None
            for j in seq[mach]:
                if j < 0 or j >= n:
                    return (10 ** 12, None, None) if need_info else 10 ** 12
                k = op_of_machine[j][mach]
                if k < 0:
                    return (10 ** 12, None, None) if need_info else 10 ** 12
                cur = node_id(j, k)
                if last is not None:
                    succ[last].append(cur)
                    indeg[cur] += 1
                last = cur

        q = [i for i in range(num_nodes) if indeg[i] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        seen = 0

        while head < len(q):
            u = q[head]
            head += 1
            seen += 1
            ju = u // m
            ku = u % m
            finish_u = start[u] + (durations[ju][ku] if ku < op_count[ju] else 0)
            for v in succ[u]:
                if finish_u > start[v]:
                    start[v] = finish_u
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != num_nodes:
            return (10 ** 12, None, None) if need_info else 10 ** 12

        best = 0
        end_node = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = node_id(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end_node = u

        if need_info:
            return best, start, pred, end_node
        return best

    def giffler_thompson(rule):
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
                tail = rem_work[j][k + 1] if k + 1 <= op_count[j] else 0
                rem = rem_work[j][k]
                ops_left = op_count[j] - k
                if rule == 0:
                    return (p, est, j)
                if rule == 1:
                    return (-p, est, j)
                if rule == 2:
                    return (-rem, est, j)
                if rule == 3:
                    return (rem, est, j)
                if rule == 4:
                    return (-ops_left, -rem, est, j)
                if rule == 5:
                    return (ops_left, p, est, j)
                if rule == 6:
                    return (est + p, -rem, j)
                if rule == 7:
                    return (est, -p, -rem, j)
                if rule == 8:
                    return (-tail, est, -p, j)
                if rule == 9:
                    return (tail, est, p, j)
                if rule == 10:
                    return (job_ready[j], -rem, j)
                if rule == 11:
                    return (-job_ready[j], -p, j)
                if rule == 12:
                    return (est + p + tail // 4, -rem, j)
                return (est + p - rem // 5, -p, j)

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
                return (ect - rem // 8, -p, j)

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

    best_seq = None
    best_val = 10 ** 12

    for r in range(14):
        s = giffler_thompson(r)
        v = eval_sequence(s)
        if v < best_val:
            best_val = v
            best_seq = [x[:] for x in s]

    for r in range(7):
        s = list_dispatch(r)
        v = eval_sequence(s)
        if v < best_val:
            best_val = v
            best_seq = [x[:] for x in s]

    deadline = time.perf_counter() + 1.85
    rng = random.Random(21021)

    def critical_swaps(seq):
        val, start, pred, end_node = eval_sequence(seq, True)
        if start is None:
            return []
        critical = set()
        u = end_node
        while u != -1:
            critical.add(u)
            u = pred[u]

        moves = []
        for mach in range(m):
            arr = seq[mach]
            for i in range(len(arr) - 1):
                j1 = arr[i]
                j2 = arr[i + 1]
                k1 = op_of_machine[j1][mach]
                k2 = op_of_machine[j2][mach]
                if node_id(j1, k1) in critical and node_id(j2, k2) in critical:
                    moves.append((mach, i))
        rng.shuffle(moves)
        return moves

    improved = True
    while time.perf_counter() < deadline and improved:
        improved = False
        moves = critical_swaps(best_seq)
        local_best = best_val
        local_move = None

        for mach, i in moves:
            if time.perf_counter() >= deadline:
                break
            s = [x[:] for x in best_seq]
            s[mach][i], s[mach][i + 1] = s[mach][i + 1], s[mach][i]
            v = eval_sequence(s)
            if v < local_best:
                local_best = v
                local_move = (mach, i)

        if local_move is not None:
            mach, i = local_move
            best_seq[mach][i], best_seq[mach][i + 1] = best_seq[mach][i + 1], best_seq[mach][i]
            best_val = local_best
            improved = True

    attempts = 0
    while time.perf_counter() < deadline:
        attempts += 1
        mach = rng.randrange(m)
        if len(best_seq[mach]) < 2:
            continue
        if attempts % 3 == 0:
            i = rng.randrange(len(best_seq[mach]) - 1)
        else:
            moves = critical_swaps(best_seq)
            if moves:
                mach, i = moves[rng.randrange(len(moves))]
            else:
                i = rng.randrange(len(best_seq[mach]) - 1)

        best_seq[mach][i], best_seq[mach][i + 1] = best_seq[mach][i + 1], best_seq[mach][i]
        v = eval_sequence(best_seq)
        if v < best_val:
            best_val = v
        else:
            best_seq[mach][i], best_seq[mach][i + 1] = best_seq[mach][i + 1], best_seq[mach][i]

    return Schedule.from_job_sequences(instance, best_seq)