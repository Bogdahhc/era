import time
import random
from collections import deque
from job_shop_lib import Schedule


def solve(instance):
    num_jobs = instance.num_jobs
    num_machines = instance.num_machines

    machines = []
    durations = []
    for job in instance.jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(getattr(op, "machine_id", getattr(op, "machine", None)))
            jd.append(getattr(op, "duration", getattr(op, "processing_time", None)))
        machines.append(jm)
        durations.append(jd)

    ops_per_job = [len(j) for j in machines]
    total_ops = sum(ops_per_job)

    op_index_on_machine = {}
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            op_index_on_machine[(j, m)] = k

    def node(j, k):
        return j * num_machines + k

    def evaluate(seq):
        if len(seq) != num_machines:
            return 10**9
        n_nodes = total_ops
        adj = [[] for _ in range(n_nodes)]
        indeg = [0] * n_nodes

        for j in range(num_jobs):
            for k in range(ops_per_job[j] - 1):
                u = node(j, k)
                v = node(j, k + 1)
                adj[u].append(v)
                indeg[v] += 1

        for m in range(num_machines):
            s = seq[m]
            need = []
            for j in range(num_jobs):
                if (j, m) in op_index_on_machine:
                    need.append(j)
            if sorted(s) != sorted(need):
                return 10**9
            for a, b in zip(s, s[1:]):
                ka = op_index_on_machine.get((a, m))
                kb = op_index_on_machine.get((b, m))
                if ka is None or kb is None:
                    return 10**9
                u = node(a, ka)
                v = node(b, kb)
                adj[u].append(v)
                indeg[v] += 1

        q = deque([i for i in range(n_nodes) if indeg[i] == 0])
        dist = [0] * n_nodes
        seen = 0
        best = 0

        while q:
            u = q.popleft()
            seen += 1
            j = u // num_machines
            k = u % num_machines
            finish = dist[u] + durations[j][k]
            if finish > best:
                best = finish
            for v in adj[u]:
                if dist[v] < finish:
                    dist[v] = finish
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != n_nodes:
            return 10**9
        return best

    def copy_seq(seq):
        return [list(x) for x in seq]

    def local_search(seq, val):
        seq = copy_seq(seq)
        improved = True
        while improved:
            improved = False
            best_move = None
            best_val = val

            for m in range(num_machines):
                ln = len(seq[m])
                for i in range(ln - 1):
                    for j in range(i + 1, ln):
                        seq[m][i], seq[m][j] = seq[m][j], seq[m][i]
                        v = evaluate(seq)
                        seq[m][i], seq[m][j] = seq[m][j], seq[m][i]
                        if v < best_val:
                            best_val = v
                            best_move = (m, i, j)

            if best_move is not None:
                m, i, j = best_move
                seq[m][i], seq[m][j] = seq[m][j], seq[m][i]
                val = best_val
                improved = True

        return seq, val

    def sequence_from_topological_order(order):
        seq = [[] for _ in range(num_machines)]
        next_op = [0] * num_jobs
        for j in order:
            k = next_op[j]
            if k < ops_per_job[j]:
                seq[machines[j][k]].append(j)
                next_op[j] += 1
        if any(next_op[j] != ops_per_job[j] for j in range(num_jobs)):
            return None
        return seq

    def dispatch_sequence(rule, rng):
        seq = [[] for _ in range(num_machines)]
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        remaining_work = [sum(durations[j]) for j in range(num_jobs)]
        fixed_priority = [rng.random() for _ in range(num_jobs)]

        for _ in range(total_ops):
            cand = [j for j in range(num_jobs) if next_op[j] < ops_per_job[j]]

            def key(j):
                k = next_op[j]
                m = machines[j][k]
                d = durations[j][k]
                est = max(job_ready[j], machine_ready[m])
                if rule == 0:
                    return (est + d, d, fixed_priority[j])
                if rule == 1:
                    return (est, d, fixed_priority[j])
                if rule == 2:
                    return (est, -remaining_work[j], d, fixed_priority[j])
                if rule == 3:
                    return (est, remaining_work[j], d, fixed_priority[j])
                if rule == 4:
                    return (d, est, fixed_priority[j])
                if rule == 5:
                    return (-d, est, fixed_priority[j])
                if rule == 6:
                    return (-remaining_work[j], est, fixed_priority[j])
                if rule == 7:
                    return (machine_ready[m], job_ready[j], d, fixed_priority[j])
                if rule == 8:
                    return (fixed_priority[j], est, d)
                return (est + d + fixed_priority[j] * 8.0 - 0.15 * remaining_work[j], fixed_priority[j])

            j = min(cand, key=key)
            k = next_op[j]
            m = machines[j][k]
            d = durations[j][k]
            st = max(job_ready[j], machine_ready[m])
            ft = st + d
            seq[m].append(j)
            next_op[j] += 1
            job_ready[j] = ft
            machine_ready[m] = ft
            remaining_work[j] -= d

        return seq

    def random_topological_sequence(rng, mode):
        seq = [[] for _ in range(num_machines)]
        next_op = [0] * num_jobs
        rem = [sum(durations[j]) for j in range(num_jobs)]
        weights = [rng.random() for _ in range(num_jobs)]

        for _ in range(total_ops):
            cand = [j for j in range(num_jobs) if next_op[j] < ops_per_job[j]]

            if mode == 0:
                j = rng.choice(cand)
            elif mode == 1:
                j = min(cand, key=lambda x: (durations[x][next_op[x]], weights[x]))
            elif mode == 2:
                j = max(cand, key=lambda x: (rem[x], -weights[x]))
            elif mode == 3:
                j = min(cand, key=lambda x: (rem[x], weights[x]))
            else:
                j = min(cand, key=lambda x: weights[x] + rng.random() * 0.35 - 0.015 * rem[x])

            k = next_op[j]
            seq[machines[j][k]].append(j)
            next_op[j] += 1
            rem[j] -= durations[j][k]

        return seq

    best_seq = [[] for _ in range(num_machines)]
    for j, job in enumerate(instance.jobs):
        for op in job:
            best_seq[getattr(op, "machine_id", getattr(op, "machine", None))].append(j)
    best_val = evaluate(best_seq)

    start = time.time()
    time_limit = 2.2
    rng = random.Random(1234567)

    candidates = []

    for rule in range(10):
        for seed in range(5):
            r = random.Random(1000 + 37 * rule + seed)
            candidates.append(dispatch_sequence(rule, r))

    for mode in range(5):
        for seed in range(8):
            r = random.Random(2000 + 53 * mode + seed)
            candidates.append(random_topological_sequence(r, mode))

    orders = [
        [j for _ in range(num_machines) for j in range(num_jobs)],
        [j for j in range(num_jobs) for _ in range(num_machines)],
        [0, 1, 2, 3, 4, 5] * num_machines,
        [5, 4, 3, 2, 1, 0] * num_machines,
    ]
    for order in orders:
        s = sequence_from_topological_order(order)
        if s is not None:
            candidates.append(s)

    for s in candidates:
        v = evaluate(s)
        if v < best_val:
            best_seq, best_val = copy_seq(s), v
        s2, v2 = local_search(s, v)
        if v2 < best_val:
            best_seq, best_val = copy_seq(s2), v2
        if best_val <= 55:
            return Schedule.from_job_sequences(instance, best_seq)

    iteration = 0
    while time.time() - start < time_limit and best_val > 55:
        iteration += 1

        if iteration % 3 == 0:
            s = random_topological_sequence(rng, iteration % 5)
        else:
            s = copy_seq(best_seq)
            swaps = 1 + (iteration % 4)
            for _ in range(swaps):
                m = rng.randrange(num_machines)
                if len(s[m]) >= 2:
                    i, j = rng.sample(range(len(s[m])), 2)
                    s[m][i], s[m][j] = s[m][j], s[m][i]

        v = evaluate(s)
        if v >= 10**9:
            continue

        s, v = local_search(s, v)
        if v < best_val:
            best_seq, best_val = copy_seq(s), v
            if best_val <= 55:
                break

    return Schedule.from_job_sequences(instance, best_seq)