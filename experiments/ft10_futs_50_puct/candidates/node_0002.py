import time
import random
from math import inf
from job_shop_lib import Schedule


def solve(instance):
    start_time = time.perf_counter()
    deadline = start_time + 3.6

    num_jobs = instance.num_jobs
    num_machines = instance.num_machines
    jobs = instance.jobs

    machines = []
    durations = []
    for job in jobs:
        jm = []
        jd = []
        for op in job:
            jm.append(int(getattr(op, "machine_id")))
            jd.append(int(getattr(op, "duration")))
        machines.append(jm)
        durations.append(jd)

    total_ops = sum(len(j) for j in machines)

    def try_cp_sat():
        if time.perf_counter() > deadline - 0.5:
            return None
        try:
            from ortools.sat.python import cp_model
        except Exception:
            return None

        try:
            model = cp_model.CpModel()
            horizon = sum(sum(d) for d in durations)

            starts = {}
            ends = {}
            intervals_by_machine = [[] for _ in range(num_machines)]

            for j in range(num_jobs):
                for k in range(len(machines[j])):
                    p = durations[j][k]
                    m = machines[j][k]
                    s = model.NewIntVar(0, horizon, "s_%d_%d" % (j, k))
                    e = model.NewIntVar(0, horizon, "e_%d_%d" % (j, k))
                    itv = model.NewIntervalVar(s, p, e, "i_%d_%d" % (j, k))
                    starts[(j, k)] = s
                    ends[(j, k)] = e
                    intervals_by_machine[m].append(itv)

            for j in range(num_jobs):
                for k in range(len(machines[j]) - 1):
                    model.Add(starts[(j, k + 1)] >= ends[(j, k)])

            for m in range(num_machines):
                model.AddNoOverlap(intervals_by_machine[m])

            makespan = model.NewIntVar(0, horizon, "makespan")
            model.AddMaxEquality(makespan, [ends[(j, len(machines[j]) - 1)] for j in range(num_jobs)])
            model.Minimize(makespan)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.2, min(2.35, deadline - time.perf_counter() - 0.25))
            solver.parameters.num_search_workers = 1
            solver.parameters.random_seed = 7
            solver.parameters.linearization_level = 2
            solver.parameters.cp_model_presolve = True

            status = solver.Solve(model)
            if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                return None

            seqs = [[] for _ in range(num_machines)]
            for m in range(num_machines):
                ops = []
                for j in range(num_jobs):
                    for k in range(len(machines[j])):
                        if machines[j][k] == m:
                            ops.append((solver.Value(starts[(j, k)]), solver.Value(ends[(j, k)]), j, k))
                ops.sort()
                seqs[m] = [j for _, _, j, _ in ops]
            return seqs
        except Exception:
            return None

    cp_seq = try_cp_sat()
    if cp_seq is not None:
        try:
            return Schedule.from_job_sequences(instance, cp_seq)
        except Exception:
            pass

    offsets = []
    nops = 0
    for j in range(num_jobs):
        offsets.append(nops)
        nops += len(machines[j])

    node_machine = [0] * nops
    node_duration = [0] * nops
    for j in range(num_jobs):
        for k in range(len(machines[j])):
            n = offsets[j] + k
            node_machine[n] = machines[j][k]
            node_duration[n] = durations[j][k]

    remaining_work = []
    for j in range(num_jobs):
        r = [0] * (len(durations[j]) + 1)
        for k in range(len(durations[j]) - 1, -1, -1):
            r[k] = r[k + 1] + durations[j][k]
        remaining_work.append(r)

    job_machine_indices = [[[] for _ in range(num_machines)] for _ in range(num_jobs)]
    for j in range(num_jobs):
        for k, m in enumerate(machines[j]):
            job_machine_indices[j][m].append(k)

    def evaluate(job_sequences, need_path=False):
        succ = [[] for _ in range(nops)]
        indeg = [0] * nops

        for j in range(num_jobs):
            for k in range(len(machines[j]) - 1):
                u = offsets[j] + k
                v = offsets[j] + k + 1
                succ[u].append(v)
                indeg[v] += 1

        mach_nodes = [[] for _ in range(num_machines)]
        node_pos = [-1] * nops

        for m in range(num_machines):
            counts = [0] * num_jobs
            prev = -1
            for pos, j in enumerate(job_sequences[m]):
                if j < 0 or j >= num_jobs:
                    return (inf, None, None, None, None) if need_path else inf
                c = counts[j]
                counts[j] += 1
                if c >= len(job_machine_indices[j][m]):
                    return (inf, None, None, None, None) if need_path else inf
                k = job_machine_indices[j][m][c]
                n = offsets[j] + k
                mach_nodes[m].append(n)
                node_pos[n] = pos
                if prev != -1:
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
            return (inf, None, None, None, None) if need_path else inf
        if need_path:
            return best_c, pred, best_end, mach_nodes, node_pos
        return best_c

    def giffler_thompson(rule_id, rnd=None, weights=None):
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

            conflict = [x for x in available if x[2] == best_machine and x[4] < best_ect]

            def key(x):
                j, k, m, p, est, ect = x
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
                s = (
                    weights[0] * p
                    + weights[1] * rem
                    + weights[2] * tail
                    + weights[3] * est
                    + weights[4] * ect
                    + weights[5] * job_ready[j]
                    + weights[6] * machine_ready[m]
                    + weights[7] * ops_left
                )
                return (s + rnd.random() * 1e-7, j)

            j, k, m, p, est, ect = min(conflict, key=key)
            seqs[m].append(j)
            next_op[j] += 1
            job_ready[j] = ect
            machine_ready[m] = ect
            scheduled += 1

        return seqs

    def copy_seqs(seqs):
        return [list(s) for s in seqs]

    def critical_swaps(pred, end_node, node_pos):
        path = []
        n = end_node
        while n != -1 and n is not None:
            path.append(n)
            n = pred[n]
        path.reverse()

        swaps = []
        used = set()
        for a, b in zip(path, path[1:]):
            m = node_machine[a]
            if m == node_machine[b]:
                pa = node_pos[a]
                pb = node_pos[b]
                if pa >= 0 and pb == pa + 1 and (m, pa) not in used:
                    used.add((m, pa))
                    swaps.append((m, pa))
        return swaps

    def local_search(initial, initial_val):
        current = copy_seqs(initial)
        current_val = initial_val
        best = copy_seqs(current)
        best_val = current_val
        rnd = random.Random(1777 + int(initial_val))
        tabu = {}
        iteration = 0

        while time.perf_counter() < deadline - 0.05:
            iteration += 1
            val, pred, end_node, mach_nodes, node_pos = evaluate(current, True)
            if val == inf:
                break
            swaps = critical_swaps(pred, end_node, node_pos)
            if not swaps:
                break

            best_move = None
            best_move_val = inf

            for m, pos in swaps:
                a = current[m][pos]
                b = current[m][pos + 1]
                forbid = tabu.get((m, b, a), -1)
                cand = copy_seqs(current)
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                cv = evaluate(cand)
                if cv < inf and (cv < best_val or iteration >= forbid):
                    if cv < best_move_val:
                        best_move_val = cv
                        best_move = (m, pos, a, b)
                if time.perf_counter() >= deadline - 0.05:
                    break

            if best_move is None:
                m, pos = rnd.choice(swaps)
                cand = copy_seqs(current)
                cand[m][pos], cand[m][pos + 1] = cand[m][pos + 1], cand[m][pos]
                cv = evaluate(cand)
                if cv < inf and cv <= current_val + 40:
                    current = cand
                    current_val = cv
                else:
                    break
            else:
                m, pos, a, b = best_move
                current[m][pos], current[m][pos + 1] = current[m][pos + 1], current[m][pos]
                current_val = best_move_val
                tabu[(m, a, b)] = iteration + 5 + rnd.randrange(6)
                if current_val < best_val:
                    best_val = current_val
                    best = copy_seqs(current)

        return best, best_val

    best_seq = None
    best_val = inf
    candidates = []

    for rule in range(12):
        s = giffler_thompson(rule)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)

    rnd = random.Random(1234567)
    while time.perf_counter() < deadline - 1.0 and len(candidates) < 260:
        w = [rnd.uniform(-2.5, 2.5) for _ in range(8)]
        w[1] += rnd.uniform(-2.0, 0.2)
        w[2] += rnd.uniform(-1.0, 0.5)
        s = giffler_thompson(100, rnd, w)
        v = evaluate(s)
        candidates.append((v, copy_seqs(s)))
        if v < best_val:
            best_val = v
            best_seq = copy_seqs(s)

    candidates.sort(key=lambda x: x[0])
    selected = []
    seen = set()
    for v, s in candidates:
        key = tuple(tuple(x) for x in s)
        if key not in seen:
            seen.add(key)
            selected.append((v, s))
        if len(selected) >= 24:
            break

    for v, s in selected:
        if time.perf_counter() >= deadline - 0.05:
            break
        ls, lv = local_search(s, v)
        if lv < best_val:
            best_val = lv
            best_seq = copy_seqs(ls)

    if best_seq is None:
        best_seq = [[] for _ in range(num_machines)]
        for j, job in enumerate(jobs):
            for op in job:
                best_seq[int(getattr(op, "machine_id"))].append(j)

    return Schedule.from_job_sequences(instance, best_seq)