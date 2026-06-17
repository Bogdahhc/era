"""Root candidate programs for job-shop FUTS."""

from __future__ import annotations


def baseline_candidate_code() -> str:
  """Returns a simple valid root solver based on machine job sequences."""
  return """
from job_shop_lib import Schedule


def solve(instance):
  job_sequences = [[] for _ in range(instance.num_machines)]
  for job_id, job in enumerate(instance.jobs):
    for operation in job:
      job_sequences[operation.machine_id].append(job_id)
  return Schedule.from_job_sequences(instance, job_sequences)
""".strip()

