"""Reference CP-SAT candidate for flow_1160_era_v2 smoke tests.

This candidate intentionally consumes the v2 IR surface. It keeps the public
return contract unchanged while adding:

* material_edges hard precedence candidates,
* material_inventory_events reservoir non-negative stock flow,
* material_lineage_links plate label audit surface,
* constraint_realization_boundaries conservative hard/audit boundary,
* logistics_events resource NoOverlap intervals,
* rolling_state.existing_machine_occupancy intervals in machine calendars.
"""

from __future__ import annotations

import os

from ortools.sat.python import cp_model


def _task_param(task: dict, key: str):
  for entry in task.get("parameters") or []:
    param = entry.get("param") or {}
    if key in param:
      return param[key]
  return None


def solve(dataset):
  fjspb = dataset["fjspb"]
  jobs = fjspb.get("jobs", [])
  machines = {str(k): int(v) for k, v in fjspb.get("machines", {}).items()}
  machine_frequencies = fjspb.get("machine_frequencies") or {}
  material_edges = fjspb.get("material_edges") or []
  material_lineage_links = fjspb.get("material_lineage_links") or []
  material_inventory_events = fjspb.get("material_inventory_events") or []
  constraint_realization_boundaries = fjspb.get("constraint_realization_boundaries") or {}
  boundary_state = constraint_realization_boundaries.get("state") or {}
  history_policy = fjspb.get("history_policy") or {}
  logistics_events = fjspb.get("logistics_events") or []
  buffers = fjspb.get("buffers") or []
  rolling_state = fjspb.get("rolling_state") or {}
  existing_machine_occupancy = (
      rolling_state.get("existing_machine_occupancy")
      or fjspb.get("existing_machine_occupancy")
      or []
  )

  tasks = []
  task_by_id = {}
  key_by_task_id = {}
  for job in jobs:
    for task in job.get("tasks", []):
      key = (job["job_id"], int(task["task_id"]))
      tasks.append((job, task, key))
      task_by_id[int(task["task_id"])] = task
      key_by_task_id[int(task["task_id"])] = key

  model = cp_model.CpModel()
  horizon = (
      sum(int(task["duration"]) for _job, task, _key in tasks)
      + sum(int(task.get("min_wait") or 0) for _job, task, _key in tasks)
      + sum(int(event.get("duration") or 0) for event in logistics_events)
      + int(fjspb.get("cur_ptr") or rolling_state.get("cur_ptr") or 0)
      + 10000
  )

  start_vars = {}
  end_vars = {}
  presence = {}
  optional_intervals = {}
  for _job, task, key in tasks:
    duration = int(task["duration"])
    start_vars[key] = model.NewIntVar(0, horizon, f"start_{key[0]}_{key[1]}")
    end_vars[key] = model.NewIntVar(0, horizon, f"end_{key[0]}_{key[1]}")
    model.Add(end_vars[key] == start_vars[key] + duration)
    if not task.get("is_fixed"):
      model.Add(start_vars[key] >= int(fjspb.get("cur_ptr") or rolling_state.get("cur_ptr") or 0))

    choices = []
    for machine_code in task.get("machines", []):
      chosen = model.NewBoolVar(f"assign_{key[0]}_{key[1]}_{machine_code}")
      presence[(key, machine_code)] = chosen
      choices.append(chosen)
      optional_intervals[(key, machine_code)] = model.NewOptionalIntervalVar(
          start_vars[key],
          duration,
          end_vars[key],
          chosen,
          f"interval_{key[0]}_{key[1]}_{machine_code}",
      )
    model.AddExactlyOne(choices)

    if task.get("is_fixed"):
      model.Add(start_vars[key] == int(task["fixed_start"]))
      model.Add(end_vars[key] == int(task["fixed_end"]))
      scheduled = task.get("scheduled_machine")
      for machine_code in task.get("machines", []):
        model.Add(presence[(key, machine_code)] == int(machine_code == scheduled))

  machine_to_intervals = {machine_code: [] for machine_code in machines}
  machine_to_demands = {machine_code: [] for machine_code in machines}
  for machine_code in machines:
    for _job, task, key in tasks:
      interval = optional_intervals.get((key, machine_code))
      if interval is None:
        continue
      machine_to_intervals[machine_code].append(interval)
      machine_to_demands[machine_code].append(max(1, int(task.get("required_capacity") or 1)))

  for occ_idx, occ in enumerate(existing_machine_occupancy):
    if not isinstance(occ, dict):
      continue
    machine_code = str(occ.get("machine") or occ.get("machine_code") or "")
    if machine_code not in machines:
      continue
    start = occ.get("start", occ.get("fixed_start"))
    end = occ.get("end", occ.get("fixed_end"))
    if start is None or end is None or int(end) <= int(start):
      continue
    interval = model.NewIntervalVar(
        int(start),
        int(end) - int(start),
        int(end),
        f"existing_machine_occupancy_{machine_code}_{occ_idx}",
    )
    machine_to_intervals[machine_code].append(interval)
    machine_to_demands[machine_code].append(max(1, int(occ.get("required_capacity") or occ.get("capacity") or 1)))

  for machine_code, intervals in machine_to_intervals.items():
    if intervals:
      model.AddCumulative(intervals, machine_to_demands[machine_code], max(1, int(machines[machine_code])))

  for a, b in fjspb.get("precedence_pairs") or []:
    pred_key = key_by_task_id.get(int(a))
    succ_key = key_by_task_id.get(int(b))
    if pred_key is None or succ_key is None:
      continue
    pred_task = task_by_id[int(a)]
    model.Add(start_vars[succ_key] >= end_vars[pred_key] + int(pred_task.get("min_wait") or 0))

  for edge in material_edges:
    if not edge.get("hard_precedence_candidate"):
      continue
    src_task_id = edge.get("src_task_id")
    dst_task_id = edge.get("dst_task_id")
    if src_task_id is None or dst_task_id is None:
      continue
    pred_key = key_by_task_id.get(int(src_task_id))
    succ_key = key_by_task_id.get(int(dst_task_id))
    if pred_key is None or succ_key is None:
      continue
    pred_task = task_by_id[int(src_task_id)]
    model.Add(start_vars[succ_key] >= end_vars[pred_key] + int(pred_task.get("min_wait") or 0))

  inventory_groups = {}
  lineage_labels_seen = set()
  boundary_names_seen = {
      str(row.get("name"))
      for section in ("hard_ready", "audit_only", "blocked_missing_fields")
      for row in (constraint_realization_boundaries.get(section) or [])
      if isinstance(row, dict)
  }
  required_hard_boundary_names_seen = {
      str(row.get("name"))
      for row in (boundary_state.get("required_hard_constraints") or [])
      if isinstance(row, dict) and row.get("hard_constraint")
  }
  history_policy_mode = str(history_policy.get("mode") or "strict_cold_start")
  for link in material_lineage_links:
    if not isinstance(link, dict):
      continue
    for label_key in ("source_plate_label", "destination_plate_label"):
      label = link.get(label_key)
      if label:
        lineage_labels_seen.add(str(label))

  for event in material_inventory_events:
    src_key = key_by_task_id.get(int(event.get("src_task_id")))
    dst_key = key_by_task_id.get(int(event.get("dst_task_id")))
    quantity = int(event.get("quantity") or 0)
    if src_key is None or dst_key is None or quantity <= 0:
      continue
    inventory_groups.setdefault(str(event.get("inventory_key") or "default"), []).append(
        (end_vars[src_key], quantity, start_vars[dst_key], -quantity)
    )
  for inventory_key, rows in inventory_groups.items():
    times = []
    changes = []
    total_quantity = 0
    for produce_time, produce_delta, consume_time, consume_delta in rows:
      times.extend([produce_time, consume_time])
      changes.extend([produce_delta, consume_delta])
      total_quantity += max(0, produce_delta)
    if times and total_quantity > 0:
      model.AddReservoirConstraint(times, changes, 0, total_quantity)

  for pair in fjspb.get("branch_priority_pairs") or []:
    higher_key = key_by_task_id.get(int(pair["higher_task_id"]))
    lower_key = key_by_task_id.get(int(pair["lower_task_id"]))
    if higher_key is not None and lower_key is not None:
      model.Add(start_vars[higher_key] <= start_vars[lower_key])

  for machine_code in machines:
    temp_rows = [
        (task, key)
        for _job, task, key in tasks
        if (key, machine_code) in optional_intervals
        and _task_param(task, "temperature") is not None
    ]
    for i in range(len(temp_rows)):
      task_i, key_i = temp_rows[i]
      for j in range(i + 1, len(temp_rows)):
        task_j, key_j = temp_rows[j]
        if _task_param(task_i, "temperature") != _task_param(task_j, "temperature"):
          model.AddNoOverlap([
              optional_intervals[(key_i, machine_code)],
              optional_intervals[(key_j, machine_code)],
          ])

  for _job, task, key in tasks:
    required_frequency = _task_param(task, "frequency")
    if required_frequency is None:
      continue
    for machine_code in task.get("machines", []):
      frequency_range = machine_frequencies.get(machine_code)
      if frequency_range is None:
        continue
      lo, hi = frequency_range
      if lo is not None and hi is not None and not lo <= required_frequency <= hi:
        model.Add(presence[(key, machine_code)] == 0)

  logistics_resource_intervals = {}
  buffer_to_intervals = {
      str(buffer.get("id")): {"capacity": max(1, int(buffer.get("capacity") or 1)), "intervals": []}
      for buffer in buffers
      if isinstance(buffer, dict) and buffer.get("id")
  }
  logistics_ends = []
  for event in logistics_events:
    if event.get("enforcement") != "audit_no_overlap_candidate":
      continue
    duration = int(event.get("duration") or 0)
    resources = event.get("resources") or []
    if duration <= 0 or not resources:
      continue
    event_id = str(event.get("id") or event.get("node_id"))
    start = model.NewIntVar(0, horizon, f"log_start_{event_id}")
    end = model.NewIntVar(0, horizon, f"log_end_{event_id}")
    interval = model.NewIntervalVar(start, duration, end, f"log_interval_{event_id}")
    logistics_ends.append(end)
    for task_id in event.get("predecessor_task_ids") or []:
      pred_key = key_by_task_id.get(int(task_id))
      if pred_key is not None:
        model.Add(start >= end_vars[pred_key])
    for task_id in event.get("successor_task_ids") or []:
      succ_key = key_by_task_id.get(int(task_id))
      if succ_key is not None:
        model.Add(start_vars[succ_key] >= end)
    for resource_id in resources:
      logistics_resource_intervals.setdefault(resource_id, []).append(interval)
    for buffer_id in event.get("buffer_ids") or []:
      row = buffer_to_intervals.get(str(buffer_id))
      if row is not None:
        row["intervals"].append(interval)

  for resource_id, intervals in logistics_resource_intervals.items():
    if intervals:
      model.AddNoOverlap(intervals)
  for buffer_id, row in buffer_to_intervals.items():
    intervals = row["intervals"]
    if intervals:
      model.AddCumulative(intervals, [1] * len(intervals), row["capacity"])

  makespan = model.NewIntVar(0, horizon, "makespan")
  all_ends = [end_vars[key] for _job, _task, key in tasks] + logistics_ends
  model.AddMaxEquality(makespan, all_ends)
  model.Minimize(makespan)

  solver = cp_model.CpSolver()
  timeout = float(os.environ.get("ERA_CANDIDATE_TIMEOUT_SECONDS", "30"))
  solver.parameters.max_time_in_seconds = max(1.0, timeout - 1.0)
  solver.parameters.num_search_workers = 8
  status = solver.Solve(model)
  if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    return {"assignments": []}

  assignments = []
  for job, task, key in tasks:
    chosen_machine = None
    for machine_code in task.get("machines", []):
      if solver.BooleanValue(presence[(key, machine_code)]):
        chosen_machine = machine_code
        break
    assignments.append(
        {
            "job_id": job["job_id"],
            "task_id": int(task["task_id"]),
            "machine": chosen_machine,
            "start": solver.Value(start_vars[key]),
            "end": solver.Value(end_vars[key]),
        }
    )
  return {"assignments": assignments}
