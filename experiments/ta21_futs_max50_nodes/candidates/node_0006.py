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
        mj, dj = [], []
        for op in job:
            mj.append(int(getattr(op, "machine_id", getattr(op, "machine", 0))))
            dj.append(int(getattr(op, "duration", getattr(op, "processing_time", 0))))
        machines.append(mj)
        durations.append(dj)

    op_count = [len(x) for x in machines]
    total_ops = sum(op_count)
    width = max(max(op_count), m)
    nnodes = n * width
    INF = 10 ** 12

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
        for k in range(op_count[j]):
            machine_load[machines[j][k]] += durations[j][k]

    def evaluate(seq, info=False):
        indeg = [0] * nnodes
        succ = [[] for _ in range(nnodes)]
        for j in range(n):
            for k in range(op_count[j] - 1):
                a, b = nid(j, k), nid(j, k + 1)
                succ[a].append(b)
                indeg[b] += 1

        for ma in range(m):
            arr = seq[ma]
            if len(arr) != n:
                return (INF, None, None, -1) if info else INF
            seen = [False] * n
            last = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, -1) if info else INF
                seen[j] = True
                k = op_of_machine[j][ma]
                if k < 0:
                    return (INF, None, None, -1) if info else INF
                u = nid(j, k)
                if last >= 0:
                    succ[last].append(u)
                    indeg[u] += 1
                last = u

        q = [u for u in real_nodes if indeg[u] == 0]
        st = [0] * nnodes
        pred = [-1] * nnodes
        head = 0
        cnt = 0
        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            j, k = u // width, u % width
            ft = st[u] + durations[j][k]
            for v in succ[u]:
                if ft > st[v]:
                    st[v] = ft
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if cnt != total_ops:
            return (INF, None, None, -1) if info else INF

        best, end = 0, -1
        for j in range(n):
            for k in range(op_count[j]):
                u = nid(j, k)
                c = st[u] + durations[j][k]
                if c > best:
                    best, end = c, u
        return (best, st, pred, end) if info else best

    rmachines = [list(reversed(x)) for x in machines]
    rdurations = [list(reversed(x)) for x in durations]
    rrem = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + rdurations[j][k]
        rrem.append(r)

    def keyval(rule, j, k, ma, jr, mr, ds, rr):
        p = ds[j][k]
        est = max(jr[j], mr[ma])
        ect = est + p
        tail = rr[j][k + 1]
        rw = rr[j][k]
        ops = len(ds[j]) - k
        tw = total_work[j]
        ml = machine_load[ma]
        if rule == 0: return ect - 0.32 * rw - 0.7 * p
        if rule == 1: return ect + 0.35 * tail - 0.25 * rw
        if rule == 2: return est - 0.55 * rw - 1.2 * p
        if rule == 3: return p + 0.4 * est - 0.18 * rw
        if rule == 4: return -p + 0.6 * est - 0.16 * rw
        if rule == 5: return -rw + 0.22 * ect
        if rule == 6: return tail + 0.3 * ect - 0.15 * tw
        if rule == 7: return ops * 35 + ect - 0.22 * rw
        if rule == 8: return -ops * 50 + est - 0.18 * rw
        if rule == 9: return mr[ma] + 0.35 * jr[j] - 0.30 * rw - 0.5 * p
        if rule == 10: return ect + 0.02 * ml - 0.28 * rw
        if rule == 11: return est + 1.7 * p - 0.23 * rw - 0.1 * tail
        if rule == 12: return ect - 0.16 * tw - 0.35 * p
        if rule == 13: return est - 0.25 * rw + 0.35 * tail - p
        if rule == 14: return mr[ma] - 0.20 * jr[j] + 0.2 * p - 0.26 * rw
        if rule == 15: return ect - 0.38 * rw + 0.12 * tail - 0.2 * p
        if rule == 16: return est * 0.55 - 2.0 * p + 0.12 * tail
        if rule == 17: return ect - 0.20 * rw + 0.50 * tail
        if rule == 18: return jr[j] - 0.25 * rw - p
        return ect - 0.22 * rw

    def build(rule, gt=True, reverse=False, rng=None, noise=0.0):
        ms = rmachines if reverse else machines
        ds = rdurations if reverse else durations
        rr = rrem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            cand = []
            if gt:
                bc = INF
                bm = 0
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        c = max(jr[j], mr[ma]) + ds[j][k]
                        if c < bc:
                            bc, bm = c, ma
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]) and ms[j][k] == bm and jr[j] < bc:
                        v = keyval(rule, j, k, bm, jr, mr, ds, rr)
                        if rng is not None:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        v = keyval(rule, j, k, ma, jr, mr, ds, rr)
                        if rng is not None:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
            cand.sort()
            if rng is not None and len(cand) > 1 and noise > 0 and rng.random() < 0.30:
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
            return [list(reversed(seq[ma])) for ma in range(m)]
        return seq

    def copyseq(s):
        return [x[:] for x in s]

    rng = random.Random(9121021)
    start = time.perf_counter()
    deadline = start + 4.65

    best_seq = None
    best_val = INF

    def consider(s):
        nonlocal best_seq, best_val
        v = evaluate(s)
        if v < best_val:
            best_val = v
            best_seq = copyseq(s)
        return v

    pool = []
    for rev in (False, True):
        for gt in (True, False):
            for r in range(19):
                s = build(r, gt, rev)
                v = consider(s)
                pool.append((v, copyseq(s)))

    while time.perf_counter() < deadline - 3.35:
        r = rng.randrange(19)
        s = build(r, True, rng.random() < 0.5, rng, rng.choice((3, 7, 13, 24, 40, 70)))
        v = consider(s)
        pool.append((v, copyseq(s)))

    def critical_path(seq):
        val, st, pred, end = evaluate(seq, True)
        if st is None:
            return val, set()
        cp = set()
        u = end
        while u != -1:
            cp.add(u)
            u = pred[u]
        return val, cp

    def moves(seq, broad=True):
        val, cp = critical_path(seq)
        out = []
        used = set()
        for ma in range(m):
            arr = seq[ma]
            pos = []
            for i, j in enumerate(arr):
                k = op_of_machine[j][ma]
                if k >= 0 and nid(j, k) in cp:
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
                cand = [("swap", ma, b[0], b[0] + 1), ("swap", ma, b[-1] - 1, b[-1])]
                if len(b) >= 3:
                    cand += [("insert", ma, b[0], b[-1] + 1), ("insert", ma, b[-1], b[0])]
                if broad:
                    if len(b) >= 3:
                        cand += [("swap", ma, b[1], b[1] + 1), ("swap", ma, b[-2] - 1, b[-2])]
                    if len(b) >= 4:
                        cand += [("swap", ma, b[0], b[-1]), ("insert", ma, b[1], b[-1] + 1), ("insert", ma, b[-2], b[0])]
                    for p in b:
                        for d in (-5, -4, -3, -2, 2, 3, 4, 5):
                            q = p + d
                            if 0 <= q <= n and q != p:
                                cand.append(("insert", ma, p, q))
                for mv in cand:
                    typ, ma2, a, b2 = mv
                    if typ == "swap":
                        if 0 <= a < n and 0 <= b2 < n and a != b2 and mv not in used:
                            used.add(mv); out.append(mv)
                    else:
                        if 0 <= a < n and 0 <= b2 <= n and a != b2 and mv not in used:
                            used.add(mv); out.append(mv)
        rng.shuffle(out)
        return out

    def apply(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo(seq, mv):
        typ, ma, a, b = mv
        arr = seq[ma]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            p = b - 1 if b > a else b
            x = arr.pop(p)
            arr.insert(a, x)

    def descent(seq, val, stop, broad=True, passes=60):
        for _ in range(passes):
            if time.perf_counter() >= stop:
                break
            bm = None
            bv = val
            for mv in moves(seq, broad):
                if time.perf_counter() >= stop:
                    break
                apply(seq, mv)
                v = evaluate(seq)
                undo(seq, mv)
                if v < bv:
                    bv = v
                    bm = mv
            if bm is None:
                break
            apply(seq, bm)
            val = bv
        return seq, val

    pool.sort(key=lambda x: x[0])
    for v, s in pool[:3]:
        if time.perf_counter() >= deadline - 2.70:
            break
        s, v = descent(s, v, deadline - 2.70, True, 35)
        consider(s)

    cur = copyseq(best_seq)
    curv = best_val
    tabu = {}
    it = 0

    while time.perf_counter() < deadline - 0.85:
        it += 1
        mvlist = moves(cur, True)
        if not mvlist:
            break
        cmv, cv, ckey = None, INF, None
        for mv in mvlist:
            if time.perf_counter() >= deadline - 0.85:
                break
            typ, ma, a, b = mv
            arr = cur[ma]
            if typ == "swap":
                key = (ma, min(arr[a], arr[b]), max(arr[a], arr[b]), 0)
            else:
                key = (ma, arr[a], -1 if b >= len(arr) else arr[b], 1)
            apply(cur, mv)
            v = evaluate(cur)
            undo(cur, mv)
            if v >= INF:
                continue
            if (tabu.get(key, 0) <= it or v < best_val) and v < cv:
                cmv, cv, ckey = mv, v, key
        if cmv is None:
            break
        apply(cur, cmv)
        curv = cv
        tabu[ckey] = it + 8 + rng.randrange(11)
        if curv < best_val:
            best_val = curv
            best_seq = copyseq(cur)
            if time.perf_counter() < deadline - 0.95:
                tmp = copyseq(best_seq)
                tmp, tv = descent(tmp, best_val, deadline - 0.94, False, 4)
                if tv < best_val:
                    best_val = tv
                    best_seq = copyseq(tmp)
                    cur = copyseq(tmp)
                    curv = tv
        if it % 35 == 0 and curv > best_val + 90:
            cur = copyseq(best_seq)
            curv = best_val

    cur = copyseq(best_seq)
    curv = best_val
    temp0 = max(20.0, best_val / 80.0)
    it = 0
    while time.perf_counter() < deadline:
        it += 1
        if rng.random() < 0.22:
            ml = moves(cur, False)
            if ml:
                mv = ml[0]
            else:
                mv = ("swap", rng.randrange(m), rng.randrange(n - 1), rng.randrange(1, n))
        elif rng.random() < 0.72:
            ma = rng.randrange(m)
            i = rng.randrange(n - 1)
            mv = ("swap", ma, i, i + 1)
        else:
            ma = rng.randrange(m)
            a = rng.randrange(n)
            b = rng.randrange(n)
            if a == b:
                continue
            mv = ("insert", ma, a, b)
        apply(cur, mv)
        v = evaluate(cur)
        if v < INF:
            if v <= curv:
                acc = True
            else:
                frac = (time.perf_counter() - start) / max(0.001, deadline - start)
                temp = temp0 * (1.0 - min(1.0, frac)) + 0.05
                acc = rng.random() < math.exp((curv - v) / temp)
            if acc:
                curv = v
                if v < best_val:
                    best_val = v
                    best_seq = copyseq(cur)
            else:
                undo(cur, mv)
        else:
            undo(cur, mv)
        if it % 250 == 0 and curv > best_val + 75:
            cur = copyseq(best_seq)
            curv = best_val

    return Schedule.from_job_sequences(instance, best_seq)