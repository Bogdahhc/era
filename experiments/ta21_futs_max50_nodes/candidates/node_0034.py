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

    cnt = [len(x) for x in machines]
    total_ops = sum(cnt)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(cnt), m)
    nodes = n * width
    inf = 10 ** 12

    def nid(j, k):
        return j * width + k

    real_nodes = [nid(j, k) for j in range(n) for k in range(cnt[j])]

    op_on_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                op_on_machine[j][ma] = k

    rem = []
    job_work = []
    for j in range(n):
        r = [0] * (cnt[j] + 1)
        for k in range(cnt[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem.append(r)
        job_work.append(r[0])

    load = [0] * m
    for j in range(n):
        for k, ma in enumerate(machines[j]):
            if 0 <= ma < m:
                load[ma] += durations[j][k]

    base_succ = [[] for _ in range(nodes)]
    base_indeg = [0] * nodes
    for j in range(n):
        for k in range(cnt[j] - 1):
            a, b = nid(j, k), nid(j, k + 1)
            base_succ[a].append(b)
            base_indeg[b] += 1

    def eval_seq(seq, info=False):
        indeg = base_indeg[:]
        succ = [x[:] for x in base_succ]
        for ma in range(m):
            arr = seq[ma]
            if len(arr) != n:
                return (inf, None, None, None) if info else inf
            seen = [False] * n
            prev = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (inf, None, None, None) if info else inf
                seen[j] = True
                k = op_on_machine[j][ma]
                if k < 0:
                    return (inf, None, None, None) if info else inf
                u = nid(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    indeg[u] += 1
                prev = u

        q = [u for u in real_nodes if indeg[u] == 0]
        start = [0] * nodes
        pred = [-1] * nodes
        h = 0
        done = 0
        while h < len(q):
            u = q[h]
            h += 1
            done += 1
            j, k = divmod(u, width)
            fin = start[u] + durations[j][k]
            for v in succ[u]:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if done != total_ops:
            return (inf, None, None, None) if info else inf

        best = 0
        end = -1
        for j in range(n):
            for k in range(cnt[j]):
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
        r = [0] * (cnt[j] + 1)
        for k in range(cnt[j] - 1, -1, -1):
            r[k] = r[k + 1] + rev_durations[j][k]
        rev_rem.append(r)

    def score_rule(rule, j, k, ma, jr, mr, ds, rr):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rw = rr[j][k]
        tail = rr[j][k + 1]
        tw = job_work[j]
        ml = load[ma]
        if rule == 0:
            return ect - 0.50 * rw - 0.30 * p
        if rule == 1:
            return est - 0.65 * rw - 0.55 * p
        if rule == 2:
            return ect - 0.85 * rw + 0.30 * tail - 0.20 * p
        if rule == 3:
            return jr[j] + 0.45 * mr[ma] - 0.55 * rw - 0.50 * p
        if rule == 4:
            return ect - 0.35 * tw - 0.25 * rw - 0.45 * p
        if rule == 5:
            return est + 0.75 * p - 0.58 * rw + 0.15 * tail
        if rule == 6:
            return ect + 0.04 * ml - 0.40 * rw - 0.85 * p
        if rule == 7:
            return mr[ma] + 0.25 * jr[j] - 0.48 * rw + 0.20 * tail
        if rule == 8:
            return ect - 0.72 * rw + 0.48 * tail - 0.65 * p
        if rule == 9:
            return est - 0.76 * rw - 0.30 * p + 0.20 * tail
        if rule == 10:
            return ect - 0.92 * rw + 0.45 * tail - 0.15 * p
        if rule == 11:
            return jr[j] + 0.15 * mr[ma] - 0.70 * rw - 0.25 * p
        if rule == 12:
            return ect - 0.62 * rw - 1.05 * p + 0.05 * ml
        if rule == 13:
            return est - 0.45 * rw + 1.15 * p
        if rule == 14:
            return ect - 0.25 * rw + 0.75 * tail - 0.55 * tw
        if rule == 15:
            return max(jr[j], mr[ma] + 0.20 * p) - 0.43 * rw
        if rule == 16:
            return ect - 1.05 * rw + 0.55 * tail - 0.75 * p
        if rule == 17:
            return jr[j] + 0.75 * mr[ma] - 0.55 * rw + 0.10 * tail
        if rule == 18:
            return est - 0.82 * rw - 0.85 * p + 0.30 * tail
        if rule == 19:
            return ect - 0.55 * rw + 0.18 * ml - 0.20 * p
        if rule == 20:
            return ect - 0.78 * rw + 0.12 * tail - 0.48 * p
        if rule == 21:
            return jr[j] - 0.62 * rw + 0.35 * mr[ma] - 0.60 * p
        if rule == 22:
            return ect - 0.42 * rw - 1.20 * p
        if rule == 23:
            return est + 0.35 * p - 0.70 * rw + 0.10 * tw
        return ect - 0.4 * rw

    def giffler(rule, reverse=False, rng=None, noise=0.0, randp=0.0):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rr = rev_rem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            best_c = inf
            target = 0
            for j in range(n):
                k = nxt[j]
                if k < cnt[j]:
                    ma = ms[j][k]
                    c = max(jr[j], mr[ma]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < cnt[j] and ms[j][k] == target and jr[j] < best_c:
                    v = score_rule(rule, j, k, target, jr, mr, ds, rr)
                    if rng is not None and noise:
                        v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < cnt[j]:
                        ma = ms[j][k]
                        v = score_rule(rule, j, k, ma, jr, mr, ds, rr)
                        if rng is not None and noise:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randp:
                j = cand[rng.randrange(min(4, len(cand)))][1]
            else:
                j = cand[0][1]
            k = nxt[j]
            ma = ms[j][k]
            ft = max(jr[j], mr[ma]) + ds[j][k]
            seq[ma].append(j)
            jr[j] = ft
            mr[ma] = ft
            nxt[j] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def list_dispatch(rule, reverse=False):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rr = rev_rem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            best = None
            ch = 0
            for j in range(n):
                k = nxt[j]
                if k >= cnt[j]:
                    continue
                ma = ms[j][k]
                p = ds[j][k]
                est = max(jr[j], mr[ma])
                ect = est + p
                rw = rr[j][k]
                tail = rr[j][k + 1]
                if rule == 0:
                    key = (ect, -rw, j)
                elif rule == 1:
                    key = (est, -rw, -p, j)
                elif rule == 2:
                    key = (-rw, ect, j)
                elif rule == 3:
                    key = (ect - 0.6 * rw - 0.3 * p, j)
                elif rule == 4:
                    key = (jr[j] + 0.4 * mr[ma] - 0.55 * rw - 0.4 * p, j)
                elif rule == 5:
                    key = (ect - 0.8 * rw + 0.35 * tail - 0.5 * p, j)
                elif rule == 6:
                    key = (est - 0.75 * rw - 0.5 * p + 0.25 * tail, j)
                elif rule == 7:
                    key = (machine_key(load[ma]) + ect - 0.45 * rw - p, j)
                else:
                    key = (score_rule(rule % 24, j, k, ma, jr, mr, ds, rr), j)
                if best is None or key < best:
                    best = key
                    ch = j
            k = nxt[ch]
            ma = ms[ch][k]
            ft = max(jr[ch], mr[ma]) + ds[ch][k]
            seq[ma].append(ch)
            jr[ch] = ft
            mr[ma] = ft
            nxt[ch] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def machine_key(x):
        return 0.035 * x

    rng = random.Random(210021)
    start_time = time.perf_counter()
    deadline = start_time + 7.65

    best_seq = None
    best_val = inf
    pool = []

    def copy_seq(s):
        return [x[:] for x in s]

    def consider(s):
        nonlocal best_seq, best_val, pool
        v = eval_seq(s)
        if v < inf:
            pool.append((v, copy_seq(s)))
            if len(pool) > 36:
                pool.sort(key=lambda z: z[0])
                pool = pool[:36]
            if v < best_val:
                best_val = v
                best_seq = copy_seq(s)
        return v

    for rev in (False, True):
        for r in range(24):
            consider(giffler(r, rev))
        for r in range(16):
            consider(list_dispatch(r, rev))

    while time.perf_counter() < start_time + 1.35:
        consider(
            giffler(
                rng.randrange(24),
                rng.random() < 0.5,
                rng,
                rng.choice((1, 2, 4, 7, 11, 18, 29, 45, 70, 110)),
                rng.choice((0.03, 0.06, 0.10, 0.15, 0.22, 0.30)),
            )
        )

    def crossover(a, b):
        c = [[] for _ in range(m)]
        for ma in range(m):
            x, y = (a[ma], b[ma]) if rng.random() < 0.5 else (b[ma], a[ma])
            l = rng.randrange(n)
            r = rng.randrange(l, n)
            arr = [-1] * n
            used = [False] * n
            for i in range(l, r + 1):
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

    if len(pool) > 1:
        pool.sort(key=lambda z: z[0])
        while time.perf_counter() < start_time + 1.80:
            i = rng.randrange(min(10, len(pool)))
            j = rng.randrange(min(20, len(pool)))
            if i != j:
                consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    def critical(seq):
        v, st, pr, end = eval_seq(seq, True)
        if st is None:
            return v, set()
        c = set()
        u = end
        while u >= 0:
            c.add(u)
            u = pr[u]
        return v, c

    def crit_moves(seq, broad=False):
        _, cset = critical(seq)
        if not cset:
            return []
        out = []
        seen = set()
        for ma in range(m):
            arr = seq[ma]
            pos = []
            for i, j in enumerate(arr):
                k = op_on_machine[j][ma]
                if k >= 0 and nid(j, k) in cset:
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
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-2], b[-1])]
                if len(b) > 2:
                    cand += [("s", ma, b[0], b[-1]), ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if broad:
                    for q in range(len(b) - 1):
                        cand.append(("s", ma, b[q], b[q + 1]))
                    for x in (b[0], b[-1], b[len(b) // 2]):
                        for d in (-7, -5, -3, -2, 2, 3, 5, 7):
                            y = x + d
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                    if len(b) <= 8:
                        for x in b:
                            for y in (b[0], b[0] + 1, b[-1], b[-1] + 1):
                                if 0 <= y <= n and y != x and y != x + 1:
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

    def descent(seq, val, stop):
        while time.perf_counter() < stop:
            moves = crit_moves(seq, True)
            if not moves:
                break
            bv = val
            bm = None
            for mv in moves:
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

    best_seq, best_val = descent(best_seq, best_val, start_time + 2.35)
    cur = copy_seq(best_seq)
    cur_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        moves = crit_moves(cur, broad=(it % 4 != 0))
        if not moves:
            cur = copy_seq(best_seq)
            cur_val = best_val
            moves = crit_moves(cur, True)
            if not moves:
                break

        chosen = None
        chosen_val = inf
        chosen_key = None

        for mv in moves:
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
            if v >= inf:
                continue
            if v < best_val or (tabu.get(key, 0) <= it and tabu.get(rkey, 0) <= it):
                if v < chosen_val or (v == chosen_val and rng.random() < 0.08):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key

        if chosen is None:
            cur = copy_seq(best_seq)
            cur_val = best_val
            stagn += 1
            if stagn > 10:
                break
            continue

        apply(cur, chosen)
        cur_val = chosen_val
        tabu[chosen_key] = it + 6 + rng.randrange(16)

        if cur_val < best_val:
            best_val = cur_val
            best_seq = copy_seq(cur)
            stagn = 0
            if time.perf_counter() < deadline:
                cur, cur_val = descent(cur, cur_val, min(deadline, time.perf_counter() + 0.14))
                if cur_val < best_val:
                    best_val = cur_val
                    best_seq = copy_seq(cur)
        else:
            stagn += 1

        if it % 45 == 0 or (stagn > 70 and cur_val > best_val + 45):
            cur = copy_seq(best_seq)
            cur_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                ml = crit_moves(cur, True)
                if not ml:
                    break
                mv = ml[rng.randrange(len(ml))]
                apply(cur, mv)
                if eval_seq(cur) >= inf:
                    undo(cur, mv)
            cur_val = eval_seq(cur)

    return Schedule.from_job_sequences(instance, best_seq)