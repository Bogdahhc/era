"""Read-only audit for flow_1160_era_v4 IR additions."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from implementation.flow_1160_era_v4.problem import (
    BoundaryConfig,
    DEFAULT_DATASET,
    HistoryPolicy,
    flow_data_to_fjspb,
    fetch_project,
)
from implementation.flow_1160_era_v4.seed_instance import apply_seed_instance, load_seed_spec


DEFAULT_CACHE = Path("/home/era/experiments/flow_1160_cache/1160.json")


def _load_project(dataset: str, live: bool) -> dict:
  if live:
    return fetch_project(dataset)
  path = Path(dataset)
  if path.exists():
    return json.loads(path.read_text(encoding="utf-8"))
  return json.loads(DEFAULT_CACHE.read_text(encoding="utf-8"))


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=str(DEFAULT_CACHE))
  parser.add_argument("--live", action="store_true")
  parser.add_argument(
      "--boundary-profile",
      choices=["conservative", "seeded_audit", "seeded_experimental"],
      default="conservative",
  )
  parser.add_argument("--boundary-seed", type=int, default=1160)
  parser.add_argument(
      "--seed",
      dest="seed_path",
      help="Seed JSON path for v4 seed-specific instance construction. Defaults to default_seeds/sample1_enzyme_activity.json.",
  )
  parser.add_argument("--no-seed-instance", action="store_true")
  parser.add_argument(
      "--history-policy",
      choices=["strict_cold_start", "historical_replay"],
      default="strict_cold_start",
  )
  args = parser.parse_args()

  project = _load_project(args.dataset, args.live)
  fjspb = flow_data_to_fjspb(
      project,
      boundary_config=BoundaryConfig(args.boundary_profile, args.boundary_seed),
      history_policy=HistoryPolicy(args.history_policy),
  )
  base_fjspb = fjspb
  if not args.no_seed_instance:
    fjspb = apply_seed_instance(fjspb, load_seed_spec(args.seed_path))
  tasks = [task for job in fjspb.get("jobs", []) for task in job.get("tasks", [])]
  material_edges = fjspb.get("material_edges", [])
  material_lineage_links = fjspb.get("material_lineage_links", [])
  material_inventory_events = fjspb.get("material_inventory_events", [])
  platform_realism_sources = fjspb.get("platform_realism_sources", {})
  boundaries = fjspb.get("constraint_realization_boundaries", {})
  logistics_events = fjspb.get("logistics_events", [])
  buffers = fjspb.get("buffers", [])
  resources = fjspb.get("logistics_resources", [])
  device_commands = fjspb.get("device_commands", [])
  positions = fjspb.get("positions", [])
  plate_states = fjspb.get("plate_states", [])
  robot_resources = fjspb.get("robot_resources", [])
  command_boundaries = fjspb.get("command_realization_boundaries", {})
  seed_instance = fjspb.get("seed_instance", {})
  fidelity = _platform_fidelity_report(project, base_fjspb, fjspb)

  print(
      "v4_counts",
      "tasks=", len(tasks),
      "material_edges=", len(material_edges),
      "hard_material_precedence_candidates=",
      sum(1 for edge in material_edges if edge.get("hard_precedence_candidate")),
      "material_inventory_events=", len(material_inventory_events),
      "material_lineage_links=", len(material_lineage_links),
      "platform_realism_sources=", platform_realism_sources.get("version"),
      "logistics_events=", len(logistics_events),
      "buffers=", len(buffers),
      "resources=", len(resources),
      "device_commands=", len(device_commands),
      "positions=", len(positions),
      "plate_states=", len(plate_states),
      "robot_resources=", len(robot_resources),
  )
  print("seed_instance", json.dumps({
      "seed_id": seed_instance.get("seed_id"),
      "selected_task_count": len(seed_instance.get("selected_task_ids") or []),
      "selected_material_edge_count": len(seed_instance.get("selected_material_edges") or []),
      "disabled_task_count": len(seed_instance.get("disabled_task_reason") or {}),
      "material_traversal_count": len(seed_instance.get("material_traversals") or []),
      "required_initial_material_count": len(seed_instance.get("required_initial_materials") or []),
      "initial_device_load_count": len(seed_instance.get("initial_device_loads") or []),
      "initial_position_load_count": len(seed_instance.get("initial_position_loads") or []),
      "load_parameter_binding_count": len(seed_instance.get("load_parameter_bindings") or []),
      "hard_initial_inventory_count": len(seed_instance.get("hard_initial_inventory") or []),
  }, ensure_ascii=False, sort_keys=True))
  print("platform_fidelity_report", json.dumps(fidelity, ensure_ascii=False, indent=2, sort_keys=True))
  print("duration_source_counts", dict(Counter(task.get("duration_source") for task in tasks)))
  print("history_policy", json.dumps(fjspb.get("history_policy", {}), ensure_ascii=False, sort_keys=True))
  print("task_run_status_counts", dict(Counter(task.get("run_status") for task in tasks)))
  print("material_transfer_mode_counts", dict(Counter(edge.get("transfer_mode") for edge in material_edges)))
  print("material_enforcement_counts", dict(Counter(edge.get("enforcement") for edge in material_edges)))
  print("material_pre_plate_label_count", sum(1 for edge in material_edges if edge.get("pre_plate_label")))
  print("material_quantity_consume_rule_counts", dict(Counter(str(edge.get("quantity_consume_rule")) for edge in material_edges)))
  print("material_plate_oper_type_counts", dict(Counter(str(edge.get("plate_oper_type")) for edge in material_edges)))
  print("material_inventory_key_counts", dict(Counter(event.get("inventory_key") for event in material_inventory_events)))
  print("platform_realism_endpoint_counts", json.dumps(platform_realism_sources.get("endpoint_counts", {}), ensure_ascii=False, sort_keys=True))
  print(
      "platform_realism_aps_loading_counts",
      json.dumps(
          (platform_realism_sources.get("aps_loading_time_candidates") or {}).get("loading_raw_counts", {}),
          ensure_ascii=False,
          sort_keys=True,
      ),
  )
  print("platform_realism_device_material_counts_by_code", json.dumps(platform_realism_sources.get("device_material_counts_by_code", {}), ensure_ascii=False, sort_keys=True))
  print("platform_realism_blocked_hard_constraints", platform_realism_sources.get("blocked_hard_constraints", []))
  print(
      "platform_realism_self_filled_assumption_profiles",
      [row.get("name") for row in (platform_realism_sources.get("self_filled_assumption_profiles") or [])],
  )
  print("platform_realism_ai_query_status", json.dumps(platform_realism_sources.get("ai_query_status", {}), ensure_ascii=False, sort_keys=True))
  print(
      "constraint_boundary_counts",
      {
          "hard_ready": len(boundaries.get("hard_ready") or []),
          "audit_only": len(boundaries.get("audit_only") or []),
          "blocked_missing_fields": len(boundaries.get("blocked_missing_fields") or []),
          "required_hard_constraints": len((boundaries.get("state") or {}).get("required_hard_constraints") or []),
          "experimental_controls": len((boundaries.get("state") or {}).get("experimental_controls") or []),
      },
  )
  print("constraint_realization_boundaries", json.dumps(boundaries, ensure_ascii=False, indent=2))
  print("logistics_kind_counts", dict(Counter(event.get("kind") for event in logistics_events)))
  print("logistics_enforcement_counts", dict(Counter(event.get("enforcement") for event in logistics_events)))
  print("rolling_state", json.dumps(fjspb.get("rolling_state", {}), ensure_ascii=False, sort_keys=True))
  print("device_command_kind_counts", dict(Counter(command.get("kind") for command in device_commands)))
  print("command_duration_source_counts", dict(Counter(command.get("duration_source") for command in device_commands)))
  print("position_kind_counts", dict(Counter(position.get("kind") for position in positions)))
  print("command_boundary_counts", {
      "hard_ready": len(command_boundaries.get("hard_ready") or []),
      "audit_only": len(command_boundaries.get("audit_only") or []),
      "blocked_missing_fields": len(command_boundaries.get("blocked_missing_fields") or []),
      "required_hard_constraints": len((command_boundaries.get("state") or {}).get("required_hard_constraints") or []),
  })
  print("command_realization_boundaries", json.dumps(command_boundaries, ensure_ascii=False, indent=2))
  print("sample_device_commands", json.dumps(device_commands[:10], ensure_ascii=False, indent=2))
  print("sample_seed_material_traversals", json.dumps((seed_instance.get("material_traversals") or [])[:10], ensure_ascii=False, indent=2))
  print("sample_seed_required_initial_materials", json.dumps((seed_instance.get("required_initial_materials") or [])[:10], ensure_ascii=False, indent=2))
  print("sample_seed_initial_device_loads", json.dumps((seed_instance.get("initial_device_loads") or [])[:10], ensure_ascii=False, indent=2))
  print("sample_seed_initial_position_loads", json.dumps((seed_instance.get("initial_position_loads") or [])[:10], ensure_ascii=False, indent=2))
  print("sample_seed_load_parameter_bindings", json.dumps((seed_instance.get("load_parameter_bindings") or [])[:10], ensure_ascii=False, indent=2))
  print("seed_load_compatibility_report", json.dumps(seed_instance.get("load_compatibility_report") or {}, ensure_ascii=False, indent=2))
  print("seed_flow_parallelism_hints", json.dumps(seed_instance.get("flow_parallelism_hints") or {}, ensure_ascii=False, indent=2))
  print("seed_realization_boundaries", json.dumps(seed_instance.get("seed_realization_boundaries") or {}, ensure_ascii=False, indent=2))
  print("sample_positions", json.dumps(positions[:10], ensure_ascii=False, indent=2))
  print("sample_plate_states", json.dumps(plate_states[:10], ensure_ascii=False, indent=2))
  print("sample_robot_resources", json.dumps(robot_resources[:10], ensure_ascii=False, indent=2))
  print("sample_material_edges", json.dumps(material_edges[:10], ensure_ascii=False, indent=2))
  print("sample_material_lineage_links", json.dumps(material_lineage_links[:10], ensure_ascii=False, indent=2))
  print("sample_material_inventory_events", json.dumps(material_inventory_events[:10], ensure_ascii=False, indent=2))
  print("sample_platform_device_material_loads", json.dumps((platform_realism_sources.get("device_material_loads") or [])[:10], ensure_ascii=False, indent=2))
  print(
      "sample_platform_aps_loading_time_candidates",
      json.dumps(((platform_realism_sources.get("aps_loading_time_candidates") or {}).get("rows") or [])[:10], ensure_ascii=False, indent=2),
  )
  print(
      "sample_platform_device_position_stock_candidates",
      json.dumps(((platform_realism_sources.get("device_position_stock_candidates") or {}).get("rows") or [])[:10], ensure_ascii=False, indent=2),
  )
  print(
      "platform_realism_self_filled_assumptions",
      json.dumps(platform_realism_sources.get("self_filled_assumption_profiles") or [], ensure_ascii=False, indent=2),
  )
  print("sample_logistics_events", json.dumps(logistics_events[:10], ensure_ascii=False, indent=2))


def _platform_fidelity_report(project: dict, base_fjspb: dict, scoped_fjspb: dict) -> dict:
  flow = project.get("flow_data") or {}
  flow_nodes = flow.get("nodeList") or []
  flow_lines = flow.get("lineList") or []
  devices = project.get("devices") or []
  positions = project.get("positions") or []
  all_nodes = project.get("all_nodes") or []
  seed_instance = scoped_fjspb.get("seed_instance") or {}
  plate_instances = seed_instance.get("plate_instances") or []

  base_tasks = _tasks_by_id(base_fjspb)
  scoped_tasks = _tasks_by_id(scoped_fjspb)
  base_selected = _base_selected_task_ids(scoped_fjspb, seed_instance)
  base_precedence = {
      (int(row[0]), int(row[1]))
      for row in base_fjspb.get("precedence_pairs") or []
      if isinstance(row, (list, tuple)) and len(row) >= 2
  }
  selected_base_precedence = {
      row for row in base_precedence
      if row[0] in base_selected and row[1] in base_selected
  }
  scoped_precedence = {
      (int(row[0]), int(row[1]))
      for row in scoped_fjspb.get("precedence_pairs") or []
      if isinstance(row, (list, tuple)) and len(row) >= 2
  }
  mapped_precedence = _mapped_pairs_by_plate(plate_instances, selected_base_precedence)
  precedence_missing = sorted(mapped_precedence - scoped_precedence)
  precedence_extra = sorted(scoped_precedence - mapped_precedence) if plate_instances else []

  base_hard_material = [
      edge for edge in base_fjspb.get("material_edges") or []
      if isinstance(edge, dict)
      and edge.get("hard_precedence_candidate")
      and edge.get("src_task_id") is not None
      and edge.get("dst_task_id") is not None
      and int(edge["src_task_id"]) in base_selected
      and int(edge["dst_task_id"]) in base_selected
  ]
  scoped_hard_material = [
      edge for edge in scoped_fjspb.get("material_edges") or []
      if isinstance(edge, dict)
      and edge.get("hard_precedence_candidate")
      and edge.get("src_task_id") is not None
      and edge.get("dst_task_id") is not None
  ]
  material_preservation = _material_preservation_report(plate_instances, base_hard_material, scoped_hard_material)

  code_to_device = {
      str(row.get("deviceCode")): row
      for row in devices
      if row.get("deviceCode")
  }
  position_counts = Counter(str(row.get("deviceName") or "<missing>") for row in positions)
  task_device_codes = {
      str(machine)
      for task in scoped_tasks.values()
      for machine in task.get("machines") or []
  }
  machine_rows = []
  for code, capacity in sorted((scoped_fjspb.get("machines") or {}).items()):
    device = code_to_device.get(str(code), {})
    machine_rows.append(
        {
            "device_code": str(code),
            "device_name": device.get("deviceName"),
            "device_type_name": device.get("deviceTypeName"),
            "workstation_type_name": device.get("workstationTypeName"),
            "machine_capacity": int(capacity),
            "position_slot_count": int(position_counts.get(str(device.get("deviceName")), 0)),
            "used_by_scoped_tasks": str(code) in task_device_codes,
            "capacity_source": "structural_duplicate_node_instances_not_devicePosition_slot_count",
        }
    )

  cross_plate_pairs = _cross_plate_precedence_pairs(scoped_precedence, scoped_tasks)
  return {
      "source_counts": {
          "flow_node_count": len(flow_nodes),
          "flow_line_count": len(flow_lines),
          "project_all_node_count": len(all_nodes),
          "device_count": len(devices),
          "device_position_count": len(positions),
          "device_material_count": len(project.get("device_materials") or []),
      },
      "base_ir_counts_before_seed": {
          "task_count": len(base_tasks),
          "precedence_pair_count": len(base_fjspb.get("precedence_pairs") or []),
          "material_edge_count": len(base_fjspb.get("material_edges") or []),
          "hard_material_precedence_count": sum(1 for edge in base_fjspb.get("material_edges") or [] if isinstance(edge, dict) and edge.get("hard_precedence_candidate")),
          "machine_count": len(base_fjspb.get("machines") or {}),
      },
      "scoped_ir_counts_after_seed": {
          "job_count": len(scoped_fjspb.get("jobs") or []),
          "task_count": len(scoped_tasks),
          "precedence_pair_count": len(scoped_fjspb.get("precedence_pairs") or []),
          "material_edge_count": len(scoped_fjspb.get("material_edges") or []),
          "machine_count": len(scoped_fjspb.get("machines") or {}),
          "position_count": len(scoped_fjspb.get("positions") or []),
          "buffer_count": len(scoped_fjspb.get("buffers") or []),
          "robot_resource_count": len(scoped_fjspb.get("robot_resources") or []),
      },
      "seed_expansion_preservation": {
          "plate_instance_count": len(plate_instances) or 1,
          "base_selected_task_count": len(base_selected),
          "base_selected_precedence_pair_count": len(selected_base_precedence),
          "expected_mapped_precedence_pair_count": len(mapped_precedence) if plate_instances else len(selected_base_precedence),
          "actual_scoped_precedence_pair_count": len(scoped_precedence),
          "missing_mapped_precedence_pairs": precedence_missing[:30],
          "extra_cross_or_unmapped_precedence_pairs": precedence_extra[:30],
          "cross_plate_precedence_pair_count": len(cross_plate_pairs),
          "sample_cross_plate_precedence_pairs": cross_plate_pairs[:20],
          "status": "ok" if not precedence_missing and not precedence_extra and not cross_plate_pairs else "check_required",
      },
      "material_edge_preservation": material_preservation,
      "resource_boundary_summary": {
          "machine_capacity_policy": "machines are shared cumulative resources; devicePosition slot counts are reported separately as position/buffer capacity",
          "shared_resource_policy": "multi-plate expansion copies tasks/material edges per plate but does not copy machines, robot_resources, buffers, or positions",
          "device_transfer_time_policy": (scoped_fjspb.get("device_transfer_times") or {}).get("contract"),
          "machine_rows": machine_rows,
          "position_counts_by_device": dict(sorted(position_counts.items())),
      },
      "hard_vs_audit_boundary_names": {
          "constraint_hard_ready": [row.get("name") for row in (scoped_fjspb.get("constraint_realization_boundaries") or {}).get("hard_ready") or []],
          "constraint_audit_only": [row.get("name") for row in (scoped_fjspb.get("constraint_realization_boundaries") or {}).get("audit_only") or []],
          "constraint_blocked_missing_fields": [row.get("name") for row in (scoped_fjspb.get("constraint_realization_boundaries") or {}).get("blocked_missing_fields") or []],
          "command_hard_ready": [row.get("name") for row in (scoped_fjspb.get("command_realization_boundaries") or {}).get("hard_ready") or []],
          "command_blocked_missing_fields": [row.get("name") for row in (scoped_fjspb.get("command_realization_boundaries") or {}).get("blocked_missing_fields") or []],
      },
  }


def _tasks_by_id(fjspb: dict) -> dict[int, dict]:
  return {
      int(task["task_id"]): task
      for job in fjspb.get("jobs") or []
      for task in job.get("tasks") or []
      if task.get("task_id") is not None
  }


def _base_selected_task_ids(scoped_fjspb: dict, seed_instance: dict) -> set[int]:
  base_ids = {
      int(task.get("base_task_id"))
      for job in scoped_fjspb.get("jobs") or []
      for task in job.get("tasks") or []
      if task.get("base_task_id") is not None
  }
  if base_ids:
    return base_ids
  return {int(value) for value in seed_instance.get("selected_task_ids") or []}


def _mapped_pairs_by_plate(plate_instances: list[dict], base_pairs: set[tuple[int, int]]) -> set[tuple[int, int]]:
  if not plate_instances:
    return base_pairs
  mapped = set()
  for plate in plate_instances:
    task_id_map = {int(k): int(v) for k, v in (plate.get("task_id_map") or {}).items()}
    for src, dst in base_pairs:
      if src in task_id_map and dst in task_id_map:
        mapped.add((task_id_map[src], task_id_map[dst]))
  return mapped


def _material_preservation_report(
    plate_instances: list[dict],
    base_hard_material: list[dict],
    scoped_hard_material: list[dict],
) -> dict:
  if not plate_instances:
    return {
        "base_selected_hard_material_edge_count": len(base_hard_material),
        "expected_scoped_hard_material_edge_count": len(base_hard_material),
        "actual_scoped_hard_material_edge_count": len(scoped_hard_material),
        "missing_base_edge_ids_by_plate": {},
        "status": "ok" if len(base_hard_material) == len(scoped_hard_material) else "check_required",
    }
  base_edge_ids = {str(edge.get("edge_id")) for edge in base_hard_material if edge.get("edge_id")}
  by_plate = defaultdict(set)
  for edge in scoped_hard_material:
    plate_id = edge.get("plate_instance_id")
    base_edge_id = edge.get("base_edge_id")
    if plate_id and base_edge_id:
      by_plate[str(plate_id)].add(str(base_edge_id))
  missing = {
      str(plate.get("plate_instance_id")): sorted(base_edge_ids - by_plate.get(str(plate.get("plate_instance_id")), set()))
      for plate in plate_instances
      if base_edge_ids - by_plate.get(str(plate.get("plate_instance_id")), set())
  }
  return {
      "base_selected_hard_material_edge_count": len(base_hard_material),
      "expected_scoped_hard_material_edge_count": len(base_hard_material) * len(plate_instances),
      "actual_scoped_hard_material_edge_count": len(scoped_hard_material),
      "missing_base_edge_ids_by_plate": {key: values[:30] for key, values in missing.items()},
      "status": "ok" if not missing and len(scoped_hard_material) == len(base_hard_material) * len(plate_instances) else "check_required",
  }


def _cross_plate_precedence_pairs(scoped_precedence: set[tuple[int, int]], scoped_tasks: dict[int, dict]) -> list[list[int]]:
  rows = []
  for src, dst in sorted(scoped_precedence):
    src_plate = scoped_tasks.get(src, {}).get("plate_instance_id")
    dst_plate = scoped_tasks.get(dst, {}).get("plate_instance_id")
    if src_plate and dst_plate and src_plate != dst_plate:
      rows.append([src, dst])
  return rows


if __name__ == "__main__":
  main()
