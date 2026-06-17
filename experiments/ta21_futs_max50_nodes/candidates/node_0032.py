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
    num_nodes = n * width
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
            if 0 <= ma < m:
                machine_load[ma] += durations[j][k]

    base_succ = [[] for _ in range(num_nodes)]
    base_indeg = [0] * num_nodes
    for j in range(n):
        for k in range(op_count[j] - 1):
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
                k = op_of_machine[j][ma]
                if k < 0:
                    return (INF, None, None, None) if info else INF
                u = nid(j, k)
                if prev >= 0:
                    succ[prev].append(u)
                    indeg[u] += 1
                prev = u

        q = [u for u in real_nodes if indeg[u] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        cnt = 0
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
                    best, end = c, u
        return (best, start, pred, end) if info else best

    rev_machines = [list(reversed(x)) for x in machines]
    rev_durations = [list(reversed(x)) for x in durations]

    def make_rem(ds):
        rr = []
        for j in range(n):
            r = [0] * (len(ds[j]) + 1)
            for k in range(len(ds[j]) - 1, -1, -1):
                r[k] = r[k + 1] + ds[j][k]
            rr.append(r)
        return rr

    rev_rem = make_rem(rev_durations)

    def score_rule(rule, j, k, ma, jr, mr, ds, rr):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        rw = rr[j][k]
        tail = rr[j][k + 1]
        tw = total_work[j]
        ml = machine_load[ma]
        if rule == 0:
            return ect - .55 * rw - .60 * p
        if rule == 1:
            return est - .75 * rw - .25 * p + .20 * tail
        if rule == 2:
            return ect - .90 * rw + .40 * tail - .50 * p
        if rule == 3:
            return jr[j] + .35 * mr[ma] - .65 * rw - .85 * p
        if rule == 4:
            return ect - .45 * tw - .10 * p
        if rule == 5:
            return mr[ma] + .15 * jr[j] - .42 * rw + .04 * ml
        if rule == 6:
            return ect + .35 * tail - .72 * rw - .15 * p
        if rule == 7:
            return est + .80 * p - .55 * rw + .18 * tail
        if rule == 8:
            return ect - .28 * rw - 1.15 * p
        if rule == 9:
            return est - .50 * rw + .70 * tail - .35 * p
        if rule == 10:
            return ect - .70 * rw + .12 * ml - .20 * p
        if rule == 11:
            return jr[j] + .70 * mr[ma] - .55 * rw + .10 * tail
        if rule == 12:
            return ect - .35 * rw + 1.35 * p - .10 * tw
        if rule == 13:
            return est - .68 * rw - .65 * p + .28 * tail
        if rule == 14:
            return ect - .82 * rw + .32 * tail - .35 * p
        if rule == 15:
            return jr[j] - .72 * rw - .35 * p + .18 * mr[ma]
        if rule == 16:
            return ect - .50 * rw - .95 * p + .05 * ml
        if rule == 17:
            return max(jr[j], mr[ma] + .2 * p) - .40 * rw
        if rule == 18:
            return ect - .62 * rw + .80 * tail - .25 * p
        if rule == 19:
            return est - .10 * rw + .60 * p + .04 * ml
        if rule == 20:
            return ect - .98 * rw + .55 * tail - .75 * p
        if rule == 21:
            return jr[j] + .12 * mr[ma] - .78 * rw - .15 * p
        if rule == 22:
            return ect + .20 * tail - .20 * tw - .45 * rw
        if rule == 23:
            return mr[ma] - .30 * jr[j] + .10 * p - .30 * rw
        return ect - .4 * rw

    def giffler(rule, reverse=False, rng=None, noise=0.0, randpick=0.0):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rr = rev_rem if reverse else rem
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
                    val = score_rule(rule, j, k, target, jr, mr, ds, rr)
                    if rng is not None and noise:
                        val += rng.uniform(-noise, noise)
                    cand.append((val, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        val = score_rule(rule, j, k, ma, jr, mr, ds, rr)
                        if rng is not None and noise:
                            val += rng.uniform(-noise, noise)
                        cand.append((val, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randpick:
                j = cand[rng.randrange(min(6, len(cand)))][1]
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
        return [list(reversed(x)) for x in seq] if reverse else seq

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
            best_key = None
            chosen = 0
            for j in range(n):
                k = nxt[j]
                if k >= len(ms[j]):
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
                    key = (-rw, ect, j)
                elif rule == 2:
                    key = (est - .55 * rw - .25 * p, ect, j)
                elif rule == 3:
                    key = (ect - .70 * rw + .20 * tail - .40 * p, j)
                elif rule == 4:
                    key = (jr[j] + .40 * mr[ma] - .55 * rw - .30 * p, j)
                elif rule == 5:
                    key = (ect - .35 * total_work[j] - .20 * rw, j)
                elif rule == 6:
                    key = (machine_load[ma] * .035 + ect - .40 * rw - .45 * p, j)
                elif rule == 7:
                    key = (mr[ma], -rw, ect, j)
                elif rule == 8:
                    key = (est - .75 * rw - .55 * p + .25 * tail, ect, j)
                elif rule == 9:
                    key = (ect - .92 * rw + .45 * tail - .62 * p, j)
                elif rule == 10:
                    key = (p, est, -rw, j)
                elif rule == 11:
                    key = (-p, est, -rw, j)
                else:
                    key = (score_rule(rule % 24, j, k, ma, jr, mr, ds, rr), j)
                if best_key is None or key < best_key:
                    best_key = key
                    chosen = j
            k = nxt[chosen]
            ma = ms[chosen][k]
            ft = max(jr[chosen], mr[ma]) + ds[chosen][k]
            seq[ma].append(chosen)
            jr[chosen] = ft
            mr[ma] = ft
            nxt[chosen] += 1
            done += 1
        return [list(reversed(x)) for x in seq] if reverse else seq

    rng = random.Random(9121021)
    start_time = time.perf_counter()
    deadline = start_time + 7.6

    def cp(seq):
        return [x[:] for x in seq]

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
            if len(pool) > 42:
                pool.sort(key=lambda z: z[0])
                pool = pool[:42]
        return v

    for rev in (False, True):
        for r in range(24):
            consider(giffler(r, rev))
        for r in range(18):
            consider(list_dispatch(r, rev))

    while time.perf_counter() < start_time + 1.35:
        consider(giffler(rng.randrange(24), rng=rng, reverse=rng.random() < .5,
                         noise=rng.choice((1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144)),
                         randpick=rng.choice((.04, .07, .10, .14, .18, .24, .32))))

    def crossover(a, b):
        child = [[] for _ in range(m)]
        for ma in range(m):
            x, y = (a[ma], b[ma]) if rng.random() < .5 else (b[ma], a[ma])
            c1 = rng.randrange(n)
            c2 = rng.randrange(c1, n)
            arr = [-1] * n
            used = [False] * n
            for i in range(c1, c2):
                arr[i] = x[i]
                used[x[i]] = True
            ptr = 0
            for v in y:
                if not used[v]:
                    while arr[ptr] != -1:
                        ptr += 1
                    arr[ptr] = v
                    used[v] = True
            child[ma] = arr
        return child

    if len(pool) > 1:
        pool.sort(key=lambda z: z[0])
        lim = start_time + 1.75
        while time.perf_counter() < lim:
            i = rng.randrange(min(len(pool), 16))
            j = rng.randrange(min(len(pool), 28))
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

    def critical_moves(seq, broad=True, wider=False):
        v, crit = critical(seq)
        if not crit:
            return []
        moves = []
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
                cand = [("s", ma, b[0], b[0] + 1), ("s", ma, b[-1] - 1, b[-1])]
                if len(b) >= 3:
                    cand += [("s", ma, b[0], b[-1]), ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if broad:
                    for t in range(len(b) - 1):
                        cand.append(("s", ma, b[t], b[t + 1]))
                    edge = (b[0], b[-1])
                    rngs = (-9, -7, -5, -3, -2, 2, 3, 5, 7, 9) if wider else (-6, -4, -3, -2, 2, 3, 4, 6)
                    for x in edge:
                        for d in rngs:
                            y = x + d
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                if wider:
                    sample = b if len(b) <= 7 else [b[0], b[1], b[2], b[-3], b[-2], b[-1]]
                    for x in sample:
                        for y in (0, b[0], b[0] + 1, b[-1], b[-1] + 1, n):
                            if 0 <= y <= n and y != x and y != x + 1:
                                cand.append(("i", ma, x, y))
                for mv in cand:
                    typ, ma2, a, bb = mv
                    if typ == "s":
                        ok = 0 <= a < n and 0 <= bb < n and a != bb
                    else:
                        ok = 0 <= a < n and 0 <= bb <= n and a != bb and bb != a + 1
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

    def descent(seq, val, stop, broad=True, wider=True):
        while time.perf_counter() < stop:
            best_mv = None
            best_v = val
            moves = critical_moves(seq, broad, wider)
            if not moves:
                break
            for mv in moves:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_seq(seq)
                undo(seq, mv)
                if v < best_v:
                    best_v = v
                    best_mv = mv
            if best_mv is None:
                break
            apply(seq, best_mv)
            val = best_v
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, start_time + 2.35, True, True)

    current = cp(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        moves = critical_moves(current, broad=(it % 6 != 0), wider=(it % 8 == 0))
        if not moves:
            current = cp(best_seq)
            current_val = best_val
            moves = critical_moves(current, True, True)
            if not moves:
                break

        chosen = None
        chosen_val = INF
        chosen_key = None
        max_scan = len(moves)
        if max_scan > 190 and time.perf_counter() > deadline - .8:
            max_scan = 190

        for mv in moves[:max_scan]:
            if time.perf_counter() >= deadline:
                break
            typ, ma, a, b = mv
            arr = current[ma]
            if typ == "s":
                key = (ma, arr[a], arr[b])
                revkey = (ma, arr[b], arr[a])
            else:
                key = (ma, arr[a], a, b)
                revkey = key
            apply(current, mv)
            v = eval_seq(current)
            undo(current, mv)
            if v >= INF:
                continue
            if tabu.get(key, 0) <= it and tabu.get(revkey, 0) <= it or v < best_val:
                if v < chosen_val or (v == chosen_val and rng.random() < .08):
                    chosen = mv
                    chosen_val = v
                    chosen_key = key

        if chosen is None:
            current = cp(best_seq)
            current_val = best_val
            stagn += 1
            if stagn > 9:
                break
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 6 + rng.randrange(18)

        if current_val < best_val:
            best_val = current_val
            best_seq = cp(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(current, current_val, min(deadline, time.perf_counter() + .16), True, False)
                if current_val < best_val:
                    best_val = current_val
                    best_seq = cp(current)
        else:
            stagn += 1

        if it % 37 == 0 or (stagn > 58 and current_val > best_val + 25):
            current = cp(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                mvlist = critical_moves(current, True, True)
                if not mvlist:
                    break
                mv = mvlist[rng.randrange(len(mvlist))]
                apply(current, mv)
                v = eval_seq(current)
                if v >= INF:
                    undo(current, mv)
            current_val = eval_seq(current)

    return Schedule.from_job_sequences(instance, best_seq)