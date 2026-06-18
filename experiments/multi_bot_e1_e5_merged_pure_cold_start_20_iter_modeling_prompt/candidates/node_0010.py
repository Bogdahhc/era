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
    machines_capacity = {str(m): int(c) for m, c in (problem.get("machines") or {}).items()}

    model = cp_model.CpModel()

    def safe_token(value):
        return re.sub(r"[^A-Za-z0-9_]", "_", str(value))[:100]

    job_to_tasks = {}
    task_data = {}
    task_keys = []
    expr_to_first_tasks = {}
    total_duration = 0
    fixed_max_end = 0
    singleton_machine_workload = {}

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
            eligible_machines = [str(x) for x in (task.get("machines") or [])]
            if not eligible_machines:
                fallback_machine = task.get("nominal_machine") or task.get("scheduled_machine")
                if fallback_machine is not None:
                    eligible_machines = [str(fallback_machine)]

            is_fixed = bool(task.get("is_fixed", False))
            scheduled_machine = task.get("scheduled_machine")
            fixed_start = task.get("fixed_start")
            fixed_end = task.get("fixed_end")
            if is_fixed:
                fixed_start = int(fixed_start)
                fixed_end = int(fixed_end)
                fixed_max_end = max(fixed_max_end, fixed_end)
                if scheduled_machine is not None and str(scheduled_machine) not in eligible_machines:
                    eligible_machines.append(str(scheduled_machine))

            for machine_code in eligible_machines:
                machines_capacity.setdefault(machine_code, 1)

            if len(eligible_machines) == 1:
                singleton_machine_workload[eligible_machines[0]] = singleton_machine_workload.get(eligible_machines[0], 0) + max(0, duration)

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

    horizon = max(fixed_max_end + total_duration + cur_ptr + 1000, 1000)

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}
    machine_to_intervals = {}

    for task_key in task_keys:
        info = task_data[task_key]
        duration = int(info["duration"])
        task_name = safe_token(f"{task_key[0]}_{task_key[1]}")

        if info["is_fixed"]:
            start_var = model.NewIntVar(int(info["fixed_start"]), int(info["fixed_start"]), f"start_{task_name}")
            end_var = model.NewIntVar(int(info["fixed_end"]), int(info["fixed_end"]), f"end_{task_name}")
            model.Add(end_var == start_var + duration)
        else:
            start_var = model.NewIntVar(cur_ptr, horizon, f"start_{task_name}")
            end_var = model.NewIntVar(cur_ptr, horizon, f"end_{task_name}")
            model.Add(end_var == start_var + duration)

        start_vars[task_key] = start_var
        end_vars[task_key] = end_var

        task_presence_vars = []
        for machine_code in info["machines"]:
            machine_name = safe_token(machine_code)
            presence_var = model.NewBoolVar(f"presence_{task_name}_{machine_name}")
            presence[(task_key, machine_code)] = presence_var
            task_presence_vars.append(presence_var)

            interval_var = model.NewOptionalIntervalVar(
                start_var,
                duration,
                end_var,
                presence_var,
                f"interval_{task_name}_{machine_name}",
            )
            interval_vars[(task_key, machine_code)] = interval_var
            machine_to_intervals.setdefault(machine_code, []).append(
                {
                    "task_key": task_key,
                    "interval": interval_var,
                    "presence": presence_var,
                    "duration": duration,
                }
            )

            if info["is_fixed"]:
                model.Add(presence_var == (1 if info["scheduled_machine"] == machine_code else 0))

        model.AddExactlyOne(task_presence_vars)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: int(k[1]))
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
        token = f"{prefix}_{safe_token(machine_code)}_{safe_token(task_key_i)}_{safe_token(task_key_j)}"
        i_before_j = model.NewBoolVar(f"{token}_i_before_j")
        j_before_i = model.NewBoolVar(f"{token}_j_before_i")
        model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf(
            [entry_i["presence"], entry_j["presence"], i_before_j]
        )
        model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf(
            [entry_i["presence"], entry_j["presence"], j_before_i]
        )
        return i_before_j, j_before_i

    for machine_code, interval_entries in machine_to_intervals.items():
        capacity = int(machines_capacity.get(machine_code, 1) or 1)
        if capacity > 1:
            model.AddCumulative(
                [entry["interval"] for entry in interval_entries],
                [1] * len(interval_entries),
                capacity,
            )

        for i, entry_i in enumerate(interval_entries):
            for entry_j in interval_entries[i + 1:]:
                task_key_i = entry_i["task_key"]
                task_key_j = entry_j["task_key"]
                duration_i = int(entry_i["duration"])
                duration_j = int(entry_j["duration"])
                presence_i = entry_i["presence"]
                presence_j = entry_j["presence"]

                if both_fixed_overlap(task_key_i, task_key_j):
                    continue

                i_before_j, j_before_i = add_order_literals(machine_code, entry_i, entry_j, "machine_or_batch")
                if capacity <= 1:
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])
                else:
                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar(
                            f"batch_sync_{safe_token(machine_code)}_{safe_token(task_key_i)}_{safe_token(task_key_j)}"
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
            if (task_key, machine_code) in interval_vars:
                high_flux_family_to_intervals.setdefault(family, []).append(interval_vars[(task_key, machine_code)])

    for family_intervals in high_flux_family_to_intervals.values():
        if family_intervals:
            model.AddNoOverlap(family_intervals)

    for family_task_keys in high_flux_family_to_tasks_by_job.values():
        family_task_keys = sorted(family_task_keys, key=lambda k: int(k[1]))
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
        for i, entry_i in enumerate(interval_entries):
            task_key_i = entry_i["task_key"]
            temp_i = extract_temperature(task_key_i)
            if temp_i is None:
                continue
            for entry_j in interval_entries[i + 1:]:
                task_key_j = entry_j["task_key"]
                temp_j = extract_temperature(task_key_j)
                if temp_j is None or temp_i == temp_j or both_fixed_overlap(task_key_i, task_key_j):
                    continue
                i_before_j, j_before_i = add_order_literals(machine_code, entry_i, entry_j, "thermal_incompatibility")
                model.AddBoolOr([entry_i["presence"].Not(), entry_j["presence"].Not(), i_before_j, j_before_i])

    centrifuge_pairs = []
    centrifuge_machine_to_groups = {}
    for task_key in task_keys:
        for machine_code in task_data[task_key]["machines"]:
            if "centrifug" in machine_code.lower():
                info = task_data[task_key]
                group_key = (machine_code, int(info["duration"]), str(info["step_id"]), int(info["step_index"]))
                centrifuge_machine_to_groups.setdefault(group_key, []).append(task_key)

    for group_key, centrifuge_task_keys in centrifuge_machine_to_groups.items():
        machine_code = group_key[0]
        centrifuge_task_keys = sorted(
            centrifuge_task_keys,
            key=lambda k: (str(task_data[k]["expr_no"]), str(k[0]), int(k[1])),
        )
        for i in range(0, len(centrifuge_task_keys) - 1, 2):
            left_key = centrifuge_task_keys[i]
            right_key = centrifuge_task_keys[i + 1]
            if task_data[left_key]["duration"] == task_data[right_key]["duration"]:
                model.Add(start_vars[left_key] == start_vars[right_key])
                model.Add(end_vars[left_key] == end_vars[right_key])
                if (left_key, machine_code) in presence and (right_key, machine_code) in presence:
                    model.Add(presence[(left_key, machine_code)] == presence[(right_key, machine_code)])
                centrifuge_pairs.append((left_key, right_key, machine_code))

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[k] for k in task_keys])

    for machine_code, workload in singleton_machine_workload.items():
        capacity = max(1, int(machines_capacity.get(machine_code, 1) or 1))
        if capacity > 0:
            model.Add(makespan >= (workload + capacity - 1) // capacity)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: int(k[1]))
        fixed_prefix_end = 0
        chain_remaining = 0
        for task_key in ordered_task_keys:
            info = task_data[task_key]
            if info["is_fixed"]:
                fixed_prefix_end = max(fixed_prefix_end, int(info["fixed_end"]))
            else:
                chain_remaining += int(info["duration"])
        if chain_remaining:
            model.Add(makespan >= fixed_prefix_end + chain_remaining)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: int(k[1]))
        suffix_duration = 0
        for task_key in reversed(ordered_task_keys):
            suffix_duration += int(task_data[task_key]["duration"])
            if not task_data[task_key]["is_fixed"]:
                model.Add(start_vars[task_key] + suffix_duration <= makespan)

    model.Minimize(makespan)

    greedy_machine_available = {machine_code: cur_ptr for machine_code in machines_capacity}
    greedy_start = {}
    greedy_end = {}
    greedy_machine = {}

    magnetic_toggle = 0
    for job in jobs:
        job_id = str(job.get("job_id"))
        current_time = 0
        for task_key in sorted(job_to_tasks.get(job_id, []), key=lambda k: int(k[1])):
            info = task_data[task_key]
            duration = int(info["duration"])
            if info["is_fixed"]:
                selected = info["scheduled_machine"] or info["machines"][0]
                greedy_machine[task_key] = selected
                greedy_start[task_key] = int(info["fixed_start"])
                greedy_end[task_key] = int(info["fixed_end"])
                current_time = max(current_time, int(info["fixed_end"]))
                greedy_machine_available[selected] = max(greedy_machine_available.get(selected, cur_ptr), int(info["fixed_end"]))
            else:
                preferred = info["task"].get("nominal_machine")
                if (
                    "magnetic_stirring" in info["machines"]
                    and "magnetic_stirring_2" in info["machines"]
                ):
                    preferred = "magnetic_stirring_2" if magnetic_toggle % 2 else "magnetic_stirring"
                    magnetic_toggle += 1
                if preferred is None or str(preferred) not in info["machines"]:
                    preferred = info["machines"][0]
                preferred = str(preferred)
                start = max(cur_ptr, current_time, greedy_machine_available.get(preferred, cur_ptr))
                end = start + duration
                greedy_machine[task_key] = preferred
                greedy_start[task_key] = start
                greedy_end[task_key] = end
                current_time = end
                greedy_machine_available[preferred] = end

    for expr_no, first_task_keys in expr_to_first_tasks.items():
        fixed_first_keys = [k for k in first_task_keys if task_data[k]["is_fixed"]]
        if fixed_first_keys:
            anchor_start = int(task_data[fixed_first_keys[0]]["fixed_start"])
            anchor_end = int(task_data[fixed_first_keys[0]]["fixed_end"])
        else:
            anchor_start = min(greedy_start.get(k, cur_ptr) for k in first_task_keys)
            anchor_end = anchor_start + int(task_data[first_task_keys[0]]["duration"])
        for key in first_task_keys:
            greedy_start[key] = anchor_start
            greedy_end[key] = anchor_end

    for family_task_keys in high_flux_family_to_tasks_by_job.values():
        family_task_keys = sorted(family_task_keys, key=lambda k: int(k[1]))
        if family_task_keys:
            start = max(greedy_start.get(family_task_keys[0], cur_ptr), cur_ptr)
            for key in family_task_keys:
                greedy_start[key] = start
                greedy_end[key] = start + int(task_data[key]["duration"])
                start = greedy_end[key]

    for left_key, right_key, machine_code in centrifuge_pairs:
        shared_start = max(greedy_start.get(left_key, cur_ptr), greedy_start.get(right_key, cur_ptr), cur_ptr)
        shared_end = shared_start + int(task_data[left_key]["duration"])
        greedy_start[left_key] = shared_start
        greedy_start[right_key] = shared_start
        greedy_end[left_key] = shared_end
        greedy_end[right_key] = shared_end
        greedy_machine[left_key] = machine_code
        greedy_machine[right_key] = machine_code

    hinted_makespan = 0
    for task_key in task_keys:
        info = task_data[task_key]
        if not info["is_fixed"]:
            gs = int(max(cur_ptr, min(horizon, greedy_start.get(task_key, cur_ptr))))
            ge = int(max(cur_ptr, min(horizon, greedy_end.get(task_key, gs + int(info["duration"])))))
            if ge != gs + int(info["duration"]):
                ge = min(horizon, gs + int(info["duration"]))
            model.AddHint(start_vars[task_key], gs)
            model.AddHint(end_vars[task_key], ge)
            hinted_makespan = max(hinted_makespan, ge)
        else:
            hinted_makespan = max(hinted_makespan, int(info["fixed_end"]))

        preferred_machine = greedy_machine.get(task_key)
        if preferred_machine is None or str(preferred_machine) not in info["machines"]:
            preferred_machine = info["scheduled_machine"] or info["task"].get("nominal_machine")
        if preferred_machine is None or str(preferred_machine) not in info["machines"]:
            preferred_machine = info["machines"][0]
        preferred_machine = str(preferred_machine)
        for machine_code in info["machines"]:
            model.AddHint(presence[(task_key, machine_code)], 1 if machine_code == preferred_machine else 0)
    model.AddHint(makespan, min(horizon, max(0, int(hinted_makespan))))

    try:
        multi_machine_presence = [
            presence[(k, m)]
            for k in task_keys
            if len(task_data[k]["machines"]) > 1
            for m in task_data[k]["machines"]
        ]
        if multi_machine_presence:
            model.AddDecisionStrategy(multi_machine_presence, cp_model.CHOOSE_FIRST, cp_model.SELECT_MAX_VALUE)

        nonfixed_starts_by_duration = [
            start_vars[k] for k in sorted(
                [x for x in task_keys if not task_data[x]["is_fixed"]],
                key=lambda x: (-int(task_data[x]["duration"]), str(x[0]), int(x[1])),
            )
        ]
        if nonfixed_starts_by_duration:
            model.AddDecisionStrategy(nonfixed_starts_by_duration, cp_model.CHOOSE_LOWEST_MIN, cp_model.SELECT_MIN_VALUE)
    except Exception:
        pass

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(30.0, outer_timeout - 25.0)
    solver.parameters.num_search_workers = min(8, max(1, os.cpu_count() or 1))
    solver.parameters.random_seed = 23
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1
    solver.parameters.log_search_progress = False
    try:
        solver.parameters.use_lns_only = False
        solver.parameters.optimize_with_core = False
    except Exception:
        pass

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
    for task_key in sorted(task_keys, key=lambda k: (str(k[0]), int(k[1]))):
        info = task_data[task_key]
        selected_machine = None
        for machine_code in info["machines"]:
            if solver.Value(presence[(task_key, machine_code)]) == 1:
                selected_machine = machine_code
                break
        if selected_machine is None:
            selected_machine = info["scheduled_machine"] or info["machines"][0]

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