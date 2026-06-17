#!/usr/bin/env python3
"""Reproduce exact_job_shop_era node 0077.

This script is generated for auditability. It is the materialized solver
version corresponding to specs/node_0077.json.
"""

from __future__ import annotations

import argparse
import dataclasses
import json

from job_shop_lib import Schedule
from job_shop_lib.benchmarking import load_benchmark_instance

from implementation.exact_job_shop_era.backends import create_backend_solver
from implementation.exact_job_shop_era.spec import parse_spec


SPEC_JSON = '{\n  "backend": "ortools_cp_sat",\n  "branching": "default",\n  "encoding": "interval_variables",\n  "log_search_progress": false,\n  "max_time_in_seconds": 180.0,\n  "notes": "Test CP-SAT default branching with a modestly larger exact search budget while retaining all valid makespan lower bounds for improved incumbent/proof chances on ta21.",\n  "redundant_bounds": [\n    "job_chain_lb",\n    "machine_load_lb",\n    "critical_path_lb"\n  ],\n  "symmetry_breaking": false,\n  "warm_start": "none"\n}'


def solve(instance_name: str = "ta21", time_limit: float | None = None) -> dict:
  spec = parse_spec(SPEC_JSON)
  if time_limit is not None:
    spec = dataclasses.replace(spec, max_time_in_seconds=time_limit)
  instance = load_benchmark_instance(instance_name)
  solver = create_backend_solver(spec)
  result = solver.solve(instance)
  if result.feasible and result.schedule is not None:
    Schedule.check_schedule(result.schedule.schedule)
    if not result.schedule.is_complete():
      raise ValueError("schedule is incomplete")
  return {
      "node_id": 77,
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
  parser.add_argument(
      "--time-limit",
      type=float,
      help="Override spec.max_time_in_seconds for this standalone run.",
  )
  args = parser.parse_args()
  print(json.dumps(solve(args.instance, args.time_limit), indent=2, sort_keys=True))


if __name__ == "__main__":
  main()
