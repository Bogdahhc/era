"""Prompt construction for job-shop code mutation."""

from __future__ import annotations

import json

from implementation.job_shop_era.problem import JobShopProblem


def build_prompt(
    problem: JobShopProblem,
    parent_code: str,
    parent_score: float,
    research_idea: str | None = None,
) -> str:
  """Builds the LLM prompt for one FUTS expansion."""
  idea = f"\nResearch idea to try:\n{research_idea}\n" if research_idea else ""
  instance_json = json.dumps(problem.prompt_instance_dict, indent=2)
  return f"""
{problem.description}

You are mutating one candidate solver inside an ERA/FUTS tree search.
The candidate code is executed in a sandbox. FUTS maximizes score, where:
score = -(makespan + elapsed_seconds / 100).
Lower makespan is still the main objective; runtime breaks close ties.

Hard constraints:
- Each job's operations must be scheduled in order.
- Each machine can process at most one operation at a time.
- Every operation must be scheduled exactly once on its required machine.
- Crashing, timing out, incomplete schedules, or infeasible schedules get the worst score.

Use the Python package job_shop_lib. Return complete Python code that exposes:

def solve(instance):
  ...
  return schedule

`instance` is a job_shop_lib.JobShopInstance. `schedule` must be a
job_shop_lib.Schedule. Prefer lightweight heuristics over expensive global
optimization. Do not use network access, file I/O, multiprocessing, or long
parameter searches.

Useful API:
- Schedule.from_job_sequences(instance, job_sequences)
- instance.jobs
- instance.num_jobs
- instance.num_machines
{idea}
Parent score: {parent_score}

Instance JSON for reference:
{instance_json}

Parent candidate code:
```python
{parent_code}
```

Return only Python code. Do not include Markdown fences.
""".strip()
