import re
import random
import time
import os
from pathlib import Path
from typing import Protocol


from openai import OpenAI


def load_openai_env(env_path: str | Path | None = None, override: bool = True) -> None:
    """Loads private OpenAI settings from ~/.config/era/openai.env if present."""
    path = Path(env_path or "~/.config/era/openai.env").expanduser()
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or not line.startswith("export "):
            continue
        key_value = line.removeprefix("export ").split("=", 1)
        if len(key_value) != 2:
            continue
        key, value = key_value
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value


class LLM(Protocol):
    def draw_sample(self, prompt: str) -> str:
        ...


def strip_code_fences(text: str) -> str:
    """Removes common Markdown code fences from a model response."""
    text = re.sub(r"^```(?:python)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)
    return text.strip()


class OpenAILLM:
    """OpenAI GPT adapter with the draw_sample interface expected by FUTS."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gpt-5.5",
        base_url: str | None = None,
        wire_api: str = "responses",
        max_retries: int = 5,
    ):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=_default_headers(base_url),
        )
        self.model_name = model_name
        self.wire_api = wire_api
        self.max_retries = max_retries

    def draw_sample(self, prompt: str) -> str:
        full_prompt = f"""
You are an expert operations research engineer and Python programmer.
Your task is to write Python code for the provided scorable optimization task.
Return only runnable Python code.

--- BEGIN PROMPT ---
{prompt}
--- END PROMPT ---
""".strip()
        base_delay = 5
        for attempt in range(self.max_retries):
            try:
                content = self._create_response(full_prompt)
                return strip_code_fences(content)
            except Exception as exc:
                if _is_retryable(exc) and attempt < self.max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    print(f"  [!] OpenAI API retry in {delay:.1f}s: {exc}")
                    time.sleep(delay)
                    continue
                else:
                    print(f"OpenAI API error: {exc}")
                    raise

    def _create_response(self, full_prompt: str) -> str:
        if self.wire_api == "chat":
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You generate complete Python programs. Return only "
                            "code, with no Markdown fences or explanatory text."
                        ),
                    },
                    {"role": "user", "content": full_prompt},
                ],
            )
            return response.choices[0].message.content or ""

        response = self.client.responses.create(
            model=self.model_name,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You generate complete Python programs. Return only "
                        "code, with no Markdown fences or explanatory text."
                    ),
                },
                {"role": "user", "content": full_prompt},
            ],
        )
        return response.output_text


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("429", "rate limit", "timeout", "temporarily"))


def _default_headers(base_url: str | None) -> dict[str, str] | None:
    user_agent = os.environ.get("OPENAI_USER_AGENT")
    if not user_agent and base_url and "allrealai.com" in base_url:
        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        )
    if not user_agent:
        return None
    return {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }


# Backwards-compatible alias for older examples that import GeminiLLM.
GeminiLLM = OpenAILLM
