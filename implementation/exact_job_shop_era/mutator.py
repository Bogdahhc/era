"""FUTS generate_fn for CP-SAT Python solver mutation."""

from __future__ import annotations

import re
from typing import Protocol

from implementation import futs
from implementation.exact_job_shop_era.prompt import build_prompt


class LLM(Protocol):
  def draw_sample(self, prompt: str) -> str:
    ...


def strip_code_fences(text: str) -> str:
  """Removes common Markdown code fences from model output."""
  text = re.sub(r"^```(?:python)?\s*", "", text.strip())
  text = re.sub(r"\s*```$", "", text)
  return text.strip()


class ExactCodeMutator:
  """Adapts an LLM into FUTS' generate_fn signature for CP-SAT code."""

  def __init__(self, llm: LLM):
    self.llm = llm
    self.feedback_context: dict | None = None

  def set_feedback_context(self, context: dict) -> None:
    self.feedback_context = context

  def __call__(self, problem, parent_solution, parent_score):
    prompt = build_prompt(
        problem,
        parent_solution.program,
        parent_score,
        feedback_context=self.feedback_context,
    )
    return futs.Solution(strip_code_fences(self.llm.draw_sample(prompt)))


class RepeatCodeMutator:
  """Deterministic mutator for smoke tests and no-LLM dry runs."""

  def __init__(self, code: str):
    self.code = code

  def set_feedback_context(self, unused_context: dict) -> None:
    return None

  def __call__(self, unused_problem, unused_parent_solution, unused_parent_score):
    return futs.Solution(self.code)
