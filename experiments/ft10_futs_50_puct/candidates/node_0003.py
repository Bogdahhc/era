import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    start_time = time.perf_counter()
    deadline = start_time + 3.8

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines = []
    durations = []
    for job in jobs:
        jm, jd = [], []
        for op in job:
            jm.append(int(getattr(op, "machine_id")))
            jd.append(int(getattr(op, "duration")))
        machines.append(jm)
        durations.append(jd)

    nops = sum(len(j) for j in machines)
    offsets = []
    x = 0
    for j in range(num_jobs):
        offsets.append(x)
        x += len(machines[j])

    node_machine = [0] * nops
    node_duration = [0] * nops
    node_job = [0] * nops
    node_op = [0] * nops
    for j in range(num_jobs):
        for k in range(len(machines[j])):
            n = offsets[j] + k
            node_machine[n] = machines[j][k]
            node_duration[n] = durations[j][k]
            node_job[n] = j
            node_op[n] = k

    job_machine_indices = [[[] for _ in range(num_machines)] for _ in range(num_jobs)]
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)

    remaining_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        remaining_work.append(r)

    def copy_seqs(s):
        return [list(a) for a in s]

    def evaluate(job_sequences, need_path=False, need_starts=False):
        succ = [[] for _ in range(nops)]
        indeg = [0] * nops

        for j in range(num_jobs):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = u + 1
                succ[u].append(v)
                indeg[v] += 1

        mach_nodes = [[] for _ in range(num_machines)]
        node_pos = [-1] * nops

        for m in range(num_machines):
            if len(job_sequences[m]) != len([1 for j in range(num_jobs) for mm in machines[j] if mm == m]):
                return (inf, None, None, None, None, None) if (need_path or need_starts) else inf
            counts = [0] * num_jobs
            prev = -1
            for pos, j in enumerate(job_sequences[m]):
                if j < 0 or j >= num_jobs:
                    return (inf, None, None, None, None, None) if (need_path or need_starts) else inf
                c = counts[j]
                counts[j] += 1
                if c >= len(job_machine_indices[j][m]):
                    return (inf, None, None, None, None, None) if (need_path or need_starts) else inf
                k = job_machine_indices[j][m][c]
                n = offsets[j] + k
                mach_nodes[m].append(n)
                node_pos[n] = pos
                if prev >= 0:
                    succ[prev].append(n)
                    indeg[n] += 1
                prev = n

        q = [i for i in range(nops) if indeg[i] == 0]
        head = 0
        dist = [0] * nops
        pred = [-1] * nops if need_path else None
        seen = 0
        best_c = 0
        best_end = -1

        while head < len(q):
            u = q[head]
            head += 1
            seen += 1
            cu = dist[u] + node_duration[u]
            if cu > best_c:
                best_c = cu
                best_end = u
            for v in succ[u]:
                if cu > dist[v]:
                    dist[v] = cu
                    if need_path:
                        pred[v] = u
                indeg[v] -= 1
                if indeg[v] == 0:
                    q.append(v)

        if seen != nops:
            return (inf, None, None, None, None, None) if (need_path or need_starts) else inf
        if need_path or need_starts:
            return best_c, pred, best_end, mach_nodes, node_pos, dist
        return best_c

    def giffler_thompson(rule_id=0, rnd=None, weights=None):
        next_op = [0] * num_jobs
        job_ready = [0] * num_jobs
        machine_ready = [0] * num_machines
        seqs = [[] for _ in range(num_machines)]
        scheduled = 0

        while scheduled < nops:
            available = []
            best_ect = inf
            best_machine = 0
            for j in range(num_jobs):
                k = next_op[j]
                if k >= len(machines[j]):
                    continue
                m = machines[j][k]
                p = durations[j][k]
                est = max(job_ready[j], machine_ready[m])
                ect = est + p
                available.append((j, k, m, p, est, ect))
                if ect < best_ect:
                    best_ect = ect
                    best_machine = m

            conflict = [a for a in available if a[2] == best_machine and a[4] < best_ect]

            def key(a):
                j, k, m, p, est, ect = a
                rem = remaining_work[j][k]
                tail = remaining_work[j][k + 1]
                ops_left = len(machines[j]) - k
                if rule_id == 0:
                    return (p, -rem, est, j)
                if rule_id == 1:
                    return (-p, -rem, est, j)
                if rule_id == 2:
                    return (-rem, p, est, j)
                if rule_id == 3:
                    return (rem, p, est, j)
                if rule_id == 4:
                    return (-ops_left, -rem, p, j)
                if rule_id == 5:
                    return (ect, -rem, p, j)
                if rule_id == 6:
                    return (est, -rem, -p, j)
                if rule_id == 7:
                    return (job_ready[j] + rem, p, j)
                if rule_id == 8:
                    return (-tail, p, est, j)
                if rule_id == 9:
                    return (machine_ready[m], job_ready[j], -rem, j)
                if rule_id == 10:
                    return (est + p + tail, -p, j)
                if rule_id == 11:
                    return (est - rem, p, j)
                if rule_id == 12:
                    return (est + p - 0.45 * rem - 0.15 * tail, p, j)
                score = (
                    weights[0] * p +
                    weights[1] * rem +
                    weights[2] * tail +
                    weights[3] * est +
                    weights[4] * ect +
                    weights[5] * job_ready[j] +
                    weights[6] * machine_ready[m] +
                    weights[7] * ops_left
                )
                return (score + rnd.random() * 1e-8, j)

            j, k, m, p, est, ect = min(conflict, key=key)
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            scheduled += 1

        return seqs

    def critical_swaps(pred, end_node, node_pos):
        path = []
        n = end_node
        while n is not None and n != -1:
            path.append(n)
            n = pred[n]
        path.reverse()
        swaps = []
        used = set()
        block = []
        last_m = -1
        for n in path:
            m = node_machine[n]
            if m == last_m:
                block.append(n)
            else:
                if len(block) >= 2:
                    for a, b in zip(block, block[1:]):
                        pa = node_pos[a]
                        if pa >= 0 and node_pos[b] == pa + 1 and (node_machine[a], pa) not in used:
                            used.add((node_machine[a], pa))
                            swaps.append((node_machine[a], pa))
                block = [n]
                last_m = m
        if len(block) >= 2:
            for a, b in zip(block, block[1:]):
                pa = node_pos[a]
                if pa >= 0 and node_pos[b] == pa + 1 and (node_machine[a], pa) not in used:
                    used.add((node_machine[a], pa))
                    swaps.append((node_machine[a], pa))
        return swaps

    def local_search(initial, initial_val, max_idle_slack=70):
        current = copy_seqs(initial)
        current_val = initial_val
        best = copy_seqs(current)
        best_val = current_val
        rnd = random.Random(99173 + int(initial_val))
        tabu = {}
        it = 0
        no_improve = 0

        while time.perf_counter() < deadline - 0.12 and no_improve < 90:
            it += 1
            val, pred, end_node, mach_nodes, node_pos, _ = evaluate(current, True)
            if val == inf:
                break
            swaps = critical_swaps(pred, end_node, node_pos)
            if not swaps:
                break

            cand_moves = list(swaps)
            if rnd.random() < 0.22:
                for m, p in swaps:
                    if p > 0:
                        cand_moves.append((m, p - 1))
                    if p + 2 < len(current[m]):
                        cand_moves.append((m, p + 1))

            best_move = None
            best_move_val = inf
            rnd.shuffle(cand_moves)

            for m, pos in cand_moves:
                if pos < 0 or pos + 1 >= len(current[m]):
                    continue
                a, b = current[m][pos], current[m][pos + 1]
                forbid = tabu.get((m, b, a), -1)
                cand = copy_seqs(current)
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                cv = evaluate(cand)
                if cv < inf and (cv < best_val or it >= forbid):
                    if cv < best_move_val or (cv == best_move_val and rnd.random() < 0.5):
                        best_move_val = cv
                        best_move = (m, pos, a, b)
                if time.perf_counter() >= deadline - 0.12:
                    break

            if best_move is None:
                m, pos = rnd.choice(swaps)
                cand = copy_seqs(current)
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                cv = evaluate(cand)
                if cv < inf and cv <= current_val + max_idle_slack:
                    current = cand
                    current_val = cv
                else:
                    break
            else:
                m, pos, a, b = best_move
                current[m][pos], current[m][pos + 1] = current[m][pos + 1], current[m][pos]
                current_val = best_move_val
                tabu[(m, a, b)] = it + 7 + rnd.randrange(10)
                if current_val < best_val:
                    best_val = current_val
                    best = copy_seqs(current)
                    no_improve = 0
                    if best_val <= 930:
                        break
                else:
                    no_improve += 1

        return best, best_val

    def try_cp_sat(hint_seq, hint_val):
        if time.perf_counter() > deadline - 0.35:
            return None, inf
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None, inf
        try:
            model = cp_model.CpModel()
            horizon = sum(sum(d) for d in durations)
            starts, ends = {}, {}
            intervals_by_machine = [[] for _ in range(num_machines)]

            for j in range(num_jobs):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                    starts[(j, k)] = s
                    ends[(j, k)] = e
                    intervals_by_machine[m].append(model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k)))

            for j in range(num_jobs):
                for k in range(len(machines[j]) - 1):
                    model.Add(starts[(j, k + 1)] >= ends[(j, k)])

            for m in range(num_machines):
                model.AddNoOverlap(intervals_by_machine[m])

            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, [ends[(j, len(machines[j]) - 1)] for j in range(num_jobs)])
            if hint_val < inf:
                model.Add(makespan <= int(hint_val) - 1)
            model.Minimize(makespan)

            if hint_seq is not None:
                ev = evaluate(hint_seq, need_starts=True)
                if ev[0] < inf:
                    st = ev[5]
                    for n in range(nops):
                        j = node_job[n]
                        k = node_op[n]
                        model.AddHint(starts[(j, k)], int(st[n]))
                        model.AddHint(ends[(j, k)], int(st[n] + node_duration[n]))

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.2, deadline - time.perf_counter() - 0.08)
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 23
            solver.parameters.linearization_level = 2
            solver.parameters.cp_model_presolve = True
            solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH

            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None, inf

            seqs = [[] for _ in range(num_machines)]
            for m in range(num_machines):
                ops = []
                for j in range(num_jobs):
                    for k in range(len(machines[j])):
                        if machines[j][k] == m:
                            ops.append((solver.Value(starts[(j, k)]), solver.Value(ends[(j, k)]), j, k))
                ops.sort()
                seqs[m] = [j for _, _, j, _ in ops]
            return seqs, evaluate(seqs)
        except Exception:
            return None, inf

    best_seq = None
    best_val = inf
    candidates = []

    for rule in range(13):
        s = giffler_thompson(rule)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val, best_seq = v, copy_seqs(s)

    rnd = random.Random(24681357)
    base_weights = [
        (1.0, -1.0, -0.2, 0.15, 0.4, 0.0, 0.0, -0.1),
        (-1.0, -1.6, -0.4, 0.2, 0.2, 0.0, 0.0, -0.3),
        (0.3, -2.0, -0.6, 0.3, 0.1, 0.0, 0.0, -0.4),
        (1.2, -1.4, -0.9, 0.1, 0.3, 0.1, 0.0, -0.2),
    ]
    for w in base_weights:
        s = giffler_thompson(100, rnd, list(w))
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val, best_seq = v, copy_seqs(s)

    while time.perf_counter() < deadline - 1.45 and len(candidates) < 360:
        w = [rnd.uniform(-2.8, 2.8) for _ in range(8)]
        w[1] += rnd.uniform(-2.4, 0.0)
        w[2] += rnd.uniform(-1.4, 0.4)
        w[7] += rnd.uniform(-0.8, 0.2)
        s = giffler_thompson(100, rnd, w)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val, best_seq = v, copy_seqs(s)

    candidates.sort(key=lambda z: z[0])
    selected = []
    seen = set()
    for v, s in candidates:
        key = tuple(tuple(a) for a in s)
        if key not in seen:
            seen.add(key)
            selected.append((v, s))
        if len(selected) >= 32:
            break

    for v, s in selected:
        if time.perf_counter() >= deadline - 0.72 or best_val <= 930:
            break
        ls, lv = local_search(s, v)
        if lv < best_val:
            best_val, best_seq = lv, copy_seqs(ls)

    if best_val > 930 and time.perf_counter() < deadline - 0.30:
        cp_seq, cp_val = try_cp_sat(best_seq, best_val)
        if cp_seq is not None and cp_val < best_val:
            best_seq, best_val = copy_seqs(cp_seq), cp_val

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)