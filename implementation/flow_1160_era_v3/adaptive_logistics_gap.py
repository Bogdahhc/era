#!/usr/bin/env python3
"""Validate graph-distance logistics timing using motion-monitor feedback.

The planning matrix in ``fjspb["device_transfer_times"]`` is preserved as a
graph-distance model. The optional gap value is recorded as a validation setting
for reports/events, but it no longer caps or flattens pair-specific transfer
durations.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys

sys.path.insert(0, "/home/era")

from implementation.flow_1160_era_v3.isaac_motion import MotionTiming, build_isaac_motion_events
from implementation.flow_1160_era_v3.problem import load_problem


REF_CANDIDATE = Path("/home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py")


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  parser.add_argument("project_id", nargs="?", default="1160")
  parser.add_argument("--min-gap", type=int, default=None)
  parser.add_argument("--max-gap", type=int, default=None)
  parser.add_argument("--step", type=int, default=None)
  parser.add_argument("--mode", choices=("linear", "binary"), default="linear")
  parser.add_argument("--candidate", default=str(REF_CANDIDATE))
  parser.add_argument("--events-json", help="write best conflict-free event stream")
  parser.add_argument("--report-json", help="write adaptive gap search report")
  return parser.parse_args()


def main() -> None:
  args = parse_args()
  problem = load_problem(str(args.project_id))
  base_dataset = problem.dataset
  timing_meta = base_dataset["fjspb"].get("isaac_motion_timing") or {}
  max_gap = int(args.max_gap if args.max_gap is not None else timing_meta.get("transfer_seconds", 0))
  min_gap = int(args.min_gap if args.min_gap is not None else timing_meta.get("min_transfer_seconds", 0))
  step = max(1, int(args.step if args.step is not None else timing_meta.get("tightening_step_seconds", 60)))
  solver_module = _load_solver(Path(args.candidate))

  if args.mode == "binary":
    rows = _binary_search(base_dataset, solver_module, min_gap, max_gap)
  else:
    rows = _linear_search(base_dataset, solver_module, min_gap, max_gap, step)

  feasible_rows = [row for row in rows if row["solver_ok"] and row["motion_ok"]]
  best = min(feasible_rows, key=lambda row: (row["gap_seconds"], row["makespan_seconds"])) if feasible_rows else None
  report = {
      "project_id": str(args.project_id),
      "mode": args.mode,
      "min_gap": min_gap,
      "max_gap": max_gap,
      "step": step,
      "best_gap_seconds": None if best is None else best["gap_seconds"],
      "best_makespan_seconds": None if best is None else best["makespan_seconds"],
      "rows": rows,
  }
  print(json.dumps(report, ensure_ascii=False, indent=2))

  if args.report_json:
    _write_json(Path(args.report_json), report)
  if args.events_json and best is not None:
    dataset = _dataset_with_gap(base_dataset, int(best["gap_seconds"]))
    schedule = solver_module.solve(dataset)
    events = _events_from_schedule(str(args.project_id), dataset, schedule, int(best["gap_seconds"]))
    _write_json(Path(args.events_json), events)


def _load_solver(path: Path):
  spec = importlib.util.spec_from_file_location("adaptive_gap_candidate", str(path))
  module = importlib.util.module_from_spec(spec)
  assert spec.loader is not None
  spec.loader.exec_module(module)
  return module


def _linear_search(base_dataset: dict, solver_module, min_gap: int, max_gap: int, step: int) -> list[dict]:
  rows = []
  gap = max_gap
  while gap >= min_gap:
    rows.append(_evaluate_gap(base_dataset, solver_module, gap))
    gap -= step
  if rows[-1]["gap_seconds"] != min_gap:
    rows.append(_evaluate_gap(base_dataset, solver_module, min_gap))
  return rows


def _binary_search(base_dataset: dict, solver_module, min_gap: int, max_gap: int) -> list[dict]:
  rows = []
  lo = min_gap
  hi = max_gap
  best = None
  seen = set()
  while lo <= hi:
    gap = (lo + hi) // 2
    if gap in seen:
      break
    seen.add(gap)
    row = _evaluate_gap(base_dataset, solver_module, gap)
    rows.append(row)
    if row["solver_ok"] and row["motion_ok"]:
      best = gap
      hi = gap - 1
    else:
      lo = gap + 1
  if best is not None and best not in seen:
    rows.append(_evaluate_gap(base_dataset, solver_module, best))
  return sorted(rows, key=lambda row: row["gap_seconds"], reverse=True)


def _evaluate_gap(base_dataset: dict, solver_module, gap_seconds: int) -> dict:
  dataset = _dataset_with_gap(base_dataset, gap_seconds)
  schedule = solver_module.solve(dataset)
  assignments = schedule.get("assignments") if isinstance(schedule, dict) else None
  solver_ok = bool(assignments)
  if not solver_ok:
    return {
        "gap_seconds": int(gap_seconds),
        "solver_ok": False,
        "motion_ok": False,
        "makespan_seconds": None,
        "conflict_count": None,
        "deadlock_count": None,
        "first_error": "solver returned no assignments",
  }
  motion = build_isaac_motion_events(dataset, schedule, timing=_timing_for_gap(dataset))
  monitor = motion["motion_monitor"]
  makespan = max(int(row["end"]) for row in assignments)
  return {
      "gap_seconds": int(gap_seconds),
      "solver_ok": True,
      "motion_ok": bool(monitor["ok"]),
      "makespan_seconds": int(makespan),
      "conflict_count": int(monitor["conflict_count"]),
      "deadlock_count": int(monitor["deadlock_count"]),
      "first_error": _first_error(monitor),
  }


def _dataset_with_gap(base_dataset: dict, gap_seconds: int) -> dict:
  dataset = copy.deepcopy(base_dataset)
  timing = dataset["fjspb"].setdefault("isaac_motion_timing", {})
  if "_adaptive_original_transfer_seconds" not in timing:
    timing["_adaptive_original_transfer_seconds"] = int(timing.get("transfer_seconds") or gap_seconds)
  timing["transfer_seconds"] = int(timing["_adaptive_original_transfer_seconds"])
  timing["gap_policy"] = "adaptive_validate_graph_distance"
  timing["adaptive_validation_gap_seconds"] = int(gap_seconds)
  matrix = dataset["fjspb"].get("device_transfer_times") or {}
  pick = int(timing.get("pick_seconds") or 0)
  place = int(timing.get("place_seconds") or 0)
  drop = int(timing.get("drop_seconds") or 0)
  safety = int(timing.get("safety_gap_seconds") or 0)
  fixed_segments = pick + place + drop + safety
  for row in matrix.get("rows") or []:
    if not isinstance(row, dict):
      continue
    original = int(row.get("transfer_seconds") or gap_seconds)
    row["transfer_seconds"] = max(fixed_segments, original)
    row["move_seconds"] = max(0, int(row["transfer_seconds"]) - fixed_segments)
    row["adaptive_validation_gap_seconds"] = int(gap_seconds)
    row["adaptive_policy"] = "preserve_graph_distance_no_cap"
  return dataset


def _timing_for_gap(dataset: dict) -> MotionTiming:
  timing = dataset["fjspb"].get("isaac_motion_timing") or {}
  transfer_seconds = int(timing.get("transfer_seconds") or 0)
  pick = int(timing.get("pick_seconds") or 0)
  place = int(timing.get("place_seconds") or 0)
  drop = int(timing.get("drop_seconds") or 0)
  safety = int(timing.get("safety_gap_seconds") or 0)
  move = max(0, transfer_seconds - pick - place - drop - safety)
  return MotionTiming(
      pick_seconds=pick,
      move_seconds=move,
      place_seconds=place,
      drop_seconds=drop,
      safety_gap_seconds=safety,
  )


def _events_from_schedule(project_id: str, dataset: dict, schedule: dict, gap_seconds: int) -> dict:
  fjspb = dataset["fjspb"]
  assignments = schedule.get("assignments") or []
  task_by_id = {int(t["task_id"]): t for job in fjspb["jobs"] for t in job["tasks"]}
  asgn_by_tid = {int(row["task_id"]): row for row in assignments}
  device_actions = [
      {
          "task_id": int(row["task_id"]),
          "name": task_by_id.get(int(row["task_id"]), {}).get("name"),
          "device": row.get("machine"),
          "start": int(row["start"]),
          "end": int(row["end"]),
          "duration": int(task_by_id.get(int(row["task_id"]), {}).get("duration", 0)),
          "required_capacity": int(task_by_id.get(int(row["task_id"]), {}).get("required_capacity", 1)),
      }
      for row in assignments
  ]
  plate_moves = []
  for edge in fjspb.get("material_edges") or []:
    src_id = edge.get("src_task_id")
    dst_id = edge.get("dst_task_id")
    if src_id is None or dst_id is None:
      continue
    src = asgn_by_tid.get(int(src_id))
    dst = asgn_by_tid.get(int(dst_id))
    if not src or not dst:
      continue
    plate_moves.append(
        {
            "edge_id": edge.get("edge_id"),
            "plate": edge.get("barcode_name") or edge.get("material_name") or "plate",
            "material_code": edge.get("material_code"),
            "quantity": edge.get("quantity"),
            "from_device": src.get("machine"),
            "to_device": dst.get("machine"),
            "ready_time": int(src["end"]),
            "need_by": int(dst["start"]),
        }
    )
  logistics = []
  for event in fjspb.get("logistics_events") or []:
    succ = event.get("successor_task_ids") or []
    t0 = None
    for task_id in succ:
      row = asgn_by_tid.get(int(task_id))
      if row:
        t0 = int(row["start"])
        break
    logistics.append(
        {
            "id": event.get("id"),
            "node_name": event.get("node_name"),
            "kind": event.get("kind"),
            "resources": event.get("resources"),
            "buffer_ids": event.get("buffer_ids"),
            "duration": int(event.get("duration") or 0),
            "time": t0,
            "successor_task_ids": succ,
        }
    )
  motion = build_isaac_motion_events(dataset, schedule, timing=_timing_for_gap(dataset))
  makespan = max((int(row["end"]) for row in assignments), default=0)
  devices = [{"code": code, "capacity": cap} for code, cap in fjspb.get("machines", {}).items()]
  buffers = [
      {"id": row.get("id"), "device": row.get("device_name"), "capacity": row.get("capacity"), "type": row.get("type")}
      for row in fjspb.get("buffers", [])
  ]
  return {
      "project_id": project_id,
      "adaptive_gap_seconds": int(gap_seconds),
      "timeline_meta": {
          "makespan_seconds": int(makespan),
          "makespan_hours": round(makespan / 3600, 2),
          "device_count": len(devices),
          "buffer_count": len(buffers),
          "action_count": len(device_actions),
          "plate_move_count": len(plate_moves),
          "logistics_event_count": len(logistics),
          "robot_action_count": len(motion["robot_actions"]),
          "motion_ok": motion["motion_monitor"]["ok"],
          "motion_conflict_count": motion["motion_monitor"]["conflict_count"],
          "motion_deadlock_count": motion["motion_monitor"]["deadlock_count"],
      },
      "devices": devices,
      "buffers": buffers,
      "device_actions": sorted(device_actions, key=lambda row: row["start"]),
      "plate_moves": sorted(plate_moves, key=lambda row: row["ready_time"]),
      "logistics_events": logistics,
      "robot_actions": motion["robot_actions"],
      "plate_transfers": motion["plate_transfers"],
      "motion_timing": motion["timing"],
      "motion_monitor": motion["motion_monitor"],
  }


def _first_error(monitor: dict) -> str | None:
  for key in ("conflicts", "deadlocks"):
    rows = monitor.get(key) or []
    if rows:
      row = rows[0]
      return "%s: %s" % (row.get("type", key), row.get("message", row))
  return None


def _write_json(path: Path, payload: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  with path.open("w", encoding="utf-8") as fh:
    json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")


if __name__ == "__main__":
  main()
