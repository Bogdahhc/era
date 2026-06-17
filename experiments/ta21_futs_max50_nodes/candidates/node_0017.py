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

    op_count = [len(x) for x in machines]
    total_ops = sum(op_count)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(op_count), m)
    nnodes = n * width
    INF = 10**12

    def nid(j, k):
        return j * width + k

    real_nodes = [nid(j, k) for j in range(n) for k in range(op_count[j])]

    op_of_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_of_machine[j][ma] = k

    rem = []
    total_work = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)
        total_work.append(r[0])

    machine_load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            machine_load[ma] += durations[j][k]

    base_indeg = [0] * nnodes
    job_succ = [-1] * nnodes
    for j in range(n):
        for k in range(op_count[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
            job_succ[a] = b
            base_indeg[b] += 1

    def eval_seq(seq, need=False):
        indeg = base_indeg[:]
        msucc = [-1] * nnodes
        for ma in range(m):
            arr = seq[ma]
            if len(arr) != n:
                return (INF, None, None, -1) if need else INF
            seen = [False] * n
            prev = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, -1) if need else INF
                seen[j] = True
                k = op_of_machine[j][ma]
                if k < 0:
                    return (INF, None, None, -1) if need else INF
                u = nid(j, k)
                if prev >= 0:
                    msucc[prev] = u
                    indeg[u] += 1
                prev = u

        q = [u for u in real_nodes if indeg[u] == 0]
        start = [0] * nnodes
        pred = [-1] * nnodes
        head = 0
        cnt = 0
        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            j = u // width
            k = u % width
            fin = start[u] + durations[j][k]
            v = job_succ[u]
            if v >= 0:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
            v = msucc[u]
            if v >= 0:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if cnt != total_ops:
            return (INF, None, None, -1) if need else INF

        best = 0
        end = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end = u
        return (best, start, pred, end) if need else best

    rng = random.Random(2100217)
    rmachines = [list(reversed(x)) for x in machines]
    rdurations = [list(reversed(x)) for x in durations]
    rrem = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdurations[j][k]
        rrem.append(r)

    def score_rule(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = jr[j] if jr[j] >= mr[ma] else mr[ma]
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        tw = total_work[j]
        ml = machine_load[ma]
        if rule == 0:
            return ect - 0.55 * rr - 0.50 * p
        if rule == 1:
            return est - 0.45 * rr - 1.00 * p
        if rule == 2:
            return ect - 0.25 * rr + 1.50 * p
        if rule == 3:
            return -rr + 0.18 * ect
        if rule == 4:
            return ect + 0.45 * tail - 0.25 * tw
        if rule == 5:
            return p + 0.28 * est - 0.22 * rr
        if rule == 6:
            return -p + 0.42 * est - 0.20 * rr
        if rule == 7:
            return ect - 0.72 * rr + 0.18 * tail - 0.06 * ml
        if rule == 8:
            return jr[j] + 0.45 * mr[ma] - 0.60 * rr - 0.80 * p
        if rule == 9:
            return ect - 0.48 * tail - 0.20 * rr
        if rule == 10:
            return est + 0.65 * p - 0.62 * rr + 0.08 * tw
        if rule == 11:
            return mr[ma] + 0.30 * jr[j] + p - 0.42 * rr
        if rule == 12:
            return ect + 0.04 * ml - 0.32 * rr - 0.40 * p
        if rule == 13:
            return ect - 0.45 * tw - 0.15 * p
        if rule == 14:
            return max(jr[j], mr[ma] + 0.20 * p) - 0.38 * rr
        if rule == 15:
            return est + 1.25 * p - 0.32 * rr - 0.05 * tw
        if rule == 16:
            return ect - 0.62 * rr + 0.75 * tail - 0.25 * p
        if rule == 17:
            return jr[j] - 0.42 * rr + 0.50 * p + 0.08 * mr[ma]
        if rule == 18:
            return ect - 0.70 * rr + 0.22 * tw
        if rule == 19:
            return ect - 0.52 * rr - 0.20 * p + 0.24 * tail
        if rule == 20:
            return est - 0.68 * rr + 0.20 * tail + 0.45 * p
        if rule == 21:
            return ect - 0.55 * rr + 0.14 * ml - 0.22 * p
        if rule == 22:
            return 42 * (len(ds[j]) - k) + ect - 0.38 * rr
        if rule == 23:
            return -42 * (len(ds[j]) - k) + ect - 0.24 * rr
        if rule == 24:
            return ect - 0.78 * rr - 0.05 * ml + 0.38 * tail
        if rule == 25:
            return est - 0.58 * rr - 0.65 * p + 0.18 * tail
        if rule == 26:
            return 0.60 * jr[j] + 0.85 * mr[ma] + p - 0.50 * rr
        if rule == 27:
            return ect - 0.35 * rr + 0.006 * ml * p - 0.10 * tw
        return ect - 0.35 * rr

    def giffler(rule, reverse=False, noise=0.0, randpick=0.0):
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
                if k < len(ms[j]):
                    ma = ms[j][k]
                    c = (jr[j] if jr[j] >= mr[ma] else mr[ma]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < len(ms[j]) and ms[j][k] == target and jr[j] < best_c:
                    val = score_rule(rule, j, k, target, jr, mr, ds, rw)
                    if noise:
                        val += rng.uniform(-noise, noise)
                    cand.append((val, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        val = score_rule(rule, j, k, ma, jr, mr, ds, rw)
                        if noise:
                            val += rng.uniform(-noise, noise)
                        cand.append((val, j))
            cand.sort()
            if randpick and len(cand) > 1 and rng.random() < randpick:
                chosen = cand[rng.randrange(min(len(cand), 5))][1]
            else:
                chosen = cand[0][1]
            k = nxt[chosen]
            ma = ms[chosen][k]
            ft = (jr[chosen] if jr[chosen] >= mr[ma] else mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = ft
            mr[ma] = ft
            nxt[chosen] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def list_dispatch(rule, reverse=False):
        ms = rmachines if reverse else machines
        ds = rdurations if reverse else durations
        rw = rrem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            best_key = None
            chosen = 0
            for j in range(n):
                k = nxt[j]
                if k >= len(ms[j]):
                    continue
                ma = ms[j][k]
                p = ds[j][k]
                est = jr[j] if jr[j] >= mr[ma] else mr[ma]
                ect = est + p
                rr = rw[j][k]
                tail = rw[j][k + 1]
                if rule == 0:
                    key = (ect, -rr, j)
                elif rule == 1:
                    key = (est, -p, -rr, j)
                elif rule == 2:
                    key = (-rr, ect, j)
                elif rule == 3:
                    key = (p, est, j)
                elif rule == 4:
                    key = (-p, est, j)
                elif rule == 5:
                    key = (tail, ect, j)
                elif rule == 6:
                    key = (ect - 0.52 * rr + 0.20 * tail, j)
                elif rule == 7:
                    key = (mr[ma], -rr, ect, j)
                elif rule == 8:
                    key = (ect + 0.20 * tail - 0.18 * total_work[j], j)
                elif rule == 9:
                    key = (est + 1.20 * p - 0.35 * rr, j)
                elif rule == 10:
                    key = (jr[j] + 0.15 * mr[ma] - 0.35 * rr, ect, j)
                elif rule == 11:
                    key = (machine_load[ma] * 0.04 + ect - 0.34 * rr - 0.30 * p, j)
                elif rule == 12:
                    key = (est - 0.45 * rr + 0.80 * tail - 0.40 * p, j)
                elif rule == 13:
                    key = (ect - 0.70 * rr - 0.30 * p, j)
                else:
                    key = (mr[ma] + 0.45 * jr[j] + 0.80 * p - 0.52 * rr, j)
                if best_key is None or key < best_key:
                    best_key = key
                    chosen = j
            k = nxt[chosen]
            ma = ms[chosen][k]
            ft = (jr[chosen] if jr[chosen] >= mr[ma] else mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = ft
            mr[ma] = ft
            nxt[chosen] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def cp(seq):
        return [a[:] for a in seq]

    begin = time.perf_counter()
    deadline = begin + 5.85
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
            if len(pool) > 30:
                pool.sort(key=lambda x: x[0])
                pool = pool[:30]
        return v

    for rev in (False, True):
        for r in range(28):
            consider(giffler(r, rev))
        for r in range(15):
            consider(list_dispatch(r, rev))

    while time.perf_counter() < begin + 1.05:
        consider(giffler(rng.randrange(28), rng.random() < 0.5,
                         rng.choice((2, 5, 9, 16, 28, 45, 70, 105, 150)),
                         rng.choice((0.05, 0.10, 0.16, 0.23, 0.31))))

    def crossover(a, b):
        child = [[] for _ in range(m)]
        for ma in range(m):
            x, y = (a[ma], b[ma]) if rng.random() < 0.5 else (b[ma], a[ma])
            c1 = rng.randrange(n)
            c2 = rng.randrange(c1, n)
            arr = [-1] * n
            used = [False] * n
            for i in range(c1, c2):
                arr[i] = x[i]
                used[x[i]] = True
            ptr = 0
            for z in y:
                if not used[z]:
                    while arr[ptr] != -1:
                        ptr += 1
                    arr[ptr] = z
                    used[z] = True
            child[ma] = arr
        return child

    pool.sort(key=lambda x: x[0])
    while len(pool) >= 2 and time.perf_counter() < begin + 1.30:
        i = rng.randrange(min(10, len(pool)))
        j = rng.randrange(min(18, len(pool)))
        if i != j:
            consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    def critical(seq):
        val, starts, pred, end = eval_seq(seq, True)
        if starts is None:
            return val, set()
        s = set()
        u = end
        while u >= 0:
            s.add(u)
            u = pred[u]
        return val, s

    def moves(seq, broad=False, very=False):
        val, crit = critical(seq)
        if not crit:
            return []
        out = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = []
            for i, j in enumerate(arr):
                k = op_of_machine[j][ma]
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
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-1] - 1, b[-1])]
                if len(b) >= 3:
                    cand += [("s", ma, b[0], b[-1]), ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if broad:
                    for t in range(len(b) - 1):
                        cand.append(("s", ma, b[t], b[t + 1]))
                    lim = b if very or len(b) <= 8 else [b[0], b[1], b[-2], b[-1]]
                    for x in lim:
                        for y in (b[0], b[0] + 1, b[-1], b[-1] + 1, x - 5, x - 4, x - 3, x - 2, x + 3, x + 4, x + 5, x + 6):
                            if 0 <= y <= n and x != y and y != x + 1:
                                cand.append(("i", ma, x, y))
                for mv in cand:
                    typ, ma2, a, b2 = mv
                    if typ == "s":
                        ok = 0 <= a < n and 0 <= b2 < n and a != b2
                    else:
                        ok = 0 <= a < n and 0 <= b2 <= n and a != b2 and b2 != a + 1
                    if ok and mv not in seen:
                        seen.add(mv)
                        out.append(mv)
        rng.shuffle(out)
        return out

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

    def descent(seq, val, stop, broad=True, very=False):
        while time.perf_counter() < stop:
            blocal = val
            bmv = None
            ml = moves(seq, broad, very)
            if not ml:
                break
            for mv in ml:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < blocal:
                    blocal = v
                    bmv = mv
            if bmv is None:
                break
            apply(seq, bmv)
            val = blocal
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, begin + 1.78, True, True)

    current = cp(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        ml = moves(current, it % 5 != 0, it % 11 == 0)
        if not ml:
            current = cp(best_seq)
            current_val = best_val
            ml = moves(current, True, True)
            if not ml:
                break

        chosen = None
        chosen_val = INF
        chosen_key = None

        for mv in ml:
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
                if v < chosen_val or (v == chosen_val and rng.random() < 0.08):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key

        if chosen is None:
            current = cp(best_seq)
            current_val = best_val
            stagn += 1
            if stagn > 8:
                break
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 6 + rng.randrange(16)

        if current_val < best_val:
            best_val = current_val
            best_seq = cp(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(current, current_val, min(deadline, time.perf_counter() + 0.13), True, False)
                if current_val < best_val:
                    best_val = current_val
                    best_seq = cp(current)
        else:
            stagn += 1

        if it % 41 == 0 or (stagn > 55 and current_val > best_val + 30):
            current = cp(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                ml2 = moves(current, True, True)
                if not ml2:
                    break
                mv = ml2[rng.randrange(len(ml2))]
                apply(current, mv)
                if eval_seq(current) >= INF:
                    undo(current, mv)
            current_val = eval_seq(current)

    return Schedule.from_job_sequences(instance, best_seq)