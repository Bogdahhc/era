"""Seed-specific instance builder for flow_1160_era_v4.

V4 keeps the v3 task/command IR, then scopes it to one declared experiment
seed. The seed layer must traverse the task/material graph from every selected
initial material, then add load compatibility evidence from device/position
parameters. It must not invent hard stock, plate identity, or branch selection
rules.
"""

from __future__ import annotations

from collections import defaultdict, deque
import copy
import json
from pathlib import Path
from typing import Any


DEFAULT_SEED_PATH = Path(__file__).with_name("default_seeds") / "sample1_enzyme_activity.json"


def load_seed_spec(path: str | None = None) -> dict:
  seed_path = Path(path) if path else DEFAULT_SEED_PATH
  return json.loads(seed_path.read_text(encoding="utf-8"))


def apply_seed_instance(fjspb: dict, seed_spec: dict | None) -> dict:
  """Return an fjspb copy scoped to the selected seed instance."""

  if not seed_spec:
    return fjspb
  scoped = copy.deepcopy(fjspb)
  material_traversals = _material_traversals(scoped, seed_spec)
  selected_task_ids = _select_task_ids(scoped, seed_spec, material_traversals)
  if not selected_task_ids:
    raise ValueError("seed %r selected no tasks" % (seed_spec.get("seed_id") or "<unnamed>"))

  all_task_ids = _all_task_ids(scoped)
  disabled = {
      task_id: "not_reachable_from_seed_targets"
      for task_id in sorted(all_task_ids - selected_task_ids)
  }
  _filter_jobs(scoped, selected_task_ids)
  _filter_task_pair_rows(scoped, "precedence_pairs", selected_task_ids)
  _filter_branch_priority_pairs(scoped, selected_task_ids)
  _filter_branch_groups(scoped, selected_task_ids)
  selected_material_edges = _filter_material_edges(scoped, selected_task_ids)
  _filter_material_flow_groups(scoped, selected_material_edges)
  _filter_material_lineage_links(scoped, selected_material_edges)
  _filter_material_inventory_events(scoped, selected_task_ids, selected_material_edges)
  _filter_logistics_events(scoped, selected_task_ids)
  _filter_device_commands(scoped, selected_task_ids)
  _filter_machine_surface(scoped)
  plate_instances = _expand_initial_unit_instances(scoped, seed_spec, selected_task_ids)
  if plate_instances:
    selected_task_ids = _all_task_ids(scoped)
    selected_material_edges = {
        str(edge.get("edge_id"))
        for edge in scoped.get("material_edges") or []
        if isinstance(edge, dict) and edge.get("edge_id")
    }
  _refresh_boundary_counts(scoped)

  scoped["seed_instance"] = _seed_instance_record(
      seed_spec,
      scoped,
      selected_task_ids,
      selected_material_edges,
      material_traversals,
      plate_instances,
      disabled,
  )
  scoped["model_version"] = "flow_1160_era_v4"
  scoped.setdefault("constraint_contract", []).append(
      "V4 seed_instance scopes the benchmark to declared initial_materials, "
      "target_outputs, selected_task_ids, material_traversals, and "
      "load_compatibility_report. hard_initial_inventory remains empty unless "
      "the seed explicitly declares stable stock identity, quantity, and "
      "initial position/device binding."
  )
  return scoped


def _select_task_ids(fjspb: dict, seed_spec: dict, material_traversals: list[dict]) -> set[int]:
  explicit = {int(value) for value in seed_spec.get("selected_task_ids") or []}
  if explicit:
    return explicit & _all_task_ids(fjspb)

  task_ids = _all_task_ids(fjspb)
  targets = {int(value) for value in seed_spec.get("target_task_ids") or []}
  starts = {int(value) for value in seed_spec.get("entry_task_ids") or []}
  selected = {
      int(task_id)
      for traversal in material_traversals
      for task_id in traversal.get("selected_task_ids") or []
  }
  if not selected and not targets:
    return task_ids

  if targets:
    selected |= targets
    selected |= {
        int(task_id)
        for task_id in _ancestors(fjspb, targets)
        if not material_traversals
    }
  selected |= starts
  include = {int(value) for value in seed_spec.get("include_task_ids") or []}
  exclude = {int(value) for value in seed_spec.get("exclude_task_ids") or []}
  selected |= include
  selected -= exclude
  return selected & task_ids


def _material_traversals(fjspb: dict, seed_spec: dict) -> list[dict]:
  """Traverse downstream task flow for every selected initial material."""

  initial_edges = [
      edge for edge in fjspb.get("material_edges") or []
      if isinstance(edge, dict) and edge.get("src_task_id") is None and edge.get("dst_task_id") is not None
  ]
  if not initial_edges:
    return []
  seed_materials = [row for row in seed_spec.get("initial_materials") or [] if isinstance(row, dict)]
  traverse_all = bool(seed_spec.get("traverse_all_initial_materials", False))
  matched_edges = [
      edge for edge in initial_edges
      if traverse_all or _edge_matches_any_initial_material(edge, seed_materials)
  ]
  if not matched_edges and seed_materials:
    matched_edges = [
        edge for edge in initial_edges
        if _edge_matches_any_initial_material(edge, seed_materials, loose=True)
    ]

  target_ids = {int(value) for value in seed_spec.get("target_task_ids") or []}
  target_ancestors = _ancestors(fjspb, target_ids) | target_ids if target_ids else set()
  downstream = _downstream_graph(fjspb)
  downstream_edges = _downstream_edge_graph(fjspb)
  traversals = []
  seen_keys = set()
  for edge in matched_edges:
    dst = int(edge["dst_task_id"])
    all_task_ids = _descendants(downstream, {dst}) | {dst}
    if target_ancestors:
      selected_task_ids = sorted(all_task_ids & target_ancestors)
      reaches_targets = bool(all_task_ids & target_ids)
    else:
      selected_task_ids = sorted(all_task_ids)
      reaches_targets = True
    selected_edge_ids = sorted(
        edge_id
        for task_id in selected_task_ids
        for edge_id in downstream_edges.get(task_id, set())
    )
    if edge.get("edge_id"):
      selected_edge_ids = sorted(set(selected_edge_ids) | {str(edge["edge_id"])})
    key = (
        edge.get("material_code"),
        edge.get("barcode_type"),
        edge.get("material_name"),
        edge.get("plate_name"),
        edge.get("dst_task_id"),
    )
    if key in seen_keys:
      continue
    seen_keys.add(key)
    traversals.append(
        {
            "initial_edge_id": edge.get("edge_id"),
            "material_code": edge.get("material_code"),
            "barcode_type": edge.get("barcode_type"),
            "material_name": edge.get("material_name"),
            "barcode_name": edge.get("barcode_name"),
            "plate_name": edge.get("plate_name"),
            "plate_alias": edge.get("plate_alias"),
            "entry_task_id": dst,
            "all_downstream_task_ids": sorted(all_task_ids),
            "selected_task_ids": selected_task_ids,
            "selected_material_edges": selected_edge_ids,
            "target_task_ids": sorted(target_ids),
            "reaches_targets": reaches_targets,
            "selection_rule": "per_initial_material_downstream_intersect_target_ancestors" if target_ancestors else "per_initial_material_downstream",
        }
    )
  return traversals


def _edge_matches_any_initial_material(edge: dict, seed_materials: list[dict], *, loose: bool = False) -> bool:
  if not seed_materials:
    return False
  for material in seed_materials:
    matched = True
    compared = False
    for key in ("material_code", "barcode_type", "material_name", "barcode_name", "plate_name", "plate_alias"):
      expected = material.get(key)
      if expected in (None, ""):
        continue
      compared = True
      actual = edge.get(key)
      if loose:
        if str(expected) not in str(actual):
          matched = False
          break
      elif str(actual) != str(expected):
        matched = False
        break
    if matched and compared:
      return True
  return False


def _downstream_graph(fjspb: dict) -> dict[int, set[int]]:
  graph: dict[int, set[int]] = defaultdict(set)
  for row in fjspb.get("precedence_pairs") or []:
    if isinstance(row, (list, tuple)) and len(row) >= 2:
      graph[int(row[0])].add(int(row[1]))
  for edge in fjspb.get("material_edges") or []:
    src = edge.get("src_task_id") if isinstance(edge, dict) else None
    dst = edge.get("dst_task_id") if isinstance(edge, dict) else None
    if src is not None and dst is not None:
      graph[int(src)].add(int(dst))
  return graph


def _downstream_edge_graph(fjspb: dict) -> dict[int, set[str]]:
  graph: dict[int, set[str]] = defaultdict(set)
  for edge in fjspb.get("material_edges") or []:
    if not isinstance(edge, dict):
      continue
    src = edge.get("src_task_id")
    edge_id = edge.get("edge_id")
    if src is not None and edge_id:
      graph[int(src)].add(str(edge_id))
  return graph


def _descendants(graph: dict[int, set[int]], starts: set[int]) -> set[int]:
  result = set()
  queue: deque[int] = deque(starts)
  while queue:
    task_id = queue.popleft()
    for succ in graph.get(task_id, set()):
      if succ in result:
        continue
      result.add(succ)
      queue.append(succ)
  return result


def _all_task_ids(fjspb: dict) -> set[int]:
  return {
      int(task["task_id"])
      for job in fjspb.get("jobs", []) or []
      for task in job.get("tasks", []) or []
      if task.get("task_id") is not None
  }


def _ancestors(fjspb: dict, targets: set[int]) -> set[int]:
  reverse_edges: dict[int, set[int]] = defaultdict(set)
  for row in fjspb.get("precedence_pairs") or []:
    if not isinstance(row, (list, tuple)) or len(row) < 2:
      continue
    reverse_edges[int(row[1])].add(int(row[0]))
  for edge in fjspb.get("material_edges") or []:
    if not edge.get("hard_precedence_candidate"):
      continue
    src = edge.get("src_task_id")
    dst = edge.get("dst_task_id")
    if src is not None and dst is not None:
      reverse_edges[int(dst)].add(int(src))

  selected: set[int] = set()
  queue: deque[int] = deque(int(task_id) for task_id in targets)
  while queue:
    task_id = queue.popleft()
    for pred in reverse_edges.get(task_id, set()):
      if pred in selected:
        continue
      selected.add(pred)
      queue.append(pred)
  return selected


def _filter_jobs(fjspb: dict, selected: set[int]) -> None:
  filtered_jobs = []
  for job in fjspb.get("jobs", []) or []:
    tasks = [
        task for task in job.get("tasks", []) or []
        if int(task.get("task_id")) in selected
    ]
    if tasks:
      new_job = dict(job)
      new_job["tasks"] = tasks
      filtered_jobs.append(new_job)
  fjspb["jobs"] = filtered_jobs


def _filter_task_pair_rows(fjspb: dict, key: str, selected: set[int]) -> None:
  rows = []
  for row in fjspb.get(key) or []:
    if not isinstance(row, (list, tuple)) or len(row) < 2:
      continue
    if int(row[0]) in selected and int(row[1]) in selected:
      rows.append(row)
  fjspb[key] = rows


def _filter_branch_priority_pairs(fjspb: dict, selected: set[int]) -> None:
  rows = []
  for row in fjspb.get("branch_priority_pairs") or []:
    if not isinstance(row, dict):
      continue
    higher = row.get("higher_task_id")
    lower = row.get("lower_task_id")
    if higher is not None and lower is not None and int(higher) in selected and int(lower) in selected:
      rows.append(row)
  fjspb["branch_priority_pairs"] = rows


def _filter_branch_groups(fjspb: dict, selected: set[int]) -> None:
  groups = []
  for group in fjspb.get("branch_groups") or []:
    if not isinstance(group, dict):
      continue
    new_group = copy.deepcopy(group)
    for key in ("task_ids", "branch_task_ids"):
      if isinstance(new_group.get(key), list):
        new_group[key] = [task_id for task_id in new_group[key] if int(task_id) in selected]
    branches = []
    for branch in new_group.get("branches") or []:
      if not isinstance(branch, dict):
        continue
      new_branch = dict(branch)
      for key in ("task_ids", "branch_task_ids"):
        if isinstance(new_branch.get(key), list):
          new_branch[key] = [task_id for task_id in new_branch[key] if int(task_id) in selected]
      if any(new_branch.get(key) for key in ("task_ids", "branch_task_ids")):
        branches.append(new_branch)
    if branches:
      new_group["branches"] = branches
    if any(new_group.get(key) for key in ("task_ids", "branch_task_ids", "branches")):
      groups.append(new_group)
  fjspb["branch_groups"] = groups


def _filter_material_edges(fjspb: dict, selected: set[int]) -> set[str]:
  rows = []
  edge_ids = set()
  for edge in fjspb.get("material_edges") or []:
    src = edge.get("src_task_id")
    dst = edge.get("dst_task_id")
    src_ok = src is None or int(src) in selected
    dst_ok = dst is None or int(dst) in selected
    if src_ok and dst_ok and (src is not None or dst is not None):
      rows.append(edge)
      if edge.get("edge_id"):
        edge_ids.add(str(edge["edge_id"]))
  fjspb["material_edges"] = rows
  return edge_ids


def _filter_material_flow_groups(fjspb: dict, selected_edge_ids: set[str]) -> None:
  groups = []
  for group in fjspb.get("material_flow_groups") or []:
    if not isinstance(group, dict):
      continue
    rows = [
        row for row in group.get("edges") or []
        if isinstance(row, dict) and str(row.get("edge_id")) in selected_edge_ids
    ]
    if rows:
      new_group = dict(group)
      new_group["edges"] = rows
      groups.append(new_group)
  fjspb["material_flow_groups"] = groups


def _filter_material_lineage_links(fjspb: dict, selected_edge_ids: set[str]) -> None:
  fjspb["material_lineage_links"] = [
      row for row in fjspb.get("material_lineage_links") or []
      if isinstance(row, dict) and str(row.get("edge_id")) in selected_edge_ids
  ]


def _filter_material_inventory_events(fjspb: dict, selected: set[int], selected_edge_ids: set[str]) -> None:
  rows = []
  for event in fjspb.get("material_inventory_events") or []:
    edge_id = event.get("edge_id")
    src = event.get("src_task_id")
    dst = event.get("dst_task_id")
    if edge_id is not None and str(edge_id) not in selected_edge_ids:
      continue
    if src is not None and int(src) not in selected:
      continue
    if dst is not None and int(dst) not in selected:
      continue
    rows.append(event)
  fjspb["material_inventory_events"] = rows


def _filter_logistics_events(fjspb: dict, selected: set[int]) -> None:
  rows = []
  for event in fjspb.get("logistics_events") or []:
    pred = [int(value) for value in event.get("predecessor_task_ids") or []]
    succ = [int(value) for value in event.get("successor_task_ids") or []]
    if not pred and not succ:
      continue
    if any(task_id in selected for task_id in pred + succ):
      new_event = dict(event)
      new_event["predecessor_task_ids"] = [task_id for task_id in pred if task_id in selected]
      new_event["successor_task_ids"] = [task_id for task_id in succ if task_id in selected]
      rows.append(new_event)
  fjspb["logistics_events"] = rows


def _filter_device_commands(fjspb: dict, selected: set[int]) -> None:
  rows = []
  for command in fjspb.get("device_commands") or []:
    task_id = command.get("task_id")
    pred = [int(value) for value in command.get("predecessor_task_ids") or []]
    succ = [int(value) for value in command.get("successor_task_ids") or []]
    keep = (task_id is not None and int(task_id) in selected) or any(task in selected for task in pred + succ)
    if not keep:
      continue
    new_command = dict(command)
    new_command["predecessor_task_ids"] = [task for task in pred if task in selected]
    new_command["successor_task_ids"] = [task for task in succ if task in selected]
    rows.append(new_command)
  fjspb["device_commands"] = rows


def _filter_machine_surface(fjspb: dict) -> None:
  used = {
      str(machine)
      for job in fjspb.get("jobs", []) or []
      for task in job.get("tasks", []) or []
      for machine in task.get("machines", []) or []
  }
  if used:
    fjspb["machines"] = {
        str(machine): capacity
        for machine, capacity in (fjspb.get("machines") or {}).items()
        if str(machine) in used
    }
    fjspb["machine_frequencies"] = {
        str(machine): frequencies
        for machine, frequencies in (fjspb.get("machine_frequencies") or {}).items()
        if str(machine) in used
    }
    matrix = fjspb.get("device_transfer_times") or {}
    if isinstance(matrix, dict):
      matrix = dict(matrix)
      matrix["rows"] = [
          row for row in matrix.get("rows") or []
          if str(row.get("src_machine")) in used and str(row.get("dst_machine")) in used
      ]
      fjspb["device_transfer_times"] = matrix


def _refresh_boundary_counts(fjspb: dict) -> None:
  material_edges = fjspb.get("material_edges") or []
  material_inventory_events = fjspb.get("material_inventory_events") or []
  logistics_events = fjspb.get("logistics_events") or []
  buffers = fjspb.get("buffers") or []
  device_commands = fjspb.get("device_commands") or []
  positions = fjspb.get("positions") or []
  robot_resources = fjspb.get("robot_resources") or []
  counts = {
      "task_and_material_precedence": sum(
          1 for edge in material_edges
          if edge.get("hard_precedence_candidate") and edge.get("src_task_id") is not None and edge.get("dst_task_id") is not None
      ),
      "edge_inventory_nonnegative": len(material_inventory_events),
      "logistics_resource_no_overlap": sum(
          1 for event in logistics_events
          if int(event.get("duration") or 0) > 0 and event.get("resources")
      ),
      "buffer_capacity": len(buffers),
      "rolling_existing_occupancy": len((fjspb.get("rolling_state") or {}).get("existing_machine_occupancy") or []),
      "task_run_command_alignment": sum(1 for command in device_commands if command.get("kind") == "device_run"),
      "position_capacity_from_devicePosition": len(positions),
      "robot_resource_capacity": len(robot_resources),
  }
  for boundary_key in ("constraint_realization_boundaries", "command_realization_boundaries"):
    boundary = fjspb.get(boundary_key) or {}
    for section in ("hard_ready", "audit_only", "blocked_missing_fields"):
      for row in boundary.get(section) or []:
        if isinstance(row, dict) and row.get("name") in counts:
          row["count"] = counts[row["name"]]


def _seed_instance_record(
    seed_spec: dict,
    fjspb: dict,
    selected_task_ids: set[int],
    selected_material_edges: set[str],
    material_traversals: list[dict],
    plate_instances: list[dict],
    disabled: dict[int, str],
) -> dict:
  hard_initial_inventory = seed_spec.get("hard_initial_inventory") or []
  required_initial_materials = _required_initial_materials(fjspb, seed_spec)
  initial_device_loads = _initial_device_loads(fjspb, seed_spec, required_initial_materials)
  initial_position_loads = _initial_position_loads(fjspb, seed_spec, required_initial_materials)
  load_parameter_bindings = _load_parameter_bindings(
      seed_spec,
      required_initial_materials,
      initial_device_loads,
      initial_position_loads,
  )
  load_compatibility_report = _load_compatibility_report(
      required_initial_materials,
      initial_device_loads,
      initial_position_loads,
      load_parameter_bindings,
      hard_initial_inventory,
  )
  flow_parallelism_hints = _flow_parallelism_hints(fjspb, material_traversals)
  return {
      "seed_id": seed_spec.get("seed_id") or "default_seed",
      "description": seed_spec.get("description", ""),
      "initial_units": seed_spec.get("initial_units") or [],
      "initial_unit_count": _initial_unit_count(seed_spec),
      "initial_materials": seed_spec.get("initial_materials") or [],
      "target_outputs": seed_spec.get("target_outputs") or [],
      "material_traversals": material_traversals,
      "plate_instances": plate_instances,
      "plate_instance_count": len(plate_instances) or 1,
      "required_initial_materials": required_initial_materials,
      "initial_device_loads": initial_device_loads,
      "initial_position_loads": initial_position_loads,
      "load_parameter_bindings": load_parameter_bindings,
      "load_compatibility_report": load_compatibility_report,
      "flow_parallelism_hints": flow_parallelism_hints,
      "entry_task_ids": [int(value) for value in seed_spec.get("entry_task_ids") or []],
      "target_task_ids": [int(value) for value in seed_spec.get("target_task_ids") or []],
      "selected_task_ids": sorted(selected_task_ids),
      "selected_material_edges": sorted(selected_material_edges),
      "hard_initial_inventory": hard_initial_inventory,
      "disabled_task_reason": {str(key): value for key, value in sorted(disabled.items())},
      "seed_realization_boundaries": {
          "hard_ready": [
              {
                  "name": "seed_selected_task_subgraph",
                  "hard_constraint": True,
                  "rule": "Only tasks reached by per-initial-material traversal and selected_task_ids are present in jobs/tasks and related hard precedence surfaces.",
              },
              {
                  "name": "plate_instance_expansion",
                  "hard_constraint": True,
                  "rule": "When initial_units.count > 1 and expand_initial_units is enabled, each physical culture dish/plate gets its own task ids while sharing the same machine, robot, and position resources.",
              }
          ],
          "audit_only": [
              {
                  "name": "declared_initial_materials",
                  "hard_constraint": False,
                  "reason": "Seed inputs identify user-level initial units such as culture dish count; platform stable stock identity and initial position binding remain separate.",
              },
              {
                  "name": "initial_device_load_parameters",
                  "hard_constraint": False,
                  "fields": ["device_name", "rack", "start_well", "remaining_count", "quantity", "volume"],
                  "reason": "Initial material effects on scheduling are exposed as device load parameters, but the current platform rows are not yet stable stock identities.",
              },
              {
                  "name": "initial_position_load_parameters",
                  "hard_constraint": False,
                  "fields": ["device_name", "rack", "level", "plate_barcode", "inner_or_out", "robot_interaction_flag"],
                  "reason": "Plate/position occupancy candidates affect feasible loading and robot movement, but barcode-to-material lineage is incomplete.",
              },
              {
                  "name": "load_compatibility_report",
                  "hard_constraint": False,
                  "fields": ["required_material", "compatible_device_loads", "compatible_position_loads", "status"],
                  "reason": "Reports whether each initial material has compatible load evidence; missing rows remain audit-only until stable stock and position identity are exported.",
              },
              {
                  "name": "flow_parallelism_hints",
                  "hard_constraint": False,
                  "fields": ["device_reuse_policy", "simultaneous_inbound_groups", "simultaneous_outbound_groups"],
                  "reason": "Optimization guidance: different material stages may interleave on released devices; same-priority logistics can run concurrently when resource calendars allow.",
              }
          ],
          "blocked_missing_fields": [
              {
                  "name": "hard_initial_inventory",
                  "hard_constraint": False,
                  "missing_fields": ["stock_item_id", "quantity", "initial_position_id"],
                  "upgrade_rule": "Promote only when the seed explicitly declares stable stock identity, quantity, and initial position/device binding.",
              }
          ],
      },
  }


def _expand_initial_unit_instances(
    fjspb: dict,
    seed_spec: dict,
    selected_task_ids: set[int],
) -> list[dict]:
  if not bool(seed_spec.get("expand_initial_units", False)):
    return []
  units = [row for row in seed_spec.get("initial_units") or [] if isinstance(row, dict)]
  count = sum(int(row.get("count") or 0) for row in units)
  if count <= 1:
    return []

  base_task_ids = sorted(int(task_id) for task_id in selected_task_ids)
  plate_instances = []
  instance_maps = []
  for index in range(1, count + 1):
    plate_id = "plate_%03d" % index
    task_id_map = {task_id: index * 10000 + task_id for task_id in base_task_ids}
    edge_suffix = ":%s" % plate_id
    instance_maps.append((plate_id, task_id_map, edge_suffix))
    plate_instances.append(
        {
            "plate_instance_id": plate_id,
            "unit_index": index,
            "base_task_ids": base_task_ids,
            "task_id_map": {str(k): v for k, v in task_id_map.items()},
            "shared_resource_policy": "machines, robot_resources, buffers, and positions are shared across plate instances",
        }
    )

  _expand_jobs(fjspb, instance_maps)
  _expand_precedence_pairs(fjspb, instance_maps)
  _expand_branch_priority_pairs(fjspb, instance_maps)
  _expand_material_edges(fjspb, instance_maps)
  _expand_material_inventory_events(fjspb, instance_maps)
  _expand_material_lineage_links(fjspb, instance_maps)
  _expand_logistics_events(fjspb, instance_maps)
  _expand_device_commands(fjspb, instance_maps)
  fjspb["branch_groups"] = []
  return plate_instances


def _expand_jobs(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_jobs = copy.deepcopy(fjspb.get("jobs") or [])
  jobs = []
  for plate_id, task_id_map, _suffix in instance_maps:
    for job in base_jobs:
      new_job = dict(job)
      new_job["job_id"] = "%s:%s" % (job.get("job_id", 0), plate_id)
      new_job["expr_no"] = "%s:%s" % (job.get("expr_no") or job.get("job_id", 0), plate_id)
      new_job["plate_instance_id"] = plate_id
      new_tasks = []
      for task in job.get("tasks") or []:
        old_task_id = int(task.get("task_id"))
        if old_task_id not in task_id_map:
          continue
        new_task = copy.deepcopy(task)
        new_task["base_task_id"] = old_task_id
        new_task["task_id"] = task_id_map[old_task_id]
        new_task["plate_instance_id"] = plate_id
        new_tasks.append(new_task)
      if new_tasks:
        new_job["tasks"] = new_tasks
        jobs.append(new_job)
  fjspb["jobs"] = jobs


def _expand_precedence_pairs(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = list(fjspb.get("precedence_pairs") or [])
  rows = []
  for _plate_id, task_id_map, _suffix in instance_maps:
    for row in base_rows:
      if not isinstance(row, (list, tuple)) or len(row) < 2:
        continue
      src, dst = int(row[0]), int(row[1])
      if src in task_id_map and dst in task_id_map:
        rows.append([task_id_map[src], task_id_map[dst]])
  fjspb["precedence_pairs"] = rows


def _expand_branch_priority_pairs(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = copy.deepcopy(fjspb.get("branch_priority_pairs") or [])
  rows = []
  for plate_id, task_id_map, _suffix in instance_maps:
    for row in base_rows:
      if not isinstance(row, dict):
        continue
      higher = row.get("higher_task_id")
      lower = row.get("lower_task_id")
      if higher is None or lower is None:
        continue
      higher = int(higher)
      lower = int(lower)
      if higher not in task_id_map or lower not in task_id_map:
        continue
      new_row = dict(row)
      new_row["base_higher_task_id"] = higher
      new_row["base_lower_task_id"] = lower
      new_row["higher_task_id"] = task_id_map[higher]
      new_row["lower_task_id"] = task_id_map[lower]
      new_row["plate_instance_id"] = plate_id
      rows.append(new_row)
  fjspb["branch_priority_pairs"] = rows


def _expand_material_edges(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_edges = copy.deepcopy(fjspb.get("material_edges") or [])
  rows = []
  for plate_id, task_id_map, suffix in instance_maps:
    for edge in base_edges:
      if not isinstance(edge, dict):
        continue
      src = edge.get("src_task_id")
      dst = edge.get("dst_task_id")
      src_ok = src is None or int(src) in task_id_map
      dst_ok = dst is None or int(dst) in task_id_map
      if not src_ok or not dst_ok:
        continue
      new_edge = copy.deepcopy(edge)
      new_edge["base_edge_id"] = edge.get("edge_id")
      new_edge["edge_id"] = "%s%s" % (edge.get("edge_id"), suffix)
      new_edge["plate_instance_id"] = plate_id
      if src is not None:
        new_edge["base_src_task_id"] = int(src)
        new_edge["src_task_id"] = task_id_map[int(src)]
      if dst is not None:
        new_edge["base_dst_task_id"] = int(dst)
        new_edge["dst_task_id"] = task_id_map[int(dst)]
      rows.append(new_edge)
  fjspb["material_edges"] = rows


def _expand_material_inventory_events(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = copy.deepcopy(fjspb.get("material_inventory_events") or [])
  rows = []
  for plate_id, task_id_map, suffix in instance_maps:
    for event in base_rows:
      if not isinstance(event, dict):
        continue
      src = event.get("src_task_id")
      dst = event.get("dst_task_id")
      if src is not None and int(src) not in task_id_map:
        continue
      if dst is not None and int(dst) not in task_id_map:
        continue
      new_event = copy.deepcopy(event)
      new_event["plate_instance_id"] = plate_id
      if new_event.get("edge_id"):
        new_event["base_edge_id"] = new_event["edge_id"]
        new_event["edge_id"] = "%s%s" % (new_event["edge_id"], suffix)
      if src is not None:
        new_event["base_src_task_id"] = int(src)
        new_event["src_task_id"] = task_id_map[int(src)]
      if dst is not None:
        new_event["base_dst_task_id"] = int(dst)
        new_event["dst_task_id"] = task_id_map[int(dst)]
      rows.append(new_event)
  fjspb["material_inventory_events"] = rows


def _expand_material_lineage_links(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = copy.deepcopy(fjspb.get("material_lineage_links") or [])
  rows = []
  for plate_id, _task_id_map, suffix in instance_maps:
    for row in base_rows:
      if not isinstance(row, dict):
        continue
      new_row = copy.deepcopy(row)
      new_row["plate_instance_id"] = plate_id
      if new_row.get("edge_id"):
        new_row["base_edge_id"] = new_row["edge_id"]
        new_row["edge_id"] = "%s%s" % (new_row["edge_id"], suffix)
      rows.append(new_row)
  fjspb["material_lineage_links"] = rows


def _expand_logistics_events(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = copy.deepcopy(fjspb.get("logistics_events") or [])
  rows = []
  for plate_id, task_id_map, suffix in instance_maps:
    for event in base_rows:
      if not isinstance(event, dict):
        continue
      pred = [int(value) for value in event.get("predecessor_task_ids") or [] if int(value) in task_id_map]
      succ = [int(value) for value in event.get("successor_task_ids") or [] if int(value) in task_id_map]
      if not pred and not succ:
        continue
      new_event = copy.deepcopy(event)
      new_event["base_id"] = event.get("id")
      new_event["id"] = "%s%s" % (event.get("id"), suffix)
      new_event["plate_instance_id"] = plate_id
      new_event["predecessor_task_ids"] = [task_id_map[value] for value in pred]
      new_event["successor_task_ids"] = [task_id_map[value] for value in succ]
      rows.append(new_event)
  fjspb["logistics_events"] = rows


def _expand_device_commands(fjspb: dict, instance_maps: list[tuple[str, dict[int, int], str]]) -> None:
  base_rows = copy.deepcopy(fjspb.get("device_commands") or [])
  rows = []
  for plate_id, task_id_map, suffix in instance_maps:
    for command in base_rows:
      if not isinstance(command, dict):
        continue
      task_id = command.get("task_id")
      pred = [int(value) for value in command.get("predecessor_task_ids") or [] if int(value) in task_id_map]
      succ = [int(value) for value in command.get("successor_task_ids") or [] if int(value) in task_id_map]
      keep = (task_id is not None and int(task_id) in task_id_map) or pred or succ
      if not keep:
        continue
      new_command = copy.deepcopy(command)
      old_command_id = str(command.get("command_id"))
      new_command["base_command_id"] = old_command_id
      new_command["plate_instance_id"] = plate_id
      if task_id is not None and int(task_id) in task_id_map:
        new_task_id = task_id_map[int(task_id)]
        new_command["base_task_id"] = int(task_id)
        new_command["task_id"] = new_task_id
        new_command["command_id"] = "cmd:task:%s:run" % new_task_id
      else:
        new_command["command_id"] = "%s%s" % (old_command_id, suffix)
      new_command["predecessor_task_ids"] = [task_id_map[value] for value in pred]
      new_command["successor_task_ids"] = [task_id_map[value] for value in succ]
      rows.append(new_command)
  fjspb["device_commands"] = rows


def _initial_unit_count(seed_spec: dict) -> int:
  total = 0
  for row in seed_spec.get("initial_units") or []:
    if not isinstance(row, dict):
      continue
    total += int(row.get("count") or 0)
  if total:
    return total
  for row in seed_spec.get("initial_materials") or []:
    if isinstance(row, dict) and row.get("count") is not None:
      total += int(row.get("count") or 0)
  return total


def _flow_parallelism_hints(fjspb: dict, material_traversals: list[dict]) -> dict:
  edges = [edge for edge in fjspb.get("material_edges") or [] if isinstance(edge, dict)]
  inbound = defaultdict(list)
  outbound = defaultdict(list)
  for edge in edges:
    raw_order = edge.get("raw_order")
    if raw_order != 1:
      continue
    dst = edge.get("dst_task_id")
    src = edge.get("src_task_id")
    if dst is not None:
      inbound[int(dst)].append(edge)
    if src is not None:
      outbound[int(src)].append(edge)

  def group_rows(groups: dict[int, list[dict]], task_key: str) -> list[dict]:
    rows = []
    for task_id, group_edges in sorted(groups.items()):
      if len(group_edges) < 2:
        continue
      rows.append(
          {
              task_key: task_id,
              "priority": "P1",
              "edge_ids": [edge.get("edge_id") for edge in group_edges if edge.get("edge_id")],
              "material_codes": sorted({str(edge.get("material_code")) for edge in group_edges if edge.get("material_code")}),
              "rule": "same-priority logistics may be concurrent; constrain only by explicit precedence, robot/device/position capacity, and no-conflict motion checks",
          }
      )
    return rows

  traversal_rows = [
      {
          "initial_edge_id": row.get("initial_edge_id"),
          "material_code": row.get("material_code"),
          "entry_task_id": row.get("entry_task_id"),
          "stage_task_ids": row.get("selected_task_ids") or [],
      }
      for row in material_traversals
  ]
  return {
      "device_reuse_policy": (
          "After a task interval ends, its selected device capacity is released "
          "and may be used by another material's later stage. Do not add a "
          "global per-material or per-job serial chain beyond explicit "
          "precedence/material_edges and resource calendars."
      ),
      "per_material_stage_chains": traversal_rows,
      "simultaneous_inbound_groups": group_rows(inbound, "dst_task_id"),
      "simultaneous_outbound_groups": group_rows(outbound, "src_task_id"),
      "forbidden_modeling": [
          "serializing all selected_task_ids by task_id",
          "serializing all stages of one material against unrelated materials",
          "turning P1/P2/P3 start priority into completion-before-start order",
          "forcing same-priority inbound/outbound logistics to run one-by-one without a resource conflict",
      ],
  }


def _load_compatibility_report(
    required_materials: list[dict],
    device_loads: list[dict],
    position_loads: list[dict],
    bindings: list[dict],
    hard_initial_inventory: list[dict],
) -> dict:
  device_by_code: dict[str, list[dict]] = defaultdict(list)
  for row in device_loads:
    if isinstance(row, dict) and row.get("material_code"):
      device_by_code[str(row["material_code"])].append(row)
  position_by_token: dict[str, list[dict]] = defaultdict(list)
  for row in position_loads:
    if not isinstance(row, dict):
      continue
    barcode = str(row.get("plate_barcode") or "")
    for token in _barcode_tokens_from_text(barcode):
      position_by_token[token].append(row)
  hard_by_code: dict[str, list[dict]] = defaultdict(list)
  for row in hard_initial_inventory:
    if isinstance(row, dict) and row.get("material_code"):
      hard_by_code[str(row["material_code"])].append(row)

  rows = []
  missing = []
  for material in required_materials:
    code = str(material.get("material_code") or "")
    tokens = {
        str(material.get(key))
        for key in ("material_code", "barcode_type", "barcode_name", "plate_name", "plate_alias")
        if material.get(key)
    }
    compatible_positions = []
    for token in tokens:
      compatible_positions.extend(position_by_token.get(token, []))
    compatible_devices = device_by_code.get(code, [])
    hard_rows = hard_by_code.get(code, [])
    if hard_rows:
      status = "hard_initial_inventory_ready"
    elif compatible_devices or compatible_positions:
      status = "compatible_audit_load_candidate"
    else:
      status = "missing_load_candidate"
      missing.append(code or material.get("material_name") or "<unknown>")
    rows.append(
        {
            "required_material": material,
            "compatible_device_load_count": len(compatible_devices),
            "compatible_position_load_count": len(compatible_positions),
            "hard_initial_inventory_count": len(hard_rows),
            "status": status,
            "hard_constraint": bool(hard_rows),
        }
    )
  return {
      "policy": "Every required initial material is checked against device load, position load, or hard_initial_inventory evidence.",
      "status": "hard_ready" if required_materials and not missing and hard_initial_inventory else ("audit_compatible" if required_materials and len(missing) < len(required_materials) else "audit_incomplete"),
      "required_material_count": len(required_materials),
      "missing_load_candidate_count": len(missing),
      "missing_material_codes": sorted(set(str(item) for item in missing)),
      "binding_count": len(bindings),
      "rows": rows,
  }


def _barcode_tokens_from_text(text: str) -> set[str]:
  tokens = set()
  current = []
  for char in text:
    if char.isalnum():
      current.append(char)
    elif current:
      tokens.add("".join(current))
      current = []
  if current:
    tokens.add("".join(current))
  return {token for token in tokens if token}


def _required_initial_materials(fjspb: dict, seed_spec: dict) -> list[dict]:
  rows = []
  seen = set()
  unit_count_by_key = _initial_unit_count_by_material_key(seed_spec)
  for edge in fjspb.get("material_edges") or []:
    if edge.get("src_task_id") is not None:
      continue
    if edge.get("dst_task_id") is None:
      continue
    key = (
        edge.get("material_code"),
        edge.get("barcode_type"),
        edge.get("material_name"),
        edge.get("plate_name"),
    )
    if key in seen:
      continue
    seen.add(key)
    rows.append(
        {
            "material_code": edge.get("material_code"),
            "barcode_type": edge.get("barcode_type"),
            "material_name": edge.get("material_name"),
            "barcode_name": edge.get("barcode_name"),
            "plate_name": edge.get("plate_name"),
            "plate_alias": edge.get("plate_alias"),
            "dst_task_id": edge.get("dst_task_id"),
            "unit_count": unit_count_by_key.get((edge.get("material_code"), edge.get("barcode_type")), 0),
            "unit_count_semantics": "number_of_physical_initial_units_from_seed_when_matched; 0 means this platform external input is not explicitly counted by the seed",
            "source": "selected_material_edge_external_input",
            "hard_inventory": False,
        }
    )
  return rows


def _initial_unit_count_by_material_key(seed_spec: dict) -> dict[tuple[Any, Any], int]:
  counts: dict[tuple[Any, Any], int] = defaultdict(int)
  rows = seed_spec.get("initial_units") or seed_spec.get("initial_materials") or []
  for row in rows:
    if not isinstance(row, dict):
      continue
    key = (row.get("material_code"), row.get("barcode_type"))
    counts[key] += int(row.get("count") or 0)
  return dict(counts)


def _initial_device_loads(fjspb: dict, seed_spec: dict, required_materials: list[dict]) -> list[dict]:
  sources = fjspb.get("platform_realism_sources") or {}
  rows = sources.get("device_material_loads") or []
  wanted_codes = _wanted_material_codes(seed_spec, required_materials)
  matches = []
  for row in rows:
    if not isinstance(row, dict):
      continue
    code = str(row.get("material_code") or "")
    if code not in wanted_codes:
      continue
    matches.append(
        {
            "plain_meaning": "设备上预先装载的原料/耗材余量",
            "device_name": row.get("device_name"),
            "rack": row.get("rack"),
            "material_code": row.get("material_code"),
            "start_well": row.get("start_well"),
            "remaining_count": row.get("remaining_count"),
            "quantity": row.get("quantity"),
            "volume": row.get("volume"),
            "plain_load": {
                "where": row.get("device_name"),
                "material": row.get("material_code"),
                "starts_at_well_or_slot": row.get("start_well"),
                "remaining_units": row.get("remaining_count"),
                "per_unit_quantity": row.get("quantity"),
                "volume": row.get("volume"),
            },
            "put_type": row.get("put_type"),
            "barcode": row.get("barcode"),
            "enforcement": row.get("enforcement", "audit_only_initial_load_candidate"),
            "hard_constraint": False,
            "reason": row.get("reason") or "Initial load candidate matched by seed-required material_code.",
        }
    )
  return matches


def _initial_position_loads(fjspb: dict, seed_spec: dict, required_materials: list[dict]) -> list[dict]:
  sources = fjspb.get("platform_realism_sources") or {}
  candidates = (sources.get("device_position_stock_candidates") or {}).get("rows") or []
  wanted_tokens = _wanted_barcode_tokens(seed_spec, required_materials)
  rows = []
  for row in candidates:
    if not isinstance(row, dict):
      continue
    barcode = str(row.get("plate_barcode") or "")
    if wanted_tokens and not any(token and token in barcode for token in wanted_tokens):
      continue
    rows.append(
        {
            "plain_meaning": "某个培养皿/孔板/耗材盒当前占用的物理位置",
            "device_name": row.get("device_name"),
            "device_full_name": row.get("device_full_name"),
            "position_type": row.get("position_type"),
            "rack": row.get("rack"),
            "level": row.get("level"),
            "plate_barcode": row.get("plate_barcode"),
            "plain_position": {
                "where": row.get("device_name"),
                "rack": row.get("rack"),
                "level": row.get("level"),
                "barcode": row.get("plate_barcode"),
                "meaning": "rack/level 可以理解为第几个架子/第几层或第几个孔位，具体取决于设备类型。",
            },
            "inner_or_out": row.get("inner_or_out"),
            "robot_interaction_flag": row.get("robot_interaction_flag"),
            "enforcement": row.get("enforcement", "audit_only_initial_position_candidate"),
            "hard_constraint": False,
            "reason": row.get("reason") or "Initial position candidate matched by seed barcode/material token.",
        }
    )
  return rows[:50]


def _load_parameter_bindings(
    seed_spec: dict,
    required_materials: list[dict],
    device_loads: list[dict],
    position_loads: list[dict],
) -> list[dict]:
  rows = []
  required_by_code = {
      str(row.get("material_code")): row
      for row in required_materials
      if row.get("material_code")
  }
  for row in device_loads:
    code = str(row.get("material_code") or "")
    rows.append(
        {
            "binding_type": "material_code_to_device_load",
            "material_code": code,
            "required_material": required_by_code.get(code, {}),
            "device_name": row.get("device_name"),
            "rack": row.get("rack"),
            "start_well": row.get("start_well"),
            "remaining_count": row.get("remaining_count"),
            "quantity": row.get("quantity"),
            "volume": row.get("volume"),
            "hard_constraint": False,
            "scheduling_effect": "candidate-visible load parameter for future setup, stock, and device-position constraints",
        }
    )
  for row in position_loads:
    rows.append(
        {
            "binding_type": "plate_barcode_to_position_load",
            "plate_barcode": row.get("plate_barcode"),
            "device_name": row.get("device_name"),
            "rack": row.get("rack"),
            "level": row.get("level"),
            "hard_constraint": False,
            "scheduling_effect": "candidate-visible initial occupancy candidate for future robot/position constraints",
        }
    )
  for row in seed_spec.get("load_parameter_bindings") or []:
    if isinstance(row, dict):
      explicit = dict(row)
      explicit.setdefault("source", "seed_spec")
      rows.append(explicit)
  return rows


def _wanted_material_codes(seed_spec: dict, required_materials: list[dict]) -> set[str]:
  codes = {
      str(row.get("material_code"))
      for row in required_materials
      if row.get("material_code")
  }
  for row in seed_spec.get("initial_materials") or []:
    if isinstance(row, dict) and row.get("material_code"):
      codes.add(str(row["material_code"]))
  for row in seed_spec.get("required_device_material_codes") or []:
    codes.add(str(row))
  return codes


def _wanted_barcode_tokens(seed_spec: dict, required_materials: list[dict]) -> set[str]:
  tokens = set()
  for row in required_materials:
    for key in ("barcode_type", "material_code"):
      value = row.get(key)
      if value:
        tokens.add(str(value))
  for row in seed_spec.get("initial_materials") or []:
    if not isinstance(row, dict):
      continue
    for key in ("barcode_type", "material_code", "plate_barcode_token"):
      value = row.get(key)
      if value:
        tokens.add(str(value))
  for token in seed_spec.get("position_barcode_tokens") or []:
    tokens.add(str(token))
  return tokens
