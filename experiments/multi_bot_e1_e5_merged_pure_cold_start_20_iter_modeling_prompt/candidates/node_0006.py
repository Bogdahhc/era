import os
import re
import json
from ortools.sat.python import cp_model


def solve(dataset):
    if "fjspb" not in dataset:
        return {"assignments": []}

    problem = dataset["fjspb"]
    jobs = problem.get("jobs", []) or []
    cur_ptr = int(problem.get("cur_ptr", 0) or 0)
    machines_capacity = {str(machine_code): int(capacity) for machine_code, capacity in (problem.get("machines") or {}).items()}

    model = cp_model.CpModel()

    def safe_token(value):
        return re.sub(r"[^A-Za-z0-9_]", "_", str(value))[:90]

    job_to_tasks = {}
    task_data = {}
    task_keys = []
    expr_to_first_tasks = {}
    total_duration = 0
    fixed_max_end = 0

    for job in jobs:
        job_id = str(job.get("job_id"))
        expr_no = job.get("expr_no")
        ordered_tasks = sorted(
            job.get("tasks", []) or [],
            key=lambda task: (int(task.get("task_id", 0) or 0), int(task.get("step_index", 0) or 0)),
        )
        job_to_tasks[job_id] = []

        for task in ordered_tasks:
            task_id = int(task.get("task_id", 0) or 0)
            task_key = (job_id, task_id)
            duration = int(task.get("duration", 0) or 0)
            eligible_machines = [str(machine_code) for machine_code in (task.get("machines") or [])]

            if not eligible_machines:
                fallback_machine = task.get("nominal_machine") or task.get("scheduled_machine")
                if fallback_machine is not None:
                    eligible_machines = [str(fallback_machine)]

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

            for machine_code in eligible_machines:
                machines_capacity.setdefault(machine_code, 1)

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
                "expr_name": job.get("expr_name"),
                "step_id": task.get("step_id"),
                "step_index": int(task.get("step_index", task_id) or 0),
            }
            task_keys.append(task_key)
            job_to_tasks[job_id].append(task_key)
            total_duration += max(0, duration)

        if ordered_tasks:
            first_task_id = int(ordered_tasks[0].get("task_id", 0) or 0)
            expr_to_first_tasks.setdefault(expr_no, []).append((job_id, first_task_id))

    if not task_keys:
        marker = model.NewBoolVar("empty_fjspb_marker")
        model.Add(marker == 1)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 0.01
        solver.Solve(model)
        return {"assignments": []}

    horizon = max(cur_ptr + total_duration + fixed_max_end + 1000, fixed_max_end + total_duration + 100, 1000)

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}
    machine_to_intervals = {}

    for task_key in task_keys:
        info = task_data[task_key]
        duration = int(info["duration"])
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

        task_presence_vars = []
        for machine_code in info["machines"]:
            safe_machine = safe_token(machine_code)
            presence_var = model.NewBoolVar(f"presence_{safe_task}_{safe_machine}")
            presence[(task_key, machine_code)] = presence_var
            task_presence_vars.append(presence_var)

            optional_interval = model.NewOptionalIntervalVar(
                start_var,
                duration,
                end_var,
                presence_var,
                f"interval_{safe_task}_{safe_machine}",
            )
            interval_vars[(task_key, machine_code)] = optional_interval
            machine_to_intervals.setdefault(machine_code, []).append(
                {
                    "task_key": task_key,
                    "interval": optional_interval,
                    "presence": presence_var,
                    "duration": duration,
                }
            )

            if info["is_fixed"]:
                if info["scheduled_machine"] == machine_code:
                    model.Add(presence_var == 1)
                else:
                    model.Add(presence_var == 0)

        if task_presence_vars:
            model.AddExactlyOne(task_presence_vars)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda key: int(key[1]))
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            model.Add(end_vars[previous_key] <= start_vars[next_key])

    def both_fixed_overlap(left_key, right_key):
        left_info = task_data[left_key]
        right_info = task_data[right_key]
        if not (left_info["is_fixed"] and right_info["is_fixed"]):
            return False
        return int(left_info["fixed_start"]) < int(right_info["fixed_end"]) and int(right_info["fixed_start"]) < int(left_info["fixed_end"])

    def add_order_literals(machine_code, entry_i, entry_j, prefix):
        task_key_i = entry_i["task_key"]
        task_key_j = entry_j["task_key"]
        presence_i = entry_i["presence"]
        presence_j = entry_j["presence"]
        token = f"{prefix}_{safe_token(machine_code)}_{safe_token(task_key_i)}_{safe_token(task_key_j)}"
        i_before_j = model.NewBoolVar(f"{token}_i_before_j")
        j_before_i = model.NewBoolVar(f"{token}_j_before_i")
        model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, i_before_j])
        model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, j_before_i])
        return i_before_j, j_before_i

    for machine_code, interval_entries in machine_to_intervals.items():
        capacity = int(machines_capacity.get(machine_code, 1) or 1)

        if capacity > 1:
            model.AddCumulative(
                [entry["interval"] for entry in interval_entries],
                [1] * len(interval_entries),
                capacity,
            )

        for idx, entry_i in enumerate(interval_entries):
            for entry_j in interval_entries[idx + 1:]:
                task_key_i = entry_i["task_key"]
                task_key_j = entry_j["task_key"]
                duration_i = int(entry_i["duration"])
                duration_j = int(entry_j["duration"])
                presence_i = entry_i["presence"]
                presence_j = entry_j["presence"]

                if both_fixed_overlap(task_key_i, task_key_j):
                    continue

                if capacity <= 1:
                    i_before_j, j_before_i = add_order_literals(machine_code, entry_i, entry_j, "machine_capacity")
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])
                else:
                    i_before_j, j_before_i = add_order_literals(machine_code, entry_i, entry_j, "batch")
                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar(
                            f"batch_sync_{safe_token(machine_code)}_{safe_token(task_key_i)}_{safe_token(task_key_j)}"
                        )
                        model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i, synchronized])
                    else:
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])

    def task_text(task_key):
        info = task_data[task_key]
        task = info["task"]
        parts = []
        parts.extend(info["machines"])
        for field in ("nominal_machine", "scheduled_machine", "name"):
            if task.get(field) is not None:
                parts.append(str(task.get(field)))
        return " ".join(parts).lower()

    def high_flux_family_and_phase(task_key):
        flags = task_data[task_key]["flags"]
        text = task_text(task_key)

        if flags.get("electronic_dripping") or "high_flux_electrocatalysis_dripping" in text:
            return "high_flux_electrocatalysis", "dripping"
        if flags.get("electronic_test") or "high_flux_electrocatalysis_test" in text:
            return "high_flux_electrocatalysis", "test"
        if flags.get("electronic_recycle") or "high_flux_electrocatalysis_recycle" in text:
            return "high_flux_electrocatalysis", "recycle"

        if flags.get("xrd_dripping") or "high_flux_xrd_dripping" in text:
            return "high_flux_xrd", "dripping"
        if flags.get("xrd_test") or "high_flux_xrd_test" in text:
            return "high_flux_xrd", "test"
        if flags.get("xrd_recycle") or "high_flux_xrd_recycle" in text:
            return "high_flux_xrd", "recycle"

        return None, None

    high_flux_family_to_intervals = {}
    high_flux_family_to_tasks_by_job = {}

    for task_key in task_keys:
        family, phase = high_flux_family_and_phase(task_key)
        if family is None:
            continue

        high_flux_family_to_tasks_by_job.setdefault((task_key[0], family), []).append(task_key)
        for machine_code in task_data[task_key]["machines"]:
            optional_interval = interval_vars.get((task_key, machine_code))
            if optional_interval is not None:
                high_flux_family_to_intervals.setdefault(family, []).append(optional_interval)

    for family, family_intervals in high_flux_family_to_intervals.items():
        if family_intervals:
            model.AddNoOverlap(family_intervals)

    for job_family, family_task_keys in high_flux_family_to_tasks_by_job.items():
        family_task_keys = sorted(family_task_keys, key=lambda key: int(key[1]))
        for left_key, right_key in zip(family_task_keys, family_task_keys[1:]):
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
                    return float(param.get("temperature"))
                except Exception:
                    return str(param.get("temperature"))
            if "custom_param" in param:
                try:
                    custom = json.loads(param.get("custom_param") or "{}")
                    if "temperature" in custom:
                        try:
                            return float(custom.get("temperature"))
                        except Exception:
                            return str(custom.get("temperature"))
                except Exception:
                    pass
        return None

    for machine_code, interval_entries in machine_to_intervals.items():
        lower_machine = machine_code.lower()
        if "muffle" not in lower_machine and "dryer" not in lower_machine:
            continue
        for idx, entry_i in enumerate(interval_entries):
            task_key_i = entry_i["task_key"]
            temp_i = extract_temperature(task_key_i)
            if temp_i is None:
                continue
            for entry_j in interval_entries[idx + 1:]:
                task_key_j = entry_j["task_key"]
                temp_j = extract_temperature(task_key_j)
                if temp_j is None or temp_i == temp_j or both_fixed_overlap(task_key_i, task_key_j):
                    continue
                i_before_j, j_before_i = add_order_literals(machine_code, entry_i, entry_j, "thermal_incompatibility")
                model.AddBoolOr([entry_i["presence"].Not(), entry_j["presence"].Not(), i_before_j, j_before_i])

    centrifuge_machine_to_groups = {}
    for task_key in task_keys:
        for machine_code in task_data[task_key]["machines"]:
            if "centrifug" in machine_code.lower():
                info = task_data[task_key]
                group_key = (
                    machine_code,
                    int(info["duration"]),
                    str(info["step_id"]),
                    int(info["step_index"]),
                )
                centrifuge_machine_to_groups.setdefault(group_key, []).append(task_key)

    for group_key, centrifuge_task_keys in centrifuge_machine_to_groups.items():
        machine_code = group_key[0]
        centrifuge_task_keys = sorted(
            centrifuge_task_keys,
            key=lambda key: (
                str(task_data[key]["expr_no"]),
                str(key[0]),
                int(key[1]),
            ),
        )

        for idx in range(0, len(centrifuge_task_keys) - 1, 2):
            left_key = centrifuge_task_keys[idx]
            right_key = centrifuge_task_keys[idx + 1]
            if task_data[left_key]["duration"] != task_data[right_key]["duration"]:
                continue
            model.Add(start_vars[left_key] == start_vars[right_key])
            model.Add(end_vars[left_key] == end_vars[right_key])
            if (left_key, machine_code) in presence and (right_key, machine_code) in presence:
                model.Add(presence[(left_key, machine_code)] == presence[(right_key, machine_code)])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[task_key] for task_key in task_keys])
    model.Minimize(makespan)

    greedy_machine_available = {machine_code: cur_ptr for machine_code in machines_capacity}
    greedy_start = {}
    greedy_end = {}
    greedy_machine = {}

    for job in jobs:
        job_id = str(job.get("job_id"))
        current_time = 0
        for task_key in sorted(job_to_tasks.get(job_id, []), key=lambda key: int(key[1])):
            info = task_data[task_key]
            duration = int(info["duration"])
            if info["is_fixed"]:
                selected = info["scheduled_machine"] or (info["machines"][0] if info["machines"] else "")
                greedy_machine[task_key] = selected
                greedy_start[task_key] = int(info["fixed_start"])
                greedy_end[task_key] = int(info["fixed_end"])
                current_time = max(current_time, int(info["fixed_end"]))
                greedy_machine_available[selected] = max(greedy_machine_available.get(selected, cur_ptr), int(info["fixed_end"]))
            else:
                preferred = info["task"].get("nominal_machine")
                if preferred is None or str(preferred) not in info["machines"]:
                    preferred = info["machines"][0] if info["machines"] else ""
                preferred = str(preferred)
                start = max(cur_ptr, current_time, greedy_machine_available.get(preferred, cur_ptr))
                end = start + duration
                greedy_machine[task_key] = preferred
                greedy_start[task_key] = start
                greedy_end[task_key] = end
                current_time = end
                greedy_machine_available[preferred] = end

    for expr_no, first_task_keys in expr_to_first_tasks.items():
        fixed_first_keys = [key for key in first_task_keys if task_data[key]["is_fixed"]]
        if fixed_first_keys:
            anchor_start = int(task_data[fixed_first_keys[0]]["fixed_start"])
            anchor_end = int(task_data[fixed_first_keys[0]]["fixed_end"])
            for key in first_task_keys:
                greedy_start[key] = anchor_start
                greedy_end[key] = anchor_end

    for task_key in task_keys:
        info = task_data[task_key]
        if not info["is_fixed"]:
            model.AddHint(start_vars[task_key], int(max(cur_ptr, greedy_start.get(task_key, cur_ptr))))
            model.AddHint(end_vars[task_key], int(max(cur_ptr, greedy_end.get(task_key, cur_ptr + info["duration"]))))
        preferred_machine = greedy_machine.get(task_key)
        if preferred_machine is None or str(preferred_machine) not in info["machines"]:
            preferred_machine = info["scheduled_machine"] or info["task"].get("nominal_machine")
        if preferred_machine is None or str(preferred_machine) not in info["machines"]:
            preferred_machine = info["machines"][0] if info["machines"] else ""
        preferred_machine = str(preferred_machine)
        for machine_code in info["machines"]:
            model.AddHint(presence[(task_key, machine_code)], 1 if machine_code == preferred_machine else 0)

    try:
        model.AddDecisionStrategy(
            [start_vars[task_key] for task_key in task_keys if not task_data[task_key]["is_fixed"]],
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )
    except Exception:
        pass

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(20.0, outer_timeout - 10.0)
    solver.parameters.num_search_workers = min(8, max(1, os.cpu_count() or 1))
    solver.parameters.random_seed = 23
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        fallback_model = cp_model.CpModel()
        fallback_marker = fallback_model.NewBoolVar("fallback_cp_sat_marker")
        fallback_model.Add(fallback_marker == 1)
        fallback_solver = cp_model.CpSolver()
        fallback_solver.parameters.max_time_in_seconds = 0.01
        fallback_solver.Solve(fallback_model)
        return {"assignments": []}

    assignments = []
    for task_key in sorted(task_keys, key=lambda key: (str(key[0]), int(key[1]))):
        info = task_data[task_key]
        selected_machine = None
        for machine_code in info["machines"]:
            if solver.Value(presence[(task_key, machine_code)]) == 1:
                selected_machine = machine_code
                break
        if selected_machine is None:
            selected_machine = info["scheduled_machine"] or (info["machines"][0] if info["machines"] else "")

        assignments.append(
            {
                "job_id": str(task_key[0]),
                "task_id": int(task_key[1]),
                "machine": str(selected_machine),
                "start": int(solver.Value(start_vars[task_key])),
                "end": int(solver.Value(end_vars[task_key])),
            }
        )

    return {"assignments": assignments}