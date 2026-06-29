"""CLI for running ERA/FUTS on flow_1160 (smart-scheduling flow graph) datasets."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from implementation.job_shop_era.logger import ExperimentLogger
from implementation.flow_1160_era.mutator import Flow1160Mutator, RepeatMutator
from implementation.flow_1160_era.plot import (
    plot_breakthrough,
    plot_tree_branches,
    plot_tree_branches_3d,
)
from implementation.flow_1160_era.problem import DEFAULT_DATASET, load_problem
from implementation.flow_1160_era.seed import baseline_candidate_code


def _build_mutator(no_llm: bool):
  root_code = baseline_candidate_code()
  if no_llm:
    return RepeatMutator(root_code)

  from implementation.llm import OpenAILLM, load_openai_env

  load_openai_env()
  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
    raise SystemExit("Set OPENAI_API_KEY, or pass --no-llm.")
  return Flow1160Mutator(
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
    from implementation.flow_1160_era.search import run_single_generation

    best_solution, best_score = run_single_generation(
        problem,
        mutator,
        logger,
        initial_code=initial_code,
        timeout_seconds=args.timeout_seconds,
    )
  else:
    from implementation.flow_1160_era.search import run_futs

    best_solution, best_score = run_futs(
        problem,
        mutator,
        args.iterations,
        logger,
        initial_code=initial_code,
        timeout_seconds=args.timeout_seconds,
        c_puct=args.c_puct,
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
