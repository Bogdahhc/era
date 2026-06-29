"""FUTS generate_fn implementation for flow_1160_era_v2."""

from __future__ import annotations

from typing import Protocol

from implementation import futs
from implementation.job_shop_era.mutator import strip_code_fences
from implementation.flow_1160_era.mutator import RepeatMutator
from implementation.flow_1160_era_v2.prompt import build_prompt


class LLM(Protocol):
  def draw_sample(self, prompt: str) -> str:
    ...


class Flow1160V2Mutator:
  def __init__(self, llm: LLM, research_idea: str | None = None):
    self.llm = llm
    self.research_idea = research_idea
    self.feedback_context: dict | None = None

  def set_feedback_context(self, context: dict) -> None:
    self.feedback_context = context

  def __call__(self, problem, parent_solution, parent_score):
    prompt = build_prompt(
        problem=problem,
        parent_code=parent_solution.program,
        parent_score=parent_score,
        research_idea=self.research_idea,
        feedback_context=self.feedback_context,
    )
    return futs.Solution(strip_code_fences(self.llm.draw_sample(prompt)))

