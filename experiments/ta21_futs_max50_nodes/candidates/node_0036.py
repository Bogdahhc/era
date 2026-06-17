from job_shop_lib import Schedule
import time
import random

def solve(instance):
    n = int(instance.num_jobs)
    m = int(instance.num_machines)
    jobs = list(instance.jobs)
    machines = []
    durations = []
    for job in jobs:
        ms, ds = [], []
        for op in job:
            ms.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            ds.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(ms)
        durations.append(ds)

    if n == 0 or m == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(max(0, m))])

    op_count = [len(x) for x in machines]
    total_ops = sum(op_count)
    width = max(max(op_count), m)
    INF = 10 ** 12

    def nid(j, k):
        return j * width + k

    op_on_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_on_machine[j][ma] = k

    rem = []
    tw = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)
        tw.append(r[0])

    load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                load[ma] += durations[j][k]

    real_nodes = [nid(j, k) for j in range(n) for k in range(op_count[j])]
    base_succ = [[] for _ in range(n * width)]
    base_indeg = [0] * (n * width)
    for j in range(n):
        for k in range(op_count[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
            base_succ[a].append(b)
            base_indeg[b] += 1

    def eval_seq(seq, info=False):
        indeg = base_indeg[:]
        succ = [x[:] for x in base_succ]
        for ma in range(m):
            if len(seq[ma]) != n:
                return (INF, None, None, None) if info else INF
            seen = [False] * n
            prev = -1
            for j in seq[ma]:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if info else INF
                seen[j] = True
                k = op_on_machine[j][ma]
                if k < 0:
                    return (INF, None, None, None) if info else INF
                u = nid(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    indeg[u] += 1
                prev = u
        q = [u for u in real_nodes if indeg[u] == 0]
        start = [0] * (n * width)
        pred = [-1] * (n * width)
        head = cnt = 0
        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            j, k = divmod(u, width)
            f = start[u] + durations[j][k]
            for v in succ[u]:
                if f > start[v]:
                    start[v] = f
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if cnt != total_ops:
            return (INF, None, None, None) if info else INF
        best = 0
        end = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end = u
        return (best, start, pred, end) if info else best

    rev_machines = [list(reversed(x)) for x in machines]
    rev_durations = [list(reversed(x)) for x in durations]
    rev_rem = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + rev_durations[j][k]
        rev_rem.append(r)

    def priority(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        if rule == 0: return ect - 0.75 * rr - 0.65 * p
        if rule == 1: return est - 0.70 * rr - 0.30 * p + 0.20 * tail
        if rule == 2: return ect - 0.50 * rr + 0.70 * tail - 0.90 * p
        if rule == 3: return jr[j] + 0.35 * mr[ma] - 0.62 * rr - 0.45 * p
        if rule == 4: return ect - 0.92 * rr + 0.45 * tail - 0.55 * p
        if rule == 5: return est + 0.55 * p - 0.65 * rr + 0.10 * tw[j]
        if rule == 6: return ect - 0.35 * tw[j] - 0.30 * rr - 0.25 * p
        if rule == 7: return mr[ma] + 0.35 * jr[j] - 0.55 * rr + 0.20 * tail
        if rule == 8: return ect - 0.25 * rr + 1.15 * p
        if rule == 9: return est - 0.80 * rr - 0.85 * p + 0.25 * tail
        if rule == 10: return ect - 0.60 * rr + 0.04 * load[ma] - 0.40 * p
        if rule == 11: return jr[j] + 0.75 * mr[ma] - 0.55 * rr - 0.20 * p
        if rule == 12: return ect - 0.82 * rr + 0.33 * tail - 0.33 * p
        if rule == 13: return est + 1.10 * p - 0.45 * rr
        if rule == 14: return ect - 0.42 * rr - 1.05 * p + 0.05 * load[ma]
        return ect - 0.4 * rr

    def gt(rule=0, reverse=False, rng=None, noise=0.0):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            best_c = INF
            target = 0
            for j in range(n):
                k = nxt[j]
                if k < len(ms[j]):
                    ma = ms[j][k]
                    c = max(jr[j], mr[ma]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < len(ms[j]) and ms[j][k] == target and jr[j] < best_c:
                    val = priority(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        val += rng.uniform(-noise, noise)
                    cand.append((val, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        val = priority(rule, j, k, ma, jr, mr, ds, rw)
                        if rng is not None and noise:
                            val += rng.uniform(-noise, noise)
                        cand.append((val, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < 0.12:
                chosen = cand[rng.randrange(min(4, len(cand)))][1]
            else:
                chosen = cand[0][1]
            k = nxt[chosen]
            ma = ms[chosen][k]
            ft = max(jr[chosen], mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = ft
            mr[ma] = ft
            nxt[chosen] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    begin = time.perf_counter()
    rng = random.Random(921017)
    best_seq = None
    best_val = INF

    def keep(seq):
        nonlocal best_seq, best_val
        v = eval_seq(seq)
        if v < best_val:
            best_val = v
            best_seq = [x[:] for x in seq]
        return v

    for rev in (False, True):
        for r in range(15):
            keep(gt(r, rev))

    while time.perf_counter() < begin + 0.45:
        keep(gt(rng.randrange(15), rng=rng, reverse=rng.random() < 0.5, noise=rng.choice((2, 5, 9, 15, 25, 40, 65, 100))))

    def critical(seq):
        v, st, pr, end = eval_seq(seq, True)
        if st is None:
            return v, set()
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pr[u]
        return v, s

    def moves(seq, wide=False):
        v, cset = critical(seq)
        out = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = [i for i, j in enumerate(arr) if nid(j, op_on_machine[j][ma]) in cset]
            if len(pos) < 2:
                continue
            block = [pos[0]]
            blocks = []
            for p in pos[1:]:
                if p == block[-1] + 1:
                    block.append(p)
                else:
                    if len(block) > 1:
                        blocks.append(block)
                    block = [p]
            if len(block) > 1:
                blocks.append(block)
            for b in blocks:
                cand = [(ma, b[0], b[0] + 1), (ma, b[-1] - 1, b[-1])]
                if wide:
                    for i in range(len(b) - 1):
                        cand.append((ma, b[i], b[i + 1]))
                    if len(b) > 2:
                        cand.append((ma, b[0], b[-1]))
                for mv in cand:
                    if mv not in seen and 0 <= mv[1] < n and 0 <= mv[2] < n and mv[1] != mv[2]:
                        seen.add(mv)
                        out.append(mv)
        rng.shuffle(out)
        return out

    def swap(seq, mv):
        ma, a, b = mv
        seq[ma][a], seq[ma][b] = seq[ma][b], seq[ma][a]

    stop_ls = begin + 1.05
    cur = [x[:] for x in best_seq]
    curv = best_val
    while time.perf_counter() < stop_ls:
        bm = None
        bv = curv
        for mv in moves(cur, True):
            if time.perf_counter() >= stop_ls:
                break
            swap(cur, mv)
            v = eval_seq(cur)
            swap(cur, mv)
            if v < bv:
                bv = v
                bm = mv
        if bm is None:
            break
        swap(cur, bm)
        curv = bv
        keep(cur)

    cp_result = None
    try:
        from ortools.sat.python import cp_model
        model = cp_model.CpModel()
        horizon = sum(sum(x) for x in durations)
        starts = {}
        ends = {}
        intervals_by_machine = [[] for _ in range(m)]
        for j in range(n):
            for k in range(op_count[j]):
                p = durations[j][k]
                ma = machines[j][k]
                s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                itv = model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k))
                starts[(j, k)] = s
                ends[(j, k)] = e
                intervals_by_machine[ma].append(itv)
        for j in range(n):
            for k in range(op_count[j] - 1):
                model.Add(starts[(j, k + 1)] >= ends[(j, k)])
        for ma in range(m):
            model.AddNoOverlap(intervals_by_machine[ma])
        cmax = model.NewIntVar(0, horizon, "cmax")
        model.AddMaxEquality(cmax, [ends[(j, op_count[j] - 1)] for j in range(n)])
        model.Minimize(cmax)

        hv, hstarts, _, _ = eval_seq(best_seq, True)
        if hstarts is not None:
            for j in range(n):
                for k in range(op_count[j]):
                    model.AddHint(starts[(j, k)], int(hstarts[nid(j, k)]))
            model.AddHint(cmax, int(hv))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(1.0, 7.35 - (time.perf_counter() - begin))
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 921017
        solver.parameters.cp_model_presolve = True
        status = solver.Solve(model)
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            seq = [[] for _ in range(m)]
            for ma in range(m):
                ops = []
                for j in range(n):
                    k = op_on_machine[j][ma]
                    if k >= 0:
                        ops.append((solver.Value(starts[(j, k)]), solver.Value(ends[(j, k)]), j))
                ops.sort()
                seq[ma] = [j for _, __, j in ops]
            if eval_seq(seq) < best_val:
                best_seq = seq
                best_val = eval_seq(seq)
                cp_result = seq
    except Exception:
        cp_result = None

    if cp_result is None and time.perf_counter() < begin + 7.6:
        cur = [x[:] for x in best_seq]
        curv = best_val
        tabu = {}
        it = 0
        deadline = begin + 7.65
        while time.perf_counter() < deadline:
            it += 1
            mvlist = moves(cur, it % 4 != 0)
            if not mvlist:
                cur = [x[:] for x in best_seq]
                curv = best_val
                continue
            chosen = None
            chosen_v = INF
            chosen_key = None
            for mv in mvlist:
                if time.perf_counter() >= deadline:
                    break
                ma, a, b = mv
                key = (ma, cur[ma][a], cur[ma][b])
                swap(cur, mv)
                v = eval_seq(cur)
                swap(cur, mv)
                if v < INF and (tabu.get(key, 0) <= it or v < best_val):
                    if v < chosen_v or (v == chosen_v and rng.random() < 0.2):
                        chosen_v = v
                        chosen = mv
                        chosen_key = key
            if chosen is None:
                cur = [x[:] for x in best_seq]
                curv = best_val
                continue
            swap(cur, chosen)
            curv = chosen_v
            tabu[chosen_key] = it + 7 + rng.randrange(15)
            if curv < best_val:
                best_val = curv
                best_seq = [x[:] for x in cur]
            if it % 53 == 0:
                cur = [x[:] for x in best_seq]
                curv = best_val

    return Schedule.from_job_sequences(instance, best_seq)