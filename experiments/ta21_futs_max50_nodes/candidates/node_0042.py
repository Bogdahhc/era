from job_shop_lib import Schedule
import time
import random

def solve(instance):
    n = int(instance.num_jobs)
    m = int(instance.num_machines)
    if n <= 0 or m <= 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(max(0, m))])

    machines, durations = [], []
    for job in instance.jobs:
        ma, du = [], []
        for op in job:
            ma.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            du.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(ma)
        durations.append(du)

    lens = [len(x) for x in machines]
    total_ops = sum(lens)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(lens), m)
    nodes = n * width
    INF = 10 ** 12

    def nid(j, k):
        return j * width + k

    real_nodes = [nid(j, k) for j in range(n) for k in range(lens[j])]

    op_on_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_on_machine[j][ma] = k

    rem = []
    total_work = []
    for j in range(n):
        r = [0] * (lens[j] + 1)
        for k in range(lens[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)
        total_work.append(r[0])

    machine_load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                machine_load[ma] += durations[j][k]

    base_succ = [[] for _ in range(nodes)]
    base_indeg = [0] * nodes
    for j in range(n):
        for k in range(lens[j] - 1):
            a = nid(j, k)
            b = nid(j, k + 1)
            base_succ[a].append(b)
            base_indeg[b] += 1

    def eval_seq(seq, info=False):
        indeg = base_indeg[:]
        succ = [x[:] for x in base_succ]
        for ma in range(m):
            arr = seq[ma]
            if len(arr) != n:
                return (INF, None, None, None) if info else INF
            seen = [False] * n
            prev = -1
            for j in arr:
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
        start = [0] * nodes
        pred = [-1] * nodes
        h = 0
        cnt = 0
        while h < len(q):
            u = q[h]
            h += 1
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
            for k in range(lens[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end = u
        return (best, start, pred, end) if info else best

    rmachines = [list(reversed(x)) for x in machines]
    rdurations = [list(reversed(x)) for x in durations]
    rrem = []
    for j in range(n):
        r = [0] * (lens[j] + 1)
        for k in range(lens[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdurations[j][k]
        rrem.append(r)

    weights = [
        (1.00, -0.45, -0.70, 0.00, 0.00, 0.00),
        (0.80, -0.80, -0.30, 0.25, 0.00, 0.00),
        (1.00, -0.95, -0.55, 0.55, 0.00, 0.00),
        (0.60, -0.70, -0.75, 0.20, 0.00, 0.10),
        (1.00, -0.35, -1.15, 0.00, -0.25, 0.00),
        (0.85, -0.65, -0.90, 0.35, 0.00, 0.04),
        (0.75, -0.90, -0.35, 0.20, 0.10, 0.00),
        (1.00, -0.58, -0.85, 0.00, 0.00, 0.06),
        (0.60, -0.82, -0.50, 0.35, 0.00, 0.00),
        (1.00, -1.02, -0.78, 0.62, 0.00, 0.00),
        (0.90, -0.72, -0.65, 0.18, 0.00, -0.02),
        (1.10, -0.50, -0.25, 0.00, -0.35, 0.00),
        (0.45, -0.55, -0.40, 0.00, 0.00, 0.12),
        (1.00, -0.78, -0.92, 0.40, 0.00, 0.00),
        (0.70, -0.92, -0.38, 0.22, 0.04, 0.00),
        (1.00, -0.88, -0.55, 0.35, 0.00, 0.00),
        (0.50, -0.62, -0.20, 0.00, 0.00, 0.00),
        (1.00, -0.42, -1.20, 0.00, 0.00, 0.08),
        (0.80, -0.52, -0.55, 0.75, 0.00, 0.00),
        (1.00, -0.68, -0.90, 0.30, 0.00, 0.00),
        (0.65, -0.80, -0.45, 0.00, 0.00, 0.25),
        (1.00, -0.60, -0.20, 0.15, -0.10, 0.00),
        (0.92, -1.10, -0.92, 0.72, 0.00, 0.03),
        (0.72, -0.35, -1.35, 0.00, 0.00, 0.05),
        (1.12, -0.92, -0.40, 0.42, -0.04, 0.00),
        (0.55, -1.05, -0.62, 0.55, 0.00, 0.00),
        (0.95, -1.22, -0.75, 0.80, 0.00, 0.02),
        (0.70, -0.48, -1.42, 0.08, 0.00, 0.08),
        (1.25, -0.72, -0.55, 0.20, -0.08, 0.00),
        (0.52, -1.28, -0.35, 0.72, 0.00, 0.00),
    ]

    def keyval(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        a, b, c, d, e, f = weights[rule % len(weights)]
        rmod = rule % 8
        if rmod == 1:
            base = est
        elif rmod == 2:
            base = jr[j] + 0.45 * mr[ma]
        elif rmod == 3:
            base = mr[ma] + 0.25 * jr[j]
        elif rmod == 4:
            base = ect + 0.20 * abs(jr[j] - mr[ma])
        elif rmod == 5:
            base = 0.65 * ect + 0.35 * est
        elif rmod == 6:
            base = ect + 0.18 * machine_load[ma]
        elif rmod == 7:
            base = 0.72 * est + 0.28 * jr[j]
        else:
            base = ect
        return a * base + b * rr + c * p + d * tail + e * total_work[j] + f * machine_load[ma]

    def giffler(rule, reverse=False, rng=None, noise=0.0, randpick=0.0):
        ms = rmachines if reverse else machines
        ds = rdurations if reverse else durations
        rw = rrem if reverse else rem
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
                if k < lens[j]:
                    ma = ms[j][k]
                    c = max(jr[j], mr[ma]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < lens[j] and ms[j][k] == target and jr[j] < best_c:
                    v = keyval(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < lens[j]:
                        ma = ms[j][k]
                        v = keyval(rule, j, k, ma, jr, mr, ds, rw)
                        if rng is not None and noise:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randpick:
                chosen = cand[rng.randrange(min(7, len(cand)))][1]
            else:
                chosen = cand[0][1]
            k = nxt[chosen]
            ma = ms[chosen][k]
            f = max(jr[chosen], mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = f
            mr[ma] = f
            nxt[chosen] += 1
            done += 1
        return [list(reversed(x)) for x in seq] if reverse else seq

    def simple_dispatch(rule, reverse=False):
        ms = rmachines if reverse else machines
        ds = rdurations if reverse else durations
        rw = rrem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        for _ in range(total_ops):
            best = None
            chosen = 0
            for j in range(n):
                k = nxt[j]
                if k >= lens[j]:
                    continue
                ma = ms[j][k]
                p = ds[j][k]
                est = max(jr[j], mr[ma])
                ect = est + p
                rr = rw[j][k]
                tail = rw[j][k + 1]
                r = rule % 14
                if r == 0:
                    key = (ect, -rr, -p, j)
                elif r == 1:
                    key = (est, -rr, -p, j)
                elif r == 2:
                    key = (-rr, ect, -p, j)
                elif r == 3:
                    key = (ect - 0.80 * rr + 0.35 * tail - 0.35 * p, j)
                elif r == 4:
                    key = (jr[j] + 0.4 * mr[ma] - 0.55 * rr - 0.4 * p, j)
                elif r == 5:
                    key = (machine_load[ma] * 0.04 + ect - 0.45 * rr - 0.5 * p, j)
                elif r == 6:
                    key = (ect - 0.95 * rr + 0.55 * tail - 0.75 * p, j)
                elif r == 7:
                    key = (est - 0.72 * rr - 0.65 * p, ect, j)
                elif r == 8:
                    key = (ect - 1.05 * rr + 0.70 * tail - 0.85 * p + 0.02 * machine_load[ma], j)
                elif r == 9:
                    key = (0.55 * ect + 0.45 * est - 0.58 * rr - 1.05 * p, j)
                elif r == 10:
                    key = (ect - 1.20 * rr + 0.82 * tail - 0.50 * p, j)
                elif r == 11:
                    key = (est - 0.35 * rr - 1.25 * p + 0.08 * machine_load[ma], j)
                elif r == 12:
                    key = (jr[j] - 0.90 * rr - 0.25 * p + 0.55 * tail, ect, j)
                else:
                    key = (mr[ma] + 0.25 * jr[j] - 0.62 * rr - 0.95 * p, j)
                if best is None or key < best:
                    best = key
                    chosen = j
            k = nxt[chosen]
            ma = ms[chosen][k]
            f = max(jr[chosen], mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = f
            mr[ma] = f
            nxt[chosen] += 1
        return [list(reversed(x)) for x in seq] if reverse else seq

    def cpseq(seq):
        return [x[:] for x in seq]

    rng = random.Random(31415927)
    t0 = time.perf_counter()
    deadline = t0 + 8.90
    best_seq = None
    best_val = INF
    pool = []

    def consider(seq):
        nonlocal best_seq, best_val, pool
        v = eval_seq(seq)
        if v < INF:
            if v < best_val:
                best_val = v
                best_seq = cpseq(seq)
            pool.append((v, cpseq(seq)))
            if len(pool) > 70:
                pool.sort(key=lambda x: x[0])
                pool = pool[:70]
        return v

    for rev in (False, True):
        for r in range(72):
            consider(giffler(r, rev))
        for r in range(14):
            consider(simple_dispatch(r, rev))

    while time.perf_counter() < t0 + 1.80:
        consider(giffler(rng.randrange(120), rng.random() < 0.5, rng,
                         rng.choice((1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233)),
                         rng.choice((0.012, 0.025, 0.045, 0.075, 0.12, 0.18, 0.27, 0.38))))

    def crossover(a, b):
        c = [[] for _ in range(m)]
        for ma in range(m):
            x, y = (a[ma], b[ma]) if rng.random() < 0.5 else (b[ma], a[ma])
            l = rng.randrange(n)
            r = rng.randrange(l + 1, n + 1)
            arr = [-1] * n
            used = [False] * n
            for i in range(l, r):
                arr[i] = x[i]
                used[x[i]] = True
            p = 0
            for z in y:
                if not used[z]:
                    while arr[p] != -1:
                        p += 1
                    arr[p] = z
                    used[z] = True
            c[ma] = arr
        return c

    pool.sort(key=lambda x: x[0])
    while len(pool) >= 2 and time.perf_counter() < t0 + 2.35:
        i = rng.randrange(min(18, len(pool)))
        j = rng.randrange(min(45, len(pool)))
        if i != j:
            consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    def crit_path(seq):
        v, st, pr, end = eval_seq(seq, True)
        if st is None:
            return v, set()
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pr[u]
        return v, s

    def moves_from_critical(seq, wide=False):
        v, crit = crit_path(seq)
        if not crit:
            return []
        moves = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = []
            for i, j in enumerate(arr):
                k = op_on_machine[j][ma]
                if k >= 0 and nid(j, k) in crit:
                    pos.append(i)
            if len(pos) < 2:
                continue
            blocks = []
            block = [pos[0]]
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
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-1] - 1, b[-1]),
                        ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if len(b) >= 3:
                    cand.append(("s", ma, b[0], b[-1]))
                    cand.append(("i", ma, b[1], b[-1] + 1))
                    cand.append(("i", ma, b[-2], b[0]))
                    cand.append(("s", ma, b[0] + 1, b[-1]))
                    cand.append(("s", ma, b[0], b[-1] - 1))
                if wide:
                    lim = b if len(b) <= 10 else [b[0], b[1], b[2], b[3], b[4], b[-5], b[-4], b[-3], b[-2], b[-1]]
                    targets = set()
                    for x in lim:
                        targets.add(x)
                        targets.add(x + 1)
                    for x in lim:
                        for y in targets:
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                    for ii in range(len(lim) - 1):
                        cand.append(("s", ma, lim[ii], lim[ii + 1]))
                    if len(b) <= 10:
                        for ii in range(len(b)):
                            for jj in range(ii + 2, len(b)):
                                cand.append(("s", ma, b[ii], b[jj]))
                for mv in cand:
                    typ, mm, a, z = mv
                    if typ == "s":
                        ok = 0 <= a < n and 0 <= z < n and a != z
                    else:
                        ok = 0 <= a < n and 0 <= z <= n and a != z and z != a + 1
                    if ok and mv not in seen:
                        seen.add(mv)
                        moves.append(mv)
        rng.shuffle(moves)
        return moves

    def apply(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == "s":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == "s":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            p = b - 1 if b > a else b
            x = arr.pop(p)
            arr.insert(a, x)

    def descent(seq, val, stop, wide=True):
        while time.perf_counter() < stop:
            mvlist = moves_from_critical(seq, wide)
            if not mvlist:
                break
            bm = None
            bv = val
            for mv in mvlist:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < bv:
                    bv = v
                    bm = mv
            if bm is None:
                break
            apply(seq, bm)
            val = bv
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, min(deadline, t0 + 3.30), True)

    current = cpseq(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        mvlist = moves_from_critical(current, wide=(it % 5 == 0 or stagn > 20))
        if not mvlist:
            current = cpseq(best_seq)
            current_val = best_val
            stagn += 1
            continue

        chosen = None
        chosen_val = INF
        chosen_key = None
        sample_limit = 210 if stagn < 30 else 310
        if len(mvlist) > sample_limit:
            mvlist = mvlist[:sample_limit]

        for mv in mvlist:
            if time.perf_counter() >= deadline:
                break
            typ, ma, a, b = mv
            arr = current[ma]
            if typ == "s":
                key = (ma, arr[a], arr[b])
                rkey = (ma, arr[b], arr[a])
            else:
                key = (ma, arr[a], a, b)
                rkey = key
            apply(current, mv)
            v = eval_seq(current)
            undo(current, mv)
            if v >= INF:
                continue
            if v < best_val or (tabu.get(key, 0) <= it and tabu.get(rkey, 0) <= it):
                if v < chosen_val or (v == chosen_val and rng.random() < 0.10):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key

        if chosen is None:
            current = cpseq(best_seq)
            current_val = best_val
            stagn += 1
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 6 + rng.randrange(22)

        if current_val < best_val:
            best_val = current_val
            best_seq = cpseq(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(current, current_val,
                                               min(deadline, time.perf_counter() + 0.13),
                                               False)
                if current_val < best_val:
                    best_val = current_val
                    best_seq = cpseq(current)
        else:
            stagn += 1

        if it % 39 == 0 or stagn > 68:
            current = cpseq(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(1 + rng.randrange(6)):
                ml = moves_from_critical(current, True)
                if not ml:
                    break
                mv = ml[rng.randrange(len(ml))]
                apply(current, mv)
                if eval_seq(current) >= INF:
                    undo(current, mv)
            current_val = eval_seq(current)
            if current_val >= INF:
                current = cpseq(best_seq)
                current_val = best_val

    return Schedule.from_job_sequences(instance, best_seq)