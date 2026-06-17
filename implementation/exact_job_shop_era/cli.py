"""CLI for CP-SAT Python-code FUTS on job_shop_lib benchmarks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from implementation.exact_job_shop_era.logger import ExactExperimentLogger
from implementation.exact_job_shop_era.mutator import (
    ExactCodeMutator,
    RepeatCodeMutator,
)
from implementation.exact_job_shop_era.plot import (
    plot_breakthrough,
    plot_tree_branches,
    plot_tree_branches_3d,
)
from implementation.exact_job_shop_era.problem import load_problem
from implementation.exact_job_shop_era.search import run_futs
from implementation.exact_job_shop_era.seed import baseline_cp_sat_candidate_code


def _build_mutator(no_llm: bool):
  if no_llm:
    return None

  from implementation.llm import OpenAILLM, load_openai_env

  load_openai_env()
  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
    raise SystemExit("Set OPENAI_API_KEY, or pass --no-llm.")
  return ExactCodeMutator(
      OpenAILLM(
          api_key=api_key,
          model_name=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
          base_url=os.environ.get("OPENAI_BASE_URL"),
          wire_api=os.environ.get("OPENAI_WIRE_API", "responses"),
      )
  )


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--instance", default="ft06")
  parser.add_argument("--iterations", type=int, default=10)
  parser.add_argument("--experiment-name")
  parser.add_argument("--no-llm", action="store_true")
  parser.add_argument("--c-puct", type=float, default=1.0)
  parser.add_argument("--timeout-seconds", type=int, default=30)
  parser.add_argument("--root-time-seconds", type=float)
  parser.add_argument("--early-stop-at-optimum", action="store_true")
  parser.add_argument(
      "--optimize-runtime-after-optimum",
      action="store_true",
      help=(
          "Continue after reaching the benchmark optimum. Feasible nodes keep "
          "the standard score: -(makespan + elapsed_seconds / 100)."
      ),
  )
  parser.add_argument(
      "--runtime-score-makespan-weight",
      type=float,
      default=100.0,
      help=(
          "Deprecated compatibility option; scoring is always "
          "-(makespan + elapsed_seconds / 100)."
      ),
  )
  args = parser.parse_args()
  if args.runtime_score_makespan_weight <= 0:
    raise SystemExit("--runtime-score-makespan-weight must be positive.")
  if args.early_stop_at_optimum and args.optimize_runtime_after_optimum:
    print(
        "ignore_early_stop_at_optimum=true "
        "because --optimize-runtime-after-optimum is active"
    )

  problem = load_problem(args.instance)
  logger = ExactExperimentLogger(Path("experiments"), args.experiment_name)
  root_time_seconds = (
      args.root_time_seconds
      if args.root_time_seconds is not None
      else float(max(1, min(args.timeout_seconds * 0.8, args.timeout_seconds - 10)))
  )
  root_code = baseline_cp_sat_candidate_code(root_time_seconds)
  mutator = (
      RepeatCodeMutator(root_code)
      if args.no_llm
      else _build_mutator(args.no_llm)
  )
  logger.write_manifest(problem=problem, args=args, root_candidate=root_code)
  best_solution, best_score = run_futs(
      problem=problem,
      mutator=mutator,
      num_iterations=args.iterations,
      logger=logger,
      initial_code=root_code,
      c_puct=args.c_puct,
      timeout_seconds=args.timeout_seconds,
      early_stop_at_optimum=args.early_stop_at_optimum,
      optimize_runtime_after_optimum=args.optimize_runtime_after_optimum,
      runtime_score_makespan_weight=args.runtime_score_makespan_weight,
  )
  (logger.path / "best.py").write_text(best_solution.program, encoding="utf-8")
  plot_breakthrough(logger.nodes_path, logger.path / "breakthrough.png")
  try:
    plot_tree_branches(logger.nodes_path, logger.path / "tree_branches.png")
    plot_tree_branches_3d(logger.nodes_path, logger.path / "tree_branches_3d.png")
  except ValueError as exc:
    print(f"skip_tree_plots={exc}")
  print(f"experiment_dir={logger.path}")
  print(f"best_score={best_score}")


if __name__ == "__main__":
  main()
