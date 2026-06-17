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
        mj, dj = [], []
        for op in job:
            mj.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            dj.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(mj)
        durations.append(dj)

    cnt = [len(x) for x in machines]
    total_ops = sum(cnt)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(cnt), m)
    INF = 10**12

    def nid(j, k):
        return j * width + k

    real = [nid(j, k) for j in range(n) for k in range(cnt[j])]

    op_on_m = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_on_m[j][ma] = k

    rem = []
    total_job = []
    for j in range(n):
        r = [0] * (cnt[j] + 1)
        for k in range(cnt[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)
        total_job.append(r[0])

    load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                load[ma] += durations[j][k]

    base_succ = [[] for _ in range(n * width)]
    base_ind = [0] * (n * width)
    for j in range(n):
        for k in range(cnt[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
            base_succ[a].append(b)
            base_ind[b] += 1

    def eval_seq(seq, info=False):
        ind = base_ind[:]
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
                k = op_on_m[j][ma]
                if k < 0:
                    return (INF, None, None, None) if info else INF
                u = nid(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    ind[u] += 1
                prev = u

        q = [u for u in real if ind[u] == 0]
        start = [0] * (n * width)
        pred = [-1] * (n * width)
        h = 0
        done = 0
        while h < len(q):
            u = q[h]
            h += 1
            done += 1
            j, k = divmod(u, width)
            f = start[u] + durations[j][k]
            for v in succ[u]:
                if f > start[v]:
                    start[v] = f
                    pred[v] = u
                ind[v] -= 1
                if ind[v] == 0:
                    q.append(v)
        if done != total_ops:
            return (INF, None, None, None) if info else INF

        best, end = 0, -1
        for j in range(n):
            for k in range(cnt[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best, end = c, u
        return (best, start, pred, end) if info else best

    rmachines = [list(reversed(x)) for x in machines]
    rdurations = [list(reversed(x)) for x in durations]
    rrem = []
    for j in range(n):
        r = [0] * (cnt[j] + 1)
        for k in range(cnt[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdurations[j][k]
        rrem.append(r)

    rules = [
        (0, -0.70, -0.35, 0.00, 0.00), (0, 1.80, -0.25, 0.00, 0.00),
        (-0.2, -1.20, -0.55, 0.00, 0.00), (0, -0.25, -0.35, 0.45, -0.20),
        (0, 0.00, -1.00, 0.00, 0.00), (0.3, 1.00, -0.18, 0.00, 0.00),
        (0.45, -1.00, -0.18, 0.00, 0.00), (0, 0.00, -0.22, 0.90, 0.00),
        (0, 1.00, -0.32, 0.00, 0.02), (0, -0.50, -0.30, 0.00, 0.03),
        (-0.1, 0.25, -0.42, 0.06, 0.00), (0, 0.00, -0.20, 0.00, -0.20),
        (-0.3, -0.80, -0.35, 0.00, 0.00), (0, 0.00, -0.18, -0.48, 0.00),
        (0, 1.40, -0.22, 0.00, -0.08), (0, -0.80, -0.18, 0.35, 0.00),
        (0.0, -0.25, -0.62, 0.80, 0.00), (0, 0.65, -0.12, 0.00, 0.04),
        (0, -0.15, 0.00, 0.00, -0.45), (0.0, -0.35, -0.68, 0.00, 0.05),
        (0, -0.65, -0.40, 0.32, -0.12), (0, -0.55, -0.50, 0.25, 0.00),
        (0, 0.00, -0.85, 0.38, 0.08), (0, -0.20, -0.72, 0.18, -0.02),
        (0.15, -0.95, -0.58, 0.00, 0.00), (0, 0.00, -0.55, 0.15, 0.12),
        (0.18, -1.40, -0.72, 0.12, 0.00), (-0.18, 1.60, -0.48, 0.00, 0.00),
        (0.35, -0.55, -0.95, 0.18, 0.03), (-0.35, -0.20, -0.80, 0.52, -0.05),
        (0.10, 0.35, -1.20, 0.30, 0.00), (0.0, -1.05, -0.30, 0.55, 0.00),
    ]

    def priority(rule, j, k, ma, jr, mr, ds, rw):
        est = jr[j] if jr[j] > mr[ma] else mr[ma]
        p = ds[j][k]
        ect = est + p
        a, b, c, d, e = rule
        return ect + a * est + b * p + c * rw[j][k] + d * rw[j][k + 1] + e * load[ma]

    def construct(rule, rev=False, rng=None, noise=0.0, randp=0.0):
        ms = rmachines if rev else machines
        ds = rdurations if rev else durations
        rw = rrem if rev else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            bc, target = INF, 0
            for j in range(n):
                k = nxt[j]
                if k < cnt[j]:
                    ma = ms[j][k]
                    c = (jr[j] if jr[j] > mr[ma] else mr[ma]) + ds[j][k]
                    if c < bc:
                        bc, target = c, ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < cnt[j] and ms[j][k] == target and jr[j] < bc:
                    v = priority(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < cnt[j]:
                        ma = ms[j][k]
                        v = priority(rule, j, k, ma, jr, mr, ds, rw)
                        if rng is not None and noise:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randp:
                j = cand[rng.randrange(min(6, len(cand)))][1]
            else:
                j = cand[0][1]
            k = nxt[j]
            ma = ms[j][k]
            f = (jr[j] if jr[j] > mr[ma] else mr[ma]) + ds[j][k]
            seq[ma].append(j)
            jr[j] = f
            mr[ma] = f
            nxt[j] += 1
            done += 1
        if rev:
            seq = [list(reversed(x)) for x in seq]
        return seq

    def cp(seq):
        return [x[:] for x in seq]

    begin = time.perf_counter()
    deadline = begin + 5.75
    rng = random.Random(8402157)
    best_seq, best_val = None, INF
    pool = []

    def consider(seq):
        nonlocal best_seq, best_val, pool
        v = eval_seq(seq)
        if v < INF:
            if v < best_val:
                best_val, best_seq = v, cp(seq)
            pool.append((v, cp(seq)))
            if len(pool) > 24:
                pool.sort(key=lambda x: x[0])
                pool = pool[:24]
        return v

    for rev in (False, True):
        for r in rules:
            consider(construct(r, rev))

    def sorted_seq(kind):
        seq = []
        for ma in range(m):
            if kind == 0:
                arr = sorted(range(n), key=lambda j: (op_on_m[j][ma], -rem[j][op_on_m[j][ma]], durations[j][op_on_m[j][ma]]))
            elif kind == 1:
                arr = sorted(range(n), key=lambda j: (op_on_m[j][ma], -durations[j][op_on_m[j][ma]], j))
            elif kind == 2:
                arr = sorted(range(n), key=lambda j: (-total_job[j], op_on_m[j][ma], j))
            elif kind == 3:
                arr = sorted(range(n), key=lambda j: (total_job[j], op_on_m[j][ma], j))
            elif kind == 4:
                arr = sorted(range(n), key=lambda j: (-durations[j][op_on_m[j][ma]], op_on_m[j][ma], j))
            else:
                arr = sorted(range(n), key=lambda j: (rem[j][op_on_m[j][ma] + 1], op_on_m[j][ma], j))
            seq.append(arr)
        return seq

    for k in range(6):
        consider(sorted_seq(k))

    while time.perf_counter() < begin + 1.15:
        r = rules[rng.randrange(len(rules))]
        consider(construct(r, rng.random() < 0.5, rng, rng.choice((2, 5, 9, 15, 28, 45, 75, 120)), rng.choice((0.04, 0.08, 0.13, 0.20, 0.28))))

    def critical(seq):
        v, st, pr, end = eval_seq(seq, True)
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pr[u]
        return v, s

    def moves(seq, broad=False):
        v, crit = critical(seq)
        out = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = [i for i, j in enumerate(arr) if nid(j, op_on_m[j][ma]) in crit]
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
            for bl in blocks:
                cand = [('s', ma, bl[0], bl[0] + 1), ('s', ma, bl[-1] - 1, bl[-1])]
                if len(bl) > 2:
                    cand += [('s', ma, bl[0], bl[-1]), ('i', ma, bl[0], bl[-1] + 1), ('i', ma, bl[-1], bl[0])]
                if broad:
                    for i in range(len(bl) - 1):
                        cand.append(('s', ma, bl[i], bl[i + 1]))
                    lim = bl if len(bl) <= 8 else [bl[0], bl[1], bl[2], bl[3], bl[-4], bl[-3], bl[-2], bl[-1]]
                    for x in lim:
                        for d in (-8, -6, -4, -3, -2, 2, 3, 4, 6, 8):
                            y = x + d
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(('i', ma, x, y))
                for mv in cand:
                    typ, ma2, a, b = mv
                    if typ == 's':
                        ok = 0 <= a < n and 0 <= b < n and a != b
                    else:
                        ok = 0 <= a < n and 0 <= b <= n and a != b and b != a + 1
                    if ok and mv not in seen:
                        seen.add(mv)
                        out.append(mv)
        rng.shuffle(out)
        return out

    def apply(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == 's':
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == 's':
            arr[a], arr[b] = arr[b], arr[a]
        else:
            p = b - 1 if b > a else b
            x = arr.pop(p)
            arr.insert(a, x)

    def descent(seq, val, stop):
        while time.perf_counter() < stop:
            bm, bv = None, val
            for mv in moves(seq, True):
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < bv:
                    bm, bv = mv, v
            if bm is None:
                for ma in range(m):
                    if time.perf_counter() >= stop:
                        break
                    for a in range(n - 1):
                        mv = ('s', ma, a, a + 1)
                        apply(seq, mv)
                        v = eval_seq(seq)
                        undo(seq, mv)
                        if v < bv:
                            bm, bv = mv, v
                    if bm is not None:
                        break
            if bm is None:
                break
            apply(seq, bm)
            val = bv
        return seq, val

    if best_seq is None:
        best_seq = construct(rules[0])
        best_val = eval_seq(best_seq)

    pool.sort(key=lambda x: x[0])
    t = begin + 2.15
    for v, s in pool[:9]:
        if time.perf_counter() >= t:
            break
        s, v = descent(s, v, min(t, time.perf_counter() + 0.20))
        if v < best_val:
            best_val, best_seq = v, cp(s)

    cur, curv = cp(best_seq), best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        ml = moves(cur, it % 4 != 0)
        if not ml:
            cur, curv = cp(best_seq), best_val
            ml = moves(cur, True)
            if not ml:
                break
        chosen, cv, ckey = None, INF, None
        for mv in ml:
            if time.perf_counter() >= deadline:
                break
            typ, ma, a, b = mv
            arr = cur[ma]
            key = (ma, arr[a], arr[b]) if typ == 's' else (ma, arr[a], a, b)
            rkey = (ma, arr[b], arr[a]) if typ == 's' else key
            apply(cur, mv)
            v = eval_seq(cur)
            undo(cur, mv)
            if v < INF and ((tabu.get(key, 0) <= it and tabu.get(rkey, 0) <= it) or v < best_val):
                if v < cv or (v == cv and rng.random() < 0.15):
                    chosen, cv, ckey = mv, v, key
        if chosen is None:
            cur, curv = cp(best_seq), best_val
            stagn += 1
            continue
        apply(cur, chosen)
        curv = cv
        tabu[ckey] = it + 7 + rng.randrange(13)
        if curv < best_val:
            best_val, best_seq = curv, cp(cur)
            stagn = 0
            cur, curv = descent(cur, curv, min(deadline, time.perf_counter() + 0.09))
            if curv < best_val:
                best_val, best_seq = curv, cp(cur)
        else:
            stagn += 1
        if it % 43 == 0 or stagn > 58:
            cur, curv = cp(best_seq), best_val
            stagn = 0
            for _ in range(1 + rng.randrange(5)):
                ml = moves(cur, True)
                if not ml:
                    break
                mv = ml[rng.randrange(len(ml))]
                apply(cur, mv)
                if eval_seq(cur) >= INF:
                    undo(cur, mv)
            curv = eval_seq(cur)

    return Schedule.from_job_sequences(instance, best_seq)