"""CLI for running ERA/FUTS on multi-bot online scheduling JSON or SQLite datasets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from implementation.job_shop_era.logger import ExperimentLogger
from implementation.multi_bot_online_era.mutator import MultiBotOnlineMutator, RepeatMutator
from implementation.multi_bot_online_era.plot import (
    plot_breakthrough,
    plot_tree_branches,
    plot_tree_branches_3d,
)
from implementation.multi_bot_online_era.problem import DEFAULT_DATASET, load_problem
from implementation.multi_bot_online_era.seed import baseline_candidate_code


def _parse_insert_window_ratio(value: str) -> tuple[float, float]:
  parts = [part.strip() for part in value.split(",")]
  if len(parts) != 2:
    raise argparse.ArgumentTypeError("expected LOW,HIGH, for example 0.10,0.60")
  try:
    low, high = float(parts[0]), float(parts[1])
  except ValueError as exc:
    raise argparse.ArgumentTypeError("window ratios must be floats") from exc
  if low < 0 or high < 0 or low > high:
    raise argparse.ArgumentTypeError("window must satisfy 0 <= LOW <= HIGH")
  return low, high


def _parse_insert_times(value: str) -> list[int]:
  try:
    times = [int(part.strip()) for part in value.split(",") if part.strip()]
  except ValueError as exc:
    raise argparse.ArgumentTypeError("insert times must be comma-separated integers") from exc
  if not times:
    raise argparse.ArgumentTypeError("expected at least one insertion time")
  if len(set(times)) != len(times):
    raise argparse.ArgumentTypeError("insert times must be unique")
  if any(time < 0 for time in times):
    raise argparse.ArgumentTypeError("insert times must be non-negative")
  return sorted(times)


def _build_mutator(no_llm: bool):
  root_code = baseline_candidate_code()
  if no_llm:
    return RepeatMutator(root_code)

  from implementation.llm import OpenAILLM, load_openai_env

  load_openai_env()
  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
    raise SystemExit("Set OPENAI_API_KEY, or pass --no-llm.")
  return MultiBotOnlineMutator(
      OpenAILLM(
          api_key=api_key,
          model_name=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
          base_url=os.environ.get("OPENAI_BASE_URL"),
          wire_api=os.environ.get("OPENAI_WIRE_API", "responses"),
      )
  )


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", default=DEFAULT_DATASET)
  parser.add_argument("--mode", choices=["single", "futs"], default="futs")
  parser.add_argument("--iterations", type=int, default=20)
  parser.add_argument("--timeout-seconds", type=int, default=30)
  parser.add_argument("--experiment-name")
  parser.add_argument("--no-llm", action="store_true")
  parser.add_argument("--c-puct", type=float, default=1.0)
  parser.add_argument(
      "--scenario-seed",
      type=int,
      default=0,
      help="Seed for reproducible random insertion time and inserted job templates.",
  )
  parser.add_argument(
      "--insertion-count",
      type=int,
      default=1,
      help="Number of rolling insertion events in one online scenario.",
  )
  parser.add_argument(
      "--inserted-jobs",
      type=int,
      default=2,
      help="Number of small jobs inserted into the 4_experiments-style background.",
  )
  parser.add_argument(
      "--inserted-task-count",
      type=int,
      default=4,
      help="Maximum number of tasks copied into each inserted small job.",
  )
  parser.add_argument(
      "--insert-window-ratio",
      type=_parse_insert_window_ratio,
      default=(0.10, 0.60),
      metavar="LOW,HIGH",
      help="Random insertion time window as ratios of a horizon hint.",
  )
  parser.add_argument(
      "--insert-times",
      type=_parse_insert_times,
      help=(
          "Comma-separated absolute insertion times. Overrides random "
          "--scenario-seed/--insert-window-ratio timing while keeping seeded "
          "inserted job templates."
      ),
  )
  parser.add_argument(
      "--enforce-even-centrifuge-inserts",
      action="store_true",
      help=(
          "Resample inserted job templates so every checkpoint keeps centrifuge "
          "task counts even by machine and duration."
      ),
  )
  parser.add_argument(
      "--initial-code",
      help="Optional Python candidate file to use as the FUTS root solution.",
  )
  args = parser.parse_args()

  problem = load_problem(args.dataset)
  logger = ExperimentLogger(Path("experiments"), args.experiment_name)
  mutator = _build_mutator(args.no_llm)
  initial_code = (
      Path(args.initial_code).read_text(encoding="utf-8")
      if args.initial_code
      else None
  )

  if args.mode == "single":
    from implementation.multi_bot_online_era.search import run_single_generation

    best_solution, best_score = run_single_generation(
        problem,
        mutator,
        logger,
        initial_code=initial_code,
        timeout_seconds=args.timeout_seconds,
        scenario_seed=args.scenario_seed,
        insertion_count=args.insertion_count,
        inserted_jobs=args.inserted_jobs,
        inserted_task_count=args.inserted_task_count,
        insert_window_ratio=args.insert_window_ratio,
        insert_times=args.insert_times,
        enforce_even_centrifuge_inserts=args.enforce_even_centrifuge_inserts,
    )
  else:
    from implementation.multi_bot_online_era.search import run_futs

    best_solution, best_score = run_futs(
        problem,
        mutator,
        args.iterations,
        logger,
        initial_code=initial_code,
        timeout_seconds=args.timeout_seconds,
        c_puct=args.c_puct,
        scenario_seed=args.scenario_seed,
        insertion_count=args.insertion_count,
        inserted_jobs=args.inserted_jobs,
        inserted_task_count=args.inserted_task_count,
        insert_window_ratio=args.insert_window_ratio,
        insert_times=args.insert_times,
        enforce_even_centrifuge_inserts=args.enforce_even_centrifuge_inserts,
    )

  (logger.path / "best.py").write_text(best_solution.program, encoding="utf-8")
  try:
    plot_breakthrough(logger.nodes_path, logger.path / "breakthrough.png")
  except ValueError as exc:
    print(f"skip_breakthrough_plot={exc}")
  try:
    plot_tree_branches(logger.nodes_path, logger.path / "tree_branches.png")
  except ValueError as exc:
    print(f"skip_tree_plot={exc}")
  try:
    plot_tree_branches_3d(logger.nodes_path, logger.path / "tree_branches_3d.png")
  except ValueError as exc:
    print(f"skip_tree_3d_plot={exc}")
  print(f"experiment_dir={logger.path}")
  print(f"best_score={best_score}")


if __name__ == "__main__":
  main()
