"""Benchmark listing helpers for job_shop_lib instances."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkSummary:
  name: str
  num_jobs: int
  num_machines: int
  num_operations: int
  optimum: int | None
  lower_bound: int | None
  upper_bound: int | None


def list_benchmarks(min_operations: int = 0) -> list[BenchmarkSummary]:
  """Returns job_shop_lib benchmark summaries sorted by scale then name."""
  try:
    from job_shop_lib.benchmarking import load_all_benchmark_instances
  except ImportError as exc:
    raise RuntimeError(
        "job_shop_lib is required. Install it with `pip install job-shop-lib`."
    ) from exc

  instances = load_all_benchmark_instances()
  iterable = instances.values() if isinstance(instances, dict) else instances
  rows = []
  for instance in iterable:
    if instance.num_operations < min_operations:
      continue
    rows.append(
        BenchmarkSummary(
            name=instance.name,
            num_jobs=instance.num_jobs,
            num_machines=instance.num_machines,
            num_operations=instance.num_operations,
            optimum=instance.metadata.get("optimum"),
            lower_bound=instance.metadata.get("lower_bound"),
            upper_bound=instance.metadata.get("upper_bound"),
        )
    )
  return sorted(rows, key=lambda row: (row.num_operations, row.name))


def format_benchmarks(rows: list[BenchmarkSummary]) -> str:
  """Formats benchmark summaries as a compact table."""
  header = "name jobs machines ops optimum lower upper"
  lines = [header]
  for row in rows:
    lines.append(
        " ".join(
            str(value)
            for value in (
                row.name,
                row.num_jobs,
                row.num_machines,
                row.num_operations,
                row.optimum,
                row.lower_bound,
                row.upper_bound,
            )
        )
    )
  return "\n".join(lines)
