"""Problem loading for CP-SAT-code job-shop search."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExactJobShopProblem:
  instance_name: str
  description: str
  instance_dict: dict
  optimum: int | None


def load_problem(instance_name: str = "ft06") -> ExactJobShopProblem:
  try:
    from job_shop_lib.benchmarking import load_benchmark_instance
  except ImportError as exc:
    raise RuntimeError(
        "job_shop_lib is required. Install it with `pip install job-shop-lib`."
    ) from exc

  instance = load_benchmark_instance(instance_name)
  optimum = instance.metadata.get("optimum")
  description = (
      f"Write a reusable CP-SAT Python solver for job-shop benchmark {instance.name}. "
      f"It has {instance.num_jobs} jobs, {instance.num_machines} machines, "
      f"and {instance.num_operations} operations. The solver may use OR-Tools "
      f"CP-SAT modeling, hints, decomposition, repair, or hybrid exact-search "
      f"control, but it must return a valid job_shop_lib.Schedule. The scorer "
      f"rewards low makespan."
  )
  return ExactJobShopProblem(
      instance_name=instance.name,
      description=description,
      instance_dict=instance.to_dict(),
      optimum=int(optimum) if optimum is not None else None,
  )
