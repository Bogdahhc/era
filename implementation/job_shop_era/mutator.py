"""FUTS generate_fn implementation for job-shop code mutation."""

from __future__ import annotations

import re
from typing import Protocol

from implementation import futs
from implementation.job_shop_era.prompt import build_prompt


class LLM(Protocol):
  def draw_sample(self, prompt: str) -> str:
    ...


def strip_code_fences(text: str) -> str:
  """Removes common Markdown code fences from model output."""
  text = re.sub(r"^```(?:python)?\s*", "", text.strip())
  text = re.sub(r"\s*```$", "", text)
  return text.strip()


class JobShopMutator:
  """Adapts an LLM into FUTS' generate_fn signature."""

  def __init__(self, llm: LLM, research_idea: str | None = None):
    self.llm = llm
    self.research_idea = research_idea

  def __call__(self, problem, parent_solution, parent_score):
    prompt = build_prompt(
        problem=problem,
        parent_code=parent_solution.program,
        parent_score=parent_score,
        research_idea=self.research_idea,
    )
    return futs.Solution(strip_code_fences(self.llm.draw_sample(prompt)))


class RepeatMutator:
  """Deterministic mutator for smoke tests and no-LLM dry runs."""

  def __init__(self, code: str):
    self.code = code

  def __call__(self, unused_problem, unused_parent_solution, unused_parent_score):
    return futs.Solution(self.code)

