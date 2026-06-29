"""CLI for plotting multi_bot_online_era FUTS tree branches."""

from __future__ import annotations

import argparse
from pathlib import Path

from implementation.multi_bot_online_era.plot import (
    plot_breakthrough,
    plot_tree_branches,
    plot_tree_branches_3d,
)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--experiment-dir", required=True)
  parser.add_argument("--output")
  parser.add_argument(
      "--plot",
      choices=["breakthrough", "tree2d", "tree3d", "all"],
      default="tree2d",
  )
  args = parser.parse_args()

  experiment_dir = Path(args.experiment_dir)
  nodes_path = experiment_dir / "nodes.jsonl"

  if args.plot == "all":
    plot_breakthrough(nodes_path, experiment_dir / "breakthrough.png")
    plot_tree_branches(nodes_path, experiment_dir / "tree_branches.png")
    plot_tree_branches_3d(nodes_path, experiment_dir / "tree_branches_3d.png")
    print(experiment_dir)
    return

  default_names = {
      "breakthrough": "breakthrough.png",
      "tree2d": "tree_branches.png",
      "tree3d": "tree_branches_3d.png",
  }
  output_path = (
      Path(args.output) if args.output else experiment_dir / default_names[args.plot]
  )
  if args.plot == "breakthrough":
    plot_breakthrough(nodes_path, output_path)
  elif args.plot == "tree3d":
    plot_tree_branches_3d(nodes_path, output_path)
  else:
    plot_tree_branches(nodes_path, output_path)
  print(output_path)


if __name__ == "__main__":
  main()
