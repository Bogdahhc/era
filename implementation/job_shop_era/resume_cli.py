"""CLI for resuming an existing job_shop_era FUTS experiment."""

from __future__ import annotations

import argparse
from pathlib import Path

from implementation.job_shop_era.cli import _build_mutator
from implementation.job_shop_era.logger import ExperimentLogger
from implementation.job_shop_era.plot import (
    plot_breakthrough,
    plot_tree_branches,
    plot_tree_branches_3d,
)
from implementation.job_shop_era.problem import load_problem
from implementation.job_shop_era.search import (
    load_nodes_from_experiment,
    run_futs_from_nodes,
)


def _refresh_outputs(logger: ExperimentLogger, c_puct: float) -> tuple[int, float]:
  nodes = load_nodes_from_experiment(logger.path)
  best = max(nodes, key=lambda node: node.score)
  logger.write_tree(nodes)
  logger.write_puct_audit(nodes, c_puct=c_puct)
  (logger.path / "best.py").write_text(best.solution.program, encoding="utf-8")
  plot_breakthrough(logger.nodes_path, logger.path / "breakthrough.png")
  plot_tree_branches(logger.nodes_path, logger.path / "tree_branches.png")
  plot_tree_branches_3d(logger.nodes_path, logger.path / "tree_branches_3d.png")
  return len(nodes), best.score


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--experiment-dir", required=True)
  parser.add_argument("--instance", required=True)
  parser.add_argument("--iterations", type=int, required=True)
  parser.add_argument("--timeout-seconds", type=int, default=30)
  parser.add_argument("--c-puct", type=float, default=1.0)
  parser.add_argument("--no-llm", action="store_true")
  parser.add_argument("--early-stop-at-optimum", action="store_true")
  parser.add_argument("--include-reference-values-in-prompt", action="store_true")
  args = parser.parse_args()

  if args.iterations < 0:
    raise SystemExit("--iterations must be non-negative.")

  experiment_dir = Path(args.experiment_dir)
  nodes = load_nodes_from_experiment(experiment_dir)
  previous_node_count = len(nodes)
  problem = load_problem(
      args.instance,
      include_reference_values_in_prompt=args.include_reference_values_in_prompt,
  )
  logger = ExperimentLogger(experiment_dir.parent, experiment_dir.name)
  mutator = _build_mutator(args.no_llm)

  try:
    run_futs_from_nodes(
        problem=problem,
        mutator=mutator,
        nodes=nodes,
        num_iterations=args.iterations,
        logger=logger,
        timeout_seconds=args.timeout_seconds,
        c_puct=args.c_puct,
        early_stop_at_optimum=args.early_stop_at_optimum,
    )
  finally:
    current_node_count, best_score = _refresh_outputs(logger, args.c_puct)

  with logger.nodes_path.open(encoding="utf-8") as f:
    current_node_count = sum(1 for _ in f)
  print(f"experiment_dir={logger.path}")
  print(f"previous_nodes={previous_node_count}")
  print(f"current_nodes={current_node_count}")
  print(f"added_nodes={current_node_count - previous_node_count}")
  print(f"best_score={best_score}")


if __name__ == "__main__":
  main()
