"""V3 problem loading for smart-scheduling-system project 1160.

V3 keeps the v1 ``dataset["fjspb"]`` contract runnable by existing FUTS
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
import heapq
import json
import math
from pathlib import Path
import random
from typing import Any

from implementation.flow_1160_era.problem import (
    CACHE_DIR,
    DEFAULT_DATASET,
    fetch_project,
    flow_data_to_fjspb as flow_data_to_fjspb_v1,
)
from implementation.flow_1160_era_v3.command_ir import build_command_ir
from implementation.flow_1160_era_v3.isaac_motion import MotionTiming


@dataclass(frozen=True)
class Flow1160V3Problem:
  instance_name: str
  description: str
  dataset: dict
  prompt_dataset: dict
  optimum: int | None = None


@dataclass(frozen=True)
class BoundaryConfig:
  """Interface-level control for v3 realism boundary state."""

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
) -> Flow1160V3Problem:
  project, project_id = _load_project(dataset_path)
  boundary_config = BoundaryConfig(_normalize_boundary_profile(boundary_profile), int(boundary_seed))
  policy = HistoryPolicy(_normalize_history_policy(history_policy))
  fjspb = flow_data_to_fjspb(project, boundary_config=boundary_config, history_policy=policy)
  dataset = {"fjspb": fjspb}
  summary = _summarize_fjspb_v3(fjspb)
  description = (
      "Schedule smart-scheduling-system project %s with the flow_1160_v3 IR. "
      % project_id
      + "The primary executable contract remains dataset['fjspb'].jobs/tasks/"
      "machines/precedence_pairs/branch_priority_pairs, so v1 CP-SAT "
      "candidates remain valid. V3 adds material_edges, logistics_events, "
      "buffers, logistics_resources, duration_source annotations, and "
      "rolling_state metadata. Treat material/logistics/rolling metadata as "
      "explicit audit/modeling data: use it when adding safe reusable "
      "constraints, but do not invent optional branches or replay hidden "
      "historical schedules. Default history_policy=strict_cold_start hides "
      "runtime start/end result fields from candidate-visible planning IR."
  )
  return Flow1160V3Problem(
      instance_name="proj_%s_v3" % project_id,
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
  material_flow_groups = _material_flow_groups(material_edges)
  material_lineage_links = _material_lineage_links(material_edges)
  material_inventory_events = _material_inventory_events(material_edges)
  material_conservation_model = _material_conservation_model(material_edges, material_inventory_events)
  platform_realism_sources = _platform_realism_sources(project, fjspb)
  logistics_resources, buffers, logistics_events = _logistics_layer(project, fjspb, history_policy)
  rolling_state = _rolling_state(project, fjspb, history_policy)
  isaac_motion_timing = _isaac_motion_timing_metadata()
  device_transfer_times = _device_transfer_times(fjspb, isaac_motion_timing)
  command_base = {
      **fjspb,
      "material_edges": material_edges,
      "material_flow_groups": material_flow_groups,
      "material_lineage_links": material_lineage_links,
      "material_inventory_events": material_inventory_events,
      "material_conservation_model": material_conservation_model,
      "platform_realism_sources": platform_realism_sources,
      "logistics_resources": logistics_resources,
      "buffers": buffers,
      "logistics_events": logistics_events,
      "rolling_state": rolling_state,
      "isaac_motion_timing": isaac_motion_timing,
      "device_transfer_times": device_transfer_times,
  }
  command_ir = build_command_ir(project, command_base, history_policy_mode=history_policy.mode)
  fjspb.update(
      {
          "model_version": "flow_1160_era_v3",
          "history_policy": _history_policy_metadata(history_policy),
          "material_edges": material_edges,
          "material_flow_groups": material_flow_groups,
          "material_lineage_links": material_lineage_links,
          "material_inventory_events": material_inventory_events,
          "material_conservation_model": material_conservation_model,
          "platform_realism_sources": platform_realism_sources,
          "logistics_resources": logistics_resources,
          "buffers": buffers,
          "logistics_events": logistics_events,
          "rolling_state": rolling_state,
          "isaac_motion_timing": isaac_motion_timing,
          "device_transfer_times": device_transfer_times,
          **command_ir,
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
          "V3 material_edges normalize projectAllNodeList.materialData. "
          "preNodeId-derived task-to-task edges are hard precedence candidates; "
          "quantity/merge/split/plate occupancy are currently audit metadata "
          "until explicit platform stock/balance fields are exported.",
          "V3 material_lineage_links expose prePlateNums as a source plate "
          "label, not a numeric quantity. Do not use prePlateNums in arithmetic "
          "balance constraints.",
          "V3 logistics_events describe non-main-task transport/scan/load/"
          "stack actions. In strict_cold_start history_policy, historical "
          "runtime start/end spans are hidden and cannot be used as planning "
          "durations. Exclusive resources with explicit non-history durations "
          "should become NoOverlap; capacity resources/buffers Cumulative; "
          "inventory Reservoir in future scorer versions.",
          "V3 rolling_state records fixed-prefix fields without freezing the "
          "offline benchmark. Future rolling runs should set is_fixed and "
          "existing_machine_occupancy explicitly.",
          "V3 constraint_realization_boundaries is the source of truth for "
          "what may be hard-modeled. Its state is controlled by the boundary "
          "interface profile/seed, not by candidate code. blocked_missing_fields "
          "entries must stay non-hard until their required platform fields are present.",
          "V3 device_commands/positions/plate_states/robot_resources expose a "
          "conservative device-command IR. Only independently verified command "
          "durations, resources, and positions may become hard constraints; "
          "missing movement durations, stable plate identity, from/to positions, "
          "and online replan state stay in command_realization_boundaries.",
          "V3 platform_realism_sources exposes directly fetched deviceMaterial, "
          "materialSetting, barcodeSetting, devicePosition, apsLoadingTime, "
          "deviceRunning, and dispatch queue evidence. These rows are "
          "candidate-visible audit/modeling inputs, but stock identity and "
          "APS loading-time semantics remain non-hard until independently "
          "validated to avoid double-counting or false conservation.",
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


def _isaac_motion_timing_metadata() -> dict:
  timing = MotionTiming()
  minimum_transfer = int(timing.pick_seconds) + int(timing.place_seconds) + int(timing.drop_seconds) + int(timing.safety_gap_seconds)
  return {
      "pick_seconds": int(timing.pick_seconds),
      "move_seconds": int(timing.move_seconds),
      "near_rotate_seconds": 40,
      "far_move_base_seconds": 100,
      "far_move_seconds_per_meter": 15,
      "near_distance_threshold_m": 2.5,
      "place_seconds": int(timing.place_seconds),
      "drop_seconds": int(timing.drop_seconds),
      "safety_gap_seconds": int(timing.safety_gap_seconds),
      "transfer_seconds": int(timing.transfer_seconds),
      "min_transfer_seconds": minimum_transfer,
      "tightening_step_seconds": 60,
      "duration_source": "synthetic_conservative_planning_parameter",
      "gap_policy": "graph_distance_no_cap",
      "contract": (
          "Use device_transfer_times as the primary cold-start planning matrix "
          "for material_edges src_task_id -> dst_task_id transfers. Matrix "
          "values come from a graph shortest-path distance model over the "
          "synthetic device layout and are not capped by the global fallback "
          "transfer_seconds. transfer_seconds is only a fallback for missing "
          "machine pairs and is not derived from historical startTime/endTime."
      ),
  }


def _device_transfer_times(fjspb: dict, timing: dict) -> dict:
  machines = sorted(str(code) for code in (fjspb.get("machines") or {}).keys())
  positions = _synthetic_device_layout(machines)
  graph = _layout_distance_graph(positions)
  graph_distances = _all_pairs_shortest_paths(graph, positions)
  pick = int(timing.get("pick_seconds") or 0)
  place = int(timing.get("place_seconds") or 0)
  drop = int(timing.get("drop_seconds") or 0)
  safety = int(timing.get("safety_gap_seconds") or 0)
  near_rotate = int(timing.get("near_rotate_seconds") or 0)
  far_base = int(timing.get("far_move_base_seconds") or 0)
  per_meter = int(timing.get("far_move_seconds_per_meter") or 0)
  near_threshold = float(timing.get("near_distance_threshold_m") or 0.0)

  rows = []
  for src in machines:
    for dst in machines:
      sx, sy = positions.get(src, (0.0, 0.0))
      dx, dy = positions.get(dst, (0.0, 0.0))
      direct_distance = math.hypot(dx - sx, dy - sy)
      distance = graph_distances.get((src, dst), direct_distance)
      if src == dst:
        motion_class = "same_device_rotation"
        move_seconds = max(0, near_rotate // 2)
      elif distance <= near_threshold:
        motion_class = "near_rotate"
        move_seconds = near_rotate
      else:
        motion_class = "linear_move"
        move_seconds = far_base + int(math.ceil(distance * per_meter))
      transfer_seconds = pick + move_seconds + place + drop + safety
      rows.append(
          {
              "src_machine": src,
              "dst_machine": dst,
              "distance_m": round(distance, 3),
              "direct_distance_m": round(direct_distance, 3),
              "distance_model": "rectilinear_layout_graph_shortest_path_v1",
              "motion_class": motion_class,
              "move_seconds": int(move_seconds),
              "transfer_seconds": int(transfer_seconds),
              "duration_source": "synthetic_graph_distance_model_not_historical_runtime",
          }
      )
  return {
      "model": "rectilinear_layout_graph_shortest_path_v1",
      "contract": (
          "Use this matrix for material transfer gaps conditioned on selected "
          "source/destination machines. Distances are shortest paths on a "
          "rectilinear graph induced by the synthetic device layout, so they "
          "are graph-metric, symmetric, and not truncated by a global cap. "
          "Same/near devices use rotation/short motion; distant devices use "
          "linear move time. Values are synthetic cold-start planning "
          "parameters, not historical runtime replay."
      ),
      "positions": [
          {"machine": code, "x": positions[code][0], "y": positions[code][1]}
          for code in machines
      ],
      "graph": {
          "nodes": [
              {"id": _point_id(point), "x": point[0], "y": point[1]}
              for point in sorted(graph)
          ],
          "edge_count": sum(len(edges) for edges in graph.values()) // 2,
          "metric": "shortest_path_meters",
      },
      "rows": rows,
  }


def _layout_distance_graph(positions: dict[str, tuple[float, float]]) -> dict[tuple[float, float], list[tuple[tuple[float, float], float]]]:
  xs = sorted({float(x) for x, _y in positions.values()})
  ys = sorted({float(y) for _x, y in positions.values()})
  graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]] = {
      (x, y): [] for x in xs for y in ys
  }
  for y in ys:
    for a, b in zip(xs, xs[1:]):
      _add_undirected_edge(graph, (a, y), (b, y), abs(b - a))
  for x in xs:
    for a, b in zip(ys, ys[1:]):
      _add_undirected_edge(graph, (x, a), (x, b), abs(b - a))
  return graph


def _add_undirected_edge(
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
    a: tuple[float, float],
    b: tuple[float, float],
    weight: float,
) -> None:
  graph.setdefault(a, []).append((b, float(weight)))
  graph.setdefault(b, []).append((a, float(weight)))


def _all_pairs_shortest_paths(
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
    positions: dict[str, tuple[float, float]],
) -> dict[tuple[str, str], float]:
  distances: dict[tuple[str, str], float] = {}
  for src, point in positions.items():
    point_distances = _dijkstra(graph, point)
    for dst, dst_point in positions.items():
      distances[(src, dst)] = float(point_distances.get(dst_point, math.inf))
  return distances


def _dijkstra(
    graph: dict[tuple[float, float], list[tuple[tuple[float, float], float]]],
    start: tuple[float, float],
) -> dict[tuple[float, float], float]:
  distances = {start: 0.0}
  heap = [(0.0, start)]
  while heap:
    distance, node = heapq.heappop(heap)
    if distance != distances.get(node):
      continue
    for neighbor, weight in graph.get(node, []):
      candidate = distance + weight
      if candidate < distances.get(neighbor, math.inf):
        distances[neighbor] = candidate
        heapq.heappush(heap, (candidate, neighbor))
  return distances


def _point_id(point: tuple[float, float]) -> str:
  return "x%.3f:y%.3f" % (point[0], point[1])


def _synthetic_device_layout(machines: list[str]) -> dict[str, tuple[float, float]]:
  type_footprint = {
      "温控模块": (1.0, 1.0),
      "移液工作站": (1.6, 1.6),
      "培养箱": (2.0, 2.0),
      "挑单克隆仪": (1.4, 1.4),
      "酶标仪": (1.8, 1.4),
      "堆栈": (1.6, 1.6),
      "其它": (1.2, 1.2),
  }
  type_order = ["温控模块", "移液工作站", "培养箱", "挑单克隆仪", "酶标仪", "堆栈", "其它"]
  by_type: dict[str, list[str]] = defaultdict(list)
  for code in machines:
    by_type[_device_type_for_layout(code)].append(code)
  positions = {}
  col_x = -18.0
  for typ in type_order:
    rows = sorted(by_type.get(typ, []))
    if not rows:
      continue
    fw, fd = type_footprint[typ]
    for idx, code in enumerate(rows):
      positions[code] = (round(col_x + (idx % 2) * (fw + 0.5), 3), round(-7.0 + (idx // 2) * (fd + 0.5), 3))
    col_x += fw * 2 + 1.8
  return positions


def _device_type_for_layout(code: str) -> str:
  c = str(code).lower()
  if c in ("d-0007", "d-0038", "d-0039", "d-0040"):
    return "移液工作站"
  if c in ("d-0011", "d-0012", "d-0069"):
    return "培养箱"
  if c == "d-0015":
    return "挑单克隆仪"
  if c in ("d-0017", "d-0018"):
    return "酶标仪"
  if c == "d-0013":
    return "堆栈"
  if c in ("d-0001", "d-0002", "d-0003", "d-0004", "d-0005", "d-0006", "d-0036"):
    return "温控模块"
  return "其它"


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


def _material_conservation_model(edges: list[dict], inventory_events: list[dict]) -> dict:
  """Structured conservation boundary derived only from visible materialData.

  This model is intentionally narrower than full chemical/material mass balance.
  It gives candidates a machine-readable explanation of what is hard-ready and
  what remains audit-only because project 1160 lacks stable stock ids, explicit
  initial quantities, and confirmed merge/split consume rules.
  """
  field_counts = {
      "rows": len(edges),
      "rows_with_pre_node_id": sum(1 for edge in edges if edge.get("src_node_id") is not None),
      "rows_without_pre_node_id": sum(1 for edge in edges if edge.get("src_node_id") is None),
      "rows_with_task_to_task_mapping": sum(
          1 for edge in edges if edge.get("src_task_id") is not None and edge.get("dst_task_id") is not None
      ),
      "rows_with_positive_quantity": sum(1 for edge in edges if _positive_int(edge.get("quantity")) is not None),
      "rows_with_material_code": sum(1 for edge in edges if edge.get("material_code")),
      "rows_with_barcode_type": sum(1 for edge in edges if edge.get("barcode_type") is not None),
      "rows_with_plate_alias": sum(1 for edge in edges if edge.get("plate_alias")),
      "rows_with_pre_plate_label": sum(1 for edge in edges if edge.get("pre_plate_label")),
      "rows_with_plate_input_position": sum(
          1 for edge in edges if edge.get("plate_input_rack") is not None and edge.get("plate_input_level") is not None
      ),
  }
  initial_candidates = Counter()
  for edge in edges:
    if edge.get("src_node_id") is None:
      quantity = _positive_int(edge.get("quantity")) or 1
      initial_candidates[_material_inventory_key(edge)] += quantity
  group_audit = _material_group_quantity_audit(edges)
  return {
      "version": "material_conservation_model_v1",
      "source": "projectAllNodeList.materialData",
      "field_counts": field_counts,
      "inventory_event_count": len(inventory_events),
      "inventory_key_counts": dict(Counter(event.get("inventory_key") for event in inventory_events)),
      "transfer_mode_counts": dict(Counter(edge.get("transfer_mode") for edge in edges)),
      "plate_oper_type_counts": dict(Counter(str(edge.get("plate_oper_type")) for edge in edges)),
      "quantity_consume_rule_counts": dict(Counter(str(edge.get("quantity_consume_rule")) for edge in edges)),
      "initial_stock_candidates": [
          {
              "inventory_key": key,
              "quantity": quantity,
              "enforcement": "audit_only",
              "reason": "row has no preNodeId, but platform does not expose stable stock_item_id or initial position binding",
          }
          for key, quantity in sorted(initial_candidates.items())
      ],
      "hard_ready": [
          {
              "name": "edge_inventory_nonnegative",
              "event_source": "material_inventory_events",
              "required_fields": ["src_task_id", "dst_task_id", "quantity", "inventory_key"],
              "allowed_cp_sat": "AddReservoirConstraint(+quantity at source end, -quantity at destination start, min_level=0)",
              "scope": "task-to-task material edges only",
          }
      ],
      "audit_only": [
          {
              "name": "initial_stock_candidates",
              "reason": "external/input rows exist, but materialData does not bind them to stable stock ids and exact initial positions",
          },
          {
              "name": "merge_split_quantity_audit",
              "reason": "quantity rows expose edge quantities, but not total produced quantity, branch allocation rule, loss/copy/dilution policy",
              "sample_groups": group_audit[:12],
          },
          {
              "name": "plate_lineage_labels",
              "reason": "prePlateNums/plateAlias are labels for lineage diagnostics, not numeric balance terms",
          },
      ],
      "blocked_full_hard_constraints": [
          "full_merge_split_balance",
          "initial_material_stock_level",
          "position_in_out_inventory",
          "stable_plate_identity_no_overlap",
      ],
      "candidate_instruction": (
          "Hard-model material_inventory_events with AddReservoirConstraint. "
          "Use initial_stock_candidates, group audits, plate labels, plateOperType, "
          "pushType, and quantityConsumeRule as diagnostics unless platform exports "
          "stable stock_item_id, explicit initial quantity/position, and consume/copy/split rules."
      ),
  }


def _platform_realism_sources(project: dict, fjspb: dict) -> dict:
  """Summarize newly verified platform endpoints without over-hardening them."""
  device_materials = list(project.get("device_materials") or [])
  material_settings = list(project.get("material_settings") or [])
  barcode_settings = list(project.get("barcode_settings") or [])
  barcode_manage = list(project.get("barcode_manage") or [])
  positions = list(project.get("positions") or [])
  device_running = list(project.get("device_running") or [])
  dispatch_queue = list(project.get("dispatch_node_queue") or [])
  device_inner_settings = list(project.get("device_inner_settings") or [])
  well_global = list(project.get("well_global") or [])
  all_nodes = list(project.get("all_nodes") or [])

  step_to_task = _step_to_task(fjspb)
  aps_rows = []
  for row in all_nodes:
    node_id = row.get("nodeId")
    loading = _optional_number(row.get("apsLoadingTime"))
    unloading = _optional_number(row.get("apsUnloadingTime"))
    if loading is None and unloading is None:
      continue
    aps_rows.append(
        {
            "node_id": node_id,
            "task_id": step_to_task.get(int(node_id)) if node_id is not None and _is_int_like(node_id) else None,
            "node_name": row.get("nodeName"),
            "device_name": row.get("deviceName"),
            "aps_loading_time_raw": loading,
            "aps_unloading_time_raw": unloading,
            "unit_status": "unverified_platform_field",
            "enforcement": "audit_only_until_duration_semantics_verified",
            "reason": "may be setup/loading overhead or already included in task duration; do not double-count without validation",
        }
    )

  nonempty_plate_positions = [
      {
          "device_name": row.get("deviceName"),
          "device_full_name": row.get("deviceFullName"),
          "position_type": row.get("positionType"),
          "rack": row.get("rack"),
          "level": row.get("level"),
          "plate_barcode": row.get("plateBarcode"),
          "inner_or_out": row.get("innerOrOut"),
          "robot_interaction_flag": row.get("robotInteractionFlag"),
          "plate_input_time_present": bool(row.get("plateInputTime")),
          "enforcement": "audit_only_initial_position_candidate",
          "reason": "plateBarcode exists only for a subset and is not bound across every material edge as stable stock_item_id",
      }
      for row in positions
      if row.get("plateBarcode")
  ]
  transfer_pose_nonempty = sum(1 for row in positions if row.get("transferPoseList"))
  device_material_loads = [_device_material_load(row) for row in device_materials]
  material_catalog = [_material_catalog_row(row) for row in material_settings]
  barcode_catalog = [_barcode_catalog_row(row) for row in barcode_settings]

  return {
      "version": "platform_realism_sources_v1",
      "source": "smart_scheduling_platform_live_endpoints_or_cache",
      "endpoint_counts": {
          "device_materials": len(device_materials),
          "material_settings": len(material_settings),
          "barcode_settings": len(barcode_settings),
          "barcode_manage": len(barcode_manage),
          "positions": len(positions),
          "positions_with_plate_barcode": len(nonempty_plate_positions),
          "positions_with_transfer_pose_list": transfer_pose_nonempty,
          "device_running": len(device_running),
          "dispatch_node_queue": len(dispatch_queue),
          "device_inner_settings": len(device_inner_settings),
          "well_global": len(well_global),
          "all_nodes_with_aps_loading_fields": len(aps_rows),
      },
      "device_material_loads": device_material_loads,
      "device_material_counts_by_code": dict(Counter(row.get("material_code") for row in device_material_loads)),
      "material_catalog": material_catalog,
      "barcode_catalog": barcode_catalog,
      "barcode_manage_counts": {
          "rows": len(barcode_manage),
          "is_used_counts": dict(Counter(str(row.get("isUsed")) for row in barcode_manage)),
          "project_id_counts": dict(Counter(str(row.get("projectId")) for row in barcode_manage)),
          "source_counts": dict(Counter(str(row.get("source")) for row in barcode_manage)),
      },
      "aps_loading_time_candidates": {
          "rows": aps_rows,
          "loading_raw_counts": dict(Counter(str(row.get("aps_loading_time_raw")) for row in aps_rows)),
          "unloading_raw_counts": dict(Counter(str(row.get("aps_unloading_time_raw")) for row in aps_rows)),
          "enforcement": "audit_only_until_semantics_verified",
          "blocked_reason": "unit and inclusion relative to task duration are not yet validated",
      },
      "device_position_stock_candidates": {
          "rows": nonempty_plate_positions,
          "enforcement": "audit_only_initial_position_candidate",
          "blocked_reason": "partial plateBarcode coverage and no stable material-edge stock identity binding",
      },
      "device_running_status": {
          "rows": [
              {
                  "device_name": row.get("deviceName"),
                  "status": row.get("status"),
                  "run_duration": row.get("runDuration"),
                  "run_project_count": row.get("runProjectCount"),
                  "malfunction_count": row.get("malfunctionCount"),
                  "malfunction_duration": row.get("malfunctionDuration"),
              }
              for row in device_running
          ],
          "status_counts": dict(Counter(str(row.get("status")) for row in device_running)),
          "enforcement": "audit_only_operational_state",
      },
      "dispatch_node_queue": {
          "rows": dispatch_queue,
          "enforcement": "audit_only_online_state",
      },
      "ai_query_status": {
          "queried_at": "2026-07-01",
          "channel": "platform_ai_chat_agent7_short_questions",
          "result": "no_verifiable_field_semantics",
          "details": [
              "apsLoadingTime query searched AI sandbox files and requested extra data dictionary/sample",
              "deviceMaterial and plateBarcode queries did not access project 1160 cache and hit request-rate limits",
          ],
          "modeling_policy": "do not promote AI output to hard constraints without platform field evidence",
      },
      "self_filled_assumption_profiles": [
          {
              "name": "aps_loading_time_minutes_pre_task_device_setup",
              "status": "experimental_self_filled_candidate",
              "hard_ready_default": False,
              "confidence": "medium",
              "assumption": (
                  "Treat apsLoadingTime as minutes of independent pre-task loading/setup time. "
                  "Create a positive setup interval before the task, occupying the selected task "
                  "device and optionally StackRobotA when the task has material transfer predecessors."
              ),
              "evidence": [
                  "apsLoadingTime exists on all 221 all_nodes rows",
                  "values are small integers 0/1/2/3/4/6/7/9, matching minute-scale setup fields better than seconds",
                  "apsUnloadingTime is zero on all rows, so only loading has useful signal",
                  "field name is APS-specific planning metadata, not hidden historical start/end span",
              ],
              "risks": [
                  "may already be included in task duration",
                  "selected resource semantics are unconfirmed",
                  "multi-instance setup may be once per task or once per plate",
              ],
              "upgrade_rule": (
                  "Promote to hard_ready only under an explicit experimental profile or after platform "
                  "documentation confirms unit, independence from duration, resource usage, and multi-instance policy."
              ),
              "expected_makespan_effect": "nondecreasing if modeled as extra positive setup time",
          },
          {
              "name": "device_material_initial_load_by_material_code",
              "status": "experimental_self_filled_candidate",
              "hard_ready_default": False,
              "confidence": "low",
              "assumption": (
                  "Use deviceMaterial remainingCount/quantity as initial stock candidates grouped by "
                  "device_name and material_code."
              ),
              "evidence": [
                  "deviceMaterial/list returns 17 project rows with materialCode and remainingCount/quantity fields",
                  "overlaps with 11 material codes used by materialData",
              ],
              "risks": [
                  "barcode is null on observed rows",
                  "rack is often null",
                  "V0/V1/V4 materialData codes are absent from deviceMaterial",
                  "no stable stock_item_id or material-edge-to-stock binding",
              ],
              "upgrade_rule": "Do not promote to hard_ready until stable stock identity and initial position binding are exported.",
              "expected_makespan_effect": "usually none unless stock shortage constraints delay or reject schedules",
          },
          {
              "name": "device_position_plate_barcode_initial_occupancy",
              "status": "experimental_self_filled_candidate",
              "hard_ready_default": False,
              "confidence": "low",
              "assumption": "Use nonempty devicePosition.plateBarcode rows as initial plate occupancy candidates.",
              "evidence": [
                  "16 of 262 devicePosition rows have plateBarcode",
                  "rack/level/deviceName are present on these rows",
              ],
              "risks": [
                  "coverage is partial",
                  "plateBarcode is not carried through every materialData edge",
                  "transferPoseList is empty, so no platform path/pose duration is available",
              ],
              "upgrade_rule": "Do not promote to hard_ready until plate barcode is stable across material flow and from/to command positions are explicit.",
              "expected_makespan_effect": "none by default; may constrain buffer/position feasibility when fully modeled",
          },
      ],
      "hard_ready": [],
      "audit_only": [
          {
              "name": "device_material_loads",
              "reason": "direct initial load counts exist, but barcode/rack binding is incomplete for stable stock identity",
          },
          {
              "name": "aps_loading_time_candidates",
              "reason": "direct fields exist on all_nodes, but unit and whether task duration already includes them must be validated",
          },
          {
              "name": "material_and_barcode_catalogs",
              "reason": "catalog metadata improves naming/geometry audits but is not per-project stock flow identity",
          },
          {
              "name": "device_position_plate_barcodes",
              "reason": "partial initial occupancy evidence; no complete lineage binding across material_edges",
          },
          {
              "name": "device_running_status",
              "reason": "current operational health/state for audit or online scheduling, not offline cold-start replay",
          },
      ],
      "blocked_hard_constraints": [
          "initial_stock_by_stable_item",
          "aps_loading_time_added_to_task_duration",
          "robot_path_from_platform_pose",
          "online_dispatch_queue_freezing",
      ],
      "candidate_instruction": (
          "Use this structure as platform-backed realism evidence. Keep rows audit-only unless "
          "a hard_ready entry appears. Do not add apsLoadingTime to task duration until unit and "
          "double-count semantics are validated; do not turn deviceMaterial counts into stock "
          "constraints without stable stock_item_id and position binding."
      ),
  }


def _device_material_load(row: dict) -> dict:
  return {
      "device_name": row.get("deviceName"),
      "rack": row.get("rack"),
      "material_code": row.get("materialCode"),
      "count": row.get("count"),
      "start_well": row.get("startWell"),
      "remaining_count": row.get("remainingCount"),
      "quantity": row.get("quantity"),
      "volume": row.get("volume"),
      "type": row.get("type"),
      "put_type": row.get("putType"),
      "reserve": row.get("reserve"),
      "barcode": row.get("barcode"),
      "enforcement": "audit_only_initial_load_candidate",
      "reason": "project stock load evidence exists but stable stock_item_id/position binding is incomplete",
  }


def _material_catalog_row(row: dict) -> dict:
  return {
      "material_code": row.get("materialCode"),
      "material_name": row.get("materialName"),
      "plate_alias": row.get("plateAlias"),
      "quantity": row.get("quantity"),
      "volume": row.get("volume"),
      "height": row.get("height"),
      "open_lid_status": row.get("openLidStatus"),
      "need_fixed_adapter_transfer": row.get("needFixedAdapterTransfer"),
      "material_type_of_transfer": row.get("materialTypeOfTransfer"),
  }


def _barcode_catalog_row(row: dict) -> dict:
  return {
      "barcode_type": row.get("barcodeType"),
      "barcode_name": row.get("barcodeName"),
      "dict_value": row.get("dictValue"),
      "mark": row.get("mark"),
      "volume": row.get("volume"),
  }


def _optional_number(value: Any) -> int | float | None:
  if value in (None, ""):
    return None
  try:
    number = float(value)
  except Exception:
    return None
  return int(number) if number.is_integer() else number


def _is_int_like(value: Any) -> bool:
  try:
    int(value)
    return True
  except Exception:
    return False


def _material_group_quantity_audit(edges: list[dict]) -> list[dict]:
  rows = []
  by_src = defaultdict(list)
  by_dst = defaultdict(list)
  for edge in edges:
    if edge.get("src_node_id") is not None:
      by_src[edge["src_node_id"]].append(edge)
    by_dst[edge["dst_node_id"]].append(edge)
  for src, group in sorted(by_src.items()):
    if len(group) <= 1:
      continue
    quantities = [_positive_int(edge.get("quantity")) for edge in group]
    rows.append(
        {
            "kind": "split",
            "node_id": src,
            "edge_count": len(group),
            "known_quantity_sum": sum(q for q in quantities if q is not None),
            "unknown_quantity_count": sum(1 for q in quantities if q is None),
            "inventory_keys": sorted({_material_inventory_key(edge) for edge in group}),
            "enforcement": "audit_only",
        }
    )
  for dst, group in sorted(by_dst.items()):
    if len(group) <= 1:
      continue
    quantities = [_positive_int(edge.get("quantity")) for edge in group]
    rows.append(
        {
            "kind": "merge",
            "node_id": dst,
            "edge_count": len(group),
            "known_quantity_sum": sum(q for q in quantities if q is not None),
            "unknown_quantity_count": sum(1 for q in quantities if q is None),
            "inventory_keys": sorted({_material_inventory_key(edge) for edge in group}),
            "enforcement": "audit_only",
        }
    )
  return rows


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


def _summarize_fjspb_v3(fjspb: dict) -> dict:
  jobs = fjspb.get("jobs", [])
  tasks = [task for job in jobs for task in job.get("tasks", [])]
  material_edges = fjspb.get("material_edges", [])
  material_lineage_links = fjspb.get("material_lineage_links", [])
  material_inventory_events = fjspb.get("material_inventory_events", [])
  material_conservation_model = fjspb.get("material_conservation_model", {})
  platform_realism_sources = fjspb.get("platform_realism_sources", {})
  boundaries = fjspb.get("constraint_realization_boundaries", {})
  logistics_events = fjspb.get("logistics_events", [])
  device_commands = fjspb.get("device_commands", [])
  positions = fjspb.get("positions", [])
  plate_states = fjspb.get("plate_states", [])
  robot_resources = fjspb.get("robot_resources", [])
  command_boundaries = fjspb.get("command_realization_boundaries", {})
  return {
      "problem_type": "flow_proj_fjspb_v3",
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
      "material_conservation_model_version": material_conservation_model.get("version"),
      "material_conservation_field_counts": material_conservation_model.get("field_counts", {}),
      "material_conservation_blocked": material_conservation_model.get("blocked_full_hard_constraints", []),
      "platform_realism_sources_version": platform_realism_sources.get("version"),
      "platform_realism_endpoint_counts": platform_realism_sources.get("endpoint_counts", {}),
      "platform_realism_blocked_hard_constraints": platform_realism_sources.get("blocked_hard_constraints", []),
      "platform_realism_self_filled_assumption_profiles": [
          row.get("name") for row in (platform_realism_sources.get("self_filled_assumption_profiles") or [])
      ],
      "platform_realism_aps_loading_counts": (
          (platform_realism_sources.get("aps_loading_time_candidates") or {}).get("loading_raw_counts", {})
      ),
      "platform_realism_device_material_counts_by_code": (
          platform_realism_sources.get("device_material_counts_by_code", {})
      ),
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
      "device_command_count": len(device_commands),
      "device_command_kind_counts": dict(Counter(command.get("kind") for command in device_commands)),
      "command_duration_source_counts": dict(Counter(command.get("duration_source") for command in device_commands)),
      "position_count": len(positions),
      "position_kind_counts": dict(Counter(position.get("kind") for position in positions)),
      "plate_state_count": len(plate_states),
      "robot_resource_count": len(robot_resources),
      "command_boundary_counts": {
          "hard_ready": len(command_boundaries.get("hard_ready") or []),
          "audit_only": len(command_boundaries.get("audit_only") or []),
          "blocked_missing_fields": len(command_boundaries.get("blocked_missing_fields") or []),
          "required_hard_constraints": len((command_boundaries.get("state") or {}).get("required_hard_constraints") or []),
      },
      "sample_device_commands": device_commands[:8],
      "sample_positions": positions[:8],
      "sample_plate_states": plate_states[:8],
      "sample_robot_resources": robot_resources[:8],
      "sample_material_edges": material_edges[:8],
      "sample_material_lineage_links": material_lineage_links[:8],
      "sample_material_inventory_events": material_inventory_events[:8],
      "sample_material_conservation_initial_stock_candidates": (
          material_conservation_model.get("initial_stock_candidates") or []
      )[:8],
      "sample_platform_device_material_loads": (
          platform_realism_sources.get("device_material_loads") or []
      )[:8],
      "sample_platform_aps_loading_time_candidates": (
          (platform_realism_sources.get("aps_loading_time_candidates") or {}).get("rows") or []
      )[:8],
      "sample_platform_device_position_stock_candidates": (
          (platform_realism_sources.get("device_position_stock_candidates") or {}).get("rows") or []
      )[:8],
      "sample_logistics_events": logistics_events[:8],
      "sample_jobs": [{**job, "tasks": job.get("tasks", [])[:10]} for job in jobs[:1]],
  }
