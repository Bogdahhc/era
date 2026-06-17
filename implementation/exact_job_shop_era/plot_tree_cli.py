"""CLI for plotting exact_job_shop_era tree branches."""

from __future__ import annotations

import argparse
from pathlib import Path

from implementation.exact_job_shop_era.plot import (
    plot_tree_branches,
    plot_tree_branches_3d,
)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--experiment-dir", required=True)
  parser.add_argument("--output")
  parser.add_argument("--three-d", action="store_true")
  args = parser.parse_args()

  experiment_dir = Path(args.experiment_dir)
  default_name = "tree_branches_3d.png" if args.three_d else "tree_branches.png"
  output_path = Path(args.output) if args.output else experiment_dir / default_name
  if args.three_d:
    plot_tree_branches_3d(experiment_dir / "nodes.jsonl", output_path)
  else:
    plot_tree_branches(experiment_dir / "nodes.jsonl", output_path)
  print(output_path)


if __name__ == "__main__":
  main()
