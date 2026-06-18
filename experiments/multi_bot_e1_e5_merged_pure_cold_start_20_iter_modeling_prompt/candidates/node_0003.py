import os
import json
import re
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

    def as_int(value, default=0):
        try:
            return int(round(float(value)))
        except Exception:
            return default

    def safe_name(value):
        return re.sub(r"[^0-9A-Za-z_]+", "_", str(value))[:90]

    def lower_join(values):
        return " ".join(str(v).lower() for v in values if v is not None)

    machines_capacity = {str(machine_code): max(1, as_int(capacity, 1)) for machine_code, capacity in fjspb.get("machines", {}).items()}
    cur_ptr = as_int(fjspb.get("cur_ptr", 0), 0)

    jobs_raw = fjspb.get("jobs", [])
    jobs = list(jobs_raw.values()) if isinstance(jobs_raw, dict) else list(jobs_raw)

    job_to_tasks = {}
    task_data = {}
    all_task_keys = []
    expr_to_first_tasks = {}

    for job in jobs:
        job_id = str(job.get("job_id"))
        expr_no = str(job.get("expr_no", ""))
        expr_name = str(job.get("expr_name", ""))
        raw_tasks = list(job.get("tasks", []))
        ordered_tasks = sorted(raw_tasks, key=lambda task: (as_int(task.get("task_id", 0)), as_int(task.get("step_index", 0))))
        job_to_tasks[job_id] = []

        for task in ordered_tasks:
            task_id = as_int(task.get("task_id", 0))
            task_key = (job_id, task_id)
            duration = max(0, as_int(task.get("duration", 0), 0))

            eligible_machines = [str(machine_code) for machine_code in (task.get("machines", []) or [])]
            scheduled_machine = str(task.get("scheduled_machine")) if task.get("scheduled_machine") is not None else None
            nominal_machine = str(task.get("nominal_machine")) if task.get("nominal_machine") is not None else None

            if bool(task.get("is_fixed", False)) and scheduled_machine is not None and scheduled_machine not in eligible_machines:
                eligible_machines.append(scheduled_machine)
            if not eligible_machines:
                eligible_machines = [scheduled_machine or nominal_machine or "unknown_machine"]

            for machine_code in eligible_machines:
                machines_capacity.setdefault(machine_code, 1)

            flags = task.get("flags", {}) or {}
            parameters = task.get("parameters", []) or []
            machine_text = lower_join(eligible_machines + [scheduled_machine, nominal_machine, task.get("name", "")])

            task_data[task_key] = {
                "job_id": job_id,
                "task_id": task_id,
                "expr_no": expr_no,
                "expr_name": expr_name,
                "task": task,
                "duration": duration,
                "machines": eligible_machines,
                "scheduled_machine": scheduled_machine,
                "nominal_machine": nominal_machine,
                "is_fixed": bool(task.get("is_fixed", False)),
                "fixed_start": task.get("fixed_start"),
                "fixed_end": task.get("fixed_end"),
                "flags": flags,
                "parameters": parameters,
                "machine_text": machine_text,
                "name": str(task.get("name", "")),
            }
            job_to_tasks[job_id].append(task_key)
            all_task_keys.append(task_key)

        if job_to_tasks[job_id]:
            first_task_key = sorted(job_to_tasks[job_id], key=lambda key: key[1])[0]
            expr_to_first_tasks.setdefault(expr_no, []).append(first_task_key)

    max_fixed_end = 0
    for task_key, info in task_data.items():
        if info["is_fixed"]:
            max_fixed_end = max(max_fixed_end, as_int(info["fixed_end"], 0))
    total_duration = sum(info["duration"] for info in task_data.values())
    longest_job_duration = 0
    for ordered_task_keys in job_to_tasks.values():
        longest_job_duration = max(longest_job_duration, sum(task_data[key]["duration"] for key in ordered_task_keys))
    horizon = max(cur_ptr, max_fixed_end) + total_duration + longest_job_duration + 1000

    model = cp_model.CpModel()

    start_vars = {}
    end_vars = {}
    presence = {}
    interval_vars = {}
    machine_to_intervals = {machine_code: [] for machine_code in machines_capacity}
    machine_to_optional_records = {machine_code: [] for machine_code in machines_capacity}

    for task_key in all_task_keys:
        job_id, task_id = task_key
        info = task_data[task_key]
        duration = info["duration"]
        task_label = "%s_%s" % (safe_name(job_id), task_id)

        start_vars[task_key] = model.NewIntVar(0, horizon, "start_%s" % task_label)
        end_vars[task_key] = model.NewIntVar(0, horizon, "end_%s" % task_label)
        model.Add(end_vars[task_key] == start_vars[task_key] + duration)

        if info["is_fixed"]:
            fixed_start = as_int(info["fixed_start"], 0)
            fixed_end = as_int(info["fixed_end"], fixed_start + duration)
            model.Add(start_vars[task_key] == fixed_start)
            model.Add(end_vars[task_key] == fixed_end)
        else:
            model.Add(start_vars[task_key] >= cur_ptr)

        task_machine_literals = []
        for machine_code in info["machines"]:
            machine_label = safe_name(machine_code)
            literal = model.NewBoolVar("presence_%s_%s" % (task_label, machine_label))
            interval = model.NewOptionalIntervalVar(
                start_vars[task_key],
                duration,
                end_vars[task_key],
                literal,
                "interval_%s_%s" % (task_label, machine_label),
            )

            presence[(task_key, machine_code)] = literal
            interval_vars[(task_key, machine_code)] = interval
            machine_to_intervals.setdefault(machine_code, []).append(interval)
            machine_to_optional_records.setdefault(machine_code, []).append((task_key, literal, interval, duration))
            task_machine_literals.append(literal)

            if info["is_fixed"] and info["scheduled_machine"] is not None:
                model.Add(literal == (1 if machine_code == info["scheduled_machine"] else 0))

        model.AddExactlyOne(task_machine_literals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda key: key[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            model.Add(end_vars[previous_key] <= start_vars[next_key])

    for machine_code, records in machine_to_optional_records.items():
        if not records:
            continue

        capacity = max(1, int(machines_capacity.get(machine_code, 1)))
        intervals = [record[2] for record in records]

        if capacity <= 1:
            model.AddNoOverlap(intervals)
        else:
            model.AddCumulative(intervals, [1] * len(intervals), capacity)
            for i in range(len(records)):
                task_key_i, presence_i, _, duration_i = records[i]
                for j in range(i + 1, len(records)):
                    task_key_j, presence_j, _, duration_j = records[j]
                    pair_label = "%s_%s_%s_%s_%s" % (
                        safe_name(machine_code),
                        safe_name(task_key_i[0]),
                        task_key_i[1],
                        safe_name(task_key_j[0]),
                        task_key_j[1],
                    )
                    before_ij = model.NewBoolVar("batch_before_ij_%s" % pair_label)
                    before_ji = model.NewBoolVar("batch_before_ji_%s" % pair_label)

                    model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, before_ij])
                    model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, before_ji])

                    if duration_i == duration_j:
                        synchronized = model.NewBoolVar("batch_sync_%s" % pair_label)
                        model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, synchronized])
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), before_ij, before_ji, synchronized])
                    else:
                        model.AddBoolOr([presence_i.Not(), presence_j.Not(), before_ij, before_ji])

    def chemistry_family(machine_code, info=None):
        text = str(machine_code).lower()
        if info is not None:
            flags = info.get("flags", {}) or {}
            if flags.get("electronic_dripping") or flags.get("electronic_test") or flags.get("electronic_recycle"):
                return "electrocatalysis_drip_test_recycle"
            if flags.get("xrd_dripping") or flags.get("xrd_test") or flags.get("xrd_recycle"):
                return "xrd_drip_test_recycle"
        if ("electrocatalysis" in text or "electronic" in text) and ("dripping" in text or "test" in text or "recycle" in text):
            return "electrocatalysis_drip_test_recycle"
        if "xrd" in text and ("dripping" in text or "test" in text or "recycle" in text):
            return "xrd_drip_test_recycle"
        return None

    chemistry_family_intervals = {}
    for (task_key, machine_code), interval in interval_vars.items():
        family = chemistry_family(machine_code, task_data[task_key])
        if family is not None:
            chemistry_family_intervals.setdefault(family, []).append(interval)
    for family, intervals in chemistry_family_intervals.items():
        if len(intervals) > 1:
            model.AddNoOverlap(intervals)

    for job_id, ordered_task_keys in job_to_tasks.items():
        ordered_task_keys = sorted(ordered_task_keys, key=lambda key: key[1])
        for previous_key, next_key in zip(ordered_task_keys, ordered_task_keys[1:]):
            previous_text = task_data[previous_key]["machine_text"]
            next_text = task_data[next_key]["machine_text"]
            previous_flags = task_data[previous_key]["flags"]
            next_flags = task_data[next_key]["flags"]

            previous_dripping = "dripping" in previous_text or previous_flags.get("electronic_dripping") or previous_flags.get("xrd_dripping")
            next_test = "test" in next_text or previous_flags.get("unused", False) or next_flags.get("electronic_test") or next_flags.get("xrd_test")
            previous_test = "test" in previous_text or previous_flags.get("electronic_test") or previous_flags.get("xrd_test")
            next_recycle = "recycle" in next_text or next_flags.get("electronic_recycle") or next_flags.get("xrd_recycle")

            same_xrd_chain = "xrd" in previous_text and "xrd" in next_text
            same_electro_chain = (
                ("electrocatalysis" in previous_text or "electronic" in previous_text)
                and ("electrocatalysis" in next_text or "electronic" in next_text)
            )

            if (same_xrd_chain or same_electro_chain) and ((previous_dripping and next_test) or (previous_test and next_recycle)):
                model.Add(end_vars[previous_key] == start_vars[next_key])

    for expr_no, first_task_keys in expr_to_first_tasks.items():
        if len(first_task_keys) > 1:
            anchor_key = first_task_keys[0]
            for other_key in first_task_keys[1:]:
                model.Add(start_vars[other_key] == start_vars[anchor_key])
                model.Add(end_vars[other_key] == end_vars[anchor_key])

    def extract_temperature(info):
        for parameter in info.get("parameters", []):
            if not isinstance(parameter, dict):
                continue
            param = parameter.get("param", {})
            if not isinstance(param, dict):
                continue
            if "temperature" in param:
                try:
                    return str(float(param.get("temperature")))
                except Exception:
                    return str(param.get("temperature"))
            custom_param = param.get("custom_param")
            if custom_param:
                try:
                    custom = json.loads(custom_param)
                    if isinstance(custom, dict) and "temperature" in custom:
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
            task_key_i, presence_i, _, _ = records[i]
            temp_i = extract_temperature(task_data[task_key_i])
            if temp_i is None:
                continue
            for j in range(i + 1, len(records)):
                task_key_j, presence_j, _, _ = records[j]
                temp_j = extract_temperature(task_data[task_key_j])
                if temp_j is None or temp_i == temp_j:
                    continue

                pair_label = "%s_%s_%s_%s_%s" % (
                    safe_name(machine_code),
                    safe_name(task_key_i[0]),
                    task_key_i[1],
                    safe_name(task_key_j[0]),
                    task_key_j[1],
                )
                before_ij = model.NewBoolVar("temp_before_ij_%s" % pair_label)
                before_ji = model.NewBoolVar("temp_before_ji_%s" % pair_label)
                model.Add(end_vars[task_key_i] <= start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j, before_ij])
                model.Add(end_vars[task_key_j] <= start_vars[task_key_i]).OnlyEnforceIf([presence_i, presence_j, before_ji])
                model.AddBoolOr([presence_i.Not(), presence_j.Not(), before_ij, before_ji])

    centrifuge_groups = {}
    for machine_code, records in machine_to_optional_records.items():
        if "centrifug" not in machine_code.lower():
            continue
        for task_key, literal, interval, duration in records:
            centrifuge_groups.setdefault((machine_code, duration), []).append((task_key, literal))

    for (machine_code, duration), records in centrifuge_groups.items():
        records = sorted(records, key=lambda rec: (
            task_data[rec[0]]["expr_no"],
            task_data[rec[0]]["expr_name"],
            rec[0][0],
            rec[0][1],
        ))
        for i in range(0, len(records) - 1, 2):
            task_key_i, presence_i = records[i]
            task_key_j, presence_j = records[i + 1]
            model.Add(presence_i == presence_j)
            model.Add(start_vars[task_key_i] == start_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j])
            model.Add(end_vars[task_key_i] == end_vars[task_key_j]).OnlyEnforceIf([presence_i, presence_j])

    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, [end_vars[task_key] for task_key in all_task_keys])
    model.Minimize(makespan)

    greedy_machine_available = {machine_code: cur_ptr for machine_code in machines_capacity}
    greedy_task_end = {}
    for job_id in sorted(job_to_tasks):
        for task_key in sorted(job_to_tasks[job_id], key=lambda key: key[1]):
            info = task_data[task_key]
            if info["is_fixed"]:
                hint_start = as_int(info["fixed_start"], 0)
                hint_end = as_int(info["fixed_end"], hint_start + info["duration"])
                preferred_machine = info["scheduled_machine"] or info["machines"][0]
            else:
                predecessor_end = cur_ptr
                ordered = sorted(job_to_tasks[job_id], key=lambda key: key[1])
                index = ordered.index(task_key)
                if index > 0:
                    predecessor_end = greedy_task_end.get(ordered[index - 1], cur_ptr)
                preferred_machine = info["scheduled_machine"] or info["nominal_machine"] or info["machines"][0]
                if preferred_machine not in info["machines"]:
                    preferred_machine = info["machines"][0]
                hint_start = max(predecessor_end, greedy_machine_available.get(preferred_machine, cur_ptr), cur_ptr)
                hint_end = hint_start + info["duration"]
                greedy_machine_available[preferred_machine] = hint_end

            greedy_task_end[task_key] = hint_end
            model.AddHint(start_vars[task_key], min(horizon, max(0, hint_start)))
            model.AddHint(end_vars[task_key], min(horizon, max(0, hint_end)))

            for machine_code in info["machines"]:
                literal = presence.get((task_key, machine_code))
                if literal is not None:
                    model.AddHint(literal, 1 if machine_code == preferred_machine else 0)

    model.AddDecisionStrategy(
        [start_vars[task_key] for task_key in all_task_keys],
        cp_model.CHOOSE_LOWEST_MIN,
        cp_model.SELECT_MIN_VALUE,
    )
    all_presence_literals = list(presence.values())
    if all_presence_literals:
        model.AddDecisionStrategy(
            all_presence_literals,
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MAX_VALUE,
        )

    solver = cp_model.CpSolver()
    outer_timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "450") or 450)
    solver.parameters.max_time_in_seconds = max(5.0, outer_timeout - 12.0)
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = 23
    solver.parameters.cp_model_presolve = True
    solver.parameters.linearization_level = 1
    solver.parameters.log_search_progress = False
    solver.parameters.use_lns = True

    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solver.parameters.max_time_in_seconds = 5.0
        solver.parameters.num_search_workers = 1
        status = solver.Solve(model)

    assignments = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for task_key in all_task_keys:
            info = task_data[task_key]
            selected_machine = None
            for machine_code in info["machines"]:
                literal = presence.get((task_key, machine_code))
                if literal is not None and solver.Value(literal) == 1:
                    selected_machine = machine_code
                    break
            if selected_machine is None:
                selected_machine = info["scheduled_machine"] or info["machines"][0]

            start = int(solver.Value(start_vars[task_key]))
            end = int(solver.Value(end_vars[task_key]))
            assignments.append({
                "job_id": task_key[0],
                "task_id": int(task_key[1]),
                "machine": selected_machine,
                "start": start,
                "end": end,
            })
    else:
        for task_key in all_task_keys:
            info = task_data[task_key]
            if info["is_fixed"]:
                start = as_int(info["fixed_start"], 0)
                end = as_int(info["fixed_end"], start + info["duration"])
                machine = info["scheduled_machine"] or info["machines"][0]
            else:
                start = cur_ptr
                end = cur_ptr + info["duration"]
                machine = info["scheduled_machine"] or info["nominal_machine"] or info["machines"][0]
                if machine not in info["machines"]:
                    machine = info["machines"][0]
            assignments.append({
                "job_id": task_key[0],
                "task_id": int(task_key[1]),
                "machine": machine,
                "start": int(start),
                "end": int(end),
            })

    assignments.sort(key=lambda assignment: (str(assignment["job_id"]), int(assignment["task_id"])))
    return {"assignments": assignments}