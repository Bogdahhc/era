from job_shop_lib import Schedule
import time
import random
import math


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
    INF = 10 ** 12

    def node_id(j, k):
        return j * width + k

    real_nodes = [node_id(j, k) for j in range(n) for k in range(op_count[j])]

    op_of_machine = [[-1] * m for _ in range(n)]
    for j in range(n):
        for k, mach in enumerate(machines[j]):
            if 0 <= mach < m:
                op_of_machine[j][mach] = k

    rem_work = []
    for j in range(n):
        r = [0] * (op_count[j] + 1)
        for k in range(op_count[j] - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        rem_work.append(r)

    total_work = [rem_work[j][0] for j in range(n)]
    machine_load = [0] * m
    for j in range(n):
        for k in range(op_count[j]):
            mach = machines[j][k]
            if 0 <= mach < m:
                machine_load[mach] += durations[j][k]

    def eval_sequence(seq, need_info=False):
        indeg = [0] * num_nodes
        succ = [[] for _ in range(num_nodes)]

        for j in range(n):
            for k in range(op_count[j] - 1):
                a = node_id(j, k)
                b = node_id(j, k + 1)
                succ[a].append(b)
                indeg[b] += 1

        for mach in range(m):
            arr = seq[mach]
            if len(arr) != n:
                return (INF, None, None, None) if need_info else INF
            seen = [False] * n
            last = -1
            for j in arr:
                if j < 0 or j >= n or seen[j]:
                    return (INF, None, None, None) if need_info else INF
                seen[j] = True
                k = op_of_machine[j][mach]
                if k < 0:
                    return (INF, None, None, None) if need_info else INF
                cur = node_id(j, k)
                if last >= 0:
                    succ[last].append(cur)
                    indeg[cur] += 1
                last = cur

        q = [u for u in real_nodes if indeg[u] == 0]
        head = 0
        start = [0] * num_nodes
        pred = [-1] * num_nodes
        cnt = 0

        while head < len(q):
            u = q[head]
            head += 1
            cnt += 1
            ju = u // width
            ku = u % width
            finish = start[u] + durations[ju][ku]
            for v in succ[u]:
                if finish > start[v]:
                    start[v] = finish
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
        rr = []
        for j in range(n):
            r = [0] * (len(ds[j]) + 1)
            for k in range(len(ds[j]) - 1, -1, -1):
                r[k] = r[k + 1] + ds[j][k]
            rr.append(r)
        return rr

    rev_rem_work = make_rem(rev_durations)

    def priority_value(rule, j, k, mach, job_ready, mach_ready, ms, ds, rw):
        p = ds[j][k]
        est = max(job_ready[j], mach_ready[mach])
        ect = est + p
        rem = rw[j][k]
        tail = rw[j][k + 1]
        ops_left = len(ds[j]) - k
        tw = total_work[j]
        ml = machine_load[mach]

        if rule == 0:
            return p * 3 + est - rem * 0.20
        if rule == 1:
            return -p * 3 + est - rem * 0.15
        if rule == 2:
            return -rem + est * 0.20
        if rule == 3:
            return rem + est * 0.10
        if rule == 4:
            return -ops_left * 60 - rem * 0.25 + est
        if rule == 5:
            return ops_left * 70 + p + est * 0.20
        if rule == 6:
            return ect - rem * 0.18
        if rule == 7:
            return est - p * 1.5 - rem * 0.10
        if rule == 8:
            return -tail * 0.75 + est - p * 0.4
        if rule == 9:
            return tail * 0.7 + est + p * 0.2
        if rule == 10:
            return job_ready[j] - rem * 0.30 - p
        if rule == 11:
            return -job_ready[j] - p * 1.5 - rem * 0.10
        if rule == 12:
            return ect + tail * 0.35 - rem * 0.25
        if rule == 13:
            return ect - rem * 0.23 - p
        if rule == 14:
            return ect + tail * 0.45 - tw * 0.12
        if rule == 15:
            return est + p * 2.0 - rem * 0.18 - tail * 0.10
        if rule == 16:
            return -tw + ect * 0.55
        if rule == 17:
            return ect + ml * 0.03 - rem * 0.20 - p * 0.25
        if rule == 18:
            return est + p - tail * 0.18 - rem * 0.15
        if rule == 19:
            return ect + mach_ready[mach] * 0.15 - rem * 0.25
        if rule == 20:
            return est * 0.6 - p * 2.0 + tail * 0.15
        if rule == 21:
            return ect - tw * 0.18 + ops_left * 15
        if rule == 22:
            return est + p * 0.35 - rem * 0.45 + ml * 0.01
        if rule == 23:
            return ect + tail * 0.15 - p * 1.1 - rem * 0.12
        if rule == 24:
            return mach_ready[mach] * 0.4 + job_ready[j] * 0.15 - rem * 0.28 - p * 0.6
        if rule == 25:
            return ect - rem * 0.35 + tail * 0.08 - p * 0.45
        if rule == 26:
            return est * 0.35 + p * 0.8 - tw * 0.20 - rem * 0.12
        if rule == 27:
            return mach_ready[mach] - job_ready[j] * 0.25 + p * 0.2 - rem * 0.22
        if rule == 28:
            return ect + ml * 0.018 - tail * 0.38 - p * 0.1
        return ect - rem * 0.2

    def giffler_thompson(rule, rng=None, noise=0.0, top_choice=False, reverse=False):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem_work if reverse else rem_work
        job_ready = [0] * n
        mach_ready = [0] * m
        next_op = [0] * n
        seq = [[] for _ in range(m)]
        done = 0

        while done < total_ops:
            best_c = INF
            target_m = 0
            for j in range(n):
                k = next_op[j]
                if k < len(ms[j]):
                    mach = ms[j][k]
                    c = max(job_ready[j], mach_ready[mach]) + ds[j][k]
                    if c < best_c:
                        best_c = c
                        target_m = mach

            conflict = []
            for j in range(n):
                k = next_op[j]
                if k < len(ms[j]) and ms[j][k] == target_m and job_ready[j] < best_c:
                    val = priority_value(rule, j, k, target_m, job_ready, mach_ready, ms, ds, rw)
                    if rng is not None and noise > 0:
                        val += rng.uniform(-noise, noise)
                    conflict.append((val, j))

            if not conflict:
                for j in range(n):
                    k = next_op[j]
                    if k < len(ms[j]):
                        mach = ms[j][k]
                        val = priority_value(rule, j, k, mach, job_ready, mach_ready, ms, ds, rw)
                        if rng is not None and noise > 0:
                            val += rng.uniform(-noise, noise)
                        conflict.append((val, j))

            conflict.sort()
            if top_choice and rng is not None and len(conflict) > 1:
                lim = min(len(conflict), 5)
                if rng.random() < 0.38:
                    chosen = conflict[rng.randrange(lim)][1]
                else:
                    chosen = conflict[0][1]
            else:
                chosen = conflict[0][1]

            k = next_op[chosen]
            mach = ms[chosen][k]
            p = ds[chosen][k]
            ft = max(job_ready[chosen], mach_ready[mach]) + p
            seq[mach].append(chosen)
            job_ready[chosen] = ft
            mach_ready[mach] = ft
            next_op[chosen] += 1
            done += 1

        if reverse:
            return [list(reversed(seq[mach])) for mach in range(m)]
        return seq

    def list_dispatch(rule, reverse=False):
        ms = rev_machines if reverse else machines
        ds = rev_durations if reverse else durations
        rw = rev_rem_work if reverse else rem_work
        job_ready = [0] * n
        mach_ready = [0] * m
        next_op = [0] * n
        seq = [[] for _ in range(m)]
        done = 0

        while done < total_ops:
            best = None
            chosen = 0
            for j in range(n):
                k = next_op[j]
                if k >= len(ms[j]):
                    continue
                mach = ms[j][k]
                p = ds[j][k]
                est = max(job_ready[j], mach_ready[mach])
                ect = est + p
                rem = rw[j][k]
                tail = rw[j][k + 1]
                ops = len(ms[j]) - k
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
                    key = (ect - rem * 0.15, -p, j)
                elif rule == 7:
                    key = (ect + tail * 0.4, -rem, j)
                elif rule == 8:
                    key = (ops, ect, p, j)
                elif rule == 9:
                    key = (-total_work[j], ect, j)
                elif rule == 10:
                    key = (est + p * 1.6 - rem * 0.2, j)
                elif rule == 11:
                    key = (mach_ready[mach] + ect - tail * 0.12, j)
                elif rule == 12:
                    key = (ect - total_work[j] * 0.12 - p * 0.3, j)
                elif rule == 13:
                    key = (est - rem * 0.18 + machine_load[mach] * 0.02, ect, j)
                elif rule == 14:
                    key = (ect - rem * 0.28 - p * 0.5, j)
                elif rule == 15:
                    key = (mach_ready[mach], -rem, ect, j)
                else:
                    key = (job_ready[j] + p - tail * 0.25, ect, j)
                if best is None or key < best:
                    best = key
                    chosen = j

            k = next_op[chosen]
            mach = ms[chosen][k]
            p = ds[chosen][k]
            ft = max(job_ready[chosen], mach_ready[mach]) + p
            seq[mach].append(chosen)
            job_ready[chosen] = ft
            mach_ready[mach] = ft
            next_op[chosen] += 1
            done += 1

        if reverse:
            return [list(reversed(seq[mach])) for mach in range(m)]
        return seq

    rng = random.Random(21021023)
    start_time = time.perf_counter()
    deadline = start_time + 3.90

    best_seq = None
    best_val = INF

    def copy_seq(seq):
        return [a[:] for a in seq]

    def consider(seq):
        nonlocal best_seq, best_val
        v = eval_sequence(seq)
        if v < best_val:
            best_val = v
            best_seq = copy_seq(seq)
        return v

    for rev in (False, True):
        for r in range(29):
            consider(giffler_thompson(r, reverse=rev))
        for r in range(17):
            consider(list_dispatch(r, reverse=rev))

    while time.perf_counter() < deadline - 3.02:
        r = rng.randrange(29)
        noise = rng.choice((2.0, 4.0, 7.0, 11.0, 18.0, 30.0, 50.0, 75.0))
        consider(giffler_thompson(r, rng, noise, True, rng.random() < 0.5))

    if best_seq is None:
        best_seq = giffler_thompson(0)
        best_val = eval_sequence(best_seq)

    def critical_data(seq):
        val, start, pred, end_node = eval_sequence(seq, True)
        if start is None:
            return val, set(), []
        path = []
        u = end_node
        while u != -1:
            path.append(u)
            u = pred[u]
        path.reverse()
        return val, set(path), path

    def neighborhood(seq, broad=False):
        val, critical, path = critical_data(seq)
        if not critical:
            return []
        moves = []
        added = set()
        for mach in range(m):
            arr = seq[mach]
            crit_pos = []
            for i, j in enumerate(arr):
                k = op_of_machine[j][mach]
                if k >= 0 and node_id(j, k) in critical:
                    crit_pos.append(i)
            if len(crit_pos) < 2:
                continue
            blocks = []
            block = [crit_pos[0]]
            for pos in crit_pos[1:]:
                if pos == block[-1] + 1:
                    block.append(pos)
                else:
                    if len(block) > 1:
                        blocks.append(block)
                    block = [pos]
            if len(block) > 1:
                blocks.append(block)

            for b in blocks:
                candidates = [
                    ("swap", mach, b[0], b[0] + 1),
                    ("swap", mach, b[-1] - 1, b[-1]),
                ]
                if len(b) >= 3:
                    candidates.append(("insert", mach, b[0], b[-1] + 1))
                    candidates.append(("insert", mach, b[-1], b[0]))
                if broad:
                    if len(b) >= 3:
                        candidates.append(("swap", mach, b[1], b[1] + 1))
                        candidates.append(("swap", mach, b[-2] - 1, b[-2]))
                    if len(b) >= 4:
                        candidates.append(("insert", mach, b[1], b[-1] + 1))
                        candidates.append(("insert", mach, b[-2], b[0]))
                        candidates.append(("swap", mach, b[0], b[-1]))
                    for idx in b:
                        for d in (-4, -3, -2, 2, 3, 4):
                            pos = idx + d
                            if 0 <= pos < n and pos != idx:
                                candidates.append(("insert", mach, idx, pos))

                for mv in candidates:
                    typ, ma, a, c = mv
                    if typ == "swap":
                        if a < 0 or c < 0 or a >= n or c >= n or a == c:
                            continue
                    else:
                        if a < 0 or a >= n or c < 0 or c > n or a == c:
                            continue
                    if mv not in added:
                        added.add(mv)
                        moves.append(mv)
        rng.shuffle(moves)
        return moves

    def apply_move(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            x = arr.pop(a)
            if b > a:
                b -= 1
            arr.insert(b, x)

    def undo_move(seq, mv):
        typ, mach, a, b = mv
        arr = seq[mach]
        if typ == "swap":
            arr[a], arr[b] = arr[b], arr[a]
        else:
            pos = b - 1 if b > a else b
            x = arr.pop(pos)
            arr.insert(a, x)

    def descent(seq, val, stop_time, broad=True, max_passes=1000):
        passes = 0
        while passes < max_passes and time.perf_counter() < stop_time:
            passes += 1
            moves = neighborhood(seq, broad)
            best_mv = None
            best_local = val
            for mv in moves:
                if time.perf_counter() >= stop_time:
                    break
                apply_move(seq, mv)
                v = eval_sequence(seq)
                undo_move(seq, mv)
                if v < best_local:
                    best_local = v
                    best_mv = mv
            if best_mv is None:
                break
            apply_move(seq, best_mv)
            val = best_local
        return seq, val

    best_seq, best_val = descent(best_seq, best_val, deadline - 2.35, True, 80)

    current = copy_seq(best_seq)
    current_val = best_val
    tabu = {}
    iteration = 0

    while time.perf_counter() < deadline - 1.02:
        iteration += 1
        moves = neighborhood(current, True)
        if not moves:
            break

        chosen_mv = None
        chosen_val = INF
        chosen_key = None

        for mv in moves:
            if time.perf_counter() >= deadline - 1.02:
                break
            typ, mach, a, b = mv
            arr = current[mach]
            if typ == "swap":
                key = (mach, min(arr[a], arr[b]), max(arr[a], arr[b]), 0)
            else:
                key = (mach, arr[a], -1 if b >= len(arr) else arr[b], 1)

            apply_move(current, mv)
            v = eval_sequence(current)
            undo_move(current, mv)
            if v >= INF:
                continue
            is_tabu = tabu.get(key, 0) > iteration
            if (not is_tabu or v < best_val) and v < chosen_val:
                chosen_val = v
                chosen_mv = mv
                chosen_key = key

        if chosen_mv is None:
            break

        apply_move(current, chosen_mv)
        current_val = chosen_val
        if chosen_key is not None:
            tabu[chosen_key] = iteration + 7 + rng.randrange(10)

        if current_val < best_val:
            best_val = current_val
            best_seq = copy_seq(current)
            if time.perf_counter() < deadline - 1.10:
                tmp = copy_seq(best_seq)
                tmp, tv = descent(tmp, best_val, deadline - 1.08, False, 5)
                if tv < best_val:
                    best_val = tv
                    best_seq = copy_seq(tmp)
                    current = copy_seq(tmp)
                    current_val = tv

        if iteration % 40 == 0 and current_val > best_val + 85:
            current = copy_seq(best_seq)
            current_val = best_val

    current = copy_seq(best_seq)
    current_val = best_val
    temp0 = max(25.0, best_val / 72.0)
    it = 0

    while time.perf_counter() < deadline:
        it += 1
        if it % 11 == 0:
            moves = neighborhood(current, False)
            if moves:
                mv = moves[0]
            else:
                mach = rng.randrange(m)
                i = rng.randrange(n - 1)
                mv = ("swap", mach, i, i + 1)
        elif rng.random() < 0.70:
            mach = rng.randrange(m)
            i = rng.randrange(n - 1)
            mv = ("swap", mach, i, i + 1)
        else:
            mach = rng.randrange(m)
            a = rng.randrange(n)
            b = rng.randrange(n)
            if a == b:
                continue
            mv = ("insert", mach, a, b)

        apply_move(current, mv)
        v = eval_sequence(current)
        if v < INF:
            if v <= current_val:
                accept = True
            else:
                frac = (time.perf_counter() - start_time) / max(0.001, deadline - start_time)
                temp = temp0 * (1.0 - min(1.0, frac)) + 0.08
                accept = rng.random() < math.exp((current_val - v) / temp)
            if accept:
                current_val = v
                if v < best_val:
                    best_val = v
                    best_seq = copy_seq(current)
                    if time.perf_counter() < deadline - 0.06:
                        loc_moves = neighborhood(best_seq, False)
                        for lm in loc_moves[:120]:
                            apply_move(best_seq, lm)
                            nv = eval_sequence(best_seq)
                            undo_move(best_seq, lm)
                            if nv < best_val:
                                apply_move(best_seq, lm)
                                best_val = nv
                                current = copy_seq(best_seq)
                                current_val = nv
                                break
            else:
                undo_move(current, mv)
        else:
            undo_move(current, mv)

        if it % 240 == 0 and current_val > best_val + 70:
            current = copy_seq(best_seq)
            current_val = best_val

    return Schedule.from_job_sequences(instance, best_seq)