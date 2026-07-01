"""CLI for monitoring flow_1160_era_v3 command schedules."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from implementation.flow_1160_era_v3.isaac_motion import MotionTiming, build_isaac_motion_events, first_motion_error
from implementation.flow_1160_era_v3.problem import DEFAULT_DATASET, load_problem
from implementation.flow_1160_era_v3.schedule_monitor import first_error, monitor_schedule


def _load_candidate(path: str):
  spec = importlib.util.spec_from_file_location("flow1160_v3_monitor_candidate", path)
  if spec is None or spec.loader is None:
    raise RuntimeError("cannot load candidate %s" % path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  if not hasattr(module, "solve"):
    raise RuntimeError("candidate %s does not define solve(dataset)" % path)
  return module.solve


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=DEFAULT_DATASET)
  parser.add_argument("--schedule-json", help="JSON file containing {'assignments': ..., 'command_assignments': ...}")
  parser.add_argument("--candidate", help="Python file defining solve(dataset); ignored when --schedule-json is set")
  parser.add_argument("--output-json", help="Optional path for the monitor report")
  parser.add_argument("--allow-conflicts", action="store_true", help="Exit 0 even when monitor finds conflicts/deadlocks")
  parser.add_argument("--pick-seconds", type=int, default=30)
  parser.add_argument("--move-seconds", type=int, default=300)
  parser.add_argument("--place-seconds", type=int, default=30)
  parser.add_argument("--drop-seconds", type=int, default=10)
  parser.add_argument("--safety-gap-seconds", type=int, default=10)
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

  problem = load_problem(
      args.dataset,
      boundary_profile=args.boundary_profile,
      boundary_seed=args.boundary_seed,
      history_policy=args.history_policy,
  )
  if args.schedule_json:
    schedule = json.loads(Path(args.schedule_json).read_text(encoding="utf-8"))
  elif args.candidate:
    schedule = _load_candidate(args.candidate)(problem.dataset)
  else:
    raise SystemExit("pass --schedule-json or --candidate")

  command_report = monitor_schedule(problem.dataset, schedule)
  timing = MotionTiming(
      pick_seconds=args.pick_seconds,
      move_seconds=args.move_seconds,
      place_seconds=args.place_seconds,
      drop_seconds=args.drop_seconds,
      safety_gap_seconds=args.safety_gap_seconds,
  )
  motion = build_isaac_motion_events(problem.dataset, schedule, timing=timing)
  report = {
      "ok": command_report["ok"] and motion["motion_monitor"]["ok"],
      "command_monitor": command_report,
      "motion_monitor": motion["motion_monitor"],
      "motion_timing": motion["timing"],
      "robot_action_count": len(motion["robot_actions"]),
      "plate_transfer_count": len(motion["plate_transfers"]),
  }
  payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
  if args.output_json:
    Path(args.output_json).write_text(payload + "\n", encoding="utf-8")
  print(payload)
  error = first_error(command_report) or first_motion_error(motion["motion_monitor"])
  if error:
    print("first_error=%s" % error, file=sys.stderr)
  if not report.get("ok") and not args.allow_conflicts:
    sys.exit(1)


if __name__ == "__main__":
  main()
