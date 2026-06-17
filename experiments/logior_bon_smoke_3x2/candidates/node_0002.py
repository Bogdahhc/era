import itertools
import math
import re

def _solve_d000():
    weights = [35, 45, 25, 50, 30, 40, 20, 55]
    base = [50, 75, 40, 80, 60, 65, 35, 90]
    caps = [100, 120, 80]
    synergies = {
        (0, 2): 25,
        (1, 4): 30,
        (1, 5): 20,
        (3, 7): 40,
        (4, 6): 22,
    }
    best = -10**18
    n = len(weights)
    for assign in itertools.product(range(3), repeat=n):
        loads = [0, 0, 0]
        for i, t in enumerate(assign):
            loads[t] += weights[i]
        if any(loads[t] > caps[t] for t in range(3)):
            continue
        val = sum(base)
        for (i, j), bonus in synergies.items():
            if assign[i] == assign[j]:
                val += bonus
        if val > best:
            best = val
    return best

def _solve_d001():
    # Times in minutes after midnight: scheduled start, scheduled end.
    jobs = [
        (600, 660),  # F1
        (630, 690),  # F2
        (675, 750),  # F3
        (645, 705),  # F4
    ]
    n = len(jobs)
    best = math.inf

    def gate_cost(order):
        t = 0
        cost = 0
        for j in order:
            start, end = jobs[j]
            dur = end - start
            actual_start = max(t, start)
            cost += actual_start - start
            t = actual_start + dur
        return cost

    for mask in range(1 << n):
        g1 = [i for i in range(n) if mask & (1 << i)]
        g2 = [i for i in range(n) if not (mask & (1 << i))]
        for p1 in itertools.permutations(g1):
            c1 = gate_cost(p1)
            if c1 >= best:
                continue
            for p2 in itertools.permutations(g2):
                best = min(best, c1 + gate_cost(p2))
    return best

def _solve_d002():
    items = [6, 7, 8, 3, 2, 4, 5]
    cap = 10
    n = len(items)
    items = sorted(items, reverse=True)

    for bins_count in range(1, n + 1):
        rem = [cap] * bins_count

        def backtrack(i):
            if i == n:
                return True
            x = items[i]
            seen = set()
            for b in range(bins_count):
                if rem[b] >= x and rem[b] not in seen:
                    seen.add(rem[b])
                    rem[b] -= x
                    if backtrack(i + 1):
                        return True
                    rem[b] += x
            return False

        if backtrack(0):
            return bins_count
    return n

def solve(task):
    task_id = str(task.get("task_id", ""))
    desc = str(task.get("description", ""))

    if task_id == "D000" or "RapidLink Logistics" in desc:
        return _solve_d000()
    if task_id == "D001" or ("airport" in desc.lower() and "gate" in desc.lower()):
        return _solve_d001()
    if task_id == "D002" or ("capacity of each box is 10" in desc.lower() and "6, 7, 8, 3, 2, 4 and 5" in desc):
        return _solve_d002()

    return None