from job_shop_lib import Schedule
import time
import random

def solve(instance):
    n = int(instance.num_jobs)
    m = int(instance.num_machines)
    if n <= 0 or m <= 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(max(0, m))])

    mach = []
    dur = []
    for job in instance.jobs:
        ma, du = [], []
        for op in job:
            ma.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            du.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        mach.append(ma)
        dur.append(du)

    lens = [len(x) for x in mach]
    total = sum(lens)
    if total == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(lens), m)
    nodes = n * width
    INF = 10 ** 12

    def nid(j, k):
        return j * width + k

    real_nodes = [nid(j, k) for j in range(n) for k in range(lens[j])]

    op_on_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(mach[j]):
            if 0 <= ma < m:
                op_on_machine[j][ma] = k

    rem = []
    work = []
    for j in range(n):
        r = [0] * (lens[j] + 1)
        for k in range(lens[j] - 1, -1, -1):
            r[k] = r[k + 1] + dur[j][k]
        rem.append(r)
        work.append(r[0])

    load = [0] * m
    for j in range(n):
        for k, ma in enumerate(mach[j]):
            if 0 <= ma < m:
                load[ma] += dur[j][k]

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
        st = [0] * nodes
        pred = [-1] * nodes
        h = 0
        cnt = 0
        while h < len(q):
            u = q[h]
            h += 1
            cnt += 1
            j, k = divmod(u, width)
            f = st[u] + dur[j][k]
            for v in succ[u]:
                if f > st[v]:
                    st[v] = f
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if cnt != total:
            return (INF, None, None, None) if info else INF

        best = 0
        end = -1
        for j in range(n):
            for k in range(lens[j]):
                u = nid(j, k)
                c = st[u] + dur[j][k]
                if c > best:
                    best = c
                    end = u
        return (best, st, pred, end) if info else best

    rmach = [list(reversed(x)) for x in mach]
    rdur = [list(reversed(x)) for x in dur]
    rrem = []
    for j in range(n):
        r = [0] * (lens[j] + 1)
        for k in range(lens[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdur[j][k]
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
        (0.92, -1.10, -0.92, 0.72, 0.00, 0.03),
        (0.72, -0.35, -1.35, 0.00, 0.00, 0.05),
        (1.12, -0.92, -0.40, 0.42, -0.04, 0.00),
        (0.55, -1.05, -0.62, 0.55, 0.00, 0.00),
        (1.05, -1.20, -0.82, 0.82, 0.00, 0.02),
        (0.88, -0.38, -1.45, 0.12, 0.00, 0.08),
        (0.62, -1.12, -0.48, 0.35, 0.00, 0.00),
        (1.18, -0.72, -0.72, 0.25, -0.08, 0.00),
    ]

    def priority(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        a, b, c, d, e, f = weights[rule % len(weights)]
        r = rule % 7
        if r == 1:
            base = est
        elif r == 2:
            base = jr[j] + 0.45 * mr[ma]
        elif r == 3:
            base = mr[ma] + 0.25 * jr[j]
        elif r == 4:
            base = ect + 0.20 * abs(jr[j] - mr[ma])
        elif r == 5:
            base = 0.65 * ect + 0.35 * est
        elif r == 6:
            base = est + 0.35 * p
        else:
            base = ect
        return a * base + b * rr + c * p + d * tail + e * work[j] + f * load[ma]

    def giffler(rule, reverse=False, rng=None, noise=0.0, randpick=0.0):
        ms = rmach if reverse else mach
        ds = rdur if reverse else dur
        rw = rrem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total:
            bc = INF
            target = 0
            for j in range(n):
                k = nxt[j]
                if k < lens[j]:
                    ma = ms[j][k]
                    c = max(jr[j], mr[ma]) + ds[j][k]
                    if c < bc:
                        bc = c
                        target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < lens[j] and ms[j][k] == target and jr[j] < bc:
                    v = priority(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < lens[j]:
                        ma = ms[j][k]
                        v = priority(rule, j, k, ma, jr, mr, ds, rw)
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
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def cp(seq):
        return [x[:] for x in seq]

    rng = random.Random(72123019)
    t0 = time.perf_counter()
    deadline = t0 + 8.9
    best_seq = None
    best_val = INF
    pool = []

    def consider(seq):
        nonlocal best_seq, best_val, pool
        v = eval_seq(seq)
        if v < INF:
            if v < best_val:
                best_val = v
                best_seq = cp(seq)
            pool.append((v, cp(seq)))
            if len(pool) > 70:
                pool.sort(key=lambda x: x[0])
                pool = pool[:70]
        return v

    for rev in (False, True):
        for r in range(75):
            consider(giffler(r, rev))

    while time.perf_counter() < t0 + 1.85:
        consider(giffler(rng.randrange(120), rng.random() < 0.5, rng,
                         rng.choice((1, 2, 4, 8, 13, 21, 34, 55, 89, 144, 233)),
                         rng.choice((0.01, 0.02, 0.04, 0.07, 0.11, 0.17, 0.25, 0.34))))

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
    while len(pool) >= 2 and time.perf_counter() < t0 + 2.25:
        i = rng.randrange(min(18, len(pool)))
        j = rng.randrange(min(45, len(pool)))
        if i != j:
            consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

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
        v, crit = critical(seq)
        if not crit:
            return []
        res = []
        seen = set()
        for ma in range(m):
            pos = []
            arr = seq[ma]
            for i, j in enumerate(arr):
                k = op_on_machine[j][ma]
                if k >= 0 and nid(j, k) in crit:
                    pos.append(i)
            if len(pos) < 2:
                continue
            blocks = []
            b = [pos[0]]
            for p in pos[1:]:
                if p == b[-1] + 1:
                    b.append(p)
                else:
                    if len(b) > 1:
                        blocks.append(b)
                    b = [p]
            if len(b) > 1:
                blocks.append(b)
            for b in blocks:
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-1] - 1, b[-1]),
                        ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if len(b) >= 3:
                    cand += [("s", ma, b[0], b[-1]), ("i", ma, b[1], b[-1] + 1), ("i", ma, b[-2], b[0])]
                if wide:
                    lim = b if len(b) <= 10 else [b[0], b[1], b[2], b[3], b[-4], b[-3], b[-2], b[-1]]
                    targets = set()
                    for x in lim:
                        targets.add(x)
                        targets.add(x + 1)
                    for x in lim:
                        for y in targets:
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                    for ii in range(len(lim)):
                        for jj in range(ii + 1, len(lim)):
                            cand.append(("s", ma, lim[ii], lim[jj]))
                for mv in cand:
                    typ, mm, a, z = mv
                    if typ == "s":
                        ok = 0 <= a < n and 0 <= z < n and a != z
                    else:
                        ok = 0 <= a < n and 0 <= z <= n and a != z and z != a + 1
                    if ok and mv not in seen:
                        seen.add(mv)
                        res.append(mv)
        rng.shuffle(res)
        return res

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

    def descent(seq, val, stop, wide):
        while time.perf_counter() < stop:
            ml = moves(seq, wide)
            if not ml:
                break
            bm = None
            bv = val
            for mv in ml:
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

    best_seq, best_val = descent(best_seq, best_val, min(deadline, t0 + 3.2), True)
    consider(best_seq)

    cur = cp(best_seq)
    cur_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        ml = moves(cur, wide=(it % 5 == 0 or stagn > 20))
        if not ml:
            cur = cp(best_seq)
            cur_val = best_val
            stagn += 1
            continue
        lim = 220 if stagn < 25 else 330
        if len(ml) > lim:
            ml = ml[:lim]
        chosen = None
        chosen_val = INF
        chosen_key = None
        for mv in ml:
            if time.perf_counter() >= deadline:
                break
            typ, ma, a, b = mv
            arr = cur[ma]
            if typ == "s":
                key = (ma, arr[a], arr[b])
                rkey = (ma, arr[b], arr[a])
            else:
                key = (ma, arr[a], a, b)
                rkey = key
            apply(cur, mv)
            v = eval_seq(cur)
            undo(cur, mv)
            if v < INF and (v < best_val or (tabu.get(key, 0) <= it and tabu.get(rkey, 0) <= it)):
                if v < chosen_val or (v == chosen_val and rng.random() < 0.12):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key
        if chosen is None:
            if pool and rng.random() < 0.35:
                cur_val, s = pool[rng.randrange(min(len(pool), 30))]
                cur = cp(s)
            else:
                cur = cp(best_seq)
                cur_val = best_val
            stagn += 1
            continue
        apply(cur, chosen)
        cur_val = chosen_val
        tabu[chosen_key] = it + 8 + rng.randrange(21)
        if cur_val < best_val:
            best_val = cur_val
            best_seq = cp(cur)
            consider(best_seq)
            stagn = 0
            cur, cur_val = descent(cur, cur_val, min(deadline, time.perf_counter() + 0.12), False)
            if cur_val < best_val:
                best_val = cur_val
                best_seq = cp(cur)
                consider(best_seq)
        else:
            stagn += 1
        if it % 47 == 0 or stagn > 75:
            if pool and rng.random() < 0.45:
                cur_val, s = pool[rng.randrange(min(len(pool), 25))]
                cur = cp(s)
            else:
                cur = cp(best_seq)
                cur_val = best_val
            for _ in range(1 + rng.randrange(5)):
                ml2 = moves(cur, True)
                if not ml2:
                    break
                mv = ml2[rng.randrange(len(ml2))]
                apply(cur, mv)
                if eval_seq(cur) >= INF:
                    undo(cur, mv)
            cur_val = eval_seq(cur)
            if cur_val >= INF:
                cur = cp(best_seq)
                cur_val = best_val
            stagn = 0

    return Schedule.from_job_sequences(instance, best_seq)