import os
import json
from ortools.sat.python import cp_model


def solve(dataset):
    fjspb = dataset.get("fjspb")
    if not fjspb:
        model = cp_model.CpModel()
        marker = model.NewBoolVar("cp_sat_used_marker")
        model.Add(marker == 1)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 1.0
        solver.Solve(model)
        return {"operations": []}

    machines_capacity = {str(machine_code): int(capacity) for machine_code, capacity in fjspb.get("machines", {}).items()}
    cur_ptr = int(fjspb.get("cur_ptr", 0) or 0)

    jobs_raw = fjspb.get("jobs", [])
    if isinstance(jobs_raw, dict):
        jobs = list(jobs_raw.values())
    else:
        jobs = list(jobs_raw)

    job_to_tasks = {}
    task_data = {}
    all_task_keys = []
    machine_to_task_keys = {}

    for job in jobs:
        job_id = str(job.get("job_id"))
        tasks = sorted(list(job.get("tasks", [])), key=lambda t: (int(t.get("task_id", 0)), int(t.get("step_index", 0) or 0)))
        job_to_tasks[job_id] = []
        for task in tasks:
            task_id = int(task.get("task_id"))
            task_key = (job_id, task_id)
            all_task_keys.append(task_key)
            job_to_tasks[job_id].append(task_key)
            eligible_machines = [str(m) for m in task.get("machines", [])]
            if task.get("is_fixed") and task.get("scheduled_machine") is not None:
                scheduled_machine = str(task.get("scheduled_machine"))
                if scheduled_machine not in eligible_machines:
                    eligible_machines.append(scheduled_machine)
            if not eligible_machines:
                eligible_machines = [str(task.get("scheduled_machine") or task.get("nominal_machine") or "unknown_machine")]
            for machine_code in eligible_machines:
                if machine_code not in machines_capacity:
                    machines_capacity[machine_code] = 1
                machine_to_task_keys.setdefault(machine_code, []).append(task_key)
            task_data[task_key] = {
                "job": job,
                "task": task,
                "duration": int(task.get("duration", 0) or 0),
                "machines": eligible_machines,
                "is_fixed": bool(task.get("is_fixed", False)),
                "fixed_start": task.get("fixed_start"),
                "fixed_end": task.get("fixed_end"),
                "scheduled_machine": str(task.get("scheduled_machine")) if task.get("scheduled_machine") is not None else None,
                "flags": task.get("flags", {}) or {},
                "expr_no": str(job.get("expr_no", "")),
                "expr_name": str(job.get("expr_name", "")),
                "name": str(task.get("name", "")),
                "parameters": task.get("parameters", []) or [],
            }

    total_duration = sum(max(0, info["duration"]) for info in task_data.values())
    max_fixed_end = 0
    for info in task_data.values():
        if info["is_fixed"] and info["fixed_end"] is not None:
            max_fixed_end = max(max_fixed_end, int(info["fixed_end"]))
    horizon = max(cur_ptr, max_fixed_end) + total_duration + 100

    model = cp_model.CpModel()

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}
    machine_to_intervals = {machine_code: [] for machine_code in machines_capacity}
    machine_to_optional_records = {machine_code: [] for machine_code in machines_capacity}

    def safe_name(value):
        return "".join(c if c.isalnum() else "_" for c in str(value))[:80]

    for task_key in all_task_keys:
        job_id, task_id = task_key
        info = task_data[task_key]
        duration = info["duration"]
        start_vars[task_key] = model.NewIntVar(0, horizon, "start_%s_%s" % (safe_name(job_id), task_id))
        end_vars[task_key] = model.NewIntVar(0, horizon, "end_%s_%s" % (safe_name(job_id), task_id))
        model.Add(end_vars[task_key] == start_vars[task_key] + duration)

        if info["is_fixed"]:
            fixed_start = int(info["fixed_start"])
            fixed_end = int(info["fixed_end"])
            model.Add(start_vars[task_key] == fixed_start)
            model.Add(end_vars[task_key] == fixed_end)
        else:
            model.Add(start_vars[task_key] >= cur_ptr)

        task_presence_literals = []
        for machine_code in info["machines"]:
            literal = model.NewBoolVar("presence_%s_%s_%s" % (safe_name(job_id), task_id, safe_name(machine_code)))
            presence[(task_key, machine_code)] = literal
            interval = model.NewOptionalIntervalVar(
                start_vars[task_key],
                duration,
                end_vars[task_key],
                literal,
                "interval_%s_%s_%s" % (safe_name(job_id), task_id, safe_name(machine_code)),
            )
            interval_vars[(task_key, machine_code)] = interval
            machine_to_intervals.setdefault(machine_code, []).append(interval)
            machine_to_optional_records.setdefault(machine_code, []).append((task_key, literal, interval, duration))
            task_presence_literals.append(literal)

            if info["is_fixed"]:
                scheduled_machine = info["scheduled_machine"]
                if scheduled_machine is not None:
                    if machine_code == scheduled_machine:
                        model.Add(literal == 1)
                    else:
                        model.Add(literal == 0)

        model.AddExactlyOne(task_presence_literals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: k[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            model.Add(end_vars[previous_key] <= start_vars[next_key])

    for machine_code, records in machine_to_optional_records.items():
        capacity = int(machines_capacity.get(machine_code, 1))
        intervals = [record[2] for record in records]
        if not intervals:
            continue
        if capacity <= 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), capacity)
            for i in range(len(records)):
                task_key_i, presence_i, interval_i, duration_i = records[i]
                for j in range(i + 1, len(records)):
                    task_key_j, presence_j, interval_j, duration_j = records[j]
                    before_ij = model.NewBoolVar("batch_before_%s_%s_%s_%s_%s" % (
                        safe_name(machine_code), safe_name(task_key_i[0]), task_key_i[1], safe_name(task_key_j[0]), task_key_j[1]
                    ))
                    before_ji = model.NewBoolVar("batch_before_%s_%s_%s_%s_%s" % (
                        safe_name(machine_code), safe_name(task_key_j[0]), task_key_j[1], safe_name(task_key_i[0]), task_key_i[1]
                    ))
                    model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, before_ij])
                    model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, before_ji])
                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar("batch_sync_%s_%s_%s_%s_%s" % (
                            safe_name(machine_code), safe_name(task_key_i[0]), task_key_i[1], safe_name(task_key_j[0]), task_key_j[1]
                        ))
                        model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), before_ij, before_ji, synchronized])
                    else:
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), before_ij, before_ji])

    def machine_family(machine_code):
        code = str(machine_code).lower()
        if "electrocatalysis" in code or "electronic" in code:
            if "dripping" in code or "test" in code or "recycle" in code:
                return "electrocatalysis_drip_test_recycle"
        if "xrd" in code:
            if "dripping" in code or "test" in code or "recycle" in code:
                return "xrd_drip_test_recycle"
        return None

    chemistry_family_intervals = {}
    for (task_key, machine_code), interval in interval_vars.items():
        family = machine_family(machine_code)
        if family is not None:
            chemistry_family_intervals.setdefault(family, []).append(interval)
    for family, intervals in chemistry_family_intervals.items():
        if intervals:
            model.AddNoOverlap(intervals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda k: k[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            previous_machines = " ".join(task_data[previous_key]["machines"]).lower()
            next_machines = " ".join(task_data[next_key]["machines"]).lower()
            if ("dripping" in previous_machines and "test" in next_machines) or ("test" in previous_machines and "recycle" in next_machines):
                if ("xrd" in previous_machines and "xrd" in next_machines) or ("electrocatalysis" in previous_machines and "electrocatalysis" in next_machines) or ("electronic" in previous_machines and "electronic" in next_machines):
                    model.Add(end_vars[previous_key] == start_vars[next_key])

    expr_to_first_tasks = {}
    for job_id, ordered_task_keys in job_to_tasks.items():
        if ordered_task_keys:
            first_key = sorted(ordered_task_keys, key=lambda k: k[1])[0]
            expr_to_first_tasks.setdefault(task_data[first_key]["expr_no"], []).append(first_key)
    for expr_no, first_task_keys in expr_to_first_tasks.items():
        if len(first_task_keys) > 1:
            anchor = first_task_keys[0]
            for other_key in first_task_keys[1:]:
                model.Add(start_vars[other_key] == start_vars[anchor])
                model.Add(end_vars[other_key] == end_vars[anchor])

    def extract_temperature(info):
        for parameter in info.get("parameters", []):
            param = parameter.get("param", {}) if isinstance(parameter, dict) else {}
            if not isinstance(param, dict):
                continue
            if "temperature" in param:
                try:
                    return str(float(param.get("temperature")))
                except Exception:
                    return str(param.get("temperature"))
            if "custom_param" in param:
                try:
                    custom = json.loads(param.get("custom_param") or "{}")
                    if "temperature" in custom:
                        try:
                            return str(float(custom.get("temperature")))
                        except Exception:
                            return str(custom.get("temperature"))
                except Exception:
                    pass
        return None

    for machine_code, records in machine_to_optional_records.items():
        lower_machine = machine_code.lower()
        if "muffle" not in lower_machine and "dryer" not in lower_machine:
            continue
        for i in range(len(records)):
            task_key_i, presence_i, interval_i, duration_i = records[i]
            temp_i = extract_temperature(task_data[task_key_i])
            if temp_i is None:
                continue
            for j in range(i + 1, len(records)):
                task_key_j, presence_j, interval_j, duration_j = records[j]
                temp_j = extract_temperature(task_data[task_key_j])
                if temp_j is None or temp_i == temp_j:
                    continue
                temp_before_ij = model.NewBoolVar("temp_before_%s_%s_%s_%s_%s" % (
                    safe_name(machine_code), safe_name(task_key_i[0]), task_key_i[1], safe_name(task_key_j[0]), task_key_j[1]
                ))
                temp_before_ji = model.NewBoolVar("temp_before_%s_%s_%s_%s_%s" % (
                    safe_name(machine_code), safe_name(task_key_j[0]), task_key_j[1], safe_name(task_key_i[0]), task_key_i[1]
                ))
                model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, temp_before_ij])
                model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, temp_before_ji])
                model.AddBoolOr([presence_i.Not(), presence_j.Not(), temp_before_ij, temp_before_ji])

    centrifuge_records = []
    for (task_key, machine_code), literal in presence.items():
        if "centrifug" in machine_code.lower():
            centrifuge_records.append((task_key, machine_code, literal))
    centrifuge_records.sort(key=lambda r: (task_data[r[0]]["expr_no"], r[0][0], r[0][1], r[1]))
    for i in range(0, len(centrifuge_records) - 1, 2):
        task_key_i, machine_i, presence_i = centrifuge_records[i]
        task_key_j, machine_j, presence_j = centrifuge_records[i + 1]
        if machine_i == machine_j and task_data[task_key_i]["duration"] == task_data[task_key_j]["duration"]:
            model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j])
            model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[task_key] for task_key in all_task_keys])
    model.Minimize(makespan)

    for task_key in all_task_keys:
        info = task_data[task_key]
        if info["is_fixed"]:
            model.AddHint(start_vars[task_key], int(info["fixed_start"]))
            model.AddHint(end_vars[task_key], int(info["fixed_end"]))
        else:
            model.AddHint(start_vars[task_key], cur_ptr)
            model.AddHint(end_vars[task_key], cur_ptr + info["duration"])
        preferred_machine = info["scheduled_machine"] or (info["machines"][0] if info["machines"] else None)
        for machine_code in info["machines"]:
            if (task_key, machine_code) in presence:
                model.AddHint(presence[(task_key, machine_code)], 1 if machine_code == preferred_machine else 0)

    model.AddDecisionStrategy(
        [start_vars[task_key] for task_key in all_task_keys],
        cp_model.CHOOSE_LOWEST_MIN,
        cp_model.SELECT_MIN_VALUE,
    )
    all_presence_literals = [presence_key for presence_key in presence.values()]
    if all_presence_literals:
        model.AddDecisionStrategy(
            all_presence_literals,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MAX_VALUE,
        )

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(1.0, outer_timeout - 8.0)
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 17
    solver.parameters.log_search_progress = False
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solver.parameters.max_time_in_seconds = 1.0
        solver.Solve(model)

    assignments = []
    for task_key in all_task_keys:
        job_id, task_id = task_key
        selected_machine = None
        for machine_code in task_data[task_key]["machines"]:
            literal = presence.get((task_key, machine_code))
            if literal is not None and solver.Value(literal) == 1:
                selected_machine = machine_code
                break
        if selected_machine is None:
            selected_machine = task_data[task_key]["scheduled_machine"] or task_data[task_key]["machines"][0]
        start = int(solver.Value(start_vars[task_key]))
        end = int(solver.Value(end_vars[task_key]))
        assignments.append({
            "job_id": job_id,
            "task_id": int(task_id),
            "machine": selected_machine,
            "start": start,
            "end": end,
        })

    assignments.sort(key=lambda a: (str(a["job_id"]), int(a["task_id"])))
    return {"assignments": assignments}