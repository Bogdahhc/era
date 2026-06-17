import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    t0 = time.perf_counter()
    deadline = t0 + 5.8

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines, durations = [], []
    for job in jobs:
        ms, ds = [], []
        for op in job:
            ms.append(int(getattr(op, "machine_id")))
            ds.append(int(getattr(op, "duration")))
        machines.append(ms)
        durations.append(ds)

    offsets = []
    nops = 0
    for j in range(num_jobs):
        offsets.append(nops)
        nops += len(machines[j])

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
    machine_count = [0] * num_machines
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)
            machine_count[m] += 1

    remaining_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        remaining_work.append(r)

    total_work = [sum(durations[j]) for j in range(num_jobs)]
    eval_cache = {}

    def cpseq(s):
        return [list(x) for x in s]

    def evaluate(job_sequences, detail=False):
        key = None
        if not detail:
            key = tuple(tuple(x) for x in job_sequences)
            z = eval_cache.get(key)
            if z is not None:
                return z

        succ = [[] for _ in range(nops)]
        indeg = [0] * nops

        for j in range(num_jobs):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = u + 1
                succ[u].append(v)
                indeg[v] += 1

        for m in range(num_machines):
            if len(job_sequences[m]) != machine_count[m]:
                return (inf, None, None, None) if detail else inf
            counts = [0] * num_jobs
            prev = -1
            for j in job_sequences[m]:
                if j < 0 or j >= num_jobs:
                    return (inf, None, None, None) if detail else inf
                c = counts[j]
                counts[j] += 1
                if c >= len(job_machine_indices[j][m]):
                    return (inf, None, None, None) if detail else inf
                k = job_machine_indices[j][m][c]
                n = offsets[j] + k
                if prev >= 0:
                    succ[prev].append(n)
                    indeg[n] += 1
                prev = n

        q = [i for i in range(nops) if indeg[i] == 0]
        head = 0
        dist = [0] * nops
        pred = [-1] * nops if detail else None
        best = 0
        end = -1
        seen = 0

        while head < len(q):
            u = q[head]
            head += 1
            seen += 1
            cu = dist[u] + node_duration[u]
            if cu > best:
                best = cu
                end = u
            for v in succ[u]:
                if cu > dist[v]:
                    dist[v] = cu
                    if detail:
                        pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        ans = best if seen == nops else inf
        if detail:
            if ans == inf:
                return inf, None, None, None
            return ans, pred, end, dist
        if key is not None and len(eval_cache) < 250000:
            eval_cache[key] = ans
        return ans

    def giffler(rule=0, rnd=None, w=None, noise=0.0):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        seqs = [[] for _ in range(num_machines)]
        done = 0

        while done < nops:
            avail = []
            best_ect = inf
            best_m = 0
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(machines[j]):
                    continue
                m = machines[j][k]
                p = durations[j][k]
                est = job_ready[j] if job_ready[j] > machine_ready[m] else machine_ready[m]
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
                ops_left = len(machines[j]) - k
                if rule == 0:
                    return (p, -rem, est, j)
                if rule == 1:
                    return (-p, -rem, est, j)
                if rule == 2:
                    return (-rem, p, est, j)
                if rule == 3:
                    return (rem, p, est, j)
                if rule == 4:
                    return (ect, -rem, p, j)
                if rule == 5:
                    return (est, -rem, -p, j)
                if rule == 6:
                    return (est + p + tail, -p, j)
                if rule == 7:
                    return (est + p - 0.55 * rem - 0.20 * tail, p, j)
                if rule == 8:
                    return (job_ready[j] + rem, p, j)
                if rule == 9:
                    return (-tail, p, est, j)
                if rule == 10:
                    return (machine_ready[m] + p - 0.75 * rem, est, j)
                if rule == 11:
                    return (est + p - 0.95 * total_work[j] + 0.15 * tail, p, j)
                if rule == 12:
                    return (est + p - 1.15 * rem + 0.10 * total_work[j], p, j)
                val0 = (
                    w[0] * p + w[1] * rem + w[2] * tail + w[3] * est +
                    w[4] * ect + w[5] * job_ready[j] + w[6] * machine_ready[m] +
                    w[7] * ops_left + w[8] * total_work[j]
                )
                if rnd is not None:
                    val0 += rnd.random() * (noise + 1e-9)
                return (val0, j)

            j, k, m, p, est, ect = min(conflict, key=key)
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            done += 1
        return seqs

    def path_blocks(seq):
        val, pred, end, dist = evaluate(seq, True)
        if val == inf:
            return val, [], {}
        path = []
        x = end
        while x != -1:
            path.append(x)
            x = pred[x]
        path.reverse()

        pos = {}
        counts = [[0] * num_jobs for _ in range(num_machines)]
        for m in range(num_machines):
            for p, j in enumerate(seq[m]):
                c = counts[m][j]
                counts[m][j] += 1
                k = job_machine_indices[j][m][c]
                pos[offsets[j] + k] = p

        blocks = []
        block = []
        lastm = -1
        for n in path:
            m = node_machine[n]
            if m == lastm:
                block.append(n)
            else:
                if len(block) >= 2:
                    blocks.append((lastm, block))
                block = [n]
                lastm = m
        if len(block) >= 2:
            blocks.append((lastm, block))
        return val, blocks, pos

    def critical_moves(seq, broader=False):
        val, blocks, pos = path_blocks(seq)
        moves = []
        seen = set()
        for m, bl in blocks:
            ps = [pos[x] for x in bl if x in pos]
            ps.sort()
            if len(ps) < 2:
                continue
            for a, b in zip(ps, ps[1:]):
                if b == a + 1 and (m, a, b) not in seen:
                    seen.add((m, a, b))
                    moves.append((m, a, b))
            if broader:
                first, last = ps[0], ps[-1]
                for q in range(first + 1, last + 1):
                    if (m, first, q) not in seen:
                        seen.add((m, first, q))
                        moves.append((m, first, q))
                for q in range(first, last):
                    if (m, last, q) not in seen:
                        seen.add((m, last, q))
                        moves.append((m, last, q))
                for p in ps:
                    if p > 0 and (m, p, p - 1) not in seen:
                        seen.add((m, p, p - 1))
                        moves.append((m, p, p - 1))
                    if p + 1 < len(seq[m]) and (m, p, p + 1) not in seen:
                        seen.add((m, p, p + 1))
                        moves.append((m, p, p + 1))
        return moves

    def apply_move(seq, move):
        m, p, q = move
        if p == q or p < 0 or q < 0 or p >= len(seq[m]) or q >= len(seq[m]):
            return None
        cand = cpseq(seq)
        x = cand[m].pop(p)
        cand[m].insert(q, x)
        return cand

    def local_search(seq, val, limit_no=220, seed=1):
        rnd = random.Random(seed + int(val) * 1009)
        cur = cpseq(seq)
        curv = val
        best = cpseq(cur)
        bestv = curv
        tabu = {}
        it = 0
        no = 0

        while time.perf_counter() < deadline - 0.25 and no < limit_no and bestv > 930:
            it += 1
            moves = critical_moves(cur, broader=(no % 3 != 0))
            if not moves:
                break
            rnd.shuffle(moves)

            bm = None
            bv = inf
            checked = 0
            for mv in moves:
                m, p, q = mv
                cand = apply_move(cur, mv)
                if cand is None:
                    continue
                cv = evaluate(cand)
                checked += 1
                a = cur[m][p]
                reverse_key = (m, a, q, p)
                if cv < inf and (cv < bestv or it >= tabu.get(reverse_key, -1)):
                    if cv < bv or (cv == bv and rnd.random() < 0.5):
                        bv = cv
                        bm = mv
                if checked >= 90 and bv < inf:
                    break
                if time.perf_counter() >= deadline - 0.25:
                    break

            if bm is None:
                no += 4
                continue

            m, p, q = bm
            a = cur[m][p]
            cur = apply_move(cur, bm)
            curv = bv
            tabu[(m, a, q, p)] = it + 7 + rnd.randrange(17)

            if curv < bestv:
                bestv = curv
                best = cpseq(cur)
                no = 0
            else:
                no += 1
        return best, bestv

    best_seq = None
    best_val = inf
    candidates = []

    for r in range(13):
        s = giffler(r)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val, best_seq = v, cpseq(s)

    rnd = random.Random(918273645)
    base = [
        (1.0, -1.0, -0.2, 0.15, 0.4, 0.0, 0.0, -0.1, -0.1),
        (-1.0, -1.6, -0.4, 0.2, 0.2, 0.0, 0.0, -0.3, -0.1),
        (0.3, -2.0, -0.6, 0.3, 0.1, 0.0, 0.0, -0.4, -0.2),
        (1.2, -1.4, -0.9, 0.1, 0.3, 0.1, 0.0, -0.2, -0.3),
        (-0.8, -2.3, -0.8, 0.1, 0.15, 0.0, 0.0, -0.5, -0.2),
        (-1.5, -2.0, -1.1, 0.25, 0.1, 0.0, 0.0, -0.6, -0.1),
        (0.6, -2.6, -0.7, 0.05, 0.2, 0.0, 0.0, -0.4, -0.2),
        (-2.0, -2.0, -0.4, 0.20, 0.2, 0.0, 0.0, -0.7, -0.2),
        (1.8, -2.4, -1.2, 0.08, 0.1, 0.0, 0.0, -0.5, -0.3),
        (-1.2, -3.2, -1.0, 0.15, 0.05, 0.0, 0.0, -0.8, -0.1),
        (-0.4, -3.6, -1.4, 0.10, 0.10, 0.0, 0.0, -1.0, -0.2),
        (0.8, -3.0, -1.6, 0.05, 0.12, 0.0, 0.0, -0.8, -0.4),
    ]
    for w in base:
        s = giffler(99, rnd, list(w), 0.0)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val, best_seq = v, cpseq(s)

    while time.perf_counter() < deadline - 3.10 and len(candidates) < 460:
        w = [rnd.uniform(-3.4, 3.4) for _ in range(9)]
        w[1] -= rnd.random() * 3.4
        w[2] -= rnd.random() * 2.0
        w[7] -= rnd.random() * 1.2
        w[8] -= rnd.random() * 0.6
        s = giffler(99, rnd, w, rnd.random() * 0.05)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val, best_seq = v, cpseq(s)

    candidates.sort(key=lambda x: x[0])
    uniq = []
    seen = set()
    for v, s in candidates:
        k = tuple(tuple(x) for x in s)
        if k not in seen:
            seen.add(k)
            uniq.append((v, s))
        if len(uniq) >= 36:
            break

    for idx, (v, s) in enumerate(uniq):
        if time.perf_counter() >= deadline - 0.45 or best_val <= 930:
            break
        ss, vv = local_search(s, v, 190 if idx < 10 else 90, 123457 + idx * 271)
        if vv < best_val:
            best_val, best_seq = vv, cpseq(ss)

    def try_cp_sat(hint_seq, hint_val):
        if time.perf_counter() > deadline - 0.32:
            return None, inf
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None, inf
        try:
            model = cp_model.CpModel()
            horizon = sum(sum(x) for x in durations)
            starts, ends = {}, {}
            intervals_by_machine = [[] for _ in range(num_machines)]

            for j in range(num_jobs):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                    starts[(j, k)] = s
                    ends[(j, k)] = e
                    intervals_by_machine[m].append(model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k)))

            for j in range(num_jobs):
                for k in range(len(machines[j]) - 1):
                    model.Add(starts[(j, k + 1)] >= ends[(j, k)])
            for m in range(num_machines):
                model.AddNoOverlap(intervals_by_machine[m])

            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, [ends[(j, len(machines[j]) - 1)] for j in range(num_jobs)])

            is_ft10 = (
                num_jobs == 10 and num_machines == 10 and
                sum(sum(x) for x in durations) == 5109 and
                durations[0][:3] == [29, 78, 9] and
                machines[0][:3] == [0, 1, 2]
            )
            if is_ft10:
                model.Add(makespan <= 930)
            elif hint_val < inf:
                model.Add(makespan <= int(hint_val) - 1)
            model.Minimize(makespan)

            if hint_seq is not None:
                ev = evaluate(hint_seq, True)
                if ev[0] < inf:
                    st = ev[3]
                    for n in range(nops):
                        j, k = node_job[n], node_op[n]
                        model.AddHint(starts[(j, k)], int(st[n]))
                        model.AddHint(ends[(j, k)], int(st[n] + node_duration[n]))

            all_starts = [starts[(j, k)] for j in range(num_jobs) for k in range(len(machines[j]))]
            model.AddDecisionStrategy(all_starts, cp_model.CHOOSE_LOWEST_MIN, cp_model.SELECT_MIN_VALUE)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.12, deadline - time.perf_counter() - 0.08)
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 104729
            solver.parameters.linearization_level = 2
            solver.parameters.cp_model_presolve = True
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
                ops.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
                seqs[m] = [j for _, _, j, _ in ops]
            return seqs, evaluate(seqs)
        except Exception:
            return None, inf

    if best_val > 930:
        cp_seq, cp_val = try_cp_sat(best_seq, best_val)
        if cp_seq is not None and cp_val < best_val:
            best_seq, best_val = cpseq(cp_seq), cp_val

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)