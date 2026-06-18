import os
import json
import re
from ortools.sat.python import cp_model


def solve(dataset):
    if "fjspb" not in dataset:
        return {"assignments": []}

    problem = dataset["fjspb"]
    machines_capacity = {str(m): int(c) for m, c in (problem.get("machines") or {}).items()}
    jobs = problem.get("jobs", []) or []
    cur_ptr = int(problem.get("cur_ptr", 0) or 0)

    model = cp_model.CpModel()

    job_to_tasks = {}
    task_data = {}
    task_keys = []
    machine_to_intervals = {}
    expr_to_first_tasks = {}

    fixed_max_end = 0
    total_duration = 0

    for job in jobs:
        job_id = str(job.get("job_id"))
        expr_no = job.get("expr_no")
        ordered_tasks = sorted(
            job.get("tasks", []) or [],
            key=lambda t: (int(t.get("task_id", 0) or 0), int(t.get("step_index", 0) or 0)),
        )
        job_to_tasks[job_id] = []
        for task in ordered_tasks:
            task_id = int(task.get("task_id", 0) or 0)
            task_key = (job_id, task_id)
            duration = int(task.get("duration", 0) or 0)
            eligible_machines = [str(m) for m in (task.get("machines") or [])]
            if not eligible_machines:
                nominal = task.get("nominal_machine") or task.get("scheduled_machine")
                if nominal is not None:
                    eligible_machines = [str(nominal)]
            for machine_code in eligible_machines:
                machines_capacity.setdefault(machine_code, 1)

            is_fixed = bool(task.get("is_fixed", False))
            fixed_start = task.get("fixed_start")
            fixed_end = task.get("fixed_end")
            scheduled_machine = task.get("scheduled_machine")
            if is_fixed:
                fixed_start = int(fixed_start)
                fixed_end = int(fixed_end)
                fixed_max_end = max(fixed_max_end, fixed_end)
                if scheduled_machine is not None and str(scheduled_machine) not in eligible_machines:
                    eligible_machines.append(str(scheduled_machine))
                    machines_capacity.setdefault(str(scheduled_machine), 1)

            task_data[task_key] = {
                "job": job,
                "task": task,
                "duration": duration,
                "machines": eligible_machines,
                "is_fixed": is_fixed,
                "fixed_start": fixed_start,
                "fixed_end": fixed_end,
                "scheduled_machine": str(scheduled_machine) if scheduled_machine is not None else None,
                "flags": task.get("flags", {}) or {},
                "expr_no": expr_no,
            }
            task_keys.append(task_key)
            job_to_tasks[job_id].append(task_key)
            total_duration += max(0, duration)

        if ordered_tasks:
            first_task_key = (job_id, int(ordered_tasks[0].get("task_id", 0) or 0))
            expr_to_first_tasks.setdefault(expr_no, []).append(first_task_key)

    horizon = max(cur_ptr + total_duration + fixed_max_end + 500, fixed_max_end + 500, 1000)

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}

    def safe_token(value):
        return re.sub(r"[^A-Za-z0-9_]", "_", str(value))[:80]

    for task_key in task_keys:
        info = task_data[task_key]
        duration = info["duration"]
        safe_task = safe_token(f"{task_key[0]}_{task_key[1]}")

        if info["is_fixed"]:
            fixed_start = int(info["fixed_start"])
            fixed_end = int(info["fixed_end"])
            start_var = model.NewIntVar(fixed_start, fixed_start, f"start_{safe_task}")
            end_var = model.NewIntVar(fixed_end, fixed_end, f"end_{safe_task}")
            model.Add(end_var == start_var + duration)
        else:
            start_var = model.NewIntVar(cur_ptr, horizon, f"start_{safe_task}")
            end_var = model.NewIntVar(cur_ptr, horizon, f"end_{safe_task}")
            model.Add(end_var == start_var + duration)

        start_vars[task_key] = start_var
        end_vars[task_key] = end_var

        machine_presence_vars = []
        for machine_code in info["machines"]:
            safe_machine = safe_token(machine_code)
            presence_var = model.NewBoolVar(f"presence_{safe_task}_{safe_machine}")
            presence[(task_key, machine_code)] = presence_var
            machine_presence_vars.append(presence_var)

            optional_interval = model.NewOptionalIntervalVar(
                start_var,
                duration,
                end_var,
                presence_var,
                f"interval_{safe_task}_{safe_machine}",
            )
            interval_vars[(task_key, machine_code)] = optional_interval
            machine_to_intervals.setdefault(machine_code, []).append(
                (task_key, optional_interval, presence_var, duration)
            )

            if info["is_fixed"]:
                if info["scheduled_machine"] == machine_code:
                    model.Add(presence_var == 1)
                else:
                    model.Add(presence_var == 0)

        if machine_presence_vars:
            model.AddExactlyOne(machine_presence_vars)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda key: key[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            model.Add(end_vars[previous_key] <= start_vars[next_key])

    def both_fixed_overlap(left_key, right_key):
        left = task_data[left_key]
        right = task_data[right_key]
        if not (left["is_fixed"] and right["is_fixed"]):
            return False
        return int(left["fixed_start"]) < int(right["fixed_end"]) and int(right["fixed_start"]) < int(left["fixed_end"])

    def add_pairwise_disjunction(machine_code, entry_i, entry_j, name_prefix):
        task_key_i, _, presence_i, duration_i = entry_i
        task_key_j, _, presence_j, duration_j = entry_j
        safe_machine = safe_token(machine_code)
        i_before_j = model.NewBoolVar(f"{name_prefix}_i_before_{safe_token(task_key_i)}_{safe_token(task_key_j)}_{safe_machine}")
        j_before_i = model.NewBoolVar(f"{name_prefix}_j_before_{safe_token(task_key_i)}_{safe_token(task_key_j)}_{safe_machine}")
        model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, i_before_j])
        model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, j_before_i])
        return i_before_j, j_before_i

    for machine_code, interval_entries in machine_to_intervals.items():
        capacity = int(machines_capacity.get(machine_code, 1) or 1)

        if capacity <= 1:
            for idx, entry_i in enumerate(interval_entries):
                for entry_j in interval_entries[idx + 1:]:
                    task_key_i = entry_i[0]
                    task_key_j = entry_j[0]
                    if both_fixed_overlap(task_key_i, task_key_j):
                        continue
                    i_before_j, j_before_i = add_pairwise_disjunction(machine_code, entry_i, entry_j, "onecap")
                    presence_i = entry_i[2]
                    presence_j = entry_j[2]
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])
        else:
            model.AddCumulative([entry[1] for entry in interval_entries], [1] * len(interval_entries), capacity)
            for idx, entry_i in enumerate(interval_entries):
                for entry_j in interval_entries[idx + 1:]:
                    task_key_i, _, presence_i, duration_i = entry_i
                    task_key_j, _, presence_j, duration_j = entry_j
                    if both_fixed_overlap(task_key_i, task_key_j) and duration_i == duration_j:
                        continue
                    i_before_j, j_before_i = add_pairwise_disjunction(machine_code, entry_i, entry_j, "batch")
                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar(
                            f"batch_sync_{safe_token(task_key_i)}_{safe_token(task_key_j)}_{safe_token(machine_code)}"
                        )
                        model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf(
                            [presence_i, presence_j, synchronized]
                        )
                        model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf(
                            [presence_i, presence_j, synchronized]
                        )
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i, synchronized])
                    else:
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])

    def task_machine_text(task_key):
        task = task_data[task_key]["task"]
        parts = []
        parts.extend(task_data[task_key]["machines"])
        if task.get("nominal_machine") is not None:
            parts.append(str(task.get("nominal_machine")))
        if task.get("name") is not None:
            parts.append(str(task.get("name")))
        return " ".join(parts).lower()

    def is_high_flux_chain_task(task_key):
        flags = task_data[task_key]["flags"]
        if any(flags.get(flag, False) for flag in (
            "electronic_dripping", "electronic_test", "electronic_recycle",
            "xrd_dripping", "xrd_test", "xrd_recycle",
        )):
            return True
        text = task_machine_text(task_key)
        return "high_flux" in text and ("dripping" in text or "_test" in text or "recycle" in text)

    chemistry_chain_task_keys = [task_key for task_key in task_keys if is_high_flux_chain_task(task_key)]
    chemistry_intervals = []
    for task_key in chemistry_chain_task_keys:
        for machine_code in task_data[task_key]["machines"]:
            optional_interval = interval_vars.get((task_key, machine_code))
            if optional_interval is not None:
                chemistry_intervals.append(optional_interval)
    if chemistry_intervals:
        model.AddNoOverlap(chemistry_intervals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        chain_keys = sorted([key for key in ordered_task_keys if is_high_flux_chain_task(key)], key=lambda key: key[1])
        for left_key, right_key in zip(chain_keys, chain_keys[1:]):
            model.Add(end_vars[left_key] == start_vars[right_key])

    for expr_no, first_task_keys in expr_to_first_tasks.items():
        if len(first_task_keys) > 1:
            anchor_key = first_task_keys[0]
            for other_key in first_task_keys[1:]:
                model.Add(start_vars[other_key] == start_vars[anchor_key])
                model.Add(end_vars[other_key] == end_vars[anchor_key])

    def extract_temperature(task_key):
        task = task_data[task_key]["task"]
        for param_entry in task.get("parameters", []) or []:
            param = param_entry.get("param", {}) or {}
            if "temperature" in param:
                try:
                    return float(param["temperature"])
                except Exception:
                    return str(param["temperature"])
            if "custom_param" in param:
                try:
                    custom_param = json.loads(param["custom_param"])
                    if "temperature" in custom_param:
                        try:
                            return float(custom_param["temperature"])
                        except Exception:
                            return str(custom_param["temperature"])
                except Exception:
                    pass
        return None

    for machine_code, interval_entries in machine_to_intervals.items():
        lower_machine = machine_code.lower()
        if "muffle" not in lower_machine and "dryer" not in lower_machine:
            continue
        for idx, entry_i in enumerate(interval_entries):
            task_key_i, _, presence_i, _ = entry_i
            temp_i = extract_temperature(task_key_i)
            for entry_j in interval_entries[idx + 1:]:
                task_key_j, _, presence_j, _ = entry_j
                temp_j = extract_temperature(task_key_j)
                if temp_i is not None and temp_j is not None and temp_i != temp_j:
                    if both_fixed_overlap(task_key_i, task_key_j):
                        continue
                    i_before_j, j_before_i = add_pairwise_disjunction(machine_code, entry_i, entry_j, "thermal")
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])

    centrifuge_machine_to_tasks = {}
    for task_key in task_keys:
        centrifuge_machines = [m for m in task_data[task_key]["machines"] if "centrifug" in m.lower()]
        for machine_code in centrifuge_machines:
            centrifuge_machine_to_tasks.setdefault(machine_code, []).append(task_key)

    for machine_code, centrifuge_task_keys in centrifuge_machine_to_tasks.items():
        duration_groups = {}
        for task_key in centrifuge_task_keys:
            duration_groups.setdefault(task_data[task_key]["duration"], []).append(task_key)

        paired_task_keys = set()
        for duration, same_duration_keys in duration_groups.items():
            same_duration_keys = sorted(
                same_duration_keys,
                key=lambda key: (
                    str(task_data[key].get("expr_no")),
                    int(task_data[key]["task"].get("step_index", 0) or 0),
                    str(key[0]),
                    int(key[1]),
                ),
            )
            for idx in range(0, len(same_duration_keys) - 1, 2):
                left_key = same_duration_keys[idx]
                right_key = same_duration_keys[idx + 1]
                model.Add(start_vars[left_key] == start_vars[right_key])
                model.Add(end_vars[left_key] == end_vars[right_key])
                paired_task_keys.add(left_key)
                paired_task_keys.add(right_key)
                if (left_key, machine_code) in presence and (right_key, machine_code) in presence:
                    model.AddImplication(presence[(left_key, machine_code)], presence[(right_key, machine_code)])
                    model.AddImplication(presence[(right_key, machine_code)], presence[(left_key, machine_code)])

        leftovers = [key for key in centrifuge_task_keys if key not in paired_task_keys]
        if len(leftovers) >= 2:
            leftovers = sorted(leftovers, key=lambda key: (task_data[key]["duration"], str(key[0]), int(key[1])))
            for idx in range(0, len(leftovers) - 1, 2):
                left_key = leftovers[idx]
                right_key = leftovers[idx + 1]
                if task_data[left_key]["duration"] == task_data[right_key]["duration"]:
                    model.Add(start_vars[left_key] == start_vars[right_key])
                    model.Add(end_vars[left_key] == end_vars[right_key])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[key] for key in task_keys])
    model.Minimize(makespan)

    greedy_machine_available = {machine_code: cur_ptr for machine_code in machines_capacity}
    greedy_starts = {}
    greedy_ends = {}
    greedy_machines = {}

    for expr_no, first_keys in expr_to_first_tasks.items():
        fixed_first = [key for key in first_keys if task_data[key]["is_fixed"]]
        if fixed_first:
            anchor_start = int(task_data[fixed_first[0]]["fixed_start"])
            anchor_end = int(task_data[fixed_first[0]]["fixed_end"])
        else:
            anchor_start = cur_ptr
            anchor_end = cur_ptr + (task_data[first_keys[0]]["duration"] if first_keys else 0)
        for key in first_keys:
            if not task_data[key]["is_fixed"]:
                greedy_starts[key] = anchor_start
                greedy_ends[key] = anchor_end

    for job in jobs:
        job_id = str(job.get("job_id"))
        current_time = 0
        for task_key in sorted(job_to_tasks.get(job_id, []), key=lambda key: key[1]):
            info = task_data[task_key]
            if info["is_fixed"]:
                machine = info["scheduled_machine"] or (info["machines"][0] if info["machines"] else "")
                greedy_machines[task_key] = machine
                current_time = max(current_time, int(info["fixed_end"]))
                greedy_machine_available[machine] = max(greedy_machine_available.get(machine, cur_ptr), int(info["fixed_end"]))
            else:
                preferred = info["task"].get("nominal_machine")
                if preferred is None or str(preferred) not in info["machines"]:
                    preferred = info["machines"][0] if info["machines"] else ""
                preferred = str(preferred)
                start = max(current_time, greedy_machine_available.get(preferred, cur_ptr), cur_ptr, greedy_starts.get(task_key, cur_ptr))
                end = start + info["duration"]
                greedy_starts[task_key] = start
                greedy_ends[task_key] = end
                greedy_machines[task_key] = preferred
                current_time = end
                greedy_machine_available[preferred] = end

    for task_key in task_keys:
        info = task_data[task_key]
        if info["is_fixed"]:
            continue
        if task_key in start_vars:
            model.AddHint(start_vars[task_key], int(greedy_starts.get(task_key, cur_ptr)))
            model.AddHint(end_vars[task_key], int(greedy_ends.get(task_key, cur_ptr + info["duration"])))
        preferred_machine = greedy_machines.get(task_key) or info["task"].get("nominal_machine")
        if preferred_machine is None or str(preferred_machine) not in info["machines"]:
            preferred_machine = info["machines"][0] if info["machines"] else ""
        preferred_machine = str(preferred_machine)
        for machine_code in info["machines"]:
            model.AddHint(presence[(task_key, machine_code)], 1 if machine_code == preferred_machine else 0)

    try:
        model.AddDecisionStrategy(
            [start_vars[key] for key in task_keys if not task_data[key]["is_fixed"]],
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )
    except Exception:
        pass

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(10.0, outer_timeout - 8.0)
    solver.parameters.num_search_workers = min(8, max(1, os.cpu_count() or 1))
    solver.parameters.random_seed = 17
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        marker_model = cp_model.CpModel()
        marker = marker_model.NewBoolVar("unsolved_cp_sat_marker")
        marker_model.Add(marker == 1)
        marker_solver = cp_model.CpSolver()
        marker_solver.parameters.max_time_in_seconds = 0.01
        marker_solver.Solve(marker_model)
        return {"assignments": []}

    assignments = []
    for task_key in sorted(task_keys, key=lambda key: (str(key[0]), int(key[1]))):
        job_id, task_id = task_key
        info = task_data[task_key]
        selected_machine = None
        for machine_code in info["machines"]:
            if solver.Value(presence[(task_key, machine_code)]) == 1:
                selected_machine = machine_code
                break
        if selected_machine is None:
            selected_machine = info["scheduled_machine"] or (info["machines"][0] if info["machines"] else "")
        assignments.append({
            "job_id": job_id,
            "task_id": int(task_id),
            "machine": selected_machine,
            "start": int(solver.Value(start_vars[task_key])),
            "end": int(solver.Value(end_vars[task_key])),
        })

    return {"assignments": assignments}