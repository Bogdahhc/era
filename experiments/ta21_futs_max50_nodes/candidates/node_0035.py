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

    op_count = [len(x) for x in machines]
    total_ops = sum(op_count)
    if total_ops == 0:
        return Schedule.from_job_sequences(instance, [[] for _ in range(m)])

    width = max(max(op_count), m)
    num_nodes = n * width
    inf = 10**12

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
                return (inf, None, None, None) if info else inf
            seen = [False] * n
            prev = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (inf, None, None, None) if info else inf
                seen[j] = True
                k = op_of_machine[j][ma]
                if k < 0:
                    return (inf, None, None, None) if info else inf
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
            j, k = u // width, u % width
            fin = start[u] + durations[j][k]
            for v in succ[u]:
                if fin > start[v]:
                    start[v] = fin
                    pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)
        if cnt != total_ops:
            return (inf, None, None, None) if info else inf
        best = 0
        end = -1
        for j in range(n):
            for k in range(op_count[j]):
                u = nid(j, k)
                c = start[u] + durations[j][k]
                if c > best:
                    best = c
                    end = u
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
        est = jr[j] if jr[j] > mr[ma] else mr[ma]
        ect = est + p
        r = rw[j][k]
        tail = rw[j][k + 1]
        tw = total_work[j]
        ml = machine_load[ma]
        slack = r - p
        vals = (
            ect - .35*r - .70*p,
            est - .60*r - .25*p,
            ect - .80*r + .30*tail - .20*p,
            jr[j] + .45*mr[ma] - .55*r - .55*p,
            ect - .48*tw - .10*p,
            est + 1.15*p - .35*r,
            ect + .35*tail - .70*r,
            mr[ma] + .20*jr[j] + .25*p - .45*r,
            ect - .28*r - 1.10*p + .04*ml,
            est - .72*r - .55*p + .25*tail,
            ect - .55*r + .12*ml - .25*p,
            jr[j] - .64*r + .28*mr[ma] - .70*p,
            ect - .92*r + .52*tail - .45*p,
            est - .30*r + .90*p + .03*ml,
            ect - .62*r - .62*p + .15*tail,
            jr[j] + .72*mr[ma] - .50*r + .10*tail,
            ect - .40*tw - .22*r - .20*p,
            est - .78*r - .20*p + .40*tail,
            ect + .25*tail - .72*r - .75*p,
            mr[ma] - .20*jr[j] - .32*r + .15*p,
            ect - .30*r + .85*p - .18*tw,
            est - .50*r - .95*p,
            ect - .68*r + .20*tail + .04*ml,
            jr[j] + .18*mr[ma] - .70*r - .30*p,
            ect - .82*r + .38*tail - .30*p,
            est + .45*p - .62*r + .08*tw,
            ect - .52*tw + .55*tail - .12*p,
            jr[j] + .35*mr[ma] - .58*r - .95*p,
            ect - .45*r - 1.25*p,
            est - .66*r - .40*p + .18*ml,
            ect - .75*r + .10*tail - .55*p,
            jr[j] - .60*r + .50*p,
            ect - .95*slack - .55*p + .10*ml,
            est - .85*r - .10*mr[ma] - .35*p,
            ect - .30*tw - .65*r - .80*p,
            jr[j] + mr[ma] - .70*r - .45*p,
            est + .20*tail - .90*r - .70*p,
            ect - 1.05*r + .70*tail - .20*p,
            est - .45*tw - .15*r - .50*p,
            mr[ma] + .55*p - .80*r,
        )
        return vals[rule % len(vals)]

    def construct(rule, reverse=False, giffler=True, rng=None, noise=0.0, randpick=0.0):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem if reverse else rem
        jr = [0] * n
        mr = [0] * m
        nxt = [0] * n
        seq = [[] for _ in range(m)]
        done = 0
        while done < total_ops:
            target = -1
            bestc = inf
            if giffler:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        c = max(jr[j], mr[ma]) + ds[j][k]
                        if c < bestc:
                            bestc = c
                            target = ma
            cand = []
            for j in range(n):
                k = nxt[j]
                if k >= len(ms[j]):
                    continue
                ma = ms[j][k]
                if (not giffler) or (ma == target and jr[j] < bestc):
                    v = priority(rule, j, k, ma, jr, mr, ds, rw)
                    if rng is not None and noise:
                        v += rng.uniform(-noise, noise)
                    cand.append((v, j))
            if not cand:
                for j in range(n):
                    k = nxt[j]
                    if k < len(ms[j]):
                        ma = ms[j][k]
                        v = priority(rule, j, k, ma, jr, mr, ds, rw)
                        if rng is not None and noise:
                            v += rng.uniform(-noise, noise)
                        cand.append((v, j))
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
        if reverse:
            return [list(reversed(x)) for x in seq]
        return seq

    rng = random.Random(210021)
    begin = time.perf_counter()
    deadline = begin + 8.8
    best_seq = None
    best_val = inf
    pool = []

    def copy_seq(s):
        return [x[:] for x in s]

    def consider(s):
        nonlocal best_seq, best_val, pool
        v = eval_seq(s)
        if v < inf:
            if v < best_val:
                best_val = v
                best_seq = copy_seq(s)
            pool.append((v, copy_seq(s)))
            if len(pool) > 40:
                pool.sort(key=lambda z: z[0])
                pool = pool[:40]
        return v

    for rev in (False, True):
        for r in range(40):
            consider(construct(r, rev, True))
            consider(construct(r, rev, False))

    while time.perf_counter() < begin + 1.45:
        consider(construct(rng.randrange(40), rng.random() < .5, rng.random() < .82, rng,
                           rng.choice((1, 2, 4, 7, 11, 17, 25, 38, 55, 80, 120)),
                           rng.choice((.03, .06, .10, .15, .21, .30, .42))))

    if best_seq is None:
        best_seq = construct(0)
        best_val = eval_seq(best_seq)

    def critical(seq):
        v, st, pr, end = eval_seq(seq, True)
        if st is None:
            return v, set()
        c = set()
        u = end
        while u != -1:
            c.add(u)
            u = pr[u]
        return v, c

    def moves(seq, broad=False, allpos=False):
        _, crit = critical(seq)
        out = []
        seen = set()
        if not crit:
            return out
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
                if len(b) > 2:
                    cand += [("s", ma, b[0], b[-1]), ("i", ma, b[0], b[-1] + 1), ("i", ma, b[-1], b[0])]
                if broad:
                    for i in range(len(b) - 1):
                        cand.append(("s", ma, b[i], b[i + 1]))
                    endpoints = [b[0], b[-1]]
                    if len(b) > 3:
                        endpoints += [b[1], b[-2]]
                    for x in endpoints:
                        if allpos:
                            rngs = range(n + 1)
                        else:
                            rngs = (x - 9, x - 7, x - 5, x - 3, x - 2, x + 2, x + 3, x + 5, x + 7, x + 9)
                        for y in rngs:
                            if 0 <= y <= n:
                                cand.append(("i", ma, x, y))
                for mv in cand:
                    typ, mm, a, z = mv
                    if typ == "s":
                        ok = 0 <= a < n and 0 <= z < n and a != z
                    else:
                        ok = 0 <= a < n and 0 <= z <= n and z != a and z != a + 1
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

    def descent(seq, val, stop, exhaustive=False):
        while time.perf_counter() < stop:
            best_mv = None
            best_v = val
            for mv in moves(seq, True, exhaustive):
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

    pool.sort(key=lambda z: z[0])
    for _, s in pool[:5]:
        if time.perf_counter() >= begin + 2.55:
            break
        sv = eval_seq(s)
        s, sv = descent(s, sv, min(begin + 2.55, time.perf_counter() + .28), False)
        consider(s)

    def try_cp_sat(seed_seq, seed_val, limit):
        nonlocal best_seq, best_val
        if time.perf_counter() >= limit:
            return
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return
        try:
            val, starts, _, _ = eval_seq(seed_seq, True)
            if starts is None:
                return
            model = cp_model.CpModel()
            horizon = sum(sum(x) for x in durations)
            svars = [[None] * op_count[j] for j in range(n)]
            evars = [[None] * op_count[j] for j in range(n)]
            intervals = [[] for _ in range(m)]
            for j in range(n):
                for k in range(op_count[j]):
                    p = durations[j][k]
                    ma = machines[j][k]
                    s = model.NewIntVar(0, seed_val, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, seed_val, "e_%d_%d" % (j, k))
                    itv = model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k))
                    svars[j][k] = s
                    evars[j][k] = e
                    intervals[ma].append(itv)
                    model.AddHint(s, int(starts[nid(j, k)]))
                    model.AddHint(e, int(starts[nid(j, k)] + p))
            for j in range(n):
                for k in range(op_count[j] - 1):
                    model.Add(svars[j][k + 1] >= evars[j][k])
            for ma in range(m):
                model.AddNoOverlap(intervals[ma])
            cmax = model.NewIntVar(0, seed_val, "cmax")
            model.AddMaxEquality(cmax, [evars[j][op_count[j] - 1] for j in range(n)])
            model.Add(cmax <= int(seed_val))
            model.AddHint(cmax, int(seed_val))
            model.Minimize(cmax)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.1, limit - time.perf_counter())
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 210021
            solver.parameters.cp_model_presolve = True
            solver.parameters.linearization_level = 1
            st = solver.Solve(model)
            if st == cp_model.OPTIMAL or st == cp_model.FEASIBLE:
                seq = [[] for _ in range(m)]
                tmp = [[] for _ in range(m)]
                for j in range(n):
                    for k in range(op_count[j]):
                        ma = machines[j][k]
                        tmp[ma].append((solver.Value(svars[j][k]), j))
                for ma in range(m):
                    tmp[ma].sort()
                    seq[ma] = [j for _, j in tmp[ma]]
                consider(seq)
        except Exception:
            return

    try_cp_sat(best_seq, best_val, begin + 5.1)

    best_seq, best_val = descent(copy_seq(best_seq), best_val, min(deadline, time.perf_counter() + .85), True)
    consider(best_seq)

    cur = copy_seq(best_seq)
    cur_v = best_val
    tabu = {}
    it = 0
    stagn = 0

    while time.perf_counter() < deadline:
        it += 1
        mvlist = moves(cur, True, it % 5 == 0)
        if not mvlist:
            cur = copy_seq(best_seq)
            cur_v = best_val
            continue
        chosen = None
        chosen_v = inf
        chosen_key = None
        for mv in mvlist:
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
            if v < inf and ((tabu.get(key, 0) <= it and tabu.get(rkey, 0) <= it) or v < best_val):
                if v < chosen_v or (v == chosen_v and rng.random() < .10):
                    chosen = mv
                    chosen_v = v
                    chosen_key = key
        if chosen is None:
            cur = copy_seq(best_seq)
            cur_v = best_val
            stagn += 1
            if stagn > 14:
                break
            continue
        apply(cur, chosen)
        cur_v = chosen_v
        tabu[chosen_key] = it + 5 + rng.randrange(18)
        if cur_v < best_val:
            best_val = cur_v
            best_seq = copy_seq(cur)
            stagn = 0
            cur, cur_v = descent(cur, cur_v, min(deadline, time.perf_counter() + .18), it % 3 == 0)
            if cur_v < best_val:
                best_val = cur_v
                best_seq = copy_seq(cur)
        else:
            stagn += 1
        if stagn > 50 or it % 43 == 0:
            cur = copy_seq(best_seq)
            cur_v = best_val
            stagn = 0
            for _ in range(1 + rng.randrange(6)):
                ml = moves(cur, True, False)
                if not ml:
                    break
                mv = ml[rng.randrange(len(ml))]
                apply(cur, mv)
                if eval_seq(cur) >= inf:
                    undo(cur, mv)
            cur_v = eval_seq(cur)
            if cur_v >= inf:
                cur = copy_seq(best_seq)
                cur_v = best_val

    return Schedule.from_job_sequences(instance, best_seq)