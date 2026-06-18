import os
import json
import re
from itertools import combinations
from ortools.sat.python import cp_model


def solve(dataset):
    if "fjspb" not in dataset:
        return {"assignments": []}

    problem = dataset["fjspb"]
    machines_capacity = {str(m): int(c) for m, c in problem.get("machines", {}).items()}
    jobs = problem.get("jobs", [])
    cur_ptr = int(problem.get("cur_ptr", 0) or 0)

    model = cp_model.CpModel()

    job_to_tasks = {}
    task_data = {}
    task_keys = []
    machine_to_task_keys = {}
    expr_to_first_tasks = {}

    fixed_max_end = 0
    total_duration = 0

    for job in jobs:
        job_id = job.get("job_id")
        ordered_tasks = sorted(job.get("tasks", []), key=lambda t: (int(t.get("task_id", 0)), int(t.get("step_index", 0) or 0)))
        job_to_tasks[job_id] = []
        expr_no = job.get("expr_no")
        for task in ordered_tasks:
            task_id = int(task.get("task_id"))
            task_key = (job_id, task_id)
            duration = int(task.get("duration", 0) or 0)
            eligible_machines = [str(m) for m in task.get("machines", [])]
            if not eligible_machines:
                nominal = task.get("nominal_machine") or task.get("scheduled_machine")
                if nominal:
                    eligible_machines = [str(nominal)]
            for machine_code in eligible_machines:
                machine_to_task_keys.setdefault(machine_code, []).append(task_key)
                if machine_code not in machines_capacity:
                    machines_capacity[machine_code] = 1
            task_data[task_key] = {
                "job": job,
                "task": task,
                "duration": duration,
                "machines": eligible_machines,
                "is_fixed": bool(task.get("is_fixed", False)),
                "fixed_start": task.get("fixed_start"),
                "fixed_end": task.get("fixed_end"),
                "scheduled_machine": task.get("scheduled_machine"),
                "flags": task.get("flags", {}) or {},
                "expr_no": expr_no,
            }
            task_keys.append(task_key)
            job_to_tasks[job_id].append(task_key)
            total_duration += max(0, duration)
            if task.get("is_fixed", False):
                fixed_max_end = max(fixed_max_end, int(task.get("fixed_end", 0) or 0))

        if ordered_tasks:
            first_task = ordered_tasks[0]
            first_key = (job_id, int(first_task.get("task_id")))
            expr_to_first_tasks.setdefault(expr_no, []).append(first_key)

    horizon = max(fixed_max_end + total_duration + cur_ptr + 100, cur_ptr + total_duration + 100, 1000)

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}
    machine_to_intervals = {}
    chosen_machine_vars = {}

    for task_key in task_keys:
        info = task_data[task_key]
        task = info["task"]
        duration = info["duration"]
        safe_job = re.sub(r"[^A-Za-z0-9_]", "_", str(task_key[0]))
        safe_name = f"{safe_job}_{task_key[1]}"

        if info["is_fixed"]:
            fixed_start = int(info["fixed_start"])
            fixed_end = int(info["fixed_end"])
            start_var = model.NewIntVar(fixed_start, fixed_start, f"start_{safe_name}")
            end_var = model.NewIntVar(fixed_end, fixed_end, f"end_{safe_name}")
            model.Add(end_var == start_var + duration)
        else:
            start_var = model.NewIntVar(cur_ptr, horizon, f"start_{safe_name}")
            end_var = model.NewIntVar(cur_ptr, horizon, f"end_{safe_name}")
            model.Add(end_var == start_var + duration)

        start_vars[task_key] = start_var
        end_vars[task_key] = end_var

        eligible_machines = info["machines"]
        scheduled_machine = info["scheduled_machine"]
        machine_presence_vars = []

        for machine_code in eligible_machines:
            safe_machine = re.sub(r"[^A-Za-z0-9_]", "_", str(machine_code))
            presence_var = model.NewBoolVar(f"presence_{safe_name}_{safe_machine}")
            presence[(task_key, machine_code)] = presence_var
            machine_presence_vars.append(presence_var)

            optional_interval = model.NewOptionalIntervalVar(
                start_var,
                duration,
                end_var,
                presence_var,
                f"interval_{safe_name}_{safe_machine}",
            )
            interval_vars[(task_key, machine_code)] = optional_interval
            machine_to_intervals.setdefault(machine_code, []).append((task_key, optional_interval, presence_var, duration))

            if info["is_fixed"]:
                if scheduled_machine == machine_code:
                    model.Add(presence_var == 1)
                else:
                    model.Add(presence_var == 0)

        model.AddExactlyOne(machine_presence_vars)
        chosen_machine_vars[task_key] = machine_presence_vars

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: k[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            model.Add(end_vars[previous_key] <= start_vars[next_key])

    def intervals_overlap_fixed(a_key, b_key):
        a = task_data[a_key]
        b = task_data[b_key]
        if not (a["is_fixed"] and b["is_fixed"]):
            return False
        return int(a["fixed_start"]) < int(b["fixed_end"]) and int(b["fixed_start"]) < int(a["fixed_end"])

    for machine_code, interval_entries in machine_to_intervals.items():
        capacity = int(machines_capacity.get(machine_code, 1) or 1)

        if capacity <= 1:
            for idx, (task_key_i, interval_i, presence_i, duration_i) in enumerate(interval_entries):
                for task_key_j, interval_j, presence_j, duration_j in interval_entries[idx + 1:]:
                    if intervals_overlap_fixed(task_key_i, task_key_j):
                        continue
                    i_before_j = model.NewBoolVar(f"onecap_i_before_{idx}_{len(interval_entries)}_{len(str(task_key_j))}_{machine_code}")
                    j_before_i = model.NewBoolVar(f"onecap_j_before_{idx}_{len(interval_entries)}_{len(str(task_key_j))}_{machine_code}")
                    model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, i_before_j])
                    model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, j_before_i])
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])
        else:
            use_cumulative = True
            fixed_events = []
            for task_key_i, _, _, _ in interval_entries:
                if task_data[task_key_i]["is_fixed"]:
                    fixed_events.append((int(task_data[task_key_i]["fixed_start"]), 1))
                    fixed_events.append((int(task_data[task_key_i]["fixed_end"]), -1))
            active = 0
            for _, delta in sorted(fixed_events):
                active += delta
                if active > capacity:
                    use_cumulative = False
                    break
            if use_cumulative:
                model.AddCumulative([entry[1] for entry in interval_entries], [1] * len(interval_entries), capacity)

            for idx, (task_key_i, interval_i, presence_i, duration_i) in enumerate(interval_entries):
                for jdx, (task_key_j, interval_j, presence_j, duration_j) in enumerate(interval_entries[idx + 1:], idx + 1):
                    if intervals_overlap_fixed(task_key_i, task_key_j):
                        if duration_i == duration_j:
                            continue
                    i_before_j = model.NewBoolVar(f"batch_i_before_{idx}_{jdx}_{re.sub(r'[^A-Za-z0-9_]', '_', machine_code)}")
                    j_before_i = model.NewBoolVar(f"batch_j_before_{idx}_{jdx}_{re.sub(r'[^A-Za-z0-9_]', '_', machine_code)}")
                    model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, i_before_j])
                    model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, j_before_i])
                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar(f"batch_sync_{idx}_{jdx}_{re.sub(r'[^A-Za-z0-9_]', '_', machine_code)}")
                        model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i, synchronized])
                    else:
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])

    def machine_name_for_task(task_key):
        task = task_data[task_key]["task"]
        names = []
        names.extend(str(m) for m in task_data[task_key]["machines"])
        if task.get("nominal_machine") is not None:
            names.append(str(task.get("nominal_machine")))
        if task.get("name") is not None:
            names.append(str(task.get("name")))
        return " ".join(names).lower()

    def is_drip_test_recycle(task_key):
        flags = task_data[task_key]["flags"]
        if any(flags.get(k, False) for k in (
            "electronic_dripping", "electronic_test", "electronic_recycle",
            "xrd_dripping", "xrd_test", "xrd_recycle",
        )):
            return True
        name = machine_name_for_task(task_key)
        return ("dripping" in name or "_test" in name or "recycle" in name) and ("high_flux" in name)

    chemistry_chain_tasks = [k for k in task_keys if is_drip_test_recycle(k)]
    chemistry_intervals = []
    for task_key in chemistry_chain_tasks:
        for machine_code in task_data[task_key]["machines"]:
            if (task_key, machine_code) in interval_vars:
                chemistry_intervals.append(interval_vars[(task_key, machine_code)])
    if chemistry_intervals:
        model.AddNoOverlap(chemistry_intervals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered = sorted([k for k in ordered_task_keys if is_drip_test_recycle(k)], key=lambda k: k[1])
        for left_key, right_key in zip(ordered, ordered[1:]):
            model.Add(end_vars[left_key] == start_vars[right_key])

    for expr_no, first_task_keys in expr_to_first_tasks.items():
        if len(first_task_keys) > 1:
            anchor = first_task_keys[0]
            for other_key in first_task_keys[1:]:
                model.Add(start_vars[other_key] == start_vars[anchor])
                model.Add(end_vars[other_key] == end_vars[anchor])

    def extract_temperature(task_key):
        task = task_data[task_key]["task"]
        temperatures = []
        for param_entry in task.get("parameters", []) or []:
            param = param_entry.get("param", {}) or {}
            if "temperature" in param:
                try:
                    temperatures.append(float(param["temperature"]))
                except Exception:
                    temperatures.append(str(param["temperature"]))
            if "custom_param" in param:
                try:
                    custom = json.loads(param["custom_param"])
                    if "temperature" in custom:
                        temperatures.append(float(custom["temperature"]))
                except Exception:
                    pass
        return temperatures[0] if temperatures else None

    thermal_machine_entries = []
    for machine_code, entries in machine_to_intervals.items():
        low = machine_code.lower()
        if "muffle" in low or "dryer" in low:
            thermal_machine_entries.append((machine_code, entries))

    for machine_code, entries in thermal_machine_entries:
        for idx, (task_key_i, _, presence_i, _) in enumerate(entries):
            temp_i = extract_temperature(task_key_i)
            for jdx, (task_key_j, _, presence_j, _) in enumerate(entries[idx + 1:], idx + 1):
                temp_j = extract_temperature(task_key_j)
                if temp_i is not None and temp_j is not None and temp_i != temp_j:
                    if intervals_overlap_fixed(task_key_i, task_key_j):
                        continue
                    i_before_j = model.NewBoolVar(f"thermal_i_before_{idx}_{jdx}_{re.sub(r'[^A-Za-z0-9_]', '_', machine_code)}")
                    j_before_i = model.NewBoolVar(f"thermal_j_before_{idx}_{jdx}_{re.sub(r'[^A-Za-z0-9_]', '_', machine_code)}")
                    model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, i_before_j])
                    model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, j_before_i])
                    model.AddBoolOr([presence_i.Not(), presence_j.Not(), i_before_j, j_before_i])

    centrifuge_task_keys = [k for k in task_keys if any("centrifug" in str(m).lower() for m in task_data[k]["machines"])]
    centrifuge_task_keys = sorted(centrifuge_task_keys, key=lambda k: (task_data[k]["expr_no"] or "", k[0], k[1]))
    for i in range(0, len(centrifuge_task_keys) - 1, 2):
        left_key = centrifuge_task_keys[i]
        right_key = centrifuge_task_keys[i + 1]
        if task_data[left_key]["duration"] == task_data[right_key]["duration"]:
            model.Add(start_vars[left_key] == start_vars[right_key])
            model.Add(end_vars[left_key] == end_vars[right_key])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[k] for k in task_keys])
    model.Minimize(makespan)

    for task_key in task_keys:
        info = task_data[task_key]
        if info["is_fixed"]:
            continue
        model.AddHint(start_vars[task_key], cur_ptr)
        model.AddHint(end_vars[task_key], cur_ptr + info["duration"])
        preferred = info["task"].get("nominal_machine")
        if preferred not in info["machines"] and info["machines"]:
            preferred = info["machines"][0]
        for machine_code in info["machines"]:
            model.AddHint(presence[(task_key, machine_code)], 1 if machine_code == preferred else 0)

    try:
        model.AddDecisionStrategy(
            [start_vars[k] for k in task_keys],
            cp_model.CHOOSE_LOWEST_MIN,
            cp_model.SELECT_MIN_VALUE,
        )
    except Exception:
        pass

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(5.0, outer_timeout - 8.0)
    solver.parameters.num_search_workers = min(8, max(1, os.cpu_count() or 1))
    solver.parameters.random_seed = 13
    solver.parameters.search_branching = cp_model.PORTFOLIO_SEARCH
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        repair_model = cp_model.CpModel()
        repair_marker = repair_model.NewBoolVar("repair_cp_sat_marker")
        repair_model.Add(repair_marker == 1)
        repair_solver = cp_model.CpSolver()
        repair_solver.parameters.max_time_in_seconds = 0.1
        repair_solver.Solve(repair_model)

        assignments = []
        machine_available = {m: cur_ptr for m in machines_capacity}
        for job in jobs:
            current_time = cur_ptr
            for task in sorted(job.get("tasks", []), key=lambda t: int(t.get("task_id", 0))):
                job_id = job.get("job_id")
                task_id = int(task.get("task_id"))
                duration = int(task.get("duration", 0) or 0)
                if task.get("is_fixed", False):
                    machine = task.get("scheduled_machine") or (task.get("machines") or [""])[0]
                    start = int(task.get("fixed_start"))
                    end = int(task.get("fixed_end"))
                    current_time = max(current_time, end)
                    machine_available[machine] = max(machine_available.get(machine, cur_ptr), end)
                else:
                    machine = (task.get("machines") or [task.get("nominal_machine")])[0]
                    start = max(current_time, machine_available.get(machine, cur_ptr), cur_ptr)
                    end = start + duration
                    current_time = end
                    machine_available[machine] = end
                assignments.append({
                    "job_id": job_id,
                    "task_id": task_id,
                    "machine": machine,
                    "start": int(start),
                    "end": int(end),
                })
        return {"assignments": assignments}

    assignments = []
    for task_key in sorted(task_keys, key=lambda k: (str(k[0]), int(k[1]))):
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