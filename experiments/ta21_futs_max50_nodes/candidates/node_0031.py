from job_shop_lib import Schedule
import time
import random
import math


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

    op_count = [len(x) for x in machines]
    total_ops = sum(op_count)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(op_count), m)
    INF = 10**9

    def node(j, k):
        return j * width + k

    real_nodes = [node(j, k) for j in range(n) for k in range(op_count[j])]

    op_on_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_on_machine[j][ma] = k

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

    base_succ = [[] for _ in range(n * width)]
    base_indeg = [0] * (n * width)
    for j in range(n):
        for k in range(op_count[j] - 1):
            a, b = node(j, k), node(j, k + 1)
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
                u = node(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    indeg[u] += 1
                prev = u

        q = [u for u in real_nodes if indeg[u] == 0]
        start = [0] * (n * width)
        pred = [-1] * (n * width)
        head = 0
        cnt = 0
        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            j, k = divmod(u, width)
            fin = start[u] + durations[j][k]
            for v in succ[u]:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if cnt != total_ops:
            return (INF, None, None, None) if info else INF

        best, end = 0, -1
        for j in range(n):
            for k in range(op_count[j]):
                u = node(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best, end = c, u
        return (best, start, pred, end) if info else best

    rev_machines = [list(reversed(x)) for x in machines]
    rev_durations = [list(reversed(x)) for x in durations]

    def make_rem(ds):
        out = []
        for j in range(n):
            r = [0] * (len(ds[j]) + 1)
            for k in range(len(ds[j]) - 1, -1, -1):
                r[k] = r[k + 1] + ds[j][k]
            out.append(r)
        return out

    rev_rem = make_rem(rev_durations)

    def priority(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        r = rw[j][k]
        tail = rw[j][k + 1]
        tw = total_work[j]
        ml = machine_load[ma]
        if rule == 0:
            return ect - 0.55 * r - 0.25 * p
        if rule == 1:
            return est - 0.80 * r - 0.70 * p + 0.20 * tail
        if rule == 2:
            return ect - 0.85 * r + 0.40 * tail - 0.40 * p
        if rule == 3:
            return jr[j] + 0.45 * mr[ma] - 0.65 * r - 0.65 * p
        if rule == 4:
            return ect - 0.45 * tw - 0.25 * r - 0.20 * p
        if rule == 5:
            return est + 0.30 * p - 0.72 * r + 0.12 * ml
        if rule == 6:
            return ect - 0.95 * r + 0.55 * tail - 0.70 * p
        if rule == 7:
            return mr[ma] + 0.25 * jr[j] - 0.52 * r - 0.30 * p
        if rule == 8:
            return est - 0.70 * r + 0.25 * tail + 0.10 * p
        if rule == 9:
            return ect - 0.62 * r - 1.05 * p + 0.05 * ml
        if rule == 10:
            return ect + 0.30 * tail - 0.58 * tw - 0.20 * p
        if rule == 11:
            return jr[j] - 0.75 * r + 0.25 * mr[ma] - 0.40 * p
        if rule == 12:
            return est - 0.92 * r - 0.50 * p + 0.42 * tail
        if rule == 13:
            return ect - 0.75 * r + 0.15 * tail - 0.15 * ml
        if rule == 14:
            return max(jr[j], mr[ma] + 0.2 * p) - 0.68 * r
        if rule == 15:
            return ect - 0.35 * r + 1.10 * p - 0.15 * tw
        if rule == 16:
            return est + 0.70 * p - 0.62 * r + 0.16 * tail
        if rule == 17:
            return ect - 1.10 * r + 0.70 * tail - 0.10 * p
        if rule == 18:
            return jr[j] + 0.75 * mr[ma] - 0.58 * r + 0.08 * tail
        if rule == 19:
            return ect - 0.30 * r - 1.40 * p
        return ect - 0.5 * r

    def giffler(rule, reverse=False, rng=None, noise=0.0, rp=0.0):
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
                        best_c, target = c, ma
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
            if rng is not None and len(cand) > 1 and rng.random() < rp:
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

    def list_dispatch(rule, reverse=False):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            bk, chosen = None, 0
            for j in range(n):
                k = nxt[j]
                if k >= len(ms[j]):
                    continue
                ma = ms[j][k]
                p = ds[j][k]
                est = max(jr[j], mr[ma])
                ect = est + p
                r = rw[j][k]
                tail = rw[j][k + 1]
                if rule == 0:
                    key = (ect - .70 * r - .35 * p, j)
                elif rule == 1:
                    key = (est - .80 * r - .40 * p + .25 * tail, j)
                elif rule == 2:
                    key = (-r, ect, j)
                elif rule == 3:
                    key = (jr[j] + .35 * mr[ma] - .62 * r - .55 * p, j)
                elif rule == 4:
                    key = (ect - .55 * total_work[j] + .20 * tail, j)
                elif rule == 5:
                    key = (machine_load[ma] * .03 + ect - .55 * r - .50 * p, j)
                elif rule == 6:
                    key = (est - .78 * r + .18 * tail - .65 * p, ect, j)
                elif rule == 7:
                    key = (ect - 1.0 * r + .55 * tail - .35 * p, j)
                elif rule == 8:
                    key = (mr[ma] + .20 * jr[j] - .45 * r, ect, j)
                elif rule == 9:
                    key = (ect - .40 * r - 1.2 * p, j)
                else:
                    key = (ect - .65 * r + .25 * tail, j)
                if bk is None or key < bk:
                    bk, chosen = key, j
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

    rng = random.Random(210021)
    start_time = time.perf_counter()
    deadline = start_time + 7.85

    def copyseq(s):
        return [x[:] for x in s]

    best_seq = None
    best_val = INF
    pool = []

    def consider(s):
        nonlocal best_seq, best_val, pool
        v = eval_seq(s)
        if v < INF:
            if v < best_val:
                best_val = v
                best_seq = copyseq(s)
            pool.append((v, copyseq(s)))
            if len(pool) > 50:
                pool.sort(key=lambda x: x[0])
                pool = pool[:50]
        return v

    for rev in (False, True):
        for r in range(20):
            consider(giffler(r, rev))
        for r in range(11):
            consider(list_dispatch(r, rev))

    while time.perf_counter() < start_time + 1.35:
        consider(giffler(rng.randrange(20), rng.random() < 0.5, rng,
                         rng.choice((2, 4, 7, 11, 18, 30, 50, 80, 130)),
                         rng.choice((.04, .07, .10, .14, .20, .28))))

    def crossover(a, b):
        c = [[] for _ in range(m)]
        for ma in range(m):
            x, y = (a[ma], b[ma]) if rng.random() < .5 else (b[ma], a[ma])
            i = rng.randrange(n)
            j = rng.randrange(i, n)
            arr = [-1] * n
            used = [False] * n
            for p in range(i, j):
                arr[p] = x[p]
                used[x[p]] = True
            ptr = 0
            for z in y:
                if not used[z]:
                    while arr[ptr] != -1:
                        ptr += 1
                    arr[ptr] = z
                    used[z] = True
            c[ma] = arr
        return c

    pool.sort(key=lambda x: x[0])
    while len(pool) >= 2 and time.perf_counter() < start_time + 1.75:
        i = rng.randrange(min(12, len(pool)))
        j = rng.randrange(min(24, len(pool)))
        if i != j:
            consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    def critical(seq):
        v, st, pred, end = eval_seq(seq, True)
        if st is None:
            return v, set()
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pred[u]
        return v, s

    def crit_moves(seq, broad=True):
        v, cr = critical(seq)
        if not cr:
            return []
        out = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = []
            for i, j in enumerate(arr):
                k = op_on_machine[j][ma]
                if k >= 0 and node(j, k) in cr:
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
                    lim = b if len(b) <= 7 else [b[0], b[1], b[2], b[-3], b[-2], b[-1]]
                    for x in lim:
                        for d in (-7, -5, -3, -2, 2, 3, 5, 7):
                            y = x + d
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                        for y in (b[0], b[0] + 1, b[-1], b[-1] + 1):
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                for mv in cand:
                    typ, mm, a, b2 = mv
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

    def descent(seq, val, stop):
        while time.perf_counter() < stop:
            bm, bv = None, val
            moves = crit_moves(seq, True)
            if not moves:
                break
            for mv in moves:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < bv:
                    bv, bm = v, mv
            if bm is None:
                break
            apply(seq, bm)
            val = bv
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, start_time + 2.35)

    current = copyseq(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        moves = crit_moves(current, it % 6 != 0)
        if not moves:
            current = copyseq(best_seq)
            current_val = best_val
            moves = crit_moves(current, True)
            if not moves:
                break

        chosen = None
        chosen_val = INF
        chosen_key = None

        for mv in moves:
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
                if v < chosen_val or (v == chosen_val and rng.random() < .08):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key

        if chosen is None:
            current = copyseq(best_seq)
            current_val = best_val
            stagn += 1
            if stagn > 10:
                break
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 6 + rng.randrange(16)

        if current_val < best_val:
            best_val = current_val
            best_seq = copyseq(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(current, current_val, min(deadline, time.perf_counter() + .16))
                if current_val < best_val:
                    best_val = current_val
                    best_seq = copyseq(current)
        else:
            stagn += 1

        if it % 47 == 0 or (stagn > 55 and current_val > best_val + 30):
            current = copyseq(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                mvlist = crit_moves(current, True)
                if not mvlist:
                    break
                mv = mvlist[rng.randrange(len(mvlist))]
                apply(current, mv)
                if eval_seq(current) >= INF:
                    undo(current, mv)
            current_val = eval_seq(current)

    return Schedule.from_job_sequences(instance, best_seq)