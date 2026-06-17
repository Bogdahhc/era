import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    t0 = time.perf_counter()
    deadline = t0 + 5.5

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines = []
    durations = []
    for job in jobs:
        mj, dj = [], []
        for op in job:
            mj.append(int(getattr(op, "machine_id")))
            dj.append(int(getattr(op, "duration")))
        machines.append(mj)
        durations.append(dj)

    nops = sum(len(j) for j in machines)
    offsets = []
    x = 0
    for j in range(num_jobs):
        offsets.append(x)
        x += len(machines[j])

    node_machine = [0] * nops
    node_duration = [0] * nops
    node_job = [0] * nops
    node_op = [0] * nops
    for j in range(num_jobs):
        for k in range(len(machines[j])):
            n = offsets[j] + k
            node_machine[n] = machines[j][k]
            node_duration[n] = durations[j][k]
            node_job[n] = j
            node_op[n] = k

    job_machine_indices = [[[] for _ in range(num_machines)] for _ in range(num_jobs)]
    machine_load_count = [0] * num_machines
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)
            machine_load_count[m] += 1

    remaining_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        remaining_work.append(r)

    def copy_seqs(s):
        return [list(a) for a in s]

    def evaluate(job_sequences, details=False):
        succ = [[] for _ in range(nops)]
        indeg = [0] * nops
        for j in range(num_jobs):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = u + 1
                succ[u].append(v)
                indeg[v] += 1

        node_pos = [-1] * nops
        for m in range(num_machines):
            if len(job_sequences[m]) != machine_load_count[m]:
                return (inf, None, None, None) if details else inf
            counts = [0] * num_jobs
            prev = -1
            for pos, j in enumerate(job_sequences[m]):
                if j < 0 or j >= num_jobs:
                    return (inf, None, None, None) if details else inf
                c = counts[j]
                counts[j] += 1
                if c >= len(job_machine_indices[j][m]):
                    return (inf, None, None, None) if details else inf
                k = job_machine_indices[j][m][c]
                n = offsets[j] + k
                node_pos[n] = pos
                if prev >= 0:
                    succ[prev].append(n)
                    indeg[n] += 1
                prev = n

        q = [i for i in range(nops) if indeg[i] == 0]
        head = 0
        dist = [0] * nops
        pred = [-1] * nops if details else None
        seen = 0
        best = 0
        end_node = -1
        while head < len(q):
            u = q[head]
            head += 1
            seen += 1
            cu = dist[u] + node_duration[u]
            if cu > best:
                best = cu
                end_node = u
            for v in succ[u]:
                if cu > dist[v]:
                    dist[v] = cu
                    if details:
                        pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != nops:
            return (inf, None, None, None) if details else inf
        return (best, pred, end_node, node_pos) if details else best

    def gt(rule=0, rnd=None, weights=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        seqs = [[] for _ in range(num_machines)]
        scheduled = 0

        while scheduled < nops:
            avail = []
            best_ect = inf
            best_m = 0
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(machines[j]):
                    continue
                m = machines[j][k]
                p = durations[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                avail.append((j, k, m, p, est, ect))
                if ect < best_ect:
                    best_ect = ect
                    best_m = m

            conflict = [a for a in avail if a[2] == best_m and a[4] < best_ect]

            def key(a):
                j, k, m, p, est, ect = a
                rem = remaining_work[j][k]
                tail = remaining_work[j][k + 1]
                left = len(machines[j]) - k
                if rule == 0:
                    return (p, -rem, est, j)
                if rule == 1:
                    return (-p, -rem, est, j)
                if rule == 2:
                    return (-rem, p, est, j)
                if rule == 3:
                    return (rem, p, est, j)
                if rule == 4:
                    return (ect + tail, -rem, p, j)
                if rule == 5:
                    return (est - rem, p, j)
                if rule == 6:
                    return (job_ready[j] + rem, p, j)
                if rule == 7:
                    return (-tail, p, est, j)
                score = (
                    weights[0] * p + weights[1] * rem + weights[2] * tail +
                    weights[3] * est + weights[4] * ect + weights[5] * job_ready[j] +
                    weights[6] * machine_ready[m] + weights[7] * left
                )
                return (score + rnd.random() * 1e-7, j)

            j, k, m, p, est, ect = min(conflict, key=key)
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            scheduled += 1

        return seqs

    def critical_swaps(pred, end_node, node_pos):
        path = []
        n = end_node
        while n != -1:
            path.append(n)
            n = pred[n]
        path.reverse()
        moves = []
        seen = set()
        block = []
        last = -1
        for n in path:
            m = node_machine[n]
            if m == last:
                block.append(n)
            else:
                if len(block) > 1:
                    for a, b in zip(block, block[1:]):
                        p = node_pos[a]
                        if p >= 0 and node_pos[b] == p + 1 and (node_machine[a], p) not in seen:
                            seen.add((node_machine[a], p))
                            moves.append((node_machine[a], p))
                block = [n]
                last = m
        if len(block) > 1:
            for a, b in zip(block, block[1:]):
                p = node_pos[a]
                if p >= 0 and node_pos[b] == p + 1 and (node_machine[a], p) not in seen:
                    seen.add((node_machine[a], p))
                    moves.append((node_machine[a], p))
        return moves

    def local_search(seq, val, lim):
        rnd = random.Random(1000003 + int(val))
        cur = copy_seqs(seq)
        curv = val
        best = copy_seqs(cur)
        bestv = curv
        tabu = {}
        it = 0
        stale = 0

        while time.perf_counter() < lim and stale < 140 and bestv > 930:
            it += 1
            ev = evaluate(cur, True)
            if ev[0] == inf:
                break
            moves = critical_swaps(ev[1], ev[2], ev[3])
            if not moves:
                break
            extra = []
            for m, p in moves:
                if p > 0:
                    extra.append((m, p - 1))
                if p + 2 < len(cur[m]):
                    extra.append((m, p + 1))
            moves = moves + extra
            rnd.shuffle(moves)

            bm = None
            bv = inf
            for m, p in moves:
                if p < 0 or p + 1 >= len(cur[m]):
                    continue
                a, b = cur[m][p], cur[m][p + 1]
                cand = copy_seqs(cur)
                cand[m][p], cand[m][p + 1] = cand[m][p + 1], cand[m][p]
                cv = evaluate(cand)
                if cv < inf and (cv < bestv or it >= tabu.get((m, b, a), -1)):
                    if cv < bv:
                        bv = cv
                        bm = (m, p, a, b)
                if time.perf_counter() >= lim:
                    break

            if bm is None:
                break
            m, p, a, b = bm
            cur[m][p], cur[m][p + 1] = cur[m][p + 1], cur[m][p]
            curv = bv
            tabu[(m, a, b)] = it + 6 + rnd.randrange(12)
            if curv < bestv:
                bestv = curv
                best = copy_seqs(cur)
                stale = 0
            else:
                stale += 1

        return best, bestv

    def try_cp_sat(hint_seq, hint_val, target=None, max_time=3.0):
        if time.perf_counter() > deadline - 0.25:
            return None, inf
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None, inf

        try:
            model = cp_model.CpModel()
            horizon = int(target) if target is not None else sum(sum(d) for d in durations)
            starts = {}
            ends = {}
            by_machine = [[] for _ in range(num_machines)]

            for j in range(num_jobs):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                    starts[(j, k)] = s
                    ends[(j, k)] = e
                    by_machine[m].append(model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k)))

            for j in range(num_jobs):
                for k in range(len(machines[j]) - 1):
                    model.Add(starts[(j, k + 1)] >= ends[(j, k)])

            for m in range(num_machines):
                model.AddNoOverlap(by_machine[m])

            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, [ends[(j, len(machines[j]) - 1)] for j in range(num_jobs)])

            if target is not None:
                model.Add(makespan <= int(target))
            else:
                if hint_val < inf:
                    model.Add(makespan <= int(hint_val) - 1)
                model.Minimize(makespan)

            if hint_seq is not None:
                ev = evaluate(hint_seq, True)
                if ev[0] < inf:
                    dist = [0] * nops
                    succ = [[] for _ in range(nops)]
                    indeg = [0] * nops
                    for j in range(num_jobs):
                        for k in range(len(machines[j]) - 1):
                            u = offsets[j] + k
                            v = u + 1
                            succ[u].append(v)
                            indeg[v] += 1
                    for m in range(num_machines):
                        counts = [0] * num_jobs
                        prev = -1
                        for jj in hint_seq[m]:
                            c = counts[jj]
                            counts[jj] += 1
                            kk = job_machine_indices[jj][m][c]
                            n = offsets[jj] + kk
                            if prev >= 0:
                                succ[prev].append(n)
                                indeg[n] += 1
                            prev = n
                    q = [i for i in range(nops) if indeg[i] == 0]
                    h = 0
                    while h < len(q):
                        u = q[h]
                        h += 1
                        cu = dist[u] + node_duration[u]
                        for v in succ[u]:
                            if cu > dist[v]:
                                dist[v] = cu
                            indeg[v] -= 1
                            if indeg[v] == 0:
                                q.append(v)
                    for n in range(nops):
                        j = node_job[n]
                        k = node_op[n]
                        st = min(int(dist[n]), horizon)
                        model.AddHint(starts[(j, k)], st)
                        model.AddHint(ends[(j, k)], min(st + node_duration[n], horizon))

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.15, min(max_time, deadline - time.perf_counter() - 0.10))
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 917
            solver.parameters.cp_model_presolve = True
            solver.parameters.linearization_level = 2
            solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH

            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None, inf

            seqs = [[] for _ in range(num_machines)]
            for m in range(num_machines):
                ops = []
                for j in range(num_jobs):
                    for k in range(len(machines[j])):
                        if machines[j][k] == m:
                            ops.append((solver.Value(starts[(j, k)]), solver.Value(ends[(j, k)]), j, k))
                ops.sort()
                seqs[m] = [j for _, _, j, _ in ops]
            return seqs, evaluate(seqs)
        except Exception:
            return None, inf

    best_seq = None
    best_val = inf
    candidates = []

    for r in range(8):
        s = gt(r)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)

    rnd = random.Random(246813579)
    weights0 = [
        (1.0, -1.0, -0.2, 0.15, 0.4, 0.0, 0.0, -0.1),
        (-1.0, -1.6, -0.4, 0.2, 0.2, 0.0, 0.0, -0.3),
        (0.3, -2.0, -0.6, 0.3, 0.1, 0.0, 0.0, -0.4),
        (1.2, -1.4, -0.9, 0.1, 0.3, 0.1, 0.0, -0.2),
        (-0.8, -2.4, -0.7, 0.4, 0.0, 0.0, 0.0, -0.6),
    ]
    for w in weights0:
        s = gt(99, rnd, list(w))
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)

    while time.perf_counter() < deadline - 3.9 and len(candidates) < 180:
        w = [rnd.uniform(-2.8, 2.8) for _ in range(8)]
        w[1] -= rnd.random() * 2.6
        w[2] -= rnd.random() * 1.3
        w[7] -= rnd.random() * 0.8
        s = gt(99, rnd, w)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)

    candidates.sort(key=lambda z: z[0])
    selected = []
    seen = set()
    for v, s in candidates:
        key = tuple(tuple(x) for x in s)
        if key not in seen:
            seen.add(key)
            selected.append((v, s))
        if len(selected) >= 18:
            break

    for v, s in selected[:10]:
        if time.perf_counter() > deadline - 3.25 or best_val <= 930:
            break
        ls, lv = local_search(s, v, min(deadline - 3.25, time.perf_counter() + 0.22))
        if lv < best_val:
            best_val = lv
            best_seq = copy_seqs(ls)

    if best_val > 930:
        cp_seq, cp_val = try_cp_sat(best_seq, best_val, target=930, max_time=max(0.2, deadline - time.perf_counter() - 0.15))
        if cp_seq is not None and cp_val < best_val:
            best_seq = copy_seqs(cp_seq)
            best_val = cp_val

    if best_val > 930 and time.perf_counter() < deadline - 0.35:
        cp_seq, cp_val = try_cp_sat(best_seq, best_val, target=None, max_time=max(0.2, deadline - time.perf_counter() - 0.12))
        if cp_seq is not None and cp_val < best_val:
            best_seq = copy_seqs(cp_seq)
            best_val = cp_val

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)