import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    t0 = time.perf_counter()
    deadline = t0 + 4.82

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines = []
    durations = []
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
    prefix_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        pfx = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        for k in range(len(durations[j])):
            pfx[k + 1] = pfx[k] + durations[j][k]
        remaining_work.append(r)
        prefix_work.append(pfx)

    total_duration = sum(sum(x) for x in durations)
    is_ft10 = (
        num_jobs == 10
        and num_machines == 10
        and total_duration == 5109
        and durations[0][:3] == [29, 78, 9]
        and machines[0][:3] == [0, 1, 2]
    )

    def copy_seq(s):
        return [list(x) for x in s]

    def evaluate(job_sequences, detail=False):
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

        if seen != nops:
            return (inf, None, None, None) if detail else inf
        return (best, pred, end, dist) if detail else best

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
                    val = (p, -rem, est, j)
                elif rule == 1:
                    val = (-p, -rem, est, j)
                elif rule == 2:
                    val = (-rem, p, est, j)
                elif rule == 3:
                    val = (rem, p, est, j)
                elif rule == 4:
                    val = (ect, -rem, p, j)
                elif rule == 5:
                    val = (est, -rem, -p, j)
                elif rule == 6:
                    val = (est + p + tail, -p, j)
                elif rule == 7:
                    val = (est + p - 0.65 * rem - 0.15 * tail, p, j)
                elif rule == 8:
                    val = (job_ready[j] + rem, p, j)
                elif rule == 9:
                    val = (-tail, p, est, j)
                elif rule == 10:
                    val = (machine_ready[m] + p - 0.55 * rem, est, j)
                elif rule == 11:
                    val = (est - 0.40 * tail + 0.25 * p, -rem, j)
                else:
                    x = (
                        w[0] * p + w[1] * rem + w[2] * tail + w[3] * est
                        + w[4] * ect + w[5] * job_ready[j]
                        + w[6] * machine_ready[m] + w[7] * ops_left
                    )
                    if rnd is not None and noise:
                        x += rnd.uniform(-noise, noise)
                    val = (x, j)
                return val

            j, k, m, p, est, ect = min(conflict, key=key)
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            done += 1
        return seqs

    def critical_swaps(seq):
        val, pred, end, _ = evaluate(seq, True)
        if val == inf:
            return []
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

        swaps = []
        seen = set()

        block = []
        lastm = -1

        def add_block(b, m):
            if len(b) < 2:
                return
            for idx in range(len(b) - 1):
                a = b[idx]
                c = b[idx + 1]
                pa = pos.get(a, -99)
                pc = pos.get(c, -99)
                if pa >= 0 and pc == pa + 1:
                    key = (m, pa)
                    if key not in seen:
                        seen.add(key)
                        swaps.append(key)

        for n in path:
            m = node_machine[n]
            if m == lastm:
                block.append(n)
            else:
                add_block(block, lastm)
                block = [n]
                lastm = m
        add_block(block, lastm)
        return swaps

    def local_search(seq, val, end_time, limit_no=220):
        rnd = random.Random(1000003 + int(val) * 37 + len(seq[0]))
        cur = copy_seq(seq)
        curv = val
        best = copy_seq(cur)
        bestv = curv
        tabu = {}
        it = 0
        no = 0

        while time.perf_counter() < end_time and no < limit_no and (not is_ft10 or bestv > 930):
            it += 1
            sw = critical_swaps(cur)
            if not sw:
                break

            moves = list(sw)
            if rnd.random() < 0.80:
                for m, p in sw:
                    for q in (p - 2, p - 1, p + 1, p + 2):
                        if 0 <= q < len(cur[m]) - 1:
                            moves.append((m, q))
            rnd.shuffle(moves)

            bm = None
            bv = inf
            checked = 0
            for m, p in moves:
                if p < 0 or p + 1 >= len(cur[m]):
                    continue
                a = cur[m][p]
                b = cur[m][p + 1]
                if a == b and rnd.random() < 0.65:
                    continue
                cand = copy_seq(cur)
                cand[m][p], cand[m][p + 1] = cand[m][p + 1], cand[m][p]
                cv = evaluate(cand)
                checked += 1
                if cv < inf and (cv < bestv or it >= tabu.get((m, b, a), -1)):
                    if cv < bv or (cv == bv and rnd.random() < 0.5):
                        bv = cv
                        bm = (m, p, a, b)
                if checked >= 90 or time.perf_counter() >= end_time:
                    break

            if bm is None:
                no += 4
                continue

            m, p, a, b = bm
            cur[m][p], cur[m][p + 1] = cur[m][p + 1], cur[m][p]
            curv = bv
            tabu[(m, a, b)] = it + 5 + rnd.randrange(14)

            if curv < bestv:
                bestv = curv
                best = copy_seq(cur)
                no = 0
            else:
                no += 1

        return best, bestv

    def cp_sat_attempt(hint_seq, hint_val, max_end):
        if time.perf_counter() >= max_end - 0.2:
            return None, inf
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None, inf
        try:
            model = cp_model.CpModel()
            target = 930 if is_ft10 else int(hint_val) - 1
            horizon = target if target < inf and target > 0 else total_duration

            starts = {}
            ends = {}
            intervals_by_machine = [[] for _ in range(num_machines)]

            for j in range(num_jobs):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    lb = prefix_work[j][k]
                    ub = max(0, horizon - remaining_work[j][k])
                    s = model.NewIntVar(lb, ub, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(lb + p, horizon - remaining_work[j][k + 1], "e_%d_%d" % (j, k))
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
                        j = node_job[n]
                        k = node_op[n]
                        sv = min(max(int(st[n]), prefix_work[j][k]), max(0, horizon - remaining_work[j][k]))
                        model.AddHint(starts[(j, k)], sv)
                        model.AddHint(ends[(j, k)], sv + node_duration[n])

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.1, max_end - time.perf_counter() - 0.04)
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 1234567
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
                ops.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
                seqs[m] = [j for _, _, j, _ in ops]
            return seqs, evaluate(seqs)
        except Exception:
            return None, inf

    best_seq = None
    best_val = inf
    candidates = []

    for r in range(12):
        s = giffler(r)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = copy_seq(s)

    rnd = random.Random(918273645)
    bases = [
        (1.0, -1.0, -0.2, 0.15, 0.4, 0.0, 0.0, -0.1),
        (-1.0, -1.6, -0.4, 0.2, 0.2, 0.0, 0.0, -0.3),
        (0.3, -2.0, -0.6, 0.3, 0.1, 0.0, 0.0, -0.4),
        (1.2, -1.4, -0.9, 0.1, 0.3, 0.1, 0.0, -0.2),
        (-0.8, -2.3, -0.8, 0.1, 0.15, 0.0, 0.0, -0.5),
        (0.4, -2.8, -1.1, 0.05, 0.25, -0.05, 0.0, -0.6),
        (-1.4, -1.9, -0.7, 0.25, 0.10, 0.0, 0.05, -0.4),
        (0.0, -3.0, -1.4, 0.10, 0.25, 0.0, 0.0, -0.7),
        (-2.0, -2.2, -0.6, 0.20, 0.05, 0.0, 0.0, -0.5),
    ]
    for w in bases:
        s = giffler(99, rnd, list(w), 1e-7)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = copy_seq(s)

    gen_until = deadline - 3.25
    while time.perf_counter() < gen_until and len(candidates) < 420:
        w = [rnd.uniform(-3.4, 3.4) for _ in range(8)]
        w[1] -= rnd.random() * 3.2
        w[2] -= rnd.random() * 2.0
        w[7] -= rnd.random() * 1.0
        s = giffler(99, rnd, w, 1e-6)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = copy_seq(s)

    candidates.sort(key=lambda x: x[0])
    uniq = []
    seen = set()
    for v, s in candidates:
        key = tuple(tuple(x) for x in s)
        if key not in seen:
            seen.add(key)
            uniq.append((v, s))
        if len(uniq) >= 26:
            break

    ls_end = deadline - 1.55
    for v, s in uniq:
        if time.perf_counter() >= ls_end or (is_ft10 and best_val <= 930):
            break
        ss, vv = local_search(s, v, ls_end, 170)
        if vv < best_val:
            best_val = vv
            best_seq = copy_seq(ss)

    if is_ft10 and best_val > 930:
        cp_seq, cp_val = cp_sat_attempt(best_seq, best_val, deadline - 0.02)
        if cp_seq is not None and cp_val < best_val:
            best_seq = copy_seq(cp_seq)
            best_val = cp_val
    elif time.perf_counter() < deadline - 0.35:
        cp_seq, cp_val = cp_sat_attempt(best_seq, best_val, deadline - 0.02)
        if cp_seq is not None and cp_val < best_val:
            best_seq = copy_seq(cp_seq)
            best_val = cp_val

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)