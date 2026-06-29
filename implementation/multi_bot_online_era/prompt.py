"""Prompt construction for CP-SAT multi-bot online scheduling code mutation."""

from __future__ import annotations

import json


def build_prompt(
    problem,
    parent_code: str,
    parent_score: float,
    research_idea: str | None = None,
    feedback_context: dict | None = None,
) -> str:
  idea = f"\nResearch idea to try:\n{research_idea}\n" if research_idea else ""
  feedback = _format_feedback(feedback_context or {})
  dataset_summary = json.dumps(problem.prompt_dataset, ensure_ascii=False, indent=2)
  return f"""
{problem.description}

You are mutating one reusable online CP-SAT scheduler script inside an ERA/FUTS tree search.
Return only Python code. Do not return JSON and do not include Markdown fences.
The script must expose exactly this realtime interface:

class DynamicScheduler:
  def __init__(self, dataset):
    ...

  def handle_command(self, command):
    ...
    return response

The evaluator instantiates `DynamicScheduler(dataset)` once and then sends a
rolling command stream. A scenario may contain multiple insertion signals. Each
`reschedule` response is treated as the active plan until the next signal
arrives; the next valid plan overwrites only the still-future part of the
previous plan. The candidate receives one command at a time. It must behave like
a real runtime service that accepts inserted task tables as messages and then
returns a new plan. Supported commands are:
- {{"type": "reschedule", "now": int, "request_id": str}}: update the current
  time, build a CP-SAT model from the scheduler's current state, and return a
  response containing the latest schedule, preferably {{"schedule": ...}}.
- {{"type": "tick", "time": int}}: advance the scheduler clock without
  interrupting already fixed work.
- {{"type": "insert_jobs", "now": int, "jobs": [...]}}: add new FJSPB jobs to
  the in-memory dataset and acknowledge the insertion. The command may also
  include `insert_time`; treat it as the same event time as `now` when present.
  Do not solve by file I/O.
- {{"type": "dispatch_until", "time": int}}: return actions or assignments that
  would be dispatched up to that time. This command must not change fixed tasks.

You may also define helper functions such as `solve_snapshot(dataset)` or
`solve(dataset)`, but scored schedules must be produced through
`DynamicScheduler.handle_command`.

For SQLite inputs, `dataset["fjspb"]` is the primary problem IR. It contains:
- machines: dict machine_code -> capacity.
- jobs: each job has job_id, expr_no, expr_name, and ordered tasks.
- each task has task_id, duration, machines, parameters, flags, and is_fixed.
- only tasks with is_fixed=True expose fixed_start, fixed_end, and
  scheduled_machine. Non-fixed tasks do not expose SQLite incumbent start/end
  times or selected machines.
- constraint_contract: the verifier-enforced FJSPB rules.

Return JSON-serializable data. For FJSPB IR, prefer exactly:
{{"assignments": [{{"job_id": ..., "task_id": ..., "machine": ..., "start": ..., "end": ...}}]}}

Legacy `operations` output is still accepted for non-SQLite datasets, but for
SQLite/FJSPB use `assignments`.

Mandatory online solver requirements:
- Use OR-Tools CP-SAT via `from ortools.sat.python import cp_model`.
- Build a CP-SAT model, solve it with `cp_model.CpSolver`, and derive the
  returned assignments from solver variable values on every reschedule command.
- Maintain scheduler state in memory: current time, inserted jobs, last schedule,
  and any dispatch watermark. The scheduler should accept task insertions
  without reconstructing state from external files.
- Do not use a retrospective/offline viewpoint. At any command, only schedule
  from the current in-memory state and the command just received. Do not assume
  future insertion events, future inserted jobs, the total number of future
  insertions, or the final command stream. Do not rewrite or improve old plans
  using knowledge that would only be available after a later insertion.
- When a new reschedule is requested, treat the previously returned schedule as
  the active plan being overwritten. Tasks already started before the command
  time are locked and must not move; tasks not yet started may be re-optimized.
- Treat insertion time as an interface value, not a constant. Read it from
  `command["insert_time"]`, `command["now"]`, or the latest `tick` command.
  Do not hard-code a seed-specific timestamp such as the current scenario's
  insert_now, and do not hard-code the 4_experiments job count, inserted job
  ids, or command sequence length.
- Before coding constraints, analyze the FJSPB scene from the IR and reflect
  that analysis in clear code structure: identify jobs, ordered tasks,
  eligible machines, fixed tasks, machine capacities, batch/synchronization
  machines, chemistry conflicts, robot/device resources, and the makespan
  objective. The code should be understandable as a reusable model of this
  scheduling problem, not only a sequence of ad hoc checks.
- Use semantic variable names and dictionaries keyed by problem entities, for
  example task_key/job_task_key, machine_code, presence[(task_key, machine)],
  start_vars[task_key], end_vars[task_key], interval_vars[(task_key, machine)],
  machine_to_intervals, job_to_tasks, and makespan. Avoid opaque names that
  make it hard to audit whether a constraint belongs to a task, machine,
  resource, batch rule, or chemistry rule.
- Do not precompute a complete greedy/list schedule and then fix CP-SAT
  variables to those times or return that greedy schedule. CP-SAT must decide
  start times, machine choices, and makespan for the returned assignments.
- Do not create `raw_assignments`, `_build_constructive_schedule`, or fixed
  domains such as `NewIntVar(s0, s0, ...)` / `NewIntVar(e0, e0, ...)` for
  every task. Fixed domains are only valid for tasks with `is_fixed=True`.
- Do not replace CP-SAT with a pure greedy/list scheduler. Greedy logic is only
  allowed as a fallback, hint generator, bound, repair, or CP-SAT-guided LNS
  component around the CP-SAT model.
- The executor statically rejects candidates that do not define
  `DynamicScheduler`, `handle_command`, and CP-SAT usage.

Hard constraints:
- Every FJSPB task must appear exactly once in returned assignments.
- Each assignment machine must be one of task["machines"].
- Assignment duration must equal task["duration"].
- Tasks in each job must respect increasing task_id order.
- Non-fixed tasks must start at or after the active reschedule time/cur_ptr.
- Fixed tasks must keep fixed_start, fixed_end, and scheduled_machine.
- Machine capacity comes from dataset["fjspb"]["machines"].
- For capacity>1 batch machines, overlapping tasks must be synchronized:
  same start/end when durations match; different durations must not overlap.
- Implement the batch rule pairwise for every pair of optional intervals on the
  same machine. If both presences are true and durations differ, enforce
  `end_i <= start_j OR end_j <= start_i`. If durations match, allow only those
  two non-overlap orders or exact `start_i == start_j` and `end_i == end_j`.
- Enforce chemistry rules in the IR: dripping/test/recycle mutual exclusion
  and back-to-back chains, muffle/dryer temperature incompatibility,
  centrifugation even active count, and same-experiment first-task sync.
- Use OR-Tools Python APIs available in the local runtime. Do not call
  `model.AddMapDomain`; either use Boolean presence variables directly or
  `model.add_map_domain` if a domain-map helper is truly needed.
- Do not use network access, file I/O, multiprocessing, or external services.
- The code must be self-contained in one file and must not hard-code this
  dataset's final answer, makespan, operation start/end table, insertion time,
  scenario seed, or inserted job identities.
- Do not replay a hidden SQLite incumbent schedule. The public FJSPB IR does
  not provide non-fixed incumbent start/end times; derive non-fixed assignments
  from CP-SAT variable values.
- Keep the public API `DynamicScheduler(dataset).handle_command(command)`.
- Know and use the professional OR-Tools CP-SAT tools that match this domain:
  `NewIntVar`, `NewBoolVar`, `NewOptionalIntervalVar`, `AddExactlyOne`,
  `AddImplication`, `OnlyEnforceIf`, `AddBoolOr`, `AddNoOverlap`,
  `AddCumulative`, `AddMaxEquality`, `Minimize`, solver time limits,
  solution hints, decision strategies, and CP-SAT-guided large-neighborhood
  search where useful.
- Prefer reusable CP-SAT improvements such as tighter horizons, cumulative
  machine capacity, optional machine intervals, precedence constraints,
  batch synchronization booleans, chemistry-specific NoOverlap constraints,
  lower bounds, hints, decision strategies, symmetry breaking, repair phases,
  or CP-SAT-guided large-neighborhood search.

FUTS maximizes score:
score = -(average_checked_makespan + cumulative_stability_penalty + elapsed_seconds / 100).
Every checked reschedule contributes to the average makespan. The stability
penalty is accumulated between consecutive accepted plans: time shifts for tasks
that existed before each overwrite are penalized, and machine changes are
penalized more strongly.
For seeded random insertion scenarios, the evaluator also treats tasks from the
previous accepted schedule with `start < current_event_time` as runtime-fixed in
the next validation snapshot. A practical scheduler should therefore keep
already-started work unchanged, overwrite the previous future plan after each
signal, and only re-optimize future work.
Every generated node is still evaluated by the executor/scorer; do not assume a
change is accepted unless the dynamic command trace returns feasible schedules
with a better score.
{idea}
Parent score: {parent_score}

Evaluation feedback:

{feedback}

Dataset summary:
{dataset_summary}

Parent candidate code:
{parent_code}

Return only the complete Python candidate.
""".strip()


def _format_feedback(context: dict) -> str:
  lines = []
  parent = context.get("parent")
  best = context.get("best")
  lineage = context.get("lineage", [])
  recent = context.get("recent", [])
  recent_failures = context.get("recent_failures", [])
  next_node_id = context.get("next_node_id")
  timeout_seconds = context.get("timeout_seconds")
  score_contract = context.get("score_contract")
  scenario_config = context.get("scenario_config")

  if next_node_id is not None:
    lines.append(f"- New candidate will be node {next_node_id}.")
  if timeout_seconds is not None:
    lines.append(
        f"- The executor gives every candidate the same outer timeout: "
        f"{timeout_seconds} seconds. Candidate CP-SAT code should read "
        "ERA_CANDIDATE_TIMEOUT_SECONDS and set solver.parameters.max_time_in_seconds "
        "slightly below that outer timeout instead of hard-coding a short limit."
    )
  if score_contract:
    lines.append(f"- Scoring contract: {score_contract}")
  if scenario_config:
    lines.append(f"- Online scenario config: {json.dumps(scenario_config, ensure_ascii=False)}")
  if parent:
    lines.append("- Selected parent:")
    lines.extend(_format_eval(parent, indent="  "))
  if best:
    lines.append("- Best candidate so far:")
    lines.extend(_format_eval(best, indent="  "))
  if lineage:
    lines.append("- Parent lineage from root to selected parent:")
    for row in lineage:
      status = "feasible" if row.get("feasible") else "failed"
      lines.append(
          "  - "
          + ", ".join(
              [
                  f"node={row.get('node_id')}",
                  f"parent={row.get('parent_id')}",
                  f"status={status}",
                  f"score={_short(row.get('score'))}",
                  f"makespan={row.get('makespan')}",
                  f"elapsed={_short(row.get('elapsed_seconds'))}",
              ]
          )
      )
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
  if recent_failures:
    lines.append("- Recent failure details to avoid repeating:")
    for row in recent_failures[-3:]:
      lines.extend(_format_eval(row, indent="  "))
  if not lines:
    lines.append("- No previous evaluation details are available.")
  lines.append(
      "- Use this feedback to make one or two concrete solver-code changes. "
      "If the parent failed, fix the failure first. If it was feasible, target "
      "a reusable scheduling/search improvement rather than cosmetic rewrites."
  )
  best_code = context.get("best_code_summary")
  parent_to_best_diff = context.get("parent_to_best_diff")
  if best_code:
    lines.append("")
    lines.append("- Best candidate code summary for reuse:")
    lines.append(_indent_block(best_code, "  "))
  if parent_to_best_diff:
    lines.append("")
    lines.append("- Diff from selected parent to current best candidate:")
    lines.append(_indent_block(parent_to_best_diff, "  "))
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


def _indent_block(text: str, indent: str) -> str:
  return "\n".join(indent + line for line in text.splitlines())
