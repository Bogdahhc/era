"""CLI for running job_shop_lib optimization with ERA/FUTS."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from implementation.job_shop_era.benchmarks import format_benchmarks, list_benchmarks
from implementation.job_shop_era.logger import ExperimentLogger
from implementation.job_shop_era.mutator import JobShopMutator, RepeatMutator
from implementation.job_shop_era.plot import plot_breakthrough
from implementation.job_shop_era.problem import load_problem
from implementation.job_shop_era.seed import baseline_candidate_code


def _build_mutator(no_llm: bool):
  if no_llm:
    return RepeatMutator(baseline_candidate_code())

  from implementation.llm import OpenAILLM, load_openai_env

  load_openai_env()

  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
    raise SystemExit("Set OPENAI_API_KEY, or pass --no-llm.")
  base_url = os.environ.get("OPENAI_BASE_URL")
  model_name = os.environ.get("OPENAI_MODEL", "gpt-5.5")
  wire_api = os.environ.get("OPENAI_WIRE_API", "responses")
  return JobShopMutator(
      OpenAILLM(
          api_key=api_key,
          model_name=model_name,
          base_url=base_url,
          wire_api=wire_api,
      )
  )


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--instance", default="ft06")
  parser.add_argument("--mode", choices=["single", "bon", "futs"], default="futs")
  parser.add_argument("--iterations", type=int, default=50)
  parser.add_argument("--timeout-seconds", type=int, default=30)
  parser.add_argument("--experiment-name")
  parser.add_argument("--no-llm", action="store_true")
  parser.add_argument("--list-benchmarks", action="store_true")
  parser.add_argument("--min-operations", type=int, default=0)
  parser.add_argument("--early-stop-at-optimum", action="store_true")
  parser.add_argument("--include-reference-values-in-prompt", action="store_true")
  args = parser.parse_args()

  if args.list_benchmarks:
    print(format_benchmarks(list_benchmarks(args.min_operations)))
    return

  problem = load_problem(
      args.instance,
      include_reference_values_in_prompt=args.include_reference_values_in_prompt,
  )
  logger = ExperimentLogger(Path("experiments"), args.experiment_name)
  mutator = _build_mutator(args.no_llm)

  if args.mode == "single":
    from implementation.job_shop_era.search import run_single_generation

    best_solution, best_score = run_single_generation(
        problem,
        mutator,
        logger,
        timeout_seconds=args.timeout_seconds,
    )
  elif args.mode == "bon":
    from implementation.job_shop_era.search import run_best_of_n

    best_solution, best_score = run_best_of_n(
        problem,
        mutator,
        args.iterations,
        logger,
        timeout_seconds=args.timeout_seconds,
        early_stop_at_optimum=args.early_stop_at_optimum,
    )
  else:
    from implementation.job_shop_era.search import run_futs

    best_solution, best_score = run_futs(
        problem,
        mutator,
        args.iterations,
        logger,
        timeout_seconds=args.timeout_seconds,
        early_stop_at_optimum=args.early_stop_at_optimum,
    )

  (logger.path / "best.py").write_text(best_solution.program, encoding="utf-8")
  plot_breakthrough(logger.nodes_path, logger.path / "breakthrough.png")
  print(f"experiment_dir={logger.path}")
  print(f"best_score={best_score}")


if __name__ == "__main__":
  main()
