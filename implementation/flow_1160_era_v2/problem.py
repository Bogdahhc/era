"""V2 problem loading for smart-scheduling-system project 1160.

V2 keeps the v1 ``dataset["fjspb"]`` contract runnable by existing FUTS
candidate code, then adds three explicit modeling layers:

* ``material_edges``: normalized plate/material transfer records from
  projectAllNodeList.materialData.
* ``logistics_events`` / ``buffers`` / ``logistics_resources``: lightweight
  transport and storage metadata for non-main-task logistics nodes.
* ``rolling_state`` and task annotations: fields needed for future
  fixed-prefix / rolling scheduling without forcing offline historical rows to
  be fixed in the current benchmark.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
import copy
import json
from pathlib import Path
import random
from typing import Any

from implementation.flow_1160_era.problem import (
    CACHE_DIR,
    DEFAULT_DATASET,
    fetch_project,
    flow_data_to_fjspb as flow_data_to_fjspb_v1,
)


@dataclass(frozen=True)
class Flow1160V2Problem:
  instance_name: str
  description: str
  dataset: dict
  prompt_dataset: dict
  optimum: int | None = None


@dataclass(frozen=True)
class BoundaryConfig:
  """Interface-level control for v2 realism boundary state."""

  profile: str = "conservative"
  seed: int = 1160


@dataclass(frozen=True)
class HistoryPolicy:
  """Controls whether historical runtime result fields enter the public IR."""

  mode: str = "strict_cold_start"


RUN_STATUS_LABELS = {
    0: "PENDING",
    1: "RUNNING",
    2: "DONE",
}

LOGISTICS_KEYWORDS = {
    "scan": ("扫码", "扫描", "条码"),
    "load": ("上料", "进板", "进培养箱", "回培养箱"),
    "unload": ("下料", "出板", "退板"),
    "stack_in": ("入栈", "回栈"),
    "stack_out": ("退栈", "出栈"),
    "transport": ("转运", "搬运", "转移"),
}


BOUNDARY_PROFILES = {"conservative", "seeded_audit", "seeded_experimental"}
HISTORY_POLICIES = {"strict_cold_start", "historical_replay"}


def load_problem(
    dataset_path: str = DEFAULT_DATASET,
    *,
    boundary_profile: str = "conservative",
    boundary_seed: int = 1160,
    history_policy: str = "strict_cold_start",
) -> Flow1160V2Problem:
  project, project_id = _load_project(dataset_path)
  boundary_config = BoundaryConfig(_normalize_boundary_profile(boundary_profile), int(boundary_seed))
  policy = HistoryPolicy(_normalize_history_policy(history_policy))
  fjspb = flow_data_to_fjspb(project, boundary_config=boundary_config, history_policy=policy)
  dataset = {"fjspb": fjspb}
  summary = _summarize_fjspb_v2(fjspb)
  description = (
      "Schedule smart-scheduling-system project %s with the flow_1160_v2 IR. "
      % project_id
      + "The primary executable contract remains dataset['fjspb'].jobs/tasks/"
      "machines/precedence_pairs/branch_priority_pairs, so v1 CP-SAT "
      "candidates remain valid. V2 adds material_edges, logistics_events, "
      "buffers, logistics_resources, duration_source annotations, and "
      "rolling_state metadata. Treat material/logistics/rolling metadata as "
      "explicit audit/modeling data: use it when adding safe reusable "
      "constraints, but do not invent optional branches or replay hidden "
      "historical schedules. Default history_policy=strict_cold_start hides "
      "runtime start/end result fields from candidate-visible planning IR."
  )
  return Flow1160V2Problem(
      instance_name="proj_%s_v2" % project_id,
      description=description,
      dataset=dataset,
      prompt_dataset=copy.deepcopy(summary),
  )


def _normalize_boundary_profile(profile: str) -> str:
  value = str(profile or "conservative").strip()
  if value not in BOUNDARY_PROFILES:
    raise ValueError("unknown boundary_profile %r, expected one of %s" % (value, sorted(BOUNDARY_PROFILES)))
  return value


def _normalize_history_policy(policy: str) -> str:
  value = str(policy or "strict_cold_start").strip()
  if value not in HISTORY_POLICIES:
    raise ValueError("unknown history_policy %r, expected one of %s" % (value, sorted(HISTORY_POLICIES)))
  return value


def flow_data_to_fjspb(
    project: dict,
    boundary_config: BoundaryConfig | None = None,
    history_policy: HistoryPolicy | None = None,
) -> dict:
  boundary_config = boundary_config or BoundaryConfig()
  history_policy = history_policy or HistoryPolicy()
  v1_project = _project_for_v1(project, history_policy)
  fjspb = flow_data_to_fjspb_v1(v1_project)
  if history_policy.mode == "strict_cold_start":
    _apply_structural_machine_capacity(project, fjspb)
    _sanitize_no_history_fjspb(fjspb)
  _annotate_tasks(project, fjspb, history_policy)
  material_edges = _material_edges(project, fjspb)
  material_inventory_events = _material_inventory_events(material_edges)
  logistics_resources, buffers, logistics_events = _logistics_layer(project, fjspb, history_policy)
  rolling_state = _rolling_state(project, fjspb, history_policy)
  fjspb.update(
      {
          "model_version": "flow_1160_era_v2",
          "history_policy": _history_policy_metadata(history_policy),
          "material_edges": material_edges,
          "material_flow_groups": _material_flow_groups(material_edges),
          "material_lineage_links": _material_lineage_links(material_edges),
          "material_inventory_events": material_inventory_events,
          "logistics_resources": logistics_resources,
          "buffers": buffers,
          "logistics_events": logistics_events,
          "rolling_state": rolling_state,
          "constraint_realization_boundaries": _constraint_realization_boundaries(
              material_edges,
              material_inventory_events,
              logistics_events,
              buffers,
              rolling_state,
              boundary_config,
          ),
      }
  )
  fjspb.setdefault("constraint_contract", []).extend(
      [
          "V2 material_edges normalize projectAllNodeList.materialData. "
          "preNodeId-derived task-to-task edges are hard precedence candidates; "
          "quantity/merge/split/plate occupancy are currently audit metadata "
          "until explicit platform stock/balance fields are exported.",
          "V2 material_lineage_links expose prePlateNums as a source plate "
          "label, not a numeric quantity. Do not use prePlateNums in arithmetic "
          "balance constraints.",
          "V2 logistics_events describe non-main-task transport/scan/load/"
          "stack actions. In strict_cold_start history_policy, historical "
          "runtime start/end spans are hidden and cannot be used as planning "
          "durations. Exclusive resources with explicit non-history durations "
          "should become NoOverlap; capacity resources/buffers Cumulative; "
          "inventory Reservoir in future scorer versions.",
          "V2 rolling_state records fixed-prefix fields without freezing the "
          "offline benchmark. Future rolling runs should set is_fixed and "
          "existing_machine_occupancy explicitly.",
          "V2 constraint_realization_boundaries is the source of truth for "
          "what may be hard-modeled. Its state is controlled by the boundary "
          "interface profile/seed, not by candidate code. blocked_missing_fields "
          "entries must stay non-hard until their required platform fields are present.",
      ]
  )
  return fjspb


def _project_for_v1(project: dict, history_policy: HistoryPolicy) -> dict:
  if history_policy.mode != "strict_cold_start":
    return project
  sanitized = copy.deepcopy(project)
  for row in sanitized.get("all_nodes", []) or []:
    row.pop("startTime", None)
    row.pop("endTime", None)
  return sanitized


def _apply_structural_machine_capacity(project: dict, fjspb: dict) -> None:
  """Use non-timestamp structure to restore machine capacity in no-history mode.

  The v1 adapter used historical overlap of startTime/endTime to infer device
  concurrency. strict_cold_start removes those timestamps before v1 conversion,
  so we recover a conservative planning capacity from duplicate node instances:
  if a planned node has N material/sample instances assigned to a device, that
  device must support at least N simultaneous slots for this process shape.
  """
  node_instance = Counter(
      row.get("nodeId")
      for row in project.get("all_nodes", []) or []
      if row.get("nodeId") is not None
  )
  capacity_by_device_name = defaultdict(lambda: 1)
  for row in project.get("all_nodes", []) or []:
    node_id = row.get("nodeId")
    device_name = row.get("deviceName")
    if node_id is None or not device_name:
      continue
    capacity_by_device_name[device_name] = max(
        capacity_by_device_name[device_name],
        int(node_instance.get(node_id) or 1),
    )

  code_to_name = {
      dev.get("deviceCode"): dev.get("deviceName")
      for dev in project.get("devices", []) or []
      if dev.get("deviceCode")
  }
  for code in list(fjspb.get("machines", {})):
    fjspb["machines"][code] = max(1, int(capacity_by_device_name[code_to_name.get(code)] or 1))


def _sanitize_no_history_fjspb(fjspb: dict) -> None:
  for group in fjspb.get("branch_groups", []) or []:
    for branch in group.get("branches", []) or []:
      if "has_runtime_task_successor" in branch:
        branch["has_runtime_task_successor"] = None
    if "active_task_bearing_branch_count" in group:
      group["active_task_bearing_branch_count"] = None


def _load_project(dataset_path: str) -> tuple[dict, str]:
  path = Path(dataset_path)
  if path.exists():
    project = json.loads(path.read_text(encoding="utf-8"))
    return project, str(project.get("project_id", path.stem))
  project_id = str(dataset_path)
  cache_file = CACHE_DIR / ("%s.json" % project_id)
  if cache_file.exists():
    return json.loads(cache_file.read_text(encoding="utf-8")), project_id
  project = fetch_project(project_id)
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  cache_file.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
  return project, project_id


def _parse_time(value: Any):
  try:
    return datetime.fromisoformat(str(value).replace("Z", ""))
  except Exception:
    return None


def _json_list(value: Any) -> list:
  if isinstance(value, list):
    return value
  if not value:
    return []
  if isinstance(value, str):
    try:
      parsed = json.loads(value)
      return parsed if isinstance(parsed, list) else []
    except Exception:
      return []
  return []


def _step_to_task(fjspb: dict) -> dict[int, int]:
  result = {}
  for job in fjspb.get("jobs", []):
    for task in job.get("tasks", []):
      if task.get("step_id") is not None:
        result[int(task["step_id"])] = int(task["task_id"])
  return result


def _rows_by_node(project: dict) -> dict[int, list[dict]]:
  rows = defaultdict(list)
  for row in project.get("all_nodes", []) or []:
    if row.get("nodeId") is not None:
      rows[int(row["nodeId"])].append(row)
  return rows


def _runtime_span_by_node(project: dict) -> dict[int, int]:
  spans = {}
  for row in project.get("all_nodes", []) or []:
    node_id = row.get("nodeId")
    start = _parse_time(row.get("startTime"))
    end = _parse_time(row.get("endTime"))
    if node_id is None or not (start and end):
      continue
    span = max(0, int(round((end - start).total_seconds())))
    if span:
      spans[int(node_id)] = max(spans.get(int(node_id), 0), span)
  return spans


def _history_policy_metadata(policy: HistoryPolicy) -> dict:
  strict = policy.mode == "strict_cold_start"
  return {
      "mode": policy.mode,
      "candidate_visible_history": not strict,
      "runtime_start_end_visible": not strict,
      "runtime_span_as_duration": not strict,
      "fixed_fields_visible_only_when_is_fixed": True,
      "contract": (
          "strict_cold_start hides platform runtime result fields such as "
          "startTime/endTime from candidate-visible planning IR. They may be "
          "used only in historical_replay/audit mode, matching the "
          "multi_bot_era no-incumbent interface principle."
      ),
  }


def _annotate_tasks(project: dict, fjspb: dict, history_policy: HistoryPolicy) -> None:
  rows_by_node = _rows_by_node(project)
  span_by_node = _runtime_span_by_node(project)
  allow_history = history_policy.mode == "historical_replay"
  for job in fjspb.get("jobs", []):
    for task in job.get("tasks", []):
      step_id = task.get("step_id")
      rows = rows_by_node.get(int(step_id), []) if step_id is not None else []
      raw_durations = [row.get("duration") for row in rows]
      if raw_durations and all(v in (None, "", 0, 0.0) for v in raw_durations):
        if allow_history and int(step_id) in span_by_node:
          source = "span_fallback"
        else:
          source = "missing_default_no_history"
      elif raw_durations:
        source = "planned"
      else:
        source = "missing_default"
      statuses = Counter(_run_status_label(row.get("runStatus")) for row in rows) if allow_history else Counter()
      actual_starts = [row.get("startTime") for row in rows if row.get("startTime")] if allow_history else []
      actual_ends = [row.get("endTime") for row in rows if row.get("endTime")] if allow_history else []
      devices = [row.get("deviceName") for row in rows if row.get("deviceName")] if allow_history else []
      task.update(
          {
              "duration_source": source,
              "raw_duration_values": sorted({str(v) for v in raw_durations if v not in (None, "")}),
              "run_status": statuses.most_common(1)[0][0] if statuses else "PENDING",
              "actual_start": min(actual_starts) if actual_starts else None,
              "actual_end": max(actual_ends) if actual_ends else None,
              "observed_machine_name": Counter(devices).most_common(1)[0][0] if devices else None,
              "lock_reason": None,
          }
      )


def _run_status_label(value: Any) -> str:
  try:
    return RUN_STATUS_LABELS.get(int(value), "UNKNOWN")
  except Exception:
    return "UNKNOWN"


def _material_edges(project: dict, fjspb: dict) -> list[dict]:
  step_to_task = _step_to_task(fjspb)
  raw_edges = []
  for row in project.get("all_nodes", []) or []:
    dst_node = row.get("nodeId")
    if dst_node is None:
      continue
    for mat_idx, material in enumerate(_json_list(row.get("materialData"))):
      data_rows = material.get("data") or []
      if not isinstance(data_rows, list):
        continue
      for data_idx, item in enumerate(data_rows):
        if not isinstance(item, dict):
          continue
        src_node = item.get("preNodeId")
        raw_edges.append(
            {
                "src_node_id": int(src_node) if src_node is not None else None,
                "dst_node_id": int(dst_node),
                "src_task_id": step_to_task.get(int(src_node)) if src_node is not None else None,
                "dst_task_id": step_to_task.get(int(dst_node)),
                "material_name": material.get("materialName"),
                "material_code": material.get("materialCode"),
                "barcode_name": material.get("barcodeName"),
                "barcode_type": material.get("barcodeType"),
                "material_label": material.get("materialLabel"),
                "quantity": item.get("quantity"),
                "quantity_consume_rule": item.get("quantityConsumeRule"),
                "quantity_unit": item.get("quantityUnit") or "unit",
                "plate_name": item.get("plateNum"),
                "plate_alias": item.get("plateAlias"),
                "pre_plate_label": item.get("prePlateNums"),
                "plate_oper_type": item.get("plateOperType"),
                "discard_by_self": item.get("discardBySelf"),
                "plate_input_rack": item.get("plateInputRack"),
                "plate_input_level": item.get("plateInputLevel"),
                "push_type": material.get("pushType"),
                "raw_type": material.get("type"),
                "raw_order": item.get("order"),
                "raw_material_index": mat_idx,
                "raw_data_index": data_idx,
            }
        )
  src_counts = Counter(edge["src_node_id"] for edge in raw_edges if edge["src_node_id"] is not None)
  dst_counts = Counter(edge["dst_node_id"] for edge in raw_edges)
  result = []
  for idx, edge in enumerate(raw_edges, 1):
    src = edge["src_node_id"]
    dst = edge["dst_node_id"]
    if src is None:
      mode = "produce"
    elif dst_counts[dst] > 1:
      mode = "merge"
    elif src_counts[src] > 1:
      mode = "split"
    else:
      mode = "same_plate"
    hard_candidate = edge["src_task_id"] is not None and edge["dst_task_id"] is not None
    result.append(
        {
            "edge_id": "m_%04d" % idx,
            **edge,
            "transfer_mode": mode,
            "hard_precedence_candidate": hard_candidate,
            "enforcement": "audit_hard_candidate" if hard_candidate else "audit_only",
            "metadata": {"source": "projectAllNodeList.materialData"},
        }
    )
  return result


def _material_flow_groups(edges: list[dict]) -> dict:
  by_dst = defaultdict(list)
  by_src = defaultdict(list)
  for edge in edges:
    if edge.get("src_node_id") is not None:
      by_src[edge["src_node_id"]].append(edge["edge_id"])
    by_dst[edge["dst_node_id"]].append(edge["edge_id"])
  return {
      "merge_groups": [
          {"dst_node_id": dst, "edge_ids": ids}
          for dst, ids in sorted(by_dst.items())
          if len(ids) > 1
      ],
      "split_groups": [
          {"src_node_id": src, "edge_ids": ids}
          for src, ids in sorted(by_src.items())
          if len(ids) > 1
      ],
  }


def _material_lineage_links(edges: list[dict]) -> list[dict]:
  """Plate label lineage hints from prePlateNums.

  Platform AI short-question confirmation and project 1160 samples indicate
  ``prePlateNums`` is a source plate label such as ``质粒板A1`` rather than a
  numeric list. Keep it as lineage/audit metadata; arithmetic balance still
  comes only from explicit quantity fields.
  """
  result = []
  for edge in edges:
    pre_label = _clean_label(edge.get("pre_plate_label"))
    dst_label = _clean_label(edge.get("plate_alias")) or _clean_label(edge.get("plate_name"))
    if not (pre_label or dst_label):
      continue
    result.append(
        {
            "id": "lin_%s" % edge["edge_id"],
            "edge_id": edge["edge_id"],
            "src_task_id": edge.get("src_task_id"),
            "dst_task_id": edge.get("dst_task_id"),
            "source_plate_label": pre_label,
            "destination_plate_label": dst_label,
            "plate_oper_type": edge.get("plate_oper_type"),
            "quantity": edge.get("quantity"),
            "quantity_consume_rule": edge.get("quantity_consume_rule"),
            "enforcement": "lineage_audit_only",
        }
    )
  return result


def _clean_label(value: Any) -> str | None:
  if value is None:
    return None
  text = str(value).strip()
  return text or None


def _material_inventory_events(edges: list[dict]) -> list[dict]:
  """Conservative stock-flow events for material edges with explicit quantity.

  The platform material rows reliably expose source node, destination node, and
  quantity for many plate transfers. For rows that map to both a source task and
  a destination task, we can enforce a real temporal inventory relation: the
  source task adds quantity at its end, and the destination task consumes that
  quantity at its start. This is intentionally narrower than full merge/split
  conservation because the raw rows do not always expose the total produced
  amount at a branching source.
  """
  result = []
  for edge in edges:
    src_task_id = edge.get("src_task_id")
    dst_task_id = edge.get("dst_task_id")
    quantity = _positive_int(edge.get("quantity"))
    if src_task_id is None or dst_task_id is None or quantity is None:
      continue
    result.append(
        {
            "id": "inv_%s" % edge["edge_id"],
            "edge_id": edge["edge_id"],
            "inventory_key": _material_inventory_key(edge),
            "src_task_id": int(src_task_id),
            "dst_task_id": int(dst_task_id),
            "quantity": quantity,
            "quantity_unit": edge.get("quantity_unit") or "unit",
            "material_code": edge.get("material_code"),
            "barcode_type": edge.get("barcode_type"),
            "plate_alias": edge.get("plate_alias"),
            "transfer_mode": edge.get("transfer_mode"),
            "enforcement": "reservoir_nonnegative_candidate",
        }
    )
  return result


def _positive_int(value: Any) -> int | None:
  try:
    number = int(float(value))
  except Exception:
    return None
  return number if number > 0 else None


def _material_inventory_key(edge: dict) -> str:
  parts = [
      edge.get("material_code") or edge.get("material_name") or "unknown_material",
      edge.get("barcode_type") or edge.get("barcode_name") or "unknown_barcode",
      edge.get("quantity_unit") or "unit",
  ]
  return "|".join(str(part) for part in parts)


def _constraint_realization_boundaries(
    material_edges: list[dict],
    material_inventory_events: list[dict],
    logistics_events: list[dict],
    buffers: list[dict],
    rolling_state: dict,
    boundary_config: BoundaryConfig,
) -> dict:
  """Executable boundary for what is allowed to become a hard constraint.

  The boundary is generated through an interface profile and seed. This keeps
  semantic policy decoupled from raw data extraction and from candidate code.
  Conservative mode is deterministic and production-safe. Seeded modes are
  reproducible experiment states and still do not promote missing-field rows to
  hard constraints.
  """
  hard_material_edges = [edge for edge in material_edges if edge.get("hard_precedence_candidate")]
  hard_logistics = [
      event
      for event in logistics_events
      if event.get("enforcement") == "audit_no_overlap_candidate"
      and event.get("duration")
      and event.get("resources")
  ]
  quantity_rule_counts = Counter(str(edge.get("quantity_consume_rule")) for edge in material_edges)
  plate_oper_counts = Counter(str(edge.get("plate_oper_type")) for edge in material_edges)
  hard_ready = [
      {
          "name": "task_and_material_precedence",
          "count": len(hard_material_edges),
          "required_fields": ["src_task_id", "dst_task_id", "hard_precedence_candidate"],
          "allowed_cp_sat": ["Add(start[dst] >= end[src])"],
          "evidence": "materialData.preNodeId maps source node to destination node task ids",
      },
      {
          "name": "edge_inventory_nonnegative",
          "count": len(material_inventory_events),
          "required_fields": ["src_task_id", "dst_task_id", "quantity", "inventory_key"],
          "allowed_cp_sat": ["AddReservoirConstraint"],
          "evidence": "positive explicit quantity on a task-to-task material edge",
      },
      {
          "name": "logistics_resource_no_overlap",
          "count": len(hard_logistics),
          "required_fields": ["duration", "resources", "predecessor_task_ids", "successor_task_ids"],
          "allowed_cp_sat": ["NewIntervalVar", "AddNoOverlap", "AddMaxEquality"],
          "evidence": "non-task logistics node has observed span and inferred exclusive resource",
      },
      {
          "name": "buffer_capacity",
          "count": len(buffers),
          "required_fields": ["buffer.id", "buffer.capacity", "logistics_event.buffer_ids"],
          "allowed_cp_sat": ["AddCumulative"],
          "evidence": "devicePosition count gives capacity by deviceName",
      },
      {
          "name": "rolling_existing_occupancy",
          "count": len(rolling_state.get("existing_machine_occupancy") or []),
          "required_fields": ["machine", "start", "end", "required_capacity"],
          "allowed_cp_sat": ["fixed IntervalVar in machine cumulative calendar"],
          "evidence": "explicit rolling occupancy rows only; offline benchmark currently has none",
      },
  ]
  audit_only = [
      {
          "name": "plate_lineage_labels",
          "source_fields": ["prePlateNums", "plateAlias", "plateNum"],
          "reason": "prePlateNums is a label such as 质粒板A1, not a numeric quantity",
          "allowed_use": "retain lineage context, grouping, and diagnostics",
          "forbidden_use": "arithmetic sum conservation",
      },
      {
          "name": "quantity_consume_rule_enum",
          "observed_counts": dict(quantity_rule_counts),
          "reason": "only value 1 observed on 36 rows and platform AI returned uncertain",
          "allowed_use": "report/audit only",
          "forbidden_use": "derive all/partial/copy/dilute semantics",
      },
      {
          "name": "plate_oper_type_enum",
          "observed_counts": dict(plate_oper_counts),
          "reason": "values 1/2 lack confirmed enum mapping and appear in mixed contexts",
          "allowed_use": "report/audit only",
          "forbidden_use": "derive in/out/transfer/copy direction",
      },
  ]
  blocked_missing_fields = [
      {
          "name": "full_merge_split_balance",
          "current_evidence": ["material_flow_groups", "quantity", "preNodeId"],
          "missing_fields": [
              "flow_role",
              "consume_rule",
              "source_total_quantity",
              "branch_allocated_quantity",
              "loss_or_dilution_policy",
          ],
          "upgrade_rule": "Only hard-model when every merge/split group has explicit input/output quantity roles and loss/copy policy.",
      },
      {
          "name": "initial_material_stock",
          "current_evidence": ["devicePosition.plateBarcode", "plateInputRack", "plateInputLevel"],
          "missing_fields": [
              "stock_item_id",
              "material_code/barcode_type to plate_barcode binding",
              "initial_quantity",
              "initial_position_id",
          ],
          "upgrade_rule": "Only set reservoir initial levels when stock identity and quantity are explicit.",
      },
      {
          "name": "position_in_out_inventory",
          "current_evidence": ["logistics_events", "buffer_ids", "nodeName text"],
          "missing_fields": [
              "direction",
              "from_position_id",
              "to_position_id",
              "stock_item_id",
              "position occupancy start/end",
          ],
          "upgrade_rule": "Only model buffer stock changes when movement direction and positions are explicit.",
      },
      {
          "name": "plate_identity_no_overlap",
          "current_evidence": ["plateAlias", "plateNum", "prePlateNums"],
          "missing_fields": ["stable stock_item_id or plate_barcode carried across all edges"],
          "upgrade_rule": "Only add plate-level NoOverlap when physical plate identity is stable across source and destination rows.",
      },
  ]
  state = _boundary_state(hard_ready, audit_only, blocked_missing_fields, boundary_config)
  return {
      "interface": {
          "profile": boundary_config.profile,
          "seed": boundary_config.seed,
          "allowed_profiles": sorted(BOUNDARY_PROFILES),
          "contract": (
              "Candidate code reads state.required_hard_constraints for mandatory hard modeling. "
              "Seeded experimental rows are reproducible exploration state, not permission to "
              "hard-code missing-field semantics."
          ),
      },
      "policy": "hard constraints require explicit platform fields; inferred enum/text semantics stay audit-only",
      "state": state,
      "hard_ready": hard_ready,
      "audit_only": audit_only,
      "blocked_missing_fields": blocked_missing_fields,
  }


def _boundary_state(
    hard_ready: list[dict],
    audit_only: list[dict],
    blocked_missing_fields: list[dict],
    config: BoundaryConfig,
) -> dict:
  rng = random.Random(int(config.seed))
  required_hard = [_state_row(row, "required_hard", True, "explicit_fields") for row in hard_ready]
  audit_state = [_state_row(row, "audit_enabled", False, "audit_only") for row in audit_only]
  blocked_state = [_state_row(row, "blocked_missing_fields", False, "missing_platform_fields") for row in blocked_missing_fields]
  experimental = []

  if config.profile in {"seeded_audit", "seeded_experimental"}:
    for row in audit_state:
      row["sample_weight"] = round(rng.random(), 6)
      row["sampled_for_feedback"] = row["sample_weight"] >= 0.35
  if config.profile == "seeded_experimental":
    for row in blocked_missing_fields:
      weight = rng.random()
      experimental.append(
          {
              "name": row.get("name"),
              "status": "experimental_interface_only",
              "enabled": weight >= 0.5,
              "hard_constraint": False,
              "sample_weight": round(weight, 6),
              "source_status": "blocked_missing_fields",
              "reason": "seeded interface state for prompt exploration; required fields are still missing",
          }
      )

  return {
      "required_hard_constraints": required_hard,
      "audit_controls": audit_state,
      "blocked_controls": blocked_state,
      "experimental_controls": experimental,
  }


def _state_row(row: dict, status: str, hard_constraint: bool, reason: str) -> dict:
  return {
      "name": row.get("name"),
      "status": status,
      "enabled": True,
      "hard_constraint": bool(hard_constraint),
      "reason": reason,
  }


def _logistics_layer(
    project: dict,
    fjspb: dict,
    history_policy: HistoryPolicy,
) -> tuple[list[dict], list[dict], list[dict]]:
  resources = {}
  buffers = _buffers_from_positions(project)
  events = _logistics_events(project, fjspb, resources, history_policy)
  return sorted(resources.values(), key=lambda row: row["id"]), buffers, events


def _buffers_from_positions(project: dict) -> list[dict]:
  counts = Counter(p.get("deviceName") for p in project.get("positions", []) or [] if p.get("deviceName"))
  buffers = []
  for device_name, capacity in sorted(counts.items()):
    kind = "stack" if "Stack" in device_name or "堆栈" in device_name else "device_buffer"
    buffers.append(
        {
            "id": "buffer:%s" % device_name,
            "device_name": device_name,
            "capacity": int(capacity),
            "type": kind,
            "policy": "unknown",
            "initial_occupancy": None,
            "source": "devicePosition",
        }
    )
  return buffers


def _logistics_events(
    project: dict,
    fjspb: dict,
    resources: dict,
    history_policy: HistoryPolicy,
) -> list[dict]:
  flow = project.get("flow_data", {}) or {}
  nodes = flow.get("nodeList", []) or []
  lines = flow.get("lineList", []) or []
  task_steps = set(_step_to_task(fjspb))
  step_to_task = _step_to_task(fjspb)
  node_by_flow_id = {node.get("id"): node for node in nodes}
  step_to_flow_id = {node.get("nodeId"): node.get("id") for node in nodes if node.get("nodeId") is not None}
  adj, rev = _flow_adj(lines)
  allow_history = history_policy.mode == "historical_replay"
  span_by_node = _runtime_span_by_node(project) if allow_history else {}
  rows_by_node = _rows_by_node(project)
  events = []
  for node in nodes:
    node_id = node.get("nodeId")
    if node_id is None or int(node_id) in task_steps:
      continue
    kind = _logistics_kind(node)
    if kind == "logic":
      continue
    historical_span = int(span_by_node.get(int(node_id), 0))
    duration = historical_span if allow_history else 0
    if duration:
      duration_source = "span"
    elif allow_history:
      duration_source = "missing_default_zero"
    else:
      duration_source = "missing_planning_duration_no_history"
    resource_ids = _resource_ids_for_event(
        kind,
        rows_by_node.get(int(node_id), []),
        node,
        allow_history=allow_history,
    )
    buffer_ids = _buffer_ids_for_resources(resource_ids)
    for resource_id, resource_type in resource_ids:
      resources.setdefault(
          resource_id,
          {"id": resource_id, "type": resource_type, "capacity": 1, "source": "inferred"},
      )
    flow_id = step_to_flow_id.get(int(node_id))
    predecessor_steps = _nearest_task_steps(flow_id, rev, node_by_flow_id, task_steps) if flow_id else []
    successor_steps = _nearest_task_steps(flow_id, adj, node_by_flow_id, task_steps) if flow_id else []
    events.append(
        {
            "id": "log_%s" % node_id,
            "node_id": int(node_id),
            "node_name": node.get("nodeName") or node.get("name"),
            "kind": kind,
            "duration": duration,
            "duration_source": duration_source,
            "historical_span_hidden": (not allow_history and _runtime_span_exists(project, int(node_id))),
            "planning_duration_required": not allow_history,
            "resources": [rid for rid, _typ in resource_ids],
            "buffer_ids": buffer_ids,
            "predecessor_step_ids": predecessor_steps,
            "successor_step_ids": successor_steps,
            "predecessor_task_ids": [step_to_task[step] for step in predecessor_steps if step in step_to_task],
            "successor_task_ids": [step_to_task[step] for step in successor_steps if step in step_to_task],
            "enforcement": "audit_no_overlap_candidate" if resource_ids and duration else "precedence_only",
        }
    )
  return sorted(events, key=lambda row: row["node_id"])


def _runtime_span_exists(project: dict, node_id: int) -> bool:
  for row in project.get("all_nodes", []) or []:
    if row.get("nodeId") is None or int(row["nodeId"]) != int(node_id):
      continue
    if _parse_time(row.get("startTime")) and _parse_time(row.get("endTime")):
      return True
  return False


def _flow_adj(lines: list[dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
  adj = defaultdict(list)
  rev = defaultdict(list)
  for line in lines:
    src, dst = line.get("from"), line.get("to")
    if src and dst:
      adj[src].append(dst)
      rev[dst].append(src)
  return adj, rev


def _nearest_task_steps(start_flow_id: str, graph: dict, node_by_flow_id: dict, task_steps: set[int]) -> list[int]:
  found = set()
  seen = set()
  queue = deque(graph.get(start_flow_id, []))
  while queue:
    flow_id = queue.popleft()
    if flow_id in seen:
      continue
    seen.add(flow_id)
    node = node_by_flow_id.get(flow_id, {})
    node_id = node.get("nodeId")
    if node_id is not None and int(node_id) in task_steps:
      found.add(int(node_id))
      continue
    queue.extend(graph.get(flow_id, []))
  return sorted(found)


def _logistics_kind(node: dict) -> str:
  name = str(node.get("nodeName") or node.get("name") or "")
  ws = node.get("workstationTypeName")
  if ws == "堆栈":
    if any(word in name for word in LOGISTICS_KEYWORDS["stack_out"]):
      return "stack_out"
    if any(word in name for word in LOGISTICS_KEYWORDS["stack_in"]):
      return "stack_in"
    return "stack"
  for kind, words in LOGISTICS_KEYWORDS.items():
    if any(word in name for word in words):
      return kind
  if str(node.get("nodeType")) in {"1", "3", "4"}:
    return "logic"
  return "precedence_marker"


def _resource_ids_for_event(
    kind: str,
    rows: list[dict],
    node: dict,
    *,
    allow_history: bool,
) -> list[tuple[str, str]]:
  device_names = sorted({row.get("deviceName") for row in rows if row.get("deviceName")}) if allow_history else []
  if not device_names and node.get("workstationTypeName") == "堆栈":
    device_names = ["StackRobotA"]
  if kind in {"stack", "stack_in", "stack_out"}:
    return [("stacker:%s" % name, "stacker") for name in device_names]
  if kind == "scan":
    return [("scanner:%s" % (device_names[0] if device_names else "generic"), "scanner")]
  if kind in {"load", "unload"}:
    return [("port:%s" % name, "port") for name in device_names] or [("loader:generic", "loader")]
  if kind == "transport":
    return [("transport:%s" % name, "transport") for name in device_names] or [("transport:generic", "transport")]
  return []


def _buffer_ids_for_resources(resource_ids: list[tuple[str, str]]) -> list[str]:
  buffer_ids = []
  for resource_id, _resource_type in resource_ids:
    if ":" not in resource_id:
      continue
    device_name = resource_id.split(":", 1)[1]
    if device_name and device_name != "generic":
      buffer_ids.append("buffer:%s" % device_name)
  return sorted(set(buffer_ids))


def _rolling_state(project: dict, fjspb: dict, history_policy: HistoryPolicy) -> dict:
  rows = project.get("all_nodes", []) or []
  status_counts = (
      Counter(_run_status_label(row.get("runStatus")) for row in rows)
      if history_policy.mode == "historical_replay"
      else Counter({"HIDDEN_BY_STRICT_COLD_START": len(rows)})
  )
  return {
      "mode": "offline_reoptimize",
      "history_policy": history_policy.mode,
      "cur_ptr": fjspb.get("cur_ptr", 0),
      "rolling_time_now": None,
      "run_status_counts": dict(status_counts),
      "existing_machine_occupancy": [],
      "fixed_policy": (
          "Offline benchmark keeps tasks unfixed. Future rolling runs should "
          "set is_fixed/fixed_start/fixed_end/scheduled_machine and populate "
          "existing_machine_occupancy for DONE/RUNNING work."
      ),
  }


def _summarize_fjspb_v2(fjspb: dict) -> dict:
  jobs = fjspb.get("jobs", [])
  tasks = [task for job in jobs for task in job.get("tasks", [])]
  material_edges = fjspb.get("material_edges", [])
  material_lineage_links = fjspb.get("material_lineage_links", [])
  material_inventory_events = fjspb.get("material_inventory_events", [])
  boundaries = fjspb.get("constraint_realization_boundaries", {})
  logistics_events = fjspb.get("logistics_events", [])
  return {
      "problem_type": "flow_proj_fjspb_v2",
      "model_version": fjspb.get("model_version"),
      "job_count": len(jobs),
      "task_count": len(tasks),
      "machine_count": len(fjspb.get("machines", {})),
      "precedence_pair_count": len(fjspb.get("precedence_pairs", []) or []),
      "branch_group_count": len(fjspb.get("branch_groups", []) or []),
      "branch_priority_pair_count": len(fjspb.get("branch_priority_pairs", []) or []),
      "material_edge_count": len(material_edges),
      "material_hard_precedence_candidate_count": sum(
          1 for edge in material_edges if edge.get("hard_precedence_candidate")
      ),
      "material_inventory_event_count": len(material_inventory_events),
      "material_inventory_key_counts": dict(Counter(event.get("inventory_key") for event in material_inventory_events)),
      "material_lineage_link_count": len(material_lineage_links),
      "material_pre_plate_label_count": sum(1 for edge in material_edges if edge.get("pre_plate_label")),
      "material_quantity_consume_rule_counts": dict(Counter(str(edge.get("quantity_consume_rule")) for edge in material_edges)),
      "material_plate_oper_type_counts": dict(Counter(str(edge.get("plate_oper_type")) for edge in material_edges)),
      "material_transfer_mode_counts": dict(Counter(edge.get("transfer_mode") for edge in material_edges)),
      "constraint_boundary_counts": {
          "hard_ready": len(boundaries.get("hard_ready") or []),
          "audit_only": len(boundaries.get("audit_only") or []),
          "blocked_missing_fields": len(boundaries.get("blocked_missing_fields") or []),
          "required_hard_constraints": len((boundaries.get("state") or {}).get("required_hard_constraints") or []),
          "experimental_controls": len((boundaries.get("state") or {}).get("experimental_controls") or []),
      },
      "constraint_boundary_interface": boundaries.get("interface", {}),
      "blocked_constraint_names": [
          row.get("name") for row in (boundaries.get("blocked_missing_fields") or []) if isinstance(row, dict)
      ],
      "logistics_event_count": len(logistics_events),
      "logistics_kind_counts": dict(Counter(event.get("kind") for event in logistics_events)),
      "buffer_count": len(fjspb.get("buffers", []) or []),
      "resource_count": len(fjspb.get("logistics_resources", []) or []),
      "duration_source_counts": dict(Counter(task.get("duration_source") for task in tasks)),
      "rolling_state": fjspb.get("rolling_state", {}),
      "sample_material_edges": material_edges[:8],
      "sample_material_lineage_links": material_lineage_links[:8],
      "sample_material_inventory_events": material_inventory_events[:8],
      "sample_logistics_events": logistics_events[:8],
      "sample_jobs": [{**job, "tasks": job.get("tasks", [])[:10]} for job in jobs[:1]],
  }
