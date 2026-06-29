"""Prompt construction for CP-SAT flow_1160 scheduling code mutation."""

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

You are mutating one reusable CP-SAT scheduler script inside an ERA/FUTS tree search.
Return only Python code. Do not return JSON and do not include Markdown fences.
The script must expose exactly:

def solve(dataset):
  ...
  return schedule

`dataset["fjspb"]` is the primary problem IR (derived from the smart-scheduling
project flow graph). It contains:
- machines: dict machine_code -> capacity.
- machine_frequencies: dict machine_code -> [min_freq, max_freq]; a task that
  needs a frequency (see parameters.frequency) must be placed on a machine whose
  range covers it.
- jobs: each job has job_id, expr_no, expr_name, and ordered tasks.
- each task has task_id, duration, machines (eligible machine codes), parameters,
  flags, and is_fixed. parameters[0]["param"] may carry:
    temperature -> required temperature (C). Two tasks on the SAME machine that
    overlap in time must have the SAME temperature.
    frequency -> required shaking frequency (rpm); must fall inside the chosen
    machine's machine_frequencies range.
- precedence_pairs: list of [a, b] explicit edges straight from the flow graph.
  These are the only precedence edges to model. For every pair,
  assignment(a).end <= assignment(b).start.
- branch_groups: graph metadata for condition/experimental branches. It
  records outgoing branch label/order, downstream task ids, and whether those
  branch successors appear in runtime data. In project 1160, task-bearing
  experimental branches are required scheduled work unless future metadata
  explicitly provides a mutually exclusive condition selector. Do not skip a
  task merely because it sits under a branch group.
- branch_priority_pairs: list of priority ordering constraints derived from
  UI branch labels P1/P2/P3 (`line.order`/`line.label`). For every pair, the
  first task on the higher-priority branch must start no later than the first
  task on the next lower-priority branch.
- only tasks with is_fixed=True expose fixed_start, fixed_end, and
  scheduled_machine. Non-fixed tasks expose no incumbent start/end or machine.
- constraint_contract: the verifier-enforced rules.

Return JSON-serializable data, exactly:
{{"assignments": [{{"job_id": ..., "task_id": ..., "machine": ..., "start": ..., "end": ...}}]}}

Mandatory solver requirements:
- Use OR-Tools CP-SAT via `from ortools.sat.python import cp_model`.
- Build a CP-SAT model, solve it with `cp_model.CpSolver`, and derive the
  returned assignments from solver variable values.
- Before coding constraints, analyze the scene from the IR and reflect that
  analysis in clear code structure: identify jobs, ordered tasks, eligible
  machines, machine capacities, temperature/frequency requirements,
  precedence_pairs edges, and the makespan objective. The code should be
  understandable as a reusable model of this scheduling problem, not only a
  sequence of ad hoc checks.
- Use semantic variable names and dictionaries keyed by problem entities, for
  example task_key/job_task_key, machine_code, presence[(task_key, machine)],
  start_vars[task_key], end_vars[task_key], interval_vars[(task_key, machine)],
  machine_to_intervals, job_to_tasks, and makespan. Avoid opaque names that
  make it hard to audit whether a constraint belongs to a task, machine,
  precedence edge, batch rule, or capacity rule.
- Do not precompute a complete greedy/list schedule and then fix CP-SAT
  variables to those times or return that greedy schedule. CP-SAT must decide
  start times, machine choices, and makespan for the returned assignments.
- Do not create `raw_assignments`, `_build_constructive_schedule`, or fixed
  domains such as `NewIntVar(s0, s0, ...)` / `NewIntVar(e0, e0, ...)` for
  every task. Fixed domains are only valid for tasks with `is_fixed=True`.
- Do not replace CP-SAT with a pure greedy/list scheduler. Greedy logic is only
  allowed as a fallback, hint generator, bound, repair, or CP-SAT-guided LNS
  component around the CP-SAT model.
- The executor statically rejects candidates that do not use cp_model.

Hard constraints:
- Every task must appear exactly once in returned assignments.
- Each assignment machine must be one of task["machines"].
- Assignment duration must equal task["duration"].
- Do NOT chain tasks into a total order by adding
  `end(task_id i) <= start(task_id i+1)` for every adjacent pair. That
  serializes the whole job and forbids all parallelism. The ONLY precedence
  constraints you should add to the CP-SAT model are the explicit
  `precedence_pairs` edges below. Parallelism comes from cumulative capacity on
  shared machines, NOT from task_id adjacency.
- For every precedence_pairs edge [a, b], assignment(a).end <= assignment(b).start.
- Preserve branch semantics by using precedence_pairs over the full task set.
  Do not model branch_groups as optional/mutually exclusive paths unless the IR
  explicitly marks a branch selector; this project currently does not.
- Branch priority: for each branch_priority_pairs row, add
  start(higher_task_id) <= start(lower_task_id). This restores the P1/P2/P3
  priority shown in the flow graph; it is a start-order rule, not a requirement
  that the higher-priority branch finishes before the lower-priority branch.
- Min-wait (hard): if task a has min_wait>0, then for every successor b reached via
  precedence_pairs, assignment(b).start >= assignment(a).end + a.min_wait (settle/
  stabilization floor). max_wait is a soft time-window preference (real schedules
  often exceed it due to device queuing) — try to respect it but it is NOT a hard
  constraint.
- Non-fixed tasks must start at or after dataset["fjspb"]["cur_ptr"].
- Fixed tasks must keep fixed_start, fixed_end, and scheduled_machine.
- Machine capacity (dataset["fjspb"]["machines"]) is the real per-device
  concurrency measured from runtime data, NOT the storage slot count.
- Cumulative scheduling: each task carries required_capacity = how many
  board/sample instances it occupies on the machine (its multi-well parallelism).
  At any instant the SUM of required_capacity of tasks running on the same
  machine must be <= that machine's capacity. Implement with AddCumulative.
- Example: a "coating A1-A6" task with required_capacity=8 fully occupies
  Smart8A (capacity 8); two smaller tasks (required 3 and 2) may share Smart8A
  simultaneously since 3+2 <= 8. A required_capacity=1 task on a capacity-1
  machine must not overlap any other task (plain NoOverlap).
- Temperature compatibility: if two tasks placed on the SAME machine overlap in
  time and both declare parameters.temperature, those temperatures must be equal.
  A missing temperature parameter means no modeled temperature requirement; do
  not infer 4C/37C/42C for tasks that omit it.
- Frequency match: if a task declares parameters.frequency, the chosen machine's
  machine_frequencies range must contain it.
- Apply special flags ONLY when the IR actually carries them: the
  electronic_dripping/test/recycle and xrd_dripping/test/recycle chains (mutual
  exclusion + back-to-back) and the centrifugation even-active-count rule. This
  project's tasks carry NO such flags, so do not invent them. Same-experiment
  first-task sync applies only when multiple jobs share an expr_no (not the case
  for this single-job flow project).
- Use OR-Tools Python APIs available in the local runtime. Do not call
  `model.AddMapDomain`; either use Boolean presence variables directly or
  `model.add_map_domain` if a domain-map helper is truly needed.
- Do not use network access, file I/O, multiprocessing, or external services.
- The code must be self-contained in one file and must not hard-code this
  dataset's final answer, makespan, or operation start/end table.
- Do not assume any hidden incumbent schedule exists. The public IR does not
  provide non-fixed incumbent start/end times; derive non-fixed assignments
  from CP-SAT variable values.
- Keep the public API `solve(dataset)`.
- Know and use the professional OR-Tools CP-SAT tools that match this domain:
  `NewIntVar`, `NewBoolVar`, `NewOptionalIntervalVar`, `AddExactlyOne`,
  `AddImplication`, `OnlyEnforceIf`, `AddBoolOr`, `AddNoOverlap`,
  `AddCumulative`, `AddMaxEquality`, `Minimize`, solver time limits,
  solution hints, decision strategies, and CP-SAT-guided large-neighborhood
  search where useful.
- Prefer reusable CP-SAT improvements such as tighter horizons, cumulative
  machine capacity, optional machine intervals, precedence_pairs constraints,
  temperature-grouped NoOverlap on shared machines, batch synchronization
  booleans, lower bounds, hints, decision strategies, symmetry breaking,
  repair phases, or CP-SAT-guided large-neighborhood search.

FUTS maximizes score:
score = -(makespan + elapsed_seconds / 100).
Lower makespan is the main objective; runtime breaks close ties.
Every generated node is still evaluated by the executor/scorer; do not assume a
change is accepted unless it returns a feasible schedule with a better score.
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
