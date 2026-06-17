"""Adapters that plug job_shop_lib scheduling into implementation.futs.search.

The repository's FUTS implementation is intentionally task-agnostic. It expects
two user-provided callables:

- generate_fn(problem, parent_solution, parent_score) -> futs.Solution
- execute_fn(problem, solution) -> float

This module builds those callables for job_shop_lib benchmark instances.
"""

from __future__ import annotations

from dataclasses import dataclass

from implementation import futs
from implementation.job_shop_era.executor import JobShopExecutor
from implementation.job_shop_era.mutator import JobShopMutator, RepeatMutator
from implementation.job_shop_era.problem import JobShopProblem, load_problem
from implementation.job_shop_era.seed import baseline_candidate_code


@dataclass(frozen=True)
class JobShopFutsComponents:
  """Complete argument bundle for implementation.futs.search."""

  problem: JobShopProblem
  initial_solution: futs.Solution
  initial_score: float
  generate_fn: futs.Generate
  execute_fn: futs.Execute


def make_execute_fn(timeout_seconds: int = 30) -> JobShopExecutor:
  """Creates FUTS' execute_fn for job_shop_lib schedules."""
  return JobShopExecutor(timeout_seconds=timeout_seconds)


def make_generate_fn(llm, research_idea: str | None = None) -> JobShopMutator:
  """Creates FUTS' generate_fn using an LLM with draw_sample(prompt)."""
  return JobShopMutator(llm=llm, research_idea=research_idea)


def make_repeat_generate_fn() -> RepeatMutator:
  """Creates a deterministic generate_fn for no-LLM smoke tests."""
  return RepeatMutator(baseline_candidate_code())


def make_openai_generate_fn(research_idea: str | None = None) -> JobShopMutator:
  """Creates an OpenAI-backed generate_fn using private env configuration."""
  from implementation.llm import OpenAILLM, load_openai_env

  import os

  load_openai_env()
  api_key = os.environ.get("OPENAI_API_KEY")
  if not api_key:
    raise RuntimeError("Set OPENAI_API_KEY or configure ~/.config/era/openai.env.")
  return make_generate_fn(
      OpenAILLM(
          api_key=api_key,
          base_url=os.environ.get("OPENAI_BASE_URL"),
          model_name=os.environ.get("OPENAI_MODEL", "gpt-5.5"),
          wire_api=os.environ.get("OPENAI_WIRE_API", "responses"),
      ),
      research_idea=research_idea,
  )


def build_components(
    instance_name: str = "ft06",
    generate_fn=None,
    timeout_seconds: int = 30,
    initial_code: str | None = None,
    include_reference_values_in_prompt: bool = False,
) -> JobShopFutsComponents:
  """Builds the standard FUTS argument bundle for a job_shop_lib instance.

  Args:
    instance_name: job_shop_lib benchmark name, e.g. "ft06" or "la01".
    generate_fn: Optional generate function. If omitted, a deterministic repeat
      generator is used so the pipe can be tested without an LLM.
    timeout_seconds: Sandbox timeout for executing generated code.
    initial_code: Optional root candidate code. Defaults to a valid dispatching
      baseline using Schedule.from_job_sequences.
    include_reference_values_in_prompt: If true, includes optimum/lower/upper
      bound metadata in the prompt. Defaults to false for benchmark runs.

  Returns:
    A JobShopFutsComponents object ready to pass into futs.search.
  """
  problem = load_problem(
      instance_name,
      include_reference_values_in_prompt=include_reference_values_in_prompt,
  )
  initial_solution = futs.Solution(initial_code or baseline_candidate_code())
  execute_fn = make_execute_fn(timeout_seconds=timeout_seconds)
  initial_score = execute_fn(problem, initial_solution)
  return JobShopFutsComponents(
      problem=problem,
      initial_solution=initial_solution,
      initial_score=initial_score,
      generate_fn=generate_fn or make_repeat_generate_fn(),
      execute_fn=execute_fn,
  )
