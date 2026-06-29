"""CLI for previewing seeded online insertion scenarios."""

from __future__ import annotations

import argparse
import json

from implementation.multi_bot_online_era.cli import (
    _parse_insert_times,
    _parse_insert_window_ratio,
)
from implementation.multi_bot_online_era.problem import load_problem
from implementation.multi_bot_online_era.scenario import (
    build_online_scenario,
    render_command_sender_script,
)


DEFAULT_4_EXPERIMENTS = (
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods/database_paper/4_experiments.sqlite"
)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=DEFAULT_4_EXPERIMENTS)
  parser.add_argument("--scenario-seed", type=int, default=0)
  parser.add_argument("--insertion-count", type=int, default=1)
  parser.add_argument("--inserted-jobs", type=int, default=2)
  parser.add_argument("--inserted-task-count", type=int, default=4)
  parser.add_argument(
      "--insert-window-ratio",
      type=_parse_insert_window_ratio,
      default=(0.10, 0.60),
      metavar="LOW,HIGH",
  )
  parser.add_argument(
      "--insert-times",
      type=_parse_insert_times,
      help="Comma-separated absolute insertion times. Overrides random timing.",
  )
  parser.add_argument(
      "--enforce-even-centrifuge-inserts",
      action="store_true",
      help="Resample inserted templates to keep centrifuge counts even.",
  )
  parser.add_argument("--full", action="store_true", help="Print full commands JSON.")
  parser.add_argument(
      "--emit-command-script",
      action="store_true",
      help="Print a seed-generated Python command sender script.",
  )
  args = parser.parse_args()

  problem = load_problem(args.dataset)
  scenario = build_online_scenario(
      problem.dataset,
      scenario_seed=args.scenario_seed,
      insertion_count=args.insertion_count,
      inserted_jobs=args.inserted_jobs,
      inserted_task_count=args.inserted_task_count,
      insert_window_ratio=args.insert_window_ratio,
      insert_times=args.insert_times,
      enforce_even_centrifuge_inserts=args.enforce_even_centrifuge_inserts,
  )
  if args.emit_command_script:
    print(render_command_sender_script(scenario))
    return
  payload = {
      "dataset": args.dataset,
      "metadata": scenario.metadata,
      "commands": scenario.commands if args.full else _summarize_commands(scenario.commands),
      "checks": [
          {
              "event_index": check.event_index,
              "request_id": check.request_id,
              "jobs": len(check.dataset.get("fjspb", {}).get("jobs", [])),
              "cur_ptr": check.dataset.get("fjspb", {}).get("cur_ptr"),
          }
          for check in scenario.checks
      ],
  }
  print(json.dumps(payload, ensure_ascii=False, indent=2))


def _summarize_commands(commands: list[dict]) -> list[dict]:
  summary = []
  for command in commands:
    row = {
        "type": command.get("type"),
        "request_id": command.get("request_id"),
    }
    if "now" in command:
      row["now"] = command["now"]
    if "insert_time" in command:
      row["insert_time"] = command["insert_time"]
    if "time" in command:
      row["time"] = command["time"]
    if "jobs" in command:
      row["jobs"] = len(command["jobs"])
      row["task_counts"] = [len(job.get("tasks", [])) for job in command["jobs"]]
    summary.append(row)
  return summary


if __name__ == "__main__":
  main()
