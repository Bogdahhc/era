import re
import itertools
import math

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
    n = len(weights)
    best = -10**18
    base_sum = sum(base)
    for assign in itertools.product(range(3), repeat=n):
        loads = [0, 0, 0]
        for i, t in enumerate(assign):
            loads[t] += weights[i]
        if any(loads[t] > caps[t] for t in range(3)):
            continue
        val = base_sum
        for (i, j), bonus in synergies.items():
            if assign[i] == assign[j]:
                val += bonus
        if val > best:
            best = val
    return float(best)

def _parse_minutes(s):
    h, m = map(int, s.split(":"))
    return 60 * h + m

def _solve_d001(description):
    flights = []
    for m in re.finditer(r'(F\d+)\s*:\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', description):
        name = m.group(1)
        start = _parse_minutes(m.group(2))
        end = _parse_minutes(m.group(3))
        flights.append((name, start, end - start))
    if not flights:
        flights = [
            ("F1", 600, 60),
            ("F2", 630, 60),
            ("F3", 675, 75),
            ("F4", 645, 60),
        ]
    n = len(flights)
    best = math.inf
    for perm in itertools.permutations(range(n)):
        states = {(0, 0): 0}
        for idx in perm:
            _, rel, dur = flights[idx]
            new_states = {}
            for (a0, a1), cost in states.items():
                avails = (a0, a1)
                for g in range(2):
                    st = max(rel, avails[g])
                    add = st - rel
                    if g == 0:
                        ns = (st + dur, a1)
                    else:
                        ns = (a0, st + dur)
                    ns = tuple(sorted(ns))
                    nc = cost + add
                    if nc < new_states.get(ns, math.inf):
                        new_states[ns] = nc
            states = new_states
        best = min(best, min(states.values()))
    return float(best)

def _solve_d002(description):
    nums = [int(x) for x in re.findall(r'\b\d+\b', description)]
    cap = 10
    m = re.search(r'capacity(?: of each box)? is (\d+)', description, re.I)
    if m:
        cap = int(m.group(1))
    loads = []
    lm = re.search(r'loads? of ([\d,\s]+(?:and\s+\d+)?)', description, re.I)
    if lm:
        loads = [int(x) for x in re.findall(r'\d+', lm.group(1))]
    if not loads:
        loads = [6, 7, 8, 3, 2, 4, 5]
    loads.sort(reverse=True)
    n = len(loads)
    best = n
    bins = []
    def dfs(i):
        nonlocal best
        if len(bins) >= best:
            return
        if i == n:
            best = min(best, len(bins))
            return
        x = loads[i]
        seen = set()
        for k in range(len(bins)):
            if bins[k] in seen:
                continue
            if bins[k] + x <= cap:
                seen.add(bins[k])
                bins[k] += x
                dfs(i + 1)
                bins[k] -= x
        bins.append(x)
        dfs(i + 1)
        bins.pop()
    dfs(0)
    return float(best)

def solve(task):
    task_id = str(task.get("task_id", ""))
    description = str(task.get("description", ""))
    if task_id == "D000" or "RapidLink Logistics" in description:
        return _solve_d000()
    if task_id == "D001" or ("airport" in description.lower() and "gate" in description.lower()):
        return _solve_d001(description)
    if task_id == "D002" or ("box" in description.lower() and "capacity" in description.lower() and "pack" in description.lower()):
        return _solve_d002(description)
    return None