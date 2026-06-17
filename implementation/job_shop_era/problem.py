"""Problem loading for job_shop_lib benchmark instances."""

from __future__ import annotations

from dataclasses import dataclass
import copy


REFERENCE_METADATA_KEYS = frozenset(("optimum", "lower_bound", "upper_bound"))


@dataclass(frozen=True)
class JobShopProblem:
  """Problem object passed to FUTS generate and execute callbacks."""

  instance_name: str
  description: str
  instance_dict: dict
  prompt_instance_dict: dict

  @property
  def optimum(self) -> int | None:
    value = self.instance_dict.get("metadata", {}).get("optimum")
    return int(value) if value is not None else None

  @property
  def lower_bound(self) -> int | None:
    value = self.instance_dict.get("metadata", {}).get("lower_bound")
    return int(value) if value is not None else None

  @property
  def upper_bound(self) -> int | None:
    value = self.instance_dict.get("metadata", {}).get("upper_bound")
    return int(value) if value is not None else None


def _hide_reference_values(instance_dict: dict) -> dict:
  prompt_dict = copy.deepcopy(instance_dict)
  metadata = prompt_dict.get("metadata")
  if isinstance(metadata, dict):
    for key in REFERENCE_METADATA_KEYS:
      metadata.pop(key, None)
  return prompt_dict


def load_problem(
    instance_name: str = "ft06",
    include_reference_values_in_prompt: bool = False,
) -> JobShopProblem:
  """Loads a job_shop_lib benchmark instance.

  This task does not require a train/validation split yet. The complete
  benchmark instance is passed into generated solvers and scored by makespan.
  """
  try:
    from job_shop_lib.benchmarking import load_benchmark_instance
  except ImportError as exc:
    raise RuntimeError(
        "job_shop_lib is required. Install it with `pip install job-shop-lib`."
    ) from exc

  instance = load_benchmark_instance(instance_name)
  instance_dict = instance.to_dict()
  optimum = instance.metadata.get("optimum")
  lower_bound = instance.metadata.get("lower_bound")
  reference_text = (
      f"Known optimum: {optimum}; lower bound: {lower_bound}."
      if include_reference_values_in_prompt
      else "Reference optimum and bounds are hidden from the solver prompt."
  )
  description = (
      f"Solve job-shop scheduling benchmark {instance.name}. "
      f"It has {instance.num_jobs} jobs, {instance.num_machines} machines, "
      f"and {instance.num_operations} operations. Minimize makespan. "
      f"{reference_text}"
  )
  prompt_instance_dict = (
      instance_dict
      if include_reference_values_in_prompt
      else _hide_reference_values(instance_dict)
  )
  return JobShopProblem(
      instance.name,
      description,
      instance_dict,
      prompt_instance_dict,
  )
