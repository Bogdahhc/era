from job_shop_lib import Schedule
import time, random

def solve(instance):
    n = int(instance.num_jobs)
    m = int(instance.num_machines)
    jobs = instance.jobs
    mach, dur = [], []
    for job in jobs:
        ma, du = [], []
        for op in job:
            ma.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            du.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        mach.append(ma)
        dur.append(du)
    L = [len(x) for x in mach]
    tot = sum(L)
    if tot == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])
    W = max(L) if L else m
    INF = 10**12

    def nid(j, k): return j * W + k

    real = [nid(j, k) for j in range(n) for k in range(L[j])]
    opm = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(mach[j]):
            if 0 <= ma < m:
                opm[j][ma] = k

    rem = []
    tw = []
    for j in range(n):
        r = [0] * (L[j] + 1)
        for k in range(L[j] - 1, -1, -1):
            r[k] = r[k + 1] + dur[j][k]
        rem.append(r)
        tw.append(r[0])
    load = [0] * m
    for j in range(n):
        for k, ma in enumerate(mach[j]):
            if 0 <= ma < m:
                load[ma] += dur[j][k]

    base_s = [[] for _ in range(n * W)]
    base_i = [0] * (n * W)
    for j in range(n):
        for k in range(L[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
            base_s[a].append(b)
            base_i[b] += 1

    def evaluate(seq, info=False):
        indeg = base_i[:]
        succ = [x[:] for x in base_s]
        for ma in range(m):
            if len(seq[ma]) != n:
                return (INF, None, None, None) if info else INF
            seen = [0] * n
            prev = -1
            for j in seq[ma]:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if info else INF
                seen[j] = 1
                k = opm[j][ma]
                if k < 0:
                    return (INF, None, None, None) if info else INF
                u = nid(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    indeg[u] += 1
                prev = u
        q = [u for u in real if indeg[u] == 0]
        st = [0] * (n * W)
        pr = [-1] * (n * W)
        h = cnt = 0
        while h < len(q):
            u = q[h]; h += 1; cnt += 1
            j, k = divmod(u, W)
            f = st[u] + dur[j][k]
            for v in succ[u]:
                if f > st[v]:
                    st[v] = f
                    pr[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if cnt != tot:
            return (INF, None, None, None) if info else INF
        best = 0; end = -1
        for j in range(n):
            for k in range(L[j]):
                u = nid(j, k)
                c = st[u] + dur[j][k]
                if c > best:
                    best = c; end = u
        return (best, st, pr, end) if info else best

    rmach = [list(reversed(x)) for x in mach]
    rdur = [list(reversed(x)) for x in dur]
    rrem = []
    for j in range(n):
        r = [0] * (L[j] + 1)
        for k in range(L[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdur[j][k]
        rrem.append(r)

    weights = [
        (1.0,-.45,-.70,0,0,0),(1.0,-.95,-.55,.55,0,0),(.85,-.65,-.90,.35,0,.04),
        (1.0,-.35,-1.15,0,-.25,0),(.6,-.82,-.50,.35,0,0),(1.0,-1.02,-.78,.62,0,0),
        (.9,-.72,-.65,.18,0,-.02),(1.1,-.50,-.25,0,-.35,0),(.45,-.55,-.40,0,0,.12),
        (1.0,-.78,-.92,.40,0,0),(.7,-.92,-.38,.22,.04,0),(.92,-1.10,-.92,.72,0,.03),
        (.72,-.35,-1.35,0,0,.05),(1.12,-.92,-.40,.42,-.04,0),(.55,-1.05,-.62,.55,0,0),
        (1.0,-.60,-.20,.15,-.10,0),(.8,-.52,-.55,.75,0,0),(.65,-.80,-.45,0,0,.25)
    ]

    def priority(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        a, b, c, d, e, f = weights[rule % len(weights)]
        mode = rule % 7
        if mode == 1: base = est
        elif mode == 2: base = jr[j] + .45 * mr[ma]
        elif mode == 3: base = mr[ma] + .25 * jr[j]
        elif mode == 4: base = ect + .2 * abs(jr[j] - mr[ma])
        elif mode == 5: base = .6 * ect + .4 * est
        elif mode == 6: base = .5 * ect + .5 * jr[j]
        else: base = ect
        return a * base + b * rr + c * p + d * tail + e * tw[j] + f * load[ma]

    def giffler(rule=0, rev=False, rng=None, noise=0.0, randp=0.0):
        ms, ds, rw = (rmach, rdur, rrem) if rev else (mach, dur, rem)
        jr = [0] * n; mr = [0] * m; nx = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < tot:
            bc = INF; target = 0
            for j in range(n):
                k = nx[j]
                if k < L[j]:
                    ma = ms[j][k]
                    c = max(jr[j], mr[ma]) + ds[j][k]
                    if c < bc:
                        bc = c; target = ma
            cand = []
            for j in range(n):
                k = nx[j]
                if k < L[j] and ms[j][k] == target and jr[j] < bc:
                    v = priority(rule, j, k, target, jr, mr, ds, rw)
                    if rng and noise: v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nx[j]
                    if k < L[j]:
                        ma = ms[j][k]
                        v = priority(rule, j, k, ma, jr, mr, ds, rw)
                        if rng and noise: v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            cand.sort()
            if rng and len(cand) > 1 and rng.random() < randp:
                j = cand[rng.randrange(min(5, len(cand)))][1]
            else:
                j = cand[0][1]
            k = nx[j]; ma = ms[j][k]
            f = max(jr[j], mr[ma]) + ds[j][k]
            seq[ma].append(j)
            jr[j] = f; mr[ma] = f; nx[j] += 1; done += 1
        if rev:
            seq = [list(reversed(x)) for x in seq]
        return seq

    def copyseq(s): return [x[:] for x in s]

    rng = random.Random(210021)
    t0 = time.perf_counter()
    deadline = t0 + 8.75
    best = None; bestv = INF
    pool = []

    def consider(s):
        nonlocal best, bestv, pool
        v = evaluate(s)
        if v < INF:
            if v < bestv:
                bestv = v; best = copyseq(s)
            pool.append((v, copyseq(s)))
            if len(pool) > 50:
                pool.sort(key=lambda x: x[0])
                pool = pool[:50]
        return v

    for rev in (False, True):
        for r in range(72):
            consider(giffler(r, rev))
    while time.perf_counter() < t0 + 1.35:
        consider(giffler(rng.randrange(140), rng.random() < .5, rng,
                         rng.choice((1,2,3,5,8,13,21,34,55,89,144)),
                         rng.choice((.02,.04,.07,.11,.17,.25))))

    def crit(seq):
        v, st, pr, end = evaluate(seq, True)
        if st is None: return v, set()
        s = set()
        while end != -1:
            s.add(end); end = pr[end]
        return v, s

    def moves(seq, wide=False):
        v, cp = crit(seq)
        if not cp: return []
        mv = []; seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = [i for i, j in enumerate(arr) if nid(j, opm[j][ma]) in cp]
            if len(pos) < 2: continue
            block = [pos[0]]
            blocks = []
            for p in pos[1:]:
                if p == block[-1] + 1: block.append(p)
                else:
                    if len(block) > 1: blocks.append(block)
                    block = [p]
            if len(block) > 1: blocks.append(block)
            for b in blocks:
                cand = [("s",ma,b[0],b[0]+1),("s",ma,b[-2],b[-1]),("i",ma,b[0],b[-1]+1),("i",ma,b[-1],b[0])]
                if len(b) > 2:
                    cand += [("s",ma,b[0],b[-1]),("i",ma,b[1],b[-1]+1),("i",ma,b[-2],b[0])]
                if wide:
                    lim = b if len(b) <= 8 else b[:4] + b[-4:]
                    tg = set()
                    for x in lim:
                        tg.add(x); tg.add(x + 1)
                    for x in lim:
                        for y in tg:
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i",ma,x,y))
                    if len(b) <= 8:
                        for a in range(len(b)):
                            for z in range(a + 2, len(b)):
                                cand.append(("s",ma,b[a],b[z]))
                for x in cand:
                    typ, mm, a, z = x
                    ok = (0 <= a < n and ((typ == "s" and 0 <= z < n and a != z) or (typ == "i" and 0 <= z <= n and z != a and z != a + 1)))
                    if ok and x not in seen:
                        seen.add(x); mv.append(x)
        rng.shuffle(mv)
        return mv

    def apply(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == "s":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a: b -= 1
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
            ml = moves(seq, wide)
            if not ml: break
            bv = val; bm = None
            for x in ml[:260]:
                if time.perf_counter() >= stop: break
                apply(seq, x); v = evaluate(seq); undo(seq, x)
                if v < bv:
                    bv = v; bm = x
            if bm is None: break
            apply(seq, bm); val = bv
        return seq, val

    if best is None:
        best = giffler(0); bestv = evaluate(best)
    best, bestv = descent(best, bestv, min(deadline, t0 + 2.7), True)

    cur = copyseq(best); curv = bestv
    tabu = {}; it = 0; stag = 0
    while time.perf_counter() < deadline:
        it += 1
        ml = moves(cur, wide=(stag > 18 or it % 5 == 0))
        if not ml:
            cur = copyseq(best); curv = bestv; stag += 1; continue
        limit = 180 if stag < 25 else 300
        chosen = None; cv = INF; ckey = None
        for x in ml[:limit]:
            if time.perf_counter() >= deadline: break
            typ, ma, a, b = x
            arr = cur[ma]
            key = (ma, arr[a], arr[b] if typ == "s" else b, typ)
            apply(cur, x); v = evaluate(cur); undo(cur, x)
            if v >= INF: continue
            if v < bestv or tabu.get(key, 0) <= it:
                if v < cv or (v == cv and rng.random() < .08):
                    chosen = x; cv = v; ckey = key
        if chosen is None:
            cur = copyseq(best); curv = bestv; stag += 1; continue
        apply(cur, chosen); curv = cv
        tabu[ckey] = it + 7 + rng.randrange(17)
        if curv < bestv:
            bestv = curv; best = copyseq(cur); stag = 0
            cur, curv = descent(cur, curv, min(deadline, time.perf_counter() + .12), False)
            if curv < bestv:
                bestv = curv; best = copyseq(cur)
        else:
            stag += 1
        if stag > 65 or it % 47 == 0:
            cur = copyseq(best); curv = bestv; stag = 0
            for _ in range(1 + rng.randrange(4)):
                ml = moves(cur, True)
                if not ml: break
                x = ml[rng.randrange(len(ml))]
                apply(cur, x)
                if evaluate(cur) >= INF:
                    undo(cur, x)
            curv = evaluate(cur)
            if curv >= INF:
                cur = copyseq(best); curv = bestv

    return Schedule.from_job_sequences(instance, best)