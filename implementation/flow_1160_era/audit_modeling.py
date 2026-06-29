"""Audit project-1160 flowData -> FJSPB modeling fidelity.

This script is intentionally read-only. It cross-checks raw smart-scheduling
data, the generated IR, and optional CP-SAT optimum scale.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path

from implementation.flow_1160_era.problem import (
    DEFAULT_DATASET,
    fetch_project,
    flow_data_to_fjspb,
    load_problem,
)
from implementation.flow_1160_era.scorer import validate_schedule


DEFAULT_CACHE = Path("/home/era/experiments/flow_1160_cache/1160.json")


def _canonical(obj) -> str:
  return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(obj) -> str:
  return hashlib.sha256(_canonical(obj).encode()).hexdigest()[:12]


def _parse_time(value):
  try:
    return datetime.fromisoformat(str(value).replace("Z", ""))
  except Exception:
    return None


def _param(task: dict, key: str):
  for entry in task.get("parameters") or []:
    param = entry.get("param") or {}
    if key in param:
      return param[key]
  return None


def _load_project(dataset: str, live: bool) -> dict:
  if live:
    return fetch_project(dataset)
  path = Path(dataset)
  if path.exists():
    return json.loads(path.read_text(encoding="utf-8"))
  return json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))


def _print_live_cache_compare(project_id: str, cache_path: Path) -> None:
  if not cache_path.exists():
    print(f"cache_compare: missing cache {cache_path}")
    return
  cache = json.loads(cache_path.read_text(encoding="utf-8"))
  live = fetch_project(project_id)
  for key in ("flow_data", "devices", "positions", "all_nodes"):
    print(
        "cache_compare",
        key,
        "same=",
        _canonical(cache.get(key)) == _canonical(live.get(key)),
        "cache_sha=",
        _sha(cache.get(key)),
        "live_sha=",
        _sha(live.get(key)),
    )
  print(
      "cache_compare",
      "ir",
      "same=",
      _canonical(flow_data_to_fjspb(cache)) == _canonical(flow_data_to_fjspb(live)),
      "cache_sha=",
      _sha(flow_data_to_fjspb(cache)),
      "live_sha=",
      _sha(flow_data_to_fjspb(live)),
  )


def _raw_stats(project: dict) -> None:
  flow = project.get("flow_data", {})
  nodes = flow.get("nodeList", []) or []
  lines = flow.get("lineList", []) or []
  all_nodes = project.get("all_nodes", []) or []
  devices = project.get("devices", []) or []
  positions = project.get("positions", []) or []
  print(
      "raw_counts",
      "nodes=", len(nodes),
      "lines=", len(lines),
      "all_nodes=", len(all_nodes),
      "devices=", len(devices),
      "positions=", len(positions),
  )
  print("nodeType_dist", dict(Counter(str(n.get("nodeType")) for n in nodes)))
  print(
      "workstation_nodeType0_dist",
      dict(Counter(n.get("workstationTypeName") for n in nodes if str(n.get("nodeType")) == "0")),
  )


def _ir_stats(fjspb: dict) -> None:
  tasks = fjspb["jobs"][0]["tasks"]
  print(
      "ir_counts",
      "tasks=", len(tasks),
      "machines=", len(fjspb.get("machines", {})),
      "precedence_pairs=", len(fjspb.get("precedence_pairs") or []),
  )
  print("machines", json.dumps(fjspb.get("machines", {}), ensure_ascii=False, sort_keys=True))
  print("route_patterns", Counter(tuple(t["machines"]) for t in tasks).most_common())
  print("required_capacity_dist", dict(Counter(t.get("required_capacity") for t in tasks)))
  print("temperature_dist", dict(Counter(_param(t, "temperature") for t in tasks)))
  print("frequency_dist", dict(Counter(_param(t, "frequency") for t in tasks)))
  print(
      "duration_minutes_top",
      Counter(round(int(t["duration"]) / 60, 3) for t in tasks).most_common(24),
  )
  print("sum_duration_seconds", sum(int(t["duration"]) for t in tasks))
  branch_groups = fjspb.get("branch_groups") or []
  branch_priority_pairs = fjspb.get("branch_priority_pairs") or []
  print(
      "branch_groups",
      "count=", len(branch_groups),
      "kind_dist=", dict(Counter(group.get("kind") for group in branch_groups)),
  )
  print("branch_priority_pairs", "count=", len(branch_priority_pairs), "sample=", branch_priority_pairs[:12])
  for group in branch_groups:
    if (
        group.get("kind") in ("condition_node", "required_experimental_branches", "possible_conditional_branches")
        or group.get("task_bearing_branch_count", 0) > 1
    ):
      print(
          "branch_group",
          {
              "from_node_id": group.get("from_node_id"),
              "from_name": group.get("from_name"),
              "from_task_id": group.get("from_task_id"),
              "kind": group.get("kind"),
              "branch_count": group.get("branch_count"),
              "task_bearing_branch_count": group.get("task_bearing_branch_count"),
              "active_task_bearing_branch_count": group.get("active_task_bearing_branch_count"),
              "branches": [
                  {
                      "to_node_id": branch.get("to_node_id"),
                      "to_name": branch.get("to_name"),
                      "label": branch.get("label"),
                      "order": branch.get("order"),
                      "successor_task_ids": branch.get("successor_task_ids"),
                      "has_runtime_task_successor": branch.get("has_runtime_task_successor"),
                  }
                  for branch in group.get("branches", [])
              ],
          },
      )


def _runtime_audit(project: dict, fjspb: dict) -> None:
  all_nodes = project.get("all_nodes", []) or []
  positions = project.get("positions", []) or []
  tasks = fjspb["jobs"][0]["tasks"]
  task_by_step = {t["step_id"]: t for t in tasks}

  ratios = []
  runtime_span_by_node = defaultdict(int)
  for row in all_nodes:
    start = _parse_time(row.get("startTime"))
    end = _parse_time(row.get("endTime"))
    if start and end:
      span = int(round((end - start).total_seconds()))
      runtime_span_by_node[row.get("nodeId")] = max(runtime_span_by_node[row.get("nodeId")], span)
      duration = row.get("duration")
      if duration not in (None, "", 0, 0.0):
        ratios.append((span / float(duration), row.get("nodeId"), row.get("nodeName"), duration, span))
  if ratios:
    outliers = [r for r in ratios if not 55 <= r[0] <= 65]
    print(
        "duration_ratio",
        "count=", len(ratios),
        "min=", round(min(r[0] for r in ratios), 3),
        "max=", round(max(r[0] for r in ratios), 3),
        "outliers=", len(outliers),
      )

  duration_zero_tasks = []
  raw_temp_zero_with_param = []
  rows_by_node = defaultdict(list)
  for row in all_nodes:
    rows_by_node[row.get("nodeId")].append(row)
  for task in tasks:
    rows = rows_by_node.get(task["step_id"], [])
    if rows and all(r.get("duration") in (None, "", 0, 0.0) for r in rows):
      duration_zero_tasks.append(
          (task["task_id"], task["step_id"], task["name"], task["duration"], runtime_span_by_node.get(task["step_id"]))
      )
    raw_temps = {r.get("temperature") for r in rows}
    if raw_temps and raw_temps.issubset({None, "", 0, 0.0}) and _param(task, "temperature") is not None:
      raw_temp_zero_with_param.append((task["task_id"], task["step_id"], task["name"], _param(task, "temperature")))
  print("duration_zero_tasks_using_span", duration_zero_tasks)
  print("raw_temperature_zero_but_ir_has_temperature", raw_temp_zero_with_param)

  dev_intervals = defaultdict(list)
  for row in all_nodes:
    start = _parse_time(row.get("startTime"))
    end = _parse_time(row.get("endTime"))
    dev = row.get("deviceName")
    if start and end and dev:
      dev_intervals[dev].append((start, end))
  runtime_caps = {}
  for dev, intervals in dev_intervals.items():
    events = []
    for start, end in intervals:
      events.append((start, 1))
      events.append((end, -1))
    current = peak = 0
    for _, delta in sorted(events):
      current += delta
      peak = max(peak, current)
    runtime_caps[dev] = peak
  slots = Counter(p.get("deviceName") for p in positions if p.get("deviceName"))
  print("runtime_capacity", runtime_caps)
  print("position_slots_for_runtime_devices", {dev: slots.get(dev, 0) for dev in runtime_caps})


def _serial_smoke(problem) -> None:
  fjspb = problem.dataset["fjspb"]
  job = fjspb["jobs"][0]
  by_tid = {int(t["task_id"]): t for t in job["tasks"]}
  predecessors = {int(t["task_id"]): [] for t in job["tasks"]}
  for a, b in fjspb.get("precedence_pairs") or []:
    predecessors[int(b)].append(int(a))
  for pair in fjspb.get("branch_priority_pairs") or []:
    # Conservative serial smoke: schedule the higher-priority branch task before
    # the lower-priority branch task. The real scorer only requires start order.
    predecessors[int(pair["lower_task_id"])].append(int(pair["higher_task_id"]))
  end_by_tid = {}
  current = 0
  assignments = []
  remaining = {int(task["task_id"]) for task in job["tasks"]}
  while remaining:
    ready_tids = [
        tid for tid in sorted(remaining)
        if all(pred in end_by_tid for pred in predecessors[tid])
    ]
    if not ready_tids:
      print("serial_smoke", "ok=", False, "makespan=", None, "hours=", None, "error=", "cyclic smoke dependencies")
      return
    tid = ready_tids[0]
    task = by_tid[tid]
    ready = 0
    for pred in predecessors[tid]:
      ready = max(ready, end_by_tid[pred] + int(by_tid[pred].get("min_wait") or 0))
    start = max(current, ready)
    end = start + int(task["duration"])
    assignments.append(
        {"job_id": job["job_id"], "task_id": tid, "machine": task["machines"][0], "start": start, "end": end}
    )
    end_by_tid[tid] = end
    current = end
    remaining.remove(tid)
  ok, makespan, error = validate_schedule(problem.dataset, {"assignments": assignments})
  print("serial_smoke", "ok=", ok, "makespan=", makespan, "hours=", round(makespan / 3600, 3) if makespan else None, "error=", error)


def _solve_minimal(problem, timeout_seconds: float) -> None:
  from ortools.sat.python import cp_model

  fjspb = problem.dataset["fjspb"]
  job = fjspb["jobs"][0]
  tasks = job["tasks"]
  machines = fjspb["machines"]
  model = cp_model.CpModel()
  horizon = sum(int(t["duration"]) for t in tasks) + sum(int(t.get("min_wait") or 0) for t in tasks) + 10000
  starts = {}
  ends = {}
  presence = {}
  intervals = {}
  for task in tasks:
    tid = int(task["task_id"])
    starts[tid] = model.NewIntVar(0, horizon, f"start_{tid}")
    ends[tid] = model.NewIntVar(0, horizon, f"end_{tid}")
    model.Add(ends[tid] == starts[tid] + int(task["duration"]))
    choices = []
    for machine in task["machines"]:
      chosen = model.NewBoolVar(f"presence_{tid}_{machine}")
      presence[(tid, machine)] = chosen
      choices.append(chosen)
      intervals[(tid, machine)] = model.NewOptionalIntervalVar(
          starts[tid], int(task["duration"]), ends[tid], chosen, f"interval_{tid}_{machine}"
      )
    model.AddExactlyOne(choices)
  for machine, capacity in machines.items():
    machine_intervals = []
    demands = []
    for task in tasks:
      tid = int(task["task_id"])
      if (tid, machine) in intervals:
        machine_intervals.append(intervals[(tid, machine)])
        demands.append(max(1, int(task.get("required_capacity") or 1)))
    if machine_intervals:
      model.AddCumulative(machine_intervals, demands, int(capacity))
  by_tid = {int(t["task_id"]): t for t in tasks}
  for a, b in fjspb.get("precedence_pairs") or []:
    model.Add(starts[int(b)] >= ends[int(a)] + int(by_tid[int(a)].get("min_wait") or 0))
  for pair in fjspb.get("branch_priority_pairs") or []:
    model.Add(starts[int(pair["higher_task_id"])] <= starts[int(pair["lower_task_id"])])
  for machine in machines:
    temp_tasks = [t for t in tasks if (int(t["task_id"]), machine) in intervals and _param(t, "temperature") is not None]
    for i in range(len(temp_tasks)):
      for j in range(i + 1, len(temp_tasks)):
        if _param(temp_tasks[i], "temperature") != _param(temp_tasks[j], "temperature"):
          model.AddNoOverlap([
              intervals[(int(temp_tasks[i]["task_id"]), machine)],
              intervals[(int(temp_tasks[j]["task_id"]), machine)],
          ])
  freqs = fjspb.get("machine_frequencies") or {}
  for task in tasks:
    need = _param(task, "frequency")
    if need is None:
      continue
    tid = int(task["task_id"])
    for machine in task["machines"]:
      rng = freqs.get(machine)
      if rng is None:
        continue
      lo, hi = rng
      if lo is not None and hi is not None and not lo <= need <= hi:
        model.Add(presence[(tid, machine)] == 0)
  makespan = model.NewIntVar(0, horizon, "makespan")
  model.AddMaxEquality(makespan, [ends[int(t["task_id"])] for t in tasks])
  model.Minimize(makespan)

  solver = cp_model.CpSolver()
  solver.parameters.max_time_in_seconds = timeout_seconds
  solver.parameters.num_search_workers = 8
  status = solver.Solve(model)
  print(
      "minimal_cpsat",
      "status=", solver.StatusName(status),
      "objective=", solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
      "bound=", solver.BestObjectiveBound(),
  )
  if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    return
  assignments = []
  for task in tasks:
    tid = int(task["task_id"])
    machine = next(m for m in task["machines"] if solver.BooleanValue(presence[(tid, m)]))
    assignments.append(
        {"job_id": job["job_id"], "task_id": tid, "machine": machine, "start": solver.Value(starts[tid]), "end": solver.Value(ends[tid])}
    )
  ok, makespan_value, error = validate_schedule(problem.dataset, {"assignments": assignments})
  print("minimal_cpsat_validate", "ok=", ok, "makespan=", makespan_value, "hours=", round(makespan_value / 3600, 3) if makespan_value else None, "error=", error)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=str(DEFAULT_CACHE), help="Project id or cached project JSON")
  parser.add_argument("--live", action="store_true", help="Fetch project data from the smart-scheduling API")
  parser.add_argument("--compare-live-cache", action="store_true", help="Compare live project data with the cache")
  parser.add_argument("--solve-minimal", action="store_true", help="Run an independent minimal CP-SAT optimum check")
  parser.add_argument("--timeout-seconds", type=float, default=60.0)
  args = parser.parse_args()

  if args.compare_live_cache:
    project_id = args.dataset if not Path(args.dataset).exists() else DEFAULT_DATASET
    _print_live_cache_compare(str(project_id), DEFAULT_CACHE)

  project = _load_project(args.dataset, args.live)
  fjspb = flow_data_to_fjspb(project)
  problem = load_problem(args.dataset if not args.live else str(project.get("project_id") or DEFAULT_DATASET))
  if args.live:
    problem = type(problem)(
        instance_name=problem.instance_name,
        description=problem.description,
        dataset={"fjspb": fjspb},
        prompt_dataset=problem.prompt_dataset,
        optimum=problem.optimum,
    )
  _raw_stats(project)
  _ir_stats(fjspb)
  _runtime_audit(project, fjspb)
  _serial_smoke(problem)
  if args.solve_minimal:
    _solve_minimal(problem, args.timeout_seconds)


if __name__ == "__main__":
  main()
