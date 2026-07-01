"""Traced FUTS loops for flow_1160_era_v3."""

from __future__ import annotations

import difflib

from implementation import futs
from implementation.job_shop_era.logger import ExperimentLogger, NodeRecord
from implementation.flow_1160_era.seed import baseline_candidate_code
from implementation.flow_1160_era_v3.adaptive_futs import AdaptiveLogisticsTightener
from implementation.flow_1160_era_v3.executor import Flow1160V3Executor


def _record_node(logger: ExperimentLogger, node: futs.Node, evaluation, parent_code=None):
  logger.record(
      NodeRecord(
          node_id=node.index,
          parent_id=node.parent_index,
          score=evaluation.score,
          feasible=evaluation.feasible,
          makespan=evaluation.makespan,
          elapsed_seconds=evaluation.elapsed_seconds,
          visits=node.num_visits,
          rank_score=node.rank_score,
          puct=node.puct,
          error=evaluation.error,
      ),
      node.solution.program,
      parent_code,
  )


def _evaluation_row(node: futs.Node, evaluation) -> dict:
  return {
      "node_id": node.index,
      "parent_id": node.parent_index,
      "score": node.score,
      "feasible": evaluation.feasible,
      "makespan": evaluation.makespan,
      "elapsed_seconds": evaluation.elapsed_seconds,
      "error": evaluation.error,
  }


def _evaluation_rows(nodes: list[futs.Node], raw_evaluations: dict[int, object]) -> dict[int, dict]:
  return {node.index: _evaluation_row(node, raw_evaluations[node.index]) for node in nodes}


def _lineage(parent: futs.Node, nodes: list[futs.Node]) -> list[futs.Node]:
  by_index = {node.index: node for node in nodes}
  result = []
  cursor: futs.Node | None = parent
  while cursor is not None:
    result.append(cursor)
    if cursor.parent_index is None:
      break
    cursor = by_index.get(cursor.parent_index)
  result.reverse()
  return result


def _code_summary(code: str, limit: int = 6000) -> str:
  if len(code) <= limit:
    return code
  return code[: limit // 2] + "\n\n# ... middle omitted ...\n\n" + code[-limit // 2 :]


def _diff_summary(parent_code: str, child_code: str, limit: int = 5000) -> str:
  diff = "\n".join(
      difflib.unified_diff(
          parent_code.splitlines(),
          child_code.splitlines(),
          fromfile="parent.py",
          tofile="best_or_recent.py",
          lineterm="",
          n=3,
      )
  )
  return diff if len(diff) <= limit else diff[: limit - 80] + "\n# ... diff truncated ..."


def _set_mutator_feedback(
    mutator,
    *,
    nodes,
    evaluations,
    parent,
    next_node_id,
    timeout_seconds,
    adaptive_state=None,
    recent_isaac_processes=None,
):
  if not hasattr(mutator, "set_feedback_context"):
    return
  best = max(nodes, key=lambda node: node.score)
  recent_nodes = nodes[-5:]
  context = {
      "next_node_id": next_node_id,
      "timeout_seconds": timeout_seconds,
      "score_contract": (
          "Flow1160V3Executor first rejects candidates that ignore material_edges, "
          "material_inventory_events/AddReservoirConstraint, history_policy, "
          "logistics_events, buffers/buffer_ids, isaac_motion_timing/transfer_seconds, "
          "device_transfer_times, "
          "rolling_state/existing_machine_occupancy, "
          "AddNoOverlap, AddCumulative, device_commands, positions, plate_states, "
          "robot_resources, command_templates, command_realization_boundaries, or "
          "a returned command_assignments list. Feasible schedules then use v1 scorer: "
          "score=-(makespan + elapsed_seconds/100). Schema details that caused "
          "prior failures: precedence_pairs rows are [a, b], but "
          "branch_priority_pairs rows are dicts with higher_task_id/lower_task_id; "
          "model start[higher_task_id] <= start[lower_task_id]. In strict_cold_start "
          "history_policy, do not infer logistics duration from historical "
          "startTime/endTime spans. Logistics events with audit_no_overlap_candidate, "
          "duration>0, and explicit resources must create fixed-present resource "
          "intervals, AddNoOverlap per resource, link predecessor/successor task "
          "ids, add buffer_ids intervals to AddCumulative calendars using buffer "
          "capacity, and contribute event ends to modeled makespan. Logistics rows "
          "with missing_planning_duration_no_history preserve topology only. Material "
          "inventory events must be grouped by inventory_key and modeled with "
          "AddReservoirConstraint: +quantity at source task end and -quantity at "
          "destination task start, min_level=0. If CP-SAT has no feasible solution, "
          "return empty assignments; do not return a cur_ptr or first-machine "
          "fallback schedule. constraint_realization_boundaries is an interface/"
          "seed-controlled state: only state.required_hard_constraints are "
          "mandatory hard constraints; audit_controls, blocked_controls, and "
          "experimental_controls are non-hard context unless explicit platform "
          "fields exist. v3 additionally requires command_assignments: at minimum "
          "one cmd:task:<task_id>:run row per scheduled task with command_id/start/end/"
          "resource_id, bound to task assignments; task-only output is rejected. "
          "Do not invent robot move durations, from/to positions, or stable plate identity "
          "when command_realization_boundaries reports missing fields. For every hard "
          "material_edges transfer, read fjspb['device_transfer_times'] and add CP-SAT "
          "producer-to-consumer gaps conditioned on selected source/destination machines: "
          "OnlyEnforceIf([src_machine_chosen, dst_machine_chosen]) with start[dst] >= "
          "end[src] + max(src.min_wait, pair.transfer_seconds). Use "
          "fjspb['isaac_motion_timing']['transfer_seconds'] only as a fallback for a "
          "missing pair; logistics time must be part of the generated schedule, not only "
          "an after-the-fact penalty. Scoring still applies "
          "an Isaac-motion penalty as a backstop: conservative robot pick/move/place/drop "
          "transfers are generated from material_edges, and late transfers, robot/device/"
          "plate collisions, deadlocks, or returned external isaac_conflicts are penalized. "
          "device_transfer_times is a graph-distance matrix and must not be "
          "flattened into one global cap or hard-coded gap. When adaptive logistics "
          "validation is enabled, the run carries simulation feedback and accepted "
          "validation state after a candidate remains feasible and motion-safe; "
          "candidates must keep reading per-pair device_transfer_times from dataset. "
          "If recent_isaac_logistics_processes is present, the next node must use "
          "that concrete process evidence: inspect tightest_transfers, "
          "late_transfers, longest_transfers, busiest_device_pairs, and conflict/"
          "deadlock fields before changing machine choices or transfer-gap logic. "
          "Do not blindly try different gaps or machines without citing a specific "
          "transfer, task pair, device pair, slack, or Isaac conflict from that context."
      ),
      "parent": evaluations.get(parent.index),
      "best": evaluations.get(best.index),
      "lineage": [evaluations[node.index] for node in _lineage(parent, nodes)],
      "recent": [evaluations[node.index] for node in recent_nodes],
      "parent_code_summary": _code_summary(parent.solution.program),
  }
  if adaptive_state is not None:
    context["adaptive_logistics_state"] = adaptive_state
  if recent_isaac_processes:
    context["recent_isaac_logistics_processes"] = recent_isaac_processes
  if best.index != parent.index:
    context["best_code_summary"] = _code_summary(best.solution.program)
    context["parent_to_best_diff"] = _diff_summary(parent.solution.program, best.solution.program)
  failed_recent = [evaluations[node.index] for node in recent_nodes if not evaluations[node.index].get("feasible")]
  if failed_recent:
    context["recent_failures"] = failed_recent
  mutator.set_feedback_context(context)


def run_futs(
    problem,
    mutator,
    num_iterations,
    logger,
    initial_code=None,
    timeout_seconds=30,
    c_puct=1.0,
    adaptive_logistics=False,
    adaptive_min_gap=None,
    adaptive_step=None,
    adaptive_isaac_headless=False,
    adaptive_isaac_python="/home/hehaochen/anaconda3/envs/isaacsim/bin/python",
    adaptive_isaac_speed=1200,
    adaptive_isaac_timeout_seconds=240,
):
  executor = Flow1160V3Executor(timeout_seconds)
  tightener = AdaptiveLogisticsTightener(
      problem,
      enabled=adaptive_logistics,
      min_gap=adaptive_min_gap,
      step=adaptive_step,
      isaac_headless=adaptive_isaac_headless,
      artifact_dir=logger.path,
      isaac_python=adaptive_isaac_python,
      isaac_speed=adaptive_isaac_speed,
      isaac_timeout_seconds=adaptive_isaac_timeout_seconds,
  )
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_evaluation = tightener.evaluate(problem, root_solution, executor, node_id=0, parent_id=None)
  root_score = root_evaluation.score
  nodes = [futs.Node(0, None, root_solution, root_score, num_visits=1)]
  raw_evaluations = {0: root_evaluation}
  evaluations = _evaluation_rows(nodes, raw_evaluations)
  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  _record_node(logger, nodes[0], root_evaluation)
  tightener.write_report(logger.path / "adaptive_logistics.json")

  for _ in range(num_iterations):
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    parent = max(nodes, key=lambda node: node.puct)
    _set_mutator_feedback(
        mutator,
        nodes=nodes,
        evaluations=evaluations,
        parent=parent,
        next_node_id=len(nodes),
        timeout_seconds=timeout_seconds,
        adaptive_state=tightener.state(),
        recent_isaac_processes=tightener.recent_process_summaries(),
    )
    solution = mutator(problem, parent.solution, parent.score)
    evaluation = tightener.evaluate(problem, solution, executor, node_id=len(nodes), parent_id=parent.index)
    score = evaluation.score
    child = futs.Node(len(nodes), parent.index, solution, score, num_visits=1)
    nodes.append(child)
    raw_evaluations[child.index] = evaluation
    evaluations = _evaluation_rows(nodes, raw_evaluations)
    futs.backpropagate_visit(nodes, child)
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    _record_node(logger, child, evaluation, parent.solution.program)
    logger.write_tree(nodes)
    logger.write_puct_audit(nodes, c_puct)
    tightener.write_report(logger.path / "adaptive_logistics.json")

  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  logger.write_tree(nodes)
  logger.write_puct_audit(nodes, c_puct)
  tightener.write_report(logger.path / "adaptive_logistics.json")
  best = max(nodes, key=lambda node: node.score)
  return best.solution, best.score


def run_single_generation(
    problem,
    mutator,
    logger,
    initial_code=None,
    timeout_seconds=30,
    adaptive_logistics=False,
    adaptive_min_gap=None,
    adaptive_step=None,
    adaptive_isaac_headless=False,
    adaptive_isaac_python="/home/hehaochen/anaconda3/envs/isaacsim/bin/python",
    adaptive_isaac_speed=1200,
    adaptive_isaac_timeout_seconds=240,
):
  executor = Flow1160V3Executor(timeout_seconds)
  tightener = AdaptiveLogisticsTightener(
      problem,
      enabled=adaptive_logistics,
      min_gap=adaptive_min_gap,
      step=adaptive_step,
      isaac_headless=adaptive_isaac_headless,
      artifact_dir=logger.path,
      isaac_python=adaptive_isaac_python,
      isaac_speed=adaptive_isaac_speed,
      isaac_timeout_seconds=adaptive_isaac_timeout_seconds,
  )
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_evaluation = tightener.evaluate(problem, root_solution, executor, node_id=0, parent_id=None)
  root_score = root_evaluation.score
  root = futs.Node(0, None, root_solution, root_score, num_visits=1)
  _record_node(logger, root, root_evaluation)
  evaluations = _evaluation_rows([root], {0: root_evaluation})
  _set_mutator_feedback(
      mutator,
      nodes=[root],
      evaluations=evaluations,
      parent=root,
      next_node_id=1,
      timeout_seconds=timeout_seconds,
      adaptive_state=tightener.state(),
      recent_isaac_processes=tightener.recent_process_summaries(),
  )
  candidate = mutator(problem, root_solution, root_score)
  candidate_evaluation = tightener.evaluate(problem, candidate, executor, node_id=1, parent_id=0)
  candidate_score = candidate_evaluation.score
  child = futs.Node(1, 0, candidate, candidate_score, num_visits=1)
  _record_node(logger, child, candidate_evaluation, root_solution.program)
  tightener.write_report(logger.path / "adaptive_logistics.json")
  return (candidate, candidate_score) if candidate_score > root_score else (root_solution, root_score)
