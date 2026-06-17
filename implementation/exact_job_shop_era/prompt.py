"""Prompt construction for CP-SAT code mutation."""

from __future__ import annotations


def build_prompt(
    problem,
    parent_code: str,
    parent_score: float,
    feedback_context: dict | None = None,
) -> str:
  feedback = _format_feedback(feedback_context or {})
  return f"""
{problem.description}

You are mutating a reusable Python job-shop solver script.
Return only Python code. Do not return JSON and do not include Markdown fences.

The candidate must define:

def solve(instance):
  ...
  return schedule

Requirements:
- Use OR-Tools CP-SAT via `from ortools.sat.python import cp_model`.
- Return a valid `job_shop_lib.Schedule`.
- Prefer exact/verifiable CP-SAT modeling, but you may add reusable modeling
  improvements such as tighter horizons, redundant constraints, symmetry
  breaking, decision strategies, hints, decomposition, repair phases, or
  CP-SAT-guided large-neighborhood search.
- The code must be self-contained in one file and must not read or write files.
- Do not hard-code this instance name, optimum, or benchmark answer.
- Keep the public API `solve(instance)`.

The selected parent candidate score was {parent_score}. FUTS maximizes score,
where score = -(makespan + elapsed_seconds / 100). Lower makespan is still the
main objective; runtime breaks close ties.

Evaluation feedback:

{feedback}

Parent candidate:

{parent_code}

Return only the complete Python candidate.
""".strip()


def _format_feedback(context: dict) -> str:
  lines = []
  parent = context.get("parent")
  best = context.get("best")
  recent = context.get("recent", [])
  next_node_id = context.get("next_node_id")
  timeout_seconds = context.get("timeout_seconds")

  if next_node_id is not None:
    lines.append(f"- New candidate will be node {next_node_id}.")
  if timeout_seconds is not None:
    lines.append(
        f"- The executor gives every candidate the same outer timeout: "
        f"{timeout_seconds} seconds."
    )
  if parent:
    lines.append("- Selected parent:")
    lines.extend(_format_eval(parent, indent="  "))
  if best:
    lines.append("- Best candidate so far:")
    lines.extend(_format_eval(best, indent="  "))
  if recent:
    lines.append("- Recent node results:")
    for row in recent:
      status = "feasible" if row.get("feasible") else "failed"
      parts = [
          f"node={row.get('node_id')}",
          f"parent={row.get('parent_id')}",
          f"status={status}",
          f"score={_short(row.get('score'))}",
          f"makespan={row.get('makespan')}",
          f"elapsed={_short(row.get('elapsed_seconds'))}",
      ]
      error = row.get("error")
      if error:
        parts.append(f"error={_truncate(str(error), 180)}")
      lines.append("  - " + ", ".join(parts))
  if not lines:
    lines.append("- No previous evaluation details are available.")
  lines.append(
      "- Use this feedback to make one or two concrete solver-code changes. "
      "If the parent failed, fix the failure first. If it was feasible, target "
      "a reusable modeling/search improvement rather than cosmetic rewrites."
  )
  return "\n".join(lines)


def _format_eval(row: dict, indent: str) -> list[str]:
  lines = [
      f"{indent}- node={row.get('node_id')}",
      f"{indent}- parent={row.get('parent_id')}",
      f"{indent}- feasible={row.get('feasible')}",
      f"{indent}- score={_short(row.get('score'))}",
      f"{indent}- makespan={row.get('makespan')}",
      f"{indent}- elapsed_seconds={_short(row.get('elapsed_seconds'))}",
  ]
  error = row.get("error")
  if error:
    lines.append(f"{indent}- error={_truncate(str(error), 400)}")
  return lines


def _short(value) -> str:
  if value is None:
    return "None"
  if isinstance(value, float):
    return f"{value:.6g}"
  return str(value)


def _truncate(text: str, limit: int) -> str:
  text = " ".join(text.split())
  if len(text) <= limit:
    return text
  return text[: limit - 3] + "..."
