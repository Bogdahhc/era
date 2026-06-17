"""OpenAI adapter specialized for JSON exact-solver specs."""

from __future__ import annotations

import random
import time

from openai import OpenAI


class OpenAIJsonSpecLLM:
  """LLM adapter whose system prompt forbids Python code."""

  def __init__(
      self,
      api_key: str | None = None,
      model_name: str = "gpt-5.5",
      base_url: str | None = None,
      wire_api: str = "responses",
      max_retries: int = 5,
  ):
    self.client = OpenAI(api_key=api_key, base_url=base_url)
    self.model_name = model_name
    self.wire_api = wire_api
    self.max_retries = max_retries

  def draw_sample(self, prompt: str) -> str:
    for attempt in range(self.max_retries):
      try:
        return self._create_response(prompt)
      except Exception as exc:
        if _is_retryable(exc) and attempt < self.max_retries - 1:
          delay = 5 * (2**attempt) + random.uniform(0, 1)
          print(f"  [!] OpenAI API retry in {delay:.1f}s: {exc}")
          time.sleep(delay)
          continue
        print(f"OpenAI API error: {exc}")
        raise

  def _create_response(self, prompt: str) -> str:
    system = (
        "You configure exact optimization solvers. Return only one JSON object. "
        "Do not return Python, Markdown, comments, prose, or code fences."
    )
    if self.wire_api == "chat":
      response = self.client.chat.completions.create(
          model=self.model_name,
          messages=[
              {"role": "system", "content": system},
              {"role": "user", "content": prompt},
          ],
      )
      return response.choices[0].message.content or ""

    response = self.client.responses.create(
        model=self.model_name,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    return response.output_text or ""


def _is_retryable(exc: Exception) -> bool:
  text = str(exc).lower()
  return any(
      token in text
      for token in ("429", "rate limit", "timeout", "temporarily", "524")
  )
