#!/usr/bin/env python3
"""Prove or bound a flow_1160_v3 makespan with a relaxed CP-SAT model.

The model keeps constraints that any valid v3 task-level schedule must satisfy:
task durations, hard precedence/min-wait, branch-start priority, eligible
machine choice, machine cumulative capacity, and material transfer gaps derived
from the synthetic cold-start device_transfer_times matrix.

It is still a relaxation of the full Isaac/command-level problem because it
does not require a single robot calendar or full plate-position state. If this
relaxed optimum equals a known feasible makespan, the known makespan is optimal
for the stronger full model under the same IR and logistics timing policy.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque

from ortools.sat.python import cp_model

from implementation.flow_1160_era_v3.problem import DEFAULT_DATASET, load_problem


def _task_duration(task: dict) -> int:
  return max(0, int(task.get("duration", 0) or 0))


def _build_task_maps(fjspb: dict):
  task_by_id = {}
  key_by_task_id = {}
  for job in fjspb.get("jobs", []) or []:
    job_id = job.get("job_id", 0)
    for task in job.get("tasks", []) or []:
      if task.get("task_id") is None:
        continue
      task_id = int(task["task_id"])
      key = (job_id, task_id)
      task_by_id[task_id] = task
      key_by_task_id[task_id] = key
  return task_by_id, key_by_task_id


def _param(task: dict, name: str):
  for entry in task.get("parameters", []) or []:
    if isinstance(entry, dict):
      param = entry.get("param", {}) or {}
      if name in param and param.get(name) is not None:
        return param.get(name)
  return None


def _machine_capacity(machines: dict, machine_code: str) -> int:
  try:
    return max(1, int(machines.get(machine_code, 1)))
  except Exception:
    return 1


def _required_capacity(task: dict) -> int:
  try:
    return max(1, int(task.get("required_capacity", 1) or 1))
  except Exception:
    return 1


def _frequency_ok(task: dict, machine_code: str, machine_frequencies: dict) -> bool:
  frequency = _param(task, "frequency")
  if frequency is None:
    return True
  freq_range = machine_frequencies.get(machine_code)
  if not freq_range or len(freq_range) < 2:
    return False
  try:
    return float(freq_range[0]) <= float(frequency) <= float(freq_range[1])
  except Exception:
    return False


def _eligible_machines(task: dict, machines: dict, machine_frequencies: dict) -> list[str]:
  eligible = []
  for machine_code in task.get("machines", []) or []:
    machine_code = str(machine_code)
    if machine_code not in machines:
      continue
    if _required_capacity(task) > _machine_capacity(machines, machine_code):
      continue
    if not _frequency_ok(task, machine_code, machine_frequencies):
      continue
    eligible.append(machine_code)
  if task.get("is_fixed"):
    fixed_machine = task.get("scheduled_machine")
    if fixed_machine and fixed_machine not in eligible and fixed_machine in machines:
      if (
          _required_capacity(task) <= _machine_capacity(machines, fixed_machine)
          and _frequency_ok(task, fixed_machine, machine_frequencies)
      ):
        eligible.append(str(fixed_machine))
  return sorted(set(eligible))


def _device_transfer_lookup(fjspb: dict, override_cap: int | None) -> dict[tuple[str, str], int]:
  timing = fjspb.get("isaac_motion_timing") or {}
  default_transfer = int(timing.get("transfer_seconds") or 0)
  lookup = {}
  for row in (fjspb.get("device_transfer_times") or {}).get("rows", []) or []:
    if not isinstance(row, dict):
      continue
    src = row.get("src_machine")
    dst = row.get("dst_machine")
    if src is None or dst is None:
      continue
    transfer = int(row.get("transfer_seconds") or default_transfer)
    if override_cap is not None:
      transfer = min(transfer, int(override_cap))
    lookup[(str(src), str(dst))] = max(0, transfer)
  return lookup


def _hard_edges(fjspb: dict, task_by_id: dict) -> list[tuple[int, int, int, str]]:
  edges = []
  seen = set()

  def add(src, dst, lag, source):
    if src is None or dst is None:
      return
    src = int(src)
    dst = int(dst)
    if src not in task_by_id or dst not in task_by_id or src == dst:
      return
    key = (src, dst, int(lag), source)
    if key not in seen:
      seen.add(key)
      edges.append(key)

  for pair in fjspb.get("precedence_pairs", []) or []:
    if isinstance(pair, (list, tuple)) and len(pair) >= 2:
      src, dst = int(pair[0]), int(pair[1])
      lag = max(0, int(task_by_id.get(src, {}).get("min_wait", 0) or 0))
      add(src, dst, lag, "precedence_pairs")

  for event in fjspb.get("logistics_events", []) or []:
    if not isinstance(event, dict):
      continue
    duration = max(0, int(event.get("duration", 0) or 0))
    duration_source = event.get("duration_source")
    enforcement = event.get("enforcement")
    strict_zero_transport = (
        enforcement == "precedence_only"
        or duration == 0
        or duration_source == "missing_planning_duration_no_history"
    )
    if not strict_zero_transport:
      continue
    for src in event.get("predecessor_task_ids", []) or []:
      for dst in event.get("successor_task_ids", []) or []:
        add(src, dst, 0, "logistics_zero_duration")

  return edges


def _critical_path(task_by_id: dict, edges: list[tuple[int, int, int, str]]) -> tuple[int | None, list[int]]:
  successors = defaultdict(list)
  indegree = defaultdict(int)
  for task_id in task_by_id:
    indegree[task_id] = 0
  for src, dst, lag, source in edges:
    successors[src].append((dst, lag, source))
    indegree[dst] += 1

  ready = deque(sorted(task_id for task_id, deg in indegree.items() if deg == 0))
  earliest_start = {task_id: 0 for task_id in task_by_id}
  predecessor = {}
  visited = []
  while ready:
    src = ready.popleft()
    visited.append(src)
    src_finish = earliest_start[src] + _task_duration(task_by_id[src])
    for dst, lag, _source in successors[src]:
      candidate = src_finish + lag
      if candidate > earliest_start.get(dst, 0):
        earliest_start[dst] = candidate
        predecessor[dst] = src
      indegree[dst] -= 1
      if indegree[dst] == 0:
        ready.append(dst)

  if len(visited) != len(task_by_id):
    return None, []

  end_task = max(
      task_by_id,
      key=lambda task_id: earliest_start[task_id] + _task_duration(task_by_id[task_id]),
  )
  critical_value = earliest_start[end_task] + _task_duration(task_by_id[end_task])
  path = [end_task]
  while path[-1] in predecessor:
    path.append(predecessor[path[-1]])
  path.reverse()
  return critical_value, path


def prove(args: argparse.Namespace) -> int:
  problem = load_problem(
      args.dataset,
      boundary_profile=args.boundary_profile,
      boundary_seed=args.boundary_seed,
      history_policy=args.history_policy,
  )
  fjspb = problem.dataset["fjspb"]
  task_by_id, key_by_task_id = _build_task_maps(fjspb)
  machines = {str(k): int(v) for k, v in (fjspb.get("machines") or {}).items()}
  machine_frequencies = fjspb.get("machine_frequencies") or {}
  transfer_lookup = _device_transfer_lookup(fjspb, args.override_transfer_cap)
  default_transfer = int((fjspb.get("isaac_motion_timing") or {}).get("transfer_seconds") or 0)
  if args.override_transfer_cap is not None:
    default_transfer = min(default_transfer, int(args.override_transfer_cap))

  base_edges = _hard_edges(fjspb, task_by_id)
  critical_edges = list(base_edges)
  eligible_by_task = {
      task_id: _eligible_machines(task, machines, machine_frequencies)
      for task_id, task in task_by_id.items()
  }
  for task_id, eligible in eligible_by_task.items():
    if not eligible:
      raise RuntimeError("task %s has no eligible machine" % task_id)

  min_transfer_edge_count = 0
  conditional_transfer_edge_count = 0
  material_edges = [
      edge
      for edge in (fjspb.get("material_edges") or [])
      if isinstance(edge, dict) and edge.get("hard_precedence_candidate")
  ]
  for edge in material_edges:
    src = edge.get("src_task_id")
    dst = edge.get("dst_task_id")
    if src is None or dst is None:
      continue
    src = int(src)
    dst = int(dst)
    if src not in task_by_id or dst not in task_by_id:
      continue
    min_wait = int(task_by_id[src].get("min_wait") or 0)
    pair_values = [
        transfer_lookup.get((src_machine, dst_machine), default_transfer)
        for src_machine in eligible_by_task[src]
        for dst_machine in eligible_by_task[dst]
    ]
    if not pair_values:
      continue
    min_gap = max(min_wait, min(pair_values))
    critical_edges.append((src, dst, min_gap, "material_min_transfer"))
    min_transfer_edge_count += 1
    conditional_transfer_edge_count += 1

  total_duration = sum(_task_duration(task) for task in task_by_id.values())
  total_lag = sum(max(0, edge[2]) for edge in critical_edges)
  horizon = max(1, total_duration + total_lag + 10000)

  model = cp_model.CpModel()
  start = {task_id: model.NewIntVar(0, horizon, "s_%s" % task_id) for task_id in task_by_id}
  end = {task_id: model.NewIntVar(0, horizon, "e_%s" % task_id) for task_id in task_by_id}
  for task_id, task in task_by_id.items():
    model.Add(end[task_id] == start[task_id] + _task_duration(task))
    if not task.get("is_fixed"):
      model.Add(start[task_id] >= int(fjspb.get("cur_ptr") or 0))

  presence = {}
  machine_to_intervals = defaultdict(list)
  machine_to_demands = defaultdict(list)
  if args.include_machine_capacity or args.logistics_mode == "conditional":
    for task_id, task in task_by_id.items():
      choices = []
      for machine_code in eligible_by_task[task_id]:
        is_present = model.NewBoolVar("p_%s_%s" % (task_id, machine_code))
        presence[(task_id, machine_code)] = is_present
        choices.append(is_present)
        if args.include_machine_capacity:
          interval = model.NewOptionalIntervalVar(
              start[task_id],
              _task_duration(task),
              end[task_id],
              is_present,
              "i_%s_%s" % (task_id, machine_code),
          )
          machine_to_intervals[machine_code].append(interval)
          machine_to_demands[machine_code].append(_required_capacity(task))
      model.AddExactlyOne(choices)

  if args.include_machine_capacity:
    for machine_code, intervals in machine_to_intervals.items():
      if not intervals:
        continue
      capacity = _machine_capacity(machines, machine_code)
      model.AddCumulative(intervals, machine_to_demands[machine_code], capacity)
      if capacity == 1:
        model.AddNoOverlap(intervals)

  for src, dst, lag, _source in base_edges:
    model.Add(end[src] + lag <= start[dst])

  if args.logistics_mode == "min":
    for edge in material_edges:
      src = edge.get("src_task_id")
      dst = edge.get("dst_task_id")
      if src is None or dst is None:
        continue
      src = int(src)
      dst = int(dst)
      if src not in task_by_id or dst not in task_by_id:
        continue
      min_wait = int(task_by_id[src].get("min_wait") or 0)
      pair_values = [
          transfer_lookup.get((src_machine, dst_machine), default_transfer)
          for src_machine in eligible_by_task[src]
          for dst_machine in eligible_by_task[dst]
      ]
      if pair_values:
        model.Add(end[src] + max(min_wait, min(pair_values)) <= start[dst])
  else:
    for edge in material_edges:
      src = edge.get("src_task_id")
      dst = edge.get("dst_task_id")
      if src is None or dst is None:
        continue
      src = int(src)
      dst = int(dst)
      if src not in task_by_id or dst not in task_by_id:
        continue
      min_wait = int(task_by_id[src].get("min_wait") or 0)
      for src_machine in eligible_by_task[src]:
        for dst_machine in eligible_by_task[dst]:
          gap = max(min_wait, transfer_lookup.get((src_machine, dst_machine), default_transfer))
          model.Add(end[src] + gap <= start[dst]).OnlyEnforceIf(
              [presence[(src, src_machine)], presence[(dst, dst_machine)]]
          )

  branch_priority_count = 0
  for pair in fjspb.get("branch_priority_pairs", []) or []:
    if not isinstance(pair, dict):
      continue
    higher = pair.get("higher_task_id")
    lower = pair.get("lower_task_id")
    if higher is None or lower is None:
      continue
    higher = int(higher)
    lower = int(lower)
    if higher in task_by_id and lower in task_by_id:
      model.Add(start[higher] <= start[lower])
      branch_priority_count += 1

  makespan = model.NewIntVar(0, horizon, "makespan")
  model.AddMaxEquality(makespan, list(end.values()))
  model.Minimize(makespan)

  solver = cp_model.CpSolver()
  solver.parameters.max_time_in_seconds = args.timeout_seconds
  solver.parameters.num_search_workers = args.workers
  solver.parameters.random_seed = args.boundary_seed
  solver.parameters.cp_model_presolve = True
  solver.parameters.linearization_level = 2
  status = solver.Solve(model)

  status_name = solver.StatusName(status)
  cp_obj = int(round(solver.ObjectiveValue())) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
  cp_best_bound = int(round(solver.BestObjectiveBound())) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
  critical_lb, critical_path = _critical_path(task_by_id, critical_edges)

  print("history_policy=%s" % args.history_policy)
  print("boundary_profile=%s" % args.boundary_profile)
  print("boundary_seed=%s" % args.boundary_seed)
  print("tasks=%s" % len(task_by_id))
  print("machines=%s" % len(machines))
  print("precedence_or_zero_logistics_edges=%s" % len(base_edges))
  print("material_transfer_edges=%s" % min_transfer_edge_count)
  print("conditional_transfer_edges=%s" % conditional_transfer_edge_count)
  print("branch_priority_constraints=%s" % branch_priority_count)
  print("include_machine_capacity=%s" % args.include_machine_capacity)
  print("logistics_mode=%s" % args.logistics_mode)
  print("override_transfer_cap=%s" % args.override_transfer_cap)
  print("relaxed_cp_sat_status=%s" % status_name)
  print("relaxed_cp_sat_objective=%s" % cp_obj)
  print("relaxed_cp_sat_best_bound=%s" % cp_best_bound)
  print("critical_path_lower_bound_with_min_transfers=%s" % critical_lb)
  print("known_feasible_upper_bound=%s" % args.known_upper_bound)
  if critical_path:
    print("critical_path_task_ids=%s" % ",".join(str(x) for x in critical_path))

  if status == cp_model.OPTIMAL and cp_obj == args.known_upper_bound:
    print("proof=OPTIMAL: relaxed lower bound equals known feasible upper bound")
    return 0
  if critical_lb == args.known_upper_bound:
    print("proof=OPTIMAL: DAG critical-path lower bound equals known feasible upper bound")
    return 0
  if cp_best_bound is not None:
    print("gap_to_known_upper_bound=%s" % (int(args.known_upper_bound) - cp_best_bound))
  print("proof=NOT_PROVEN")
  return 1


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=DEFAULT_DATASET)
  parser.add_argument("--history-policy", default="strict_cold_start")
  parser.add_argument("--boundary-profile", default="conservative")
  parser.add_argument("--boundary-seed", type=int, default=1160)
  parser.add_argument("--known-upper-bound", type=int, default=157086)
  parser.add_argument("--timeout-seconds", type=float, default=120.0)
  parser.add_argument("--workers", type=int, default=8)
  parser.add_argument("--include-machine-capacity", action="store_true")
  parser.add_argument(
      "--logistics-mode",
      choices=("conditional", "min"),
      default="conditional",
      help="conditional keeps machine-pair transfer gaps; min uses per-edge minimum transfer gaps.",
  )
  parser.add_argument(
      "--override-transfer-cap",
      type=int,
      default=None,
      help="Optionally cap all transfer matrix entries, matching adaptive tightening experiments.",
  )
  raise SystemExit(prove(parser.parse_args()))


if __name__ == "__main__":
  main()
