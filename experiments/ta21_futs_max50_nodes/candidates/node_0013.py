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

    def node_id(j, k):
        return j * width + k

    real_nodes = [node_id(j, k) for j in range(n) for k in range(op_count[j])]

    op_of_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, mach in enumerate(machines[j]):
            if 0 <= mach < m:
                op_of_machine[j][mach] = k

    rem_work = []
    total_work = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem_work.append(r)
        total_work.append(r[0])

    machine_load = [0] * m
    for j in range(n):
        for k, mach in enumerate(machines[j]):
            if 0 <= mach < m:
                machine_load[mach] += durations[j][k]

    base_succ = [[] for _ in range(num_nodes)]
    base_indeg = [0] * num_nodes
    for j in range(n):
        for k in range(op_count[j] - 1):
            a = node_id(j, k)
            b = node_id(j, k + 1)
            base_succ[a].append(b)
            base_indeg[b] += 1

    def eval_sequence(seq, need_info=False):
        indeg = base_indeg[:]
        succ = [x[:] for x in base_succ]
        for mach in range(m):
            arr = seq[mach]
            if len(arr) != n:
                return (INF, None, None, None) if need_info else INF
            seen = [False] * n
            prev = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if need_info else INF
                seen[j] = True
                k = op_of_machine[j][mach]
                if k < 0:
                    return (INF, None, None, None) if need_info else INF
                cur = node_id(j, k)
                if prev >= 0:
                    succ[prev].append(cur)
                    indeg[cur] += 1
                prev = cur

        q = [u for u in real_nodes if indeg[u] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        cnt = 0
        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            j = u // width
            k = u % width
            fin = start[u] + durations[j][k]
            for v in succ[u]:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if cnt != total_ops:
            return (INF, None, None, None) if need_info else INF

        best = 0
        end_node = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = node_id(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end_node = u
        return (best, start, pred, end_node) if need_info else best

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

    rev_rem_work = make_rem(rev_durations)

    def pval(rule, j, k, mach, jr, mr, ds, rw):
        p = ds[j][k]
        est = max(jr[j], mr[mach])
        ect = est + p
        rem = rw[j][k]
        tail = rw[j][k + 1]
        ops_left = len(ds[j]) - k
        tw = total_work[j]
        ml = machine_load[mach]
        if rule == 0:
            return ect - 0.35 * rem - 0.7 * p
        if rule == 1:
            return ect - 0.25 * rem + 1.8 * p
        if rule == 2:
            return est - 0.55 * rem - 1.2 * p
        if rule == 3:
            return ect + 0.45 * tail - 0.25 * tw
        if rule == 4:
            return -rem + 0.15 * ect
        if rule == 5:
            return p + 0.3 * est - 0.18 * rem
        if rule == 6:
            return -p + 0.45 * est - 0.18 * rem
        if rule == 7:
            return ops_left * 45 + ect - 0.35 * rem
        if rule == 8:
            return -ops_left * 45 + ect - 0.22 * rem
        if rule == 9:
            return mr[mach] * 0.45 + jr[j] * 0.2 + p - 0.32 * rem
        if rule == 10:
            return ect + ml * 0.025 - 0.3 * rem - 0.5 * p
        if rule == 11:
            return est + 0.25 * p - 0.42 * rem + 0.06 * tail
        if rule == 12:
            return ect - 0.2 * tw - 0.2 * rem
        if rule == 13:
            return jr[j] - 0.35 * rem - 0.8 * p
        if rule == 14:
            return ect - 0.48 * tail - 0.18 * rem
        if rule == 15:
            return est + 1.4 * p - 0.22 * rem - 0.08 * tw
        if rule == 16:
            return ect + 0.35 * tail - 0.8 * p - 0.18 * rem
        if rule == 17:
            return mr[mach] - 0.3 * jr[j] + 0.1 * p - 0.25 * rem
        if rule == 18:
            return ect - 0.62 * rem + 0.8 * tail - 0.25 * p
        if rule == 19:
            return est - 0.12 * rem + 0.65 * p + 0.04 * ml
        if rule == 20:
            return ect - 0.45 * tw - 0.15 * p
        if rule == 21:
            return max(jr[j], mr[mach] + 0.2 * p) - 0.38 * rem
        if rule == 22:
            return ect - 0.55 * rem + 0.15 * ml - 0.15 * p
        if rule == 23:
            return est + 0.8 * p - 0.5 * rem + 0.25 * tail
        if rule == 24:
            return jr[j] + mr[mach] * 0.6 - 0.45 * rem - 0.35 * p
        if rule == 25:
            return ect - 0.72 * rem + 0.18 * tail - 0.08 * ml
        if rule == 26:
            return est + 0.55 * p - 0.62 * rem + 0.10 * tw
        if rule == 27:
            return jr[j] + 0.35 * mr[mach] - 0.58 * rem - 0.95 * p
        if rule == 28:
            return ect + 0.55 * tail - 0.52 * tw - 0.15 * p
        return ect - 0.2 * rem

    def giffler(rule, reverse=False, rng=None, noise=0.0, randpick=0.18):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem_work if reverse else rem_work
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
                    mach = ms[j][k]
                    c = max(jr[j], mr[mach]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target = mach
            cand = []
            for j in range(n):
                k = nxt[j]
                if k < len(ms[j]) and ms[j][k] == target and jr[j] < best_c:
                    val = pval(rule, j, k, target, jr, mr, ds, rw)
                    if rng is not None and noise:
                        val += rng.uniform(-noise, noise)
                    cand.append((val, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        mach = ms[j][k]
                        val = pval(rule, j, k, mach, jr, mr, ds, rw)
                        if rng is not None and noise:
                            val += rng.uniform(-noise, noise)
                        cand.append((val, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and rng.random() < randpick:
                chosen = cand[rng.randrange(min(5, len(cand)))][1]
            else:
                chosen = cand[0][1]
            k = nxt[chosen]
            mach = ms[chosen][k]
            ft = max(jr[chosen], mr[mach]) + ds[chosen][k]
            seq[mach].append(chosen)
            jr[chosen] = ft
            mr[mach] = ft
            nxt[chosen] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    def list_dispatch(rule, reverse=False):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem_work if reverse else rem_work
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
                mach = ms[j][k]
                p = ds[j][k]
                est = max(jr[j], mr[mach])
                ect = est + p
                rem = rw[j][k]
                tail = rw[j][k + 1]
                if rule == 0:
                    key = (ect, -rem, j)
                elif rule == 1:
                    key = (est, -p, -rem, j)
                elif rule == 2:
                    key = (-rem, ect, j)
                elif rule == 3:
                    key = (p, est, j)
                elif rule == 4:
                    key = (-p, est, j)
                elif rule == 5:
                    key = (tail, ect, j)
                elif rule == 6:
                    key = (ect - 0.22 * rem - 0.5 * p, j)
                elif rule == 7:
                    key = (mr[mach], -rem, ect, j)
                elif rule == 8:
                    key = (ect + 0.2 * tail - 0.15 * total_work[j], j)
                elif rule == 9:
                    key = (est + 1.2 * p - 0.28 * rem, j)
                elif rule == 10:
                    key = (ect - 0.5 * rem + 0.4 * tail, j)
                elif rule == 11:
                    key = (jr[j] + 0.15 * mr[mach] - 0.35 * rem, ect, j)
                elif rule == 12:
                    key = (machine_load[mach] * 0.04 + ect - 0.28 * rem - 0.3 * p, j)
                elif rule == 13:
                    key = (est - 0.45 * rem + 0.8 * tail - 0.4 * p, j)
                elif rule == 14:
                    key = (ect - 0.7 * rem + 0.2 * total_work[j], j)
                elif rule == 15:
                    key = (ect - 0.55 * rem - 0.2 * p + 0.22 * tail, j)
                elif rule == 16:
                    key = (jr[j] - 0.42 * rem + 0.5 * p, mr[mach], j)
                else:
                    key = (mr[mach] + 0.4 * jr[j] - 0.35 * rem + p, j)
                if best_key is None or key < best_key:
                    best_key = key
                    chosen = j
            k = nxt[chosen]
            mach = ms[chosen][k]
            ft = max(jr[chosen], mr[mach]) + ds[chosen][k]
            seq[mach].append(chosen)
            jr[chosen] = ft
            mr[mach] = ft
            nxt[chosen] += 1
            done += 1
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    rng = random.Random(7421127)
    begin = time.perf_counter()
    deadline = begin + 5.75

    best_seq = None
    best_val = INF
    pool = []

    def cpseq(seq):
        return [x[:] for x in seq]

    def consider(seq):
        nonlocal best_seq, best_val, pool
        v = eval_sequence(seq)
        if v < INF:
            pool.append((v, cpseq(seq)))
            if len(pool) > 18:
                pool.sort(key=lambda x: x[0])
                pool = pool[:18]
        if v < best_val:
            best_val = v
            best_seq = cpseq(seq)
        return v

    for rev in (False, True):
        for r in range(29):
            consider(giffler(r, reverse=rev))
        for r in range(18):
            consider(list_dispatch(r, reverse=rev))

    while time.perf_counter() < begin + 1.08:
        consider(giffler(rng.randrange(29), reverse=(rng.random() < 0.5), rng=rng,
                         noise=rng.choice((1, 3, 6, 10, 16, 26, 42, 65, 95)),
                         randpick=rng.choice((0.08, 0.14, 0.20, 0.28))))

    def crossover(a, b):
        child = [[] for _ in range(m)]
        for mach in range(m):
            if rng.random() < 0.5:
                x, y = a[mach], b[mach]
            else:
                x, y = b[mach], a[mach]
            cut1 = rng.randrange(n)
            cut2 = rng.randrange(cut1, n)
            used = [False] * n
            arr = [-1] * n
            for i in range(cut1, cut2):
                arr[i] = x[i]
                used[x[i]] = True
            ptr = 0
            for val in y:
                if not used[val]:
                    while arr[ptr] != -1:
                        ptr += 1
                    arr[ptr] = val
                    used[val] = True
            child[mach] = arr
        return child

    if len(pool) >= 2:
        pool.sort(key=lambda x: x[0])
        tlim = begin + 1.32
        while time.perf_counter() < tlim:
            i = rng.randrange(min(8, len(pool)))
            j = rng.randrange(min(12, len(pool)))
            if i != j:
                consider(crossover(pool[i][1], pool[j][1]))

    if best_seq is None:
        best_seq = giffler(0)
        best_val = eval_sequence(best_seq)

    def critical_path(seq):
        val, starts, pred, end = eval_sequence(seq, True)
        if starts is None:
            return val, set()
        crit = set()
        u = end
        while u != -1:
            crit.add(u)
            u = pred[u]
        return val, crit

    def moves_on_critical(seq, broad=False, allblocks=False):
        val, crit = critical_path(seq)
        if not crit:
            return []
        moves = []
        seen = set()
        for mach in range(m):
            arr = seq[mach]
            pos = []
            for i, j in enumerate(arr):
                k = op_of_machine[j][mach]
                if k >= 0 and node_id(j, k) in crit:
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
                cand = [
                    ("s", mach, b[0], b[0] + 1),
                    ("s", mach, b[-1] - 1, b[-1]),
                ]
                if len(b) >= 3:
                    cand.append(("i", mach, b[0], b[-1] + 1))
                    cand.append(("i", mach, b[-1], b[0]))
                    cand.append(("s", mach, b[0], b[-1]))
                if broad:
                    for i in range(len(b) - 1):
                        cand.append(("s", mach, b[i], b[i + 1]))
                    for x in (b[0], b[-1]):
                        for d in (-6, -5, -4, -3, -2, 2, 3, 4, 5, 6):
                            y = x + d
                            if 0 <= y < n and y != x:
                                cand.append(("i", mach, x, y))
                    if allblocks:
                        lim = b if len(b) <= 8 else [b[0], b[1], b[2], b[-3], b[-2], b[-1]]
                        for x in lim:
                            for y in (b[0], b[0] + 1, b[-1], b[-1] + 1):
                                if 0 <= y <= n and x != y and y != x + 1:
                                    cand.append(("i", mach, x, y))
                for mv in cand:
                    typ, ma, a, b2 = mv
                    if typ == "s":
                        if not (0 <= a < n and 0 <= b2 < n and a != b2):
                            continue
                    else:
                        if not (0 <= a < n and 0 <= b2 <= n and a != b2 and b2 != a + 1):
                            continue
                    if mv not in seen:
                        seen.add(mv)
                        moves.append(mv)
        rng.shuffle(moves)
        return moves

    def apply(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "s":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "s":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            pos = b - 1 if b > a else b
            x = arr.pop(pos)
            arr.insert(a, x)

    def descent(seq, val, stop, broad=True, allblocks=False):
        while time.perf_counter() < stop:
            best_mv = None
            best_local = val
            moves = moves_on_critical(seq, broad, allblocks)
            if not moves:
                break
            for mv in moves:
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = eval_sequence(seq)
                undo(seq, mv)
                if v < best_local:
                    best_local = v
                    best_mv = mv
            if best_mv is None:
                break
            apply(seq, best_mv)
            val = best_local
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, begin + 1.78, True, True)

    current = cpseq(best_seq)
    current_val = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        broad = (it % 5 != 0)
        allblocks = (it % 9 == 0)
        moves = moves_on_critical(current, broad, allblocks)
        if not moves:
            current = cpseq(best_seq)
            current_val = best_val
            moves = moves_on_critical(current, True, True)
            if not moves:
                break

        chosen = None
        chosen_val = INF
        chosen_key = None

        for mv in moves:
            if time.perf_counter() >= deadline:
                break
            typ, mach, a, b = mv
            arr = current[mach]
            if typ == "s":
                key = (mach, arr[a], arr[b])
                revkey = (mach, arr[b], arr[a])
            else:
                key = (mach, arr[a], a, b)
                revkey = key
            apply(current, mv)
            v = eval_sequence(current)
            undo(current, mv)
            if v >= INF:
                continue
            aspiration = v < best_val
            if (tabu.get(key, 0) <= it and tabu.get(revkey, 0) <= it) or aspiration:
                if v < chosen_val or (v == chosen_val and rng.random() < 0.10):
                    chosen_val = v
                    chosen = mv
                    chosen_key = key

        if chosen is None:
            current = cpseq(best_seq)
            current_val = best_val
            stagn += 1
            if stagn > 6:
                break
            continue

        apply(current, chosen)
        current_val = chosen_val
        tabu[chosen_key] = it + 5 + rng.randrange(15)

        if current_val < best_val:
            best_val = current_val
            best_seq = cpseq(current)
            stagn = 0
            if time.perf_counter() < deadline:
                current, current_val = descent(current, current_val, min(deadline, time.perf_counter() + 0.16), True, False)
                if current_val < best_val:
                    best_val = current_val
                    best_seq = cpseq(current)
        else:
            stagn += 1

        if it % 39 == 0 or (stagn > 58 and current_val > best_val + 35):
            current = cpseq(best_seq)
            current_val = best_val
            stagn = 0
            for _ in range(2 + rng.randrange(5)):
                mvlist = moves_on_critical(current, True, True)
                if not mvlist:
                    break
                mv = mvlist[rng.randrange(len(mvlist))]
                apply(current, mv)
                v = eval_sequence(current)
                if v >= INF:
                    undo(current, mv)
            current_val = eval_sequence(current)

    return Schedule.from_job_sequences(instance, best_seq)