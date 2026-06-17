import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    start_time = time.perf_counter()
    time_limit = 3.5
    deadline = start_time + time_limit

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines = []
    durations = []
    for job in jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(int(getattr(op, "machine_id")))
            jd.append(int(getattr(op, "duration")))
        machines.append(jm)
        durations.append(jd)

    offsets = []
    total_ops = 0
    for j in range(num_jobs):
        offsets.append(total_ops)
        total_ops += len(machines[j])

    node_job = [0] * total_ops
    node_op = [0] * total_ops
    node_machine = [0] * total_ops
    node_duration = [0] * total_ops
    for j in range(num_jobs):
        for k in range(len(machines[j])):
            n = offsets[j] + k
            node_job[n] = j
            node_op[n] = k
            node_machine[n] = machines[j][k]
            node_duration[n] = durations[j][k]

    remaining_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        remaining_work.append(r)

    job_machine_indices = [[[] for _ in range(num_machines)] for _ in range(num_jobs)]
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)

    def evaluate(job_sequences, need_path=False):
        succ = [[] for _ in range(total_ops)]
        indeg = [0] * total_ops

        for j in range(num_jobs):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = offsets[j] + k + 1
                succ[u].append(v)
                indeg[v] += 1

        mach_nodes = [[] for _ in range(num_machines)]
        node_pos = [-1] * total_ops

        for m in range(num_machines):
            counts = [0] * num_jobs
            prev = -1
            seq = job_sequences[m]
            if len(seq) != len([1 for n in range(total_ops) if node_machine[n] == m]):
                return (inf, None, None, None, None) if need_path else inf
            for pos, j in enumerate(seq):
                if j < 0 or j >= num_jobs:
                    return (inf, None, None, None, None) if need_path else inf
                c = counts[j]
                counts[j] += 1
                if c >= len(job_machine_indices[j][m]):
                    return (inf, None, None, None, None) if need_path else inf
                k = job_machine_indices[j][m][c]
                n = offsets[j] + k
                mach_nodes[m].append(n)
                node_pos[n] = pos
                if prev != -1:
                    succ[prev].append(n)
                    indeg[n] += 1
                prev = n

        q = [i for i in range(total_ops) if indeg[i] == 0]
        head = 0
        dist = [0] * total_ops
        pred = [-1] * total_ops if need_path else None
        seen = 0
        best_end = -1
        best_c = 0

        while head < len(q):
            u = q[head]
            head += 1
            seen += 1
            cu = dist[u] + node_duration[u]
            if cu > best_c:
                best_c = cu
                best_end = u
            for v in succ[u]:
                if cu > dist[v]:
                    dist[v] = cu
                    if need_path:
                        pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != total_ops:
            return (inf, None, None, None, None) if need_path else inf
        if need_path:
            return best_c, pred, best_end, mach_nodes, node_pos
        return best_c

    def giffler_thompson(rule_id, rnd=None, weights=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        seqs = [[] for _ in range(num_machines)]
        scheduled = 0

        while scheduled < total_ops:
            available = []
            best_ect = inf
            best_machine = None

            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(machines[j]):
                    continue
                m = machines[j][k]
                p = durations[j][k]
                est = job_ready[j] if job_ready[j] >= machine_ready[m] else machine_ready[m]
                ect = est + p
                available.append((j, k, m, p, est, ect))
                if ect < best_ect:
                    best_ect = ect
                    best_machine = m

            conflict = [x for x in available if x[2] == best_machine and x[4] < best_ect]

            def key(x):
                j, k, m, p, est, ect = x
                rem = remaining_work[j][k]
                ops_left = len(machines[j]) - k
                if rule_id == 0:
                    return (p, rem, est, j)
                if rule_id == 1:
                    return (-p, -rem, est, j)
                if rule_id == 2:
                    return (-rem, p, est, j)
                if rule_id == 3:
                    return (rem, p, est, j)
                if rule_id == 4:
                    return (-ops_left, -rem, p, j)
                if rule_id == 5:
                    return (ect, -rem, p, j)
                if rule_id == 6:
                    return (est, -rem, -p, j)
                if rule_id == 7:
                    return (machine_ready[m], job_ready[j], p, j)
                if rule_id == 8:
                    return (-remaining_work[j][k + 1], p, est, j)
                if rule_id == 9:
                    return (job_ready[j] + remaining_work[j][k], p, j)
                s = (
                    weights[0] * p
                    + weights[1] * rem
                    + weights[2] * est
                    + weights[3] * ect
                    + weights[4] * job_ready[j]
                    + weights[5] * machine_ready[m]
                    + weights[6] * ops_left
                )
                return (s + rnd.random() * 1e-6, j)

            chosen = min(conflict, key=key)
            j, k, m, p, est, ect = chosen
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            scheduled += 1

        return seqs

    def copy_seqs(seqs):
        return [list(s) for s in seqs]

    def critical_swaps(seqs, pred, end_node, mach_nodes, node_pos):
        path = []
        n = end_node
        while n != -1 and n is not None:
            path.append(n)
            n = pred[n]
        path.reverse()

        swaps = []
        used = set()
        for a, b in zip(path, path[1:]):
            m = node_machine[a]
            if m == node_machine[b]:
                pa = node_pos[a]
                pb = node_pos[b]
                if pa >= 0 and pb == pa + 1:
                    key = (m, pa)
                    if key not in used:
                        used.add(key)
                        swaps.append(key)
        return swaps

    def local_search(initial, initial_val):
        current = copy_seqs(initial)
        current_val = initial_val
        best = copy_seqs(current)
        best_val = current_val
        no_improve_rounds = 0
        rnd_local = random.Random(99173 + int(initial_val))

        while time.perf_counter() < deadline:
            val, pred, end_node, mach_nodes, node_pos = evaluate(current, True)
            if val == inf:
                break
            swaps = critical_swaps(current, pred, end_node, mach_nodes, node_pos)

            if not swaps:
                break

            best_move = None
            best_move_val = current_val

            for m, pos in swaps:
                cand = copy_seqs(current)
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                cv = evaluate(cand)
                if cv < best_move_val:
                    best_move_val = cv
                    best_move = (m, pos)
                if time.perf_counter() >= deadline:
                    break

            if best_move is not None:
                m, pos = best_move
                current[m][pos], current[m][pos + 1] = current[m][pos + 1], current[m][pos]
                current_val = best_move_val
                no_improve_rounds = 0
                if current_val < best_val:
                    best_val = current_val
                    best = copy_seqs(current)
                continue

            no_improve_rounds += 1
            if no_improve_rounds > 3:
                break

            m, pos = rnd_local.choice(swaps)
            cand = copy_seqs(current)
            cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
            cv = evaluate(cand)
            if cv < inf and cv <= current_val + 25:
                current = cand
                current_val = cv

        return best, best_val

    best_seq = None
    best_val = inf
    candidates = []

    for rule in range(10):
        s = giffler_thompson(rule)
        v = evaluate(s)
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)
        candidates.append((v, copy_seqs(s)))

    rnd = random.Random(1234567)
    while time.perf_counter() < deadline - 1.2 and len(candidates) < 220:
        weights = [rnd.uniform(-2.0, 2.0) for _ in range(7)]
        weights[1] += rnd.uniform(-1.5, 0.5)
        s = giffler_thompson(100, rnd, weights)
        v = evaluate(s)
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)
        candidates.append((v, copy_seqs(s)))

    candidates.sort(key=lambda x: x[0])
    selected = []
    seen = set()
    for v, s in candidates:
        key = tuple(tuple(x) for x in s)
        if key not in seen:
            seen.add(key)
            selected.append((v, s))
        if len(selected) >= 18:
            break

    for v, s in selected:
        if time.perf_counter() >= deadline:
            break
        ls, lv = local_search(s, v)
        if lv < best_val:
            best_val = lv
            best_seq = copy_seqs(ls)

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)