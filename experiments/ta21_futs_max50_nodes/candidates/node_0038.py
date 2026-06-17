from job_shop_lib import Schedule
import time
import random


def solve(instance):
    n = int(instance.num_jobs)
    m = int(instance.num_machines)
    if n <= 0 or m <= 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(max(0, m))])

    machines = []
    durations = []
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
    inf = 10**12

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
            return (inf, None, None, None) if info else inf

        val = 0
        end = -1
        for j in range(n):
            for k in range(lens[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > val:
                    val = c
                    end = u
        return (val, start, pred, end) if info else val

    rev_machines = [list(reversed(x)) for x in machines]
    rev_durations = [list(reversed(x)) for x in durations]
    rev_rem = []
    for j in range(n):
        r = [0] * (lens[j] + 1)
        for k in range(lens[j] - 1, -1, -1):
            r[k] = r[k + 1] + rev_durations[j][k]
        rev_rem.append(r)

    def pr(rule, j, k, ma, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rr = rw[j][k]
        tail = rw[j][k + 1]
        tw = total_work[j]
        ml = machine_load[ma]
        if rule == 0:
            return ect - 0.70 * rr - 0.65 * p
        if rule == 1:
            return est - 0.85 * rr - 0.60 * p
        if rule == 2:
            return ect - 1.02 * rr + 0.62 * tail - 0.78 * p
        if rule == 3:
            return jr[j] + 0.45 * mr[ma] - 0.75 * rr - 0.45 * p
        if rule == 4:
            return ect - 0.35 * tw - 0.35 * rr
        if rule == 5:
            return est + 0.20 * p - 0.95 * rr + 0.25 * tail
        if rule == 6:
            return ect - 0.78 * rr - 0.92 * p + 0.40 * tail
        if rule == 7:
            return mr[ma] + 0.25 * jr[j] - 0.60 * rr + 0.10 * p
        if rule == 8:
            return ect + 0.04 * ml - 0.62 * rr - 0.45 * p
        if rule == 9:
            return est - 0.92 * rr - 0.38 * p + 0.22 * tail
        if rule == 10:
            return ect - 0.95 * rr + 0.55 * tail - 0.30 * p
        if rule == 11:
            return jr[j] - 0.82 * rr + 0.35 * tail - 0.50 * p + 0.15 * mr[ma]
        if rule == 12:
            return ect - 0.50 * tw - 0.10 * p
        if rule == 13:
            return est + 0.45 * p - 0.75 * rr + 0.12 * ml
        if rule == 14:
            return ect - 0.42 * rr - 1.20 * p + 0.08 * ml
        if rule == 15:
            return max(jr[j], mr[ma] + 0.25 * p) - 0.62 * rr
        if rule == 16:
            return ect - 0.72 * rr + 0.18 * tail - 0.12 * ml
        if rule == 17:
            return est - 0.52 * rr + 0.75 * tail - 0.55 * p
        if rule == 18:
            return jr[j] + mr[ma] * 0.65 - 0.55 * rr - 0.28 * p
        if rule == 19:
            return ect - 0.88 * rr + 0.35 * tail - 0.55 * p
        if rule == 20:
            return est - 0.80 * rr - 0.60 * p + 0.10 * tw
        if rule == 21:
            return ect - 0.35 * rr - 1.05 * p
        if rule == 22:
            return ect - 0.65 * rr - 0.22 * p + 0.22 * tail - 0.12 * tw
        if rule == 23:
            return mr[ma] - 0.18 * jr[j] - 0.50 * rr - 0.35 * p
        if rule == 24:
            return ect - 1.15 * rr + 0.70 * tail - 0.90 * p
        if rule == 25:
            return est - 1.05 * rr - 0.70 * p + 0.45 * tail
        return ect - 0.55 * rr - 0.35 * p

    def giffler(rule, reverse=False, rng=None, noise=0.0, randpick=0.0):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem if reverse else rem
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
                    val = pr(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        val += rng.uniform(-noise, noise)
                    cand.append((val, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < lens[j]:
                        ma = ms[j][k]
                        val = pr(rule, j, k, ma, jr, mr, ds, rw)
                        if rng is not None and noise:
                            val += rng.uniform(-noise, noise)
                        cand.append((val, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randpick:
                chosen = cand[rng.randrange(min(6, len(cand)))][1]
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
            best_key = None
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
                if rule == 0:
                    key = (ect, -rr, -p, j)
                elif rule == 1:
                    key = (est, -rr, -p, j)
                elif rule == 2:
                    key = (-rr, ect, j)
                elif rule == 3:
                    key = (ect - 0.55 * rr - 0.55 * p, j)
                elif rule == 4:
                    key = (jr[j] + 0.4 * mr[ma] - 0.55 * rr - 0.4 * p, ect, j)
                elif rule == 5:
                    key = (ect - 0.80 * rr + 0.35 * tail - 0.35 * p, j)
                elif rule == 6:
                    key = (est - 0.72 * rr - 0.65 * p, ect, j)
                elif rule == 7:
                    key = (machine_load[ma] * 0.04 + ect - 0.45 * rr - 0.5 * p, j)
                elif rule == 8:
                    key = (ect - 0.35 * total_work[j] - 0.28 * rr, j)
                elif rule == 9:
                    key = (mr[ma] + 0.35 * jr[j] - 0.45 * rr + 0.25 * p, j)
                elif rule == 10:
                    key = (ect - 0.95 * rr + 0.55 * tail - 0.75 * p, j)
                elif rule == 11:
                    key = (est - 0.85 * rr + 0.25 * tail - 0.15 * p, ect, j)
                elif rule == 12:
                    key = (jr[j] - 0.80 * rr - 0.45 * p + 0.25 * mr[ma], j)
                elif rule == 13:
                    key = (ect - 0.68 * rr - 0.90 * p + 0.30 * tail, j)
                elif rule == 14:
                    key = (est - 0.62 * rr + 0.10 * total_work[j] - 0.35 * p, j)
                elif rule == 15:
                    key = (ect - 1.05 * rr + 0.65 * tail - 0.85 * p, j)
                else:
                    key = (ect - 0.50 * rr - 0.35 * p, j)
                if best_key is None or key < best_key:
                    best_key = key
                    chosen = j
            k = nxt[chosen]
            ma = ms[chosen][k]
            f = max(jr[chosen], mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = f
            mr[ma] = f
            nxt[chosen] += 1
            done += 1
        return [list(reversed(x)) for x in seq] if reverse else seq

    def cp(seq):
        return [x[:] for x in seq]

    rng = random.Random(752103)
    begin = time.perf_counter()
    deadline = begin + 7.85
    best_seq = None
    best_val = inf
    pool = []

    def consider(seq):
        nonlocal best_seq, best_val, pool
        v = eval_seq(seq)
        if v < inf:
            if v < best_val:
                best_val = v
                best_seq = cp(seq)
            pool.append((v, cp(seq)))
            if len(pool) > 48:
                pool.sort(key=lambda z: z[0])
                pool = pool[:48]
        return v

    for rev in (False, True):
        for r in range(26):
            consider(giffler(r, rev))
        for r in range(16):
            consider(list_dispatch(r, rev))

    while time.perf_counter() < begin + 1.45:
        consider(
            giffler(
                rng.randrange(26),
                reverse=rng.random() < 0.5,
                rng=rng,
                noise=rng.choice((2, 4, 7, 11, 17, 25, 40, 65, 100, 150)),
                randpick=rng.choice((0.02, 0.05, 0.08, 0.12, 0.18, 0.25, 0.34)),
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
            for i in range(l, r):
                arr[i] = x[i]
                used[x[i]] = True
            p = 0
            for val in y:
                if not used[val]:
                    while arr[p] != -1:
                        p += 1
                    arr[p] = val
                    used[val] = True
            c[ma] = arr
        return c

    pool.sort(key=lambda z: z[0])
    while len(pool) >= 2 and time.perf_counter() < begin + 1.9:
        i = rng.randrange(min(14, len(pool)))
        j = rng.randrange(min(30, len(pool)))
        if i != j:
            consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_seq(best_seq)

    def crit_path(seq):
        val, starts, pred, end = eval_seq(seq, True)
        if starts is None:
            return val, set()
        s = set()
        u = end
        while u != -1:
            s.add(u)
            u = pred[u]
        return val, s

    def critical_moves(seq, broad=False, wide=False):
        val, crit = crit_path(seq)
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
                cand = [
                    ("s", ma, b[0], b[0] + 1),
                    ("s", ma, b[-1] - 1, b[-1]),
                    ("i", ma, b[0], b[-1] + 1),
                    ("i", ma, b[-1], b[0]),
                ]
                if len(b) >= 3:
                    cand.append(("s", ma, b[0], b[-1]))
                if broad:
                    for t in range(len(b) - 1):
                        cand.append(("s", ma, b[t], b[t + 1]))
                    ends = [b[0], b[-1]]
                    if len(b) > 3:
                        ends += [b[1], b[-2]]
                    for x in ends:
                        for d in (-8, -7, -6, -5, -4, -3, -2, 2, 3, 4, 5, 6, 7, 8):
                            y = x + d
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                if wide:
                    lim = b if len(b) <= 8 else [b[0], b[1], b[2], b[-3], b[-2], b[-1]]
                    targets = set()
                    for x in lim:
                        targets.add(x)
                        targets.add(x + 1)
                    targets.add(b[0])
                    targets.add(b[-1] + 1)
                    for x in lim:
                        for y in targets:
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                    if len(b) <= 8:
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
            pos = b - 1 if b > a else b
            x = arr.pop(pos)
            arr.insert(a, x)

    def descent(seq, val, stop, broad=True, wide=False):
        while time.perf_counter() < stop:
            moves = critical_moves(seq, broad, wide)
            if not moves:
                break
            best_mv = None
            best_local = val
            for mv in moves:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < best_local:
                    best_local = v
                    best_mv = mv
            if best_mv is None:
                break
            apply(seq, best_mv)
            val = best_local
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, begin + 2.55, True, True)

    current = cp(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        moves = critical_moves(current, broad=(it % 5 != 0), wide=(it % 11 == 0))
        if not moves:
            current = cp(best_seq)
            current_val = best_val
            moves = critical_moves(current, True, True)
            if not moves:
                break

        chosen = None
        chosen_val = inf
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
            if v >= inf:
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
            if stagn > 10:
                break
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 7 + rng.randrange(19)

        if current_val < best_val:
            best_val = current_val
            best_seq = cp(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(
                    current, current_val, min(deadline, time.perf_counter() + 0.13), True, False
                )
                if current_val < best_val:
                    best_val = current_val
                    best_seq = cp(current)
        else:
            stagn += 1

        if it % 47 == 0 or (stagn > 75 and current_val > best_val + 25):
            current = cp(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                ml = critical_moves(current, True, True)
                if not ml:
                    break
                mv = ml[rng.randrange(len(ml))]
                apply(current, mv)
                v = eval_seq(current)
                if v >= inf:
                    undo(current, mv)
            current_val = eval_seq(current)

    return Schedule.from_job_sequences(instance, best_seq)