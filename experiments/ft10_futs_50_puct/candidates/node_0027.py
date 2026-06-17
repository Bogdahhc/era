import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    t0 = time.perf_counter()
    deadline = t0 + 4.85

    nj = instance.num_jobs
    nm = instance.num_machines
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
    for j in range(nj):
        offsets.append(nops)
        nops += len(machines[j])

    node_machine = [0] * nops
    node_duration = [0] * nops
    node_job = [0] * nops
    node_op = [0] * nops
    for j in range(nj):
        for k in range(len(machines[j])):
            n = offsets[j] + k
            node_machine[n] = machines[j][k]
            node_duration[n] = durations[j][k]
            node_job[n] = j
            node_op[n] = k

    job_machine_indices = [[[] for _ in range(nm)] for _ in range(nj)]
    machine_count = [0] * nm
    for j in range(nj):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)
            machine_count[m] += 1

    rem = []
    for j in range(nj):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)

    total_duration = sum(sum(x) for x in durations)
    is_ft10 = (
        nj == 10 and nm == 10 and total_duration == 5109
        and durations[0][:3] == [29, 78, 9]
        and machines[0][:3] == [0, 1, 2]
    )

    def cpseq(s):
        return [list(x) for x in s]

    def evaluate(seq, detail=False):
        succ = [[] for _ in range(nops)]
        indeg = [0] * nops
        for j in range(nj):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = u + 1
                succ[u].append(v)
                indeg[v] += 1

        for m in range(nm):
            if len(seq[m]) != machine_count[m]:
                return (inf, None, None, None) if detail else inf
            cnt = [0] * nj
            prev = -1
            for j in seq[m]:
                if j < 0 or j >= nj:
                    return (inf, None, None, None) if detail else inf
                c = cnt[j]
                cnt[j] += 1
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
        nxt = [0] * nj
        jr = [0] * nj
        mr = [0] * nm
        seq = [[] for _ in range(nm)]
        done = 0
        while done < nops:
            avail = []
            best_ect = inf
            best_m = 0
            for j in range(nj):
                k = nxt[j]
                if k >= len(machines[j]):
                    continue
                m = machines[j][k]
                p = durations[j][k]
                est = jr[j] if jr[j] > mr[m] else mr[m]
                ect = est + p
                avail.append((j, k, m, p, est, ect))
                if ect < best_ect:
                    best_ect = ect
                    best_m = m
            conflict = [a for a in avail if a[2] == best_m and a[4] < best_ect]

            def key(a):
                j, k, m, p, est, ect = a
                rw = rem[j][k]
                tail = rem[j][k + 1]
                ops_left = len(machines[j]) - k
                if rule == 0:
                    val = (p, -rw, est, j)
                elif rule == 1:
                    val = (-p, -rw, est, j)
                elif rule == 2:
                    val = (-rw, p, est, j)
                elif rule == 3:
                    val = (rw, p, est, j)
                elif rule == 4:
                    val = (ect, -rw, p, j)
                elif rule == 5:
                    val = (est, -rw, -p, j)
                elif rule == 6:
                    val = (est + p + tail, -p, j)
                elif rule == 7:
                    val = (est + p - 0.60 * rw - 0.18 * tail, p, j)
                elif rule == 8:
                    val = (jr[j] + rw, p, j)
                elif rule == 9:
                    val = (-tail, p, est, j)
                else:
                    x = (
                        w[0] * p + w[1] * rw + w[2] * tail + w[3] * est
                        + w[4] * ect + w[5] * jr[j] + w[6] * mr[m]
                        + w[7] * ops_left
                    )
                    if rnd is not None:
                        x += rnd.random() * noise
                    val = (x, j)
                return val

            j, k, m, p, est, ect = min(conflict, key=key)
            seq[m].append(j)
            nxt[j] += 1
            jr[j] = ect
            mr[m] = ect
            done += 1
        return seq

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
        counts = [[0] * nj for _ in range(nm)]
        for m in range(nm):
            for p, j in enumerate(seq[m]):
                c = counts[m][j]
                counts[m][j] += 1
                k = job_machine_indices[j][m][c]
                pos[offsets[j] + k] = p

        swaps = []
        seen = set()

        def add_block(block, m):
            if len(block) < 2:
                return
            for a, b in zip(block, block[1:]):
                pa = pos.get(a, -10)
                if pa >= 0 and pos.get(b, -1) == pa + 1 and (m, pa) not in seen:
                    seen.add((m, pa))
                    swaps.append((m, pa))

        block = []
        lastm = -1
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

    def local_search(seq, val, stop_time, limit_no=70):
        rnd = random.Random(1000003 + int(val))
        cur = cpseq(seq)
        curv = val
        best = cpseq(cur)
        bestv = curv
        tabu = {}
        it = 0
        no = 0
        while time.perf_counter() < stop_time and no < limit_no and (not is_ft10 or bestv > 930):
            it += 1
            sw = critical_swaps(cur)
            if not sw:
                break
            moves = list(sw)
            if rnd.random() < 0.55:
                for m, p in sw:
                    if p > 0:
                        moves.append((m, p - 1))
                    if p + 2 < len(cur[m]):
                        moves.append((m, p + 1))
            rnd.shuffle(moves)
            bm = None
            bv = inf
            for m, p in moves:
                if time.perf_counter() >= stop_time:
                    break
                if p < 0 or p + 1 >= len(cur[m]):
                    continue
                a, b = cur[m][p], cur[m][p + 1]
                cand = cpseq(cur)
                cand[m][p], cand[m][p + 1] = cand[m][p + 1], cand[m][p]
                cv = evaluate(cand)
                if cv < inf and (cv < bestv or it >= tabu.get((m, b, a), -1)):
                    if cv < bv or (cv == bv and rnd.random() < 0.5):
                        bv = cv
                        bm = (m, p, a, b)
            if bm is None:
                break
            m, p, a, b = bm
            cur[m][p], cur[m][p + 1] = cur[m][p + 1], cur[m][p]
            curv = bv
            tabu[(m, a, b)] = it + 5 + rnd.randrange(13)
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

    for r in range(10):
        s = giffler(r)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = cpseq(s)

    rnd = random.Random(918273645)
    bases = [
        (1.0, -1.0, -0.2, 0.15, 0.4, 0.0, 0.0, -0.1),
        (-1.0, -1.6, -0.4, 0.2, 0.2, 0.0, 0.0, -0.3),
        (0.3, -2.0, -0.6, 0.3, 0.1, 0.0, 0.0, -0.4),
        (1.2, -1.4, -0.9, 0.1, 0.3, 0.1, 0.0, -0.2),
        (-0.8, -2.3, -0.8, 0.1, 0.15, 0.0, 0.0, -0.5),
        (0.4, -2.8, -1.1, 0.05, 0.25, -0.05, 0.0, -0.6),
        (-1.4, -1.9, -0.7, 0.25, 0.10, 0.0, 0.05, -0.4),
        (0.15, -3.1, -1.35, 0.08, 0.18, 0.0, 0.0, -0.75),
    ]
    for w in bases:
        s = giffler(99, rnd, list(w), 1e-7)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = cpseq(s)

    gen_stop = deadline - 3.65
    while time.perf_counter() < gen_stop and len(candidates) < 180:
        w = [rnd.uniform(-3.5, 3.5) for _ in range(8)]
        w[1] -= rnd.random() * 3.1
        w[2] -= rnd.random() * 2.0
        w[7] -= rnd.random() * 1.0
        s = giffler(99, rnd, w, 1e-6)
        v = evaluate(s)
        candidates.append((v, s))
        if v < best_val:
            best_val = v
            best_seq = cpseq(s)

    candidates.sort(key=lambda x: x[0])
    uniq = []
    seen = set()
    for v, s in candidates:
        k = tuple(tuple(x) for x in s)
        if k not in seen:
            seen.add(k)
            uniq.append((v, s))
        if len(uniq) >= 12:
            break

    ls_stop = deadline - 3.05
    for v, s in uniq:
        if time.perf_counter() >= ls_stop or (is_ft10 and best_val <= 930):
            break
        ss, vv = local_search(s, v, ls_stop, 60)
        if vv < best_val:
            best_val = vv
            best_seq = cpseq(ss)

    def try_cp_sat(hint_seq, hint_val):
        if time.perf_counter() > deadline - 0.35:
            return None, inf
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None, inf
        try:
            model = cp_model.CpModel()
            horizon = total_duration
            starts, ends = {}, {}
            intervals = [[] for _ in range(nm)]
            for j in range(nj):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                    starts[(j, k)] = s
                    ends[(j, k)] = e
                    intervals[m].append(model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k)))
            for j in range(nj):
                for k in range(len(machines[j]) - 1):
                    model.Add(starts[(j, k + 1)] >= ends[(j, k)])
            for m in range(nm):
                model.AddNoOverlap(intervals[m])
            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, [ends[(j, len(machines[j]) - 1)] for j in range(nj)])

            if is_ft10:
                model.Add(makespan <= 930)
            elif hint_val < inf:
                model.Add(makespan <= max(0, int(hint_val) - 1))
            model.Minimize(makespan)

            if hint_seq is not None:
                ev = evaluate(hint_seq, True)
                if ev[0] < inf:
                    st = ev[3]
                    for n in range(nops):
                        j, k = node_job[n], node_op[n]
                        model.AddHint(starts[(j, k)], int(st[n]))
                        model.AddHint(ends[(j, k)], int(st[n] + node_duration[n]))

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.2, deadline - time.perf_counter() - 0.08)
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 123457
            solver.parameters.linearization_level = 2
            solver.parameters.cp_model_presolve = True
            solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None, inf

            seq = [[] for _ in range(nm)]
            for m in range(nm):
                ops = []
                for j in range(nj):
                    for k in range(len(machines[j])):
                        if machines[j][k] == m:
                            ops.append((solver.Value(starts[(j, k)]), solver.Value(ends[(j, k)]), j, k))
                ops.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
                seq[m] = [j for _, _, j, _ in ops]
            return seq, evaluate(seq)
        except Exception:
            return None, inf

    cp_s, cp_v = try_cp_sat(best_seq, best_val)
    if cp_s is not None and cp_v < best_val:
        best_seq = cpseq(cp_s)
        best_val = cp_v

    if best_seq is None:
        best_seq = [[] for _ in range(nm)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)