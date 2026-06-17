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

    prefix = []
    for j in range(n):
        p = [0] * (lens[j] + 1)
        for k in range(lens[j]):
            p[k + 1] = p[k] + durations[j][k]
        prefix.append(p)

    machine_load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            machine_load[ma] += durations[j][k]

    base_succ = [[] for _ in range(nodes)]
    base_indeg = [0] * nodes
    for j in range(n):
        for k in range(lens[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
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
        h = cnt = 0
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
        (0.92, -1.10, -0.92, 0.72, 0.00, 0.03),
        (0.72, -0.35, -1.35, 0.00, 0.00, 0.05),
        (1.12, -0.92, -0.40, 0.42, -0.04, 0.00),
        (0.55, -1.05, -0.62, 0.55, 0.00, 0.00),
        (1.20, -0.85, -1.05, 0.35, 0.00, 0.00),
        (0.78, -1.25, -0.50, 0.75, 0.00, 0.04),
        (1.05, -0.30, -1.45, 0.10, 0.00, 0.08),
        (0.35, -1.00, -0.80, 0.58, 0.00, 0.00),
    ]

    def keyval(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        a, b, c, d, e, f = weights[rule % len(weights)]
        q = rule % 9
        if q == 1:
            base = est
        elif q == 2:
            base = jr[j] + 0.45 * mr[ma]
        elif q == 3:
            base = mr[ma] + 0.25 * jr[j]
        elif q == 4:
            base = ect + 0.20 * abs(jr[j] - mr[ma])
        elif q == 5:
            base = 0.65 * ect + 0.35 * est
        elif q == 6:
            base = ect + 0.18 * machine_load[ma]
        elif q == 7:
            base = est + 0.55 * p
        elif q == 8:
            base = jr[j] + mr[ma] + 0.1 * ect
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

    def priority_seq(mode):
        seq = [[] for _ in range(m)]
        for ma in range(m):
            arr = list(range(n))
            if mode == 0:
                arr.sort(key=lambda j: (op_on_machine[j][ma], prefix[j][op_on_machine[j][ma]], -rem[j][op_on_machine[j][ma]]))
            elif mode == 1:
                arr.sort(key=lambda j: (prefix[j][op_on_machine[j][ma]], op_on_machine[j][ma]))
            elif mode == 2:
                arr.sort(key=lambda j: (-rem[j][op_on_machine[j][ma]], prefix[j][op_on_machine[j][ma]]))
            elif mode == 3:
                arr.sort(key=lambda j: (-durations[j][op_on_machine[j][ma]], prefix[j][op_on_machine[j][ma]]))
            else:
                arr.sort(key=lambda j: (prefix[j][op_on_machine[j][ma]] - rem[j][op_on_machine[j][ma]], j))
            seq[ma] = arr
        return seq

    def cpseq(seq):
        return [x[:] for x in seq]

    rng = random.Random(9121021)
    t0 = time.perf_counter()
    deadline = t0 + 8.95
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
            if len(pool) > 90:
                pool.sort(key=lambda x: x[0])
                pool = pool[:90]
        return v

    for mode in range(5):
        consider(priority_seq(mode))

    for rev in (False, True):
        for r in range(110):
            consider(giffler(r, rev))

    while time.perf_counter() < t0 + 2.05:
        consider(giffler(rng.randrange(240), rng.random() < 0.5, rng,
                         rng.choice((1, 2, 4, 8, 13, 21, 34, 55, 89, 144, 233, 377)),
                         rng.choice((0.012, 0.025, 0.045, 0.075, 0.12, 0.18, 0.27, 0.36))))

    def crit_path(seq):
        v, st, pr, end = eval_seq(seq, True)
        if st is None:
            return v, set(), None
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pr[u]
        return v, s, st

    def moves_from_critical(seq, wide=False):
        v, crit, st = crit_path(seq)
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
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-1] - 1, b[-1]),
                        ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if len(b) >= 3:
                    cand.append(("s", ma, b[0], b[-1]))
                    cand.append(("i", ma, b[1], b[-1] + 1))
                    cand.append(("i", ma, b[-2], b[0]))
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
                    for ii in range(len(lim)):
                        for jj in range(ii + 1, len(lim)):
                            cand.append(("s", ma, lim[ii], lim[jj]))
                for mv in cand:
                    typ, mm, a, z = mv
                    ok = (0 <= a < n and 0 <= z < n and a != z) if typ == "s" else (0 <= a < n and 0 <= z <= n and a != z and z != a + 1)
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

    def descent(seq, val, stop, wide=True, first=False):
        while time.perf_counter() < stop:
            mvlist = moves_from_critical(seq, wide)
            if not mvlist:
                break
            bm = None
            bv = val
            lim = 310 if wide else 175
            for mv in mvlist[:lim]:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < bv:
                    bv = v
                    bm = mv
                    if first:
                        break
            if bm is None:
                break
            apply(seq, bm)
            val = bv
        return seq, val

    pool.sort(key=lambda x: x[0])
    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    for v, s in pool[:14]:
        if time.perf_counter() >= t0 + 3.25:
            break
        ss, vv = descent(cpseq(s), v, min(t0 + 3.25, time.perf_counter() + 0.16), True, False)
        if vv < best_val:
            best_val, best_seq = vv, cpseq(ss)

    current = cpseq(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        mvlist = moves_from_critical(current, wide=(it % 4 == 0 or stagn > 15))
        if not mvlist:
            current = cpseq(best_seq)
            current_val = best_val
            stagn += 1
            continue

        chosen = None
        chosen_val = INF
        chosen_key = None
        sample_limit = 205 if stagn < 28 else 320
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
                if v < chosen_val or (v == chosen_val and rng.random() < 0.13):
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
        tabu[chosen_key] = it + 6 + rng.randrange(24)

        if current_val < best_val:
            best_val = current_val
            best_seq = cpseq(current)
            stagn = 0
            current, current_val = descent(current, current_val, min(deadline, time.perf_counter() + 0.11), False, False)
            if current_val < best_val:
                best_val = current_val
                best_seq = cpseq(current)
        else:
            stagn += 1

        if it % 43 == 0 or stagn > 62:
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