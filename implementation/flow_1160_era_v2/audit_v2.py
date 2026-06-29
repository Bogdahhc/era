"""Read-only audit for flow_1160_era_v2 IR additions."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from implementation.flow_1160_era_v2.problem import (
    BoundaryConfig,
    DEFAULT_DATASET,
    HistoryPolicy,
    flow_data_to_fjspb,
    fetch_project,
)


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
  tasks = [task for job in fjspb.get("jobs", []) for task in job.get("tasks", [])]
  material_edges = fjspb.get("material_edges", [])
  material_lineage_links = fjspb.get("material_lineage_links", [])
  material_inventory_events = fjspb.get("material_inventory_events", [])
  boundaries = fjspb.get("constraint_realization_boundaries", {})
  logistics_events = fjspb.get("logistics_events", [])
  buffers = fjspb.get("buffers", [])
  resources = fjspb.get("logistics_resources", [])

  print(
      "v2_counts",
      "tasks=", len(tasks),
      "material_edges=", len(material_edges),
      "hard_material_precedence_candidates=",
      sum(1 for edge in material_edges if edge.get("hard_precedence_candidate")),
      "material_inventory_events=", len(material_inventory_events),
      "material_lineage_links=", len(material_lineage_links),
      "logistics_events=", len(logistics_events),
      "buffers=", len(buffers),
      "resources=", len(resources),
  )
  print("duration_source_counts", dict(Counter(task.get("duration_source") for task in tasks)))
  print("history_policy", json.dumps(fjspb.get("history_policy", {}), ensure_ascii=False, sort_keys=True))
  print("task_run_status_counts", dict(Counter(task.get("run_status") for task in tasks)))
  print("material_transfer_mode_counts", dict(Counter(edge.get("transfer_mode") for edge in material_edges)))
  print("material_enforcement_counts", dict(Counter(edge.get("enforcement") for edge in material_edges)))
  print("material_pre_plate_label_count", sum(1 for edge in material_edges if edge.get("pre_plate_label")))
  print("material_quantity_consume_rule_counts", dict(Counter(str(edge.get("quantity_consume_rule")) for edge in material_edges)))
  print("material_plate_oper_type_counts", dict(Counter(str(edge.get("plate_oper_type")) for edge in material_edges)))
  print("material_inventory_key_counts", dict(Counter(event.get("inventory_key") for event in material_inventory_events)))
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
  print("sample_material_edges", json.dumps(material_edges[:10], ensure_ascii=False, indent=2))
  print("sample_material_lineage_links", json.dumps(material_lineage_links[:10], ensure_ascii=False, indent=2))
  print("sample_material_inventory_events", json.dumps(material_inventory_events[:10], ensure_ascii=False, indent=2))
  print("sample_logistics_events", json.dumps(logistics_events[:10], ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
