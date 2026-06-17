#!/usr/bin/env python3
"""Reproduce exact_job_shop_era node 0000.

This script is generated for auditability. It is the materialized solver
version corresponding to specs/node_0000.json.
"""

from __future__ import annotations

import argparse
import json

from job_shop_lib import Schedule
from job_shop_lib.benchmarking import load_benchmark_instance

from implementation.exact_job_shop_era.backends import create_backend_solver
from implementation.exact_job_shop_era.spec import parse_spec


SPEC_JSON = '{\n  "backend": "ortools_cp_sat",\n  "branching": "default",\n  "encoding": "interval_variables",\n  "log_search_progress": false,\n  "max_time_in_seconds": 3.0,\n  "notes": "",\n  "redundant_bounds": [],\n  "symmetry_breaking": false,\n  "warm_start": "none"\n}'


def solve(instance_name: str = "ta21") -> dict:
  spec = parse_spec(SPEC_JSON)
  instance = load_benchmark_instance(instance_name)
  solver = create_backend_solver(spec)
  result = solver.solve(instance)
  if result.feasible and result.schedule is not None:
    Schedule.check_schedule(result.schedule.schedule)
    if not result.schedule.is_complete():
      raise ValueError("schedule is incomplete")
  return {
      "node_id": 0,
      "instance": instance.name,
      "feasible": result.feasible,
      "makespan": result.makespan,
      "status": result.status,
      "best_bound": result.best_bound,
      "relative_gap": result.relative_gap,
      "elapsed_seconds": result.elapsed_seconds,
      "branches": result.branches,
      "conflicts": result.conflicts,
      "spec": spec.to_dict(),
  }


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--instance", default="ta21")
  args = parser.parse_args()
  print(json.dumps(solve(args.instance), indent=2, sort_keys=True))


if __name__ == "__main__":
  main()
