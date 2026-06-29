"""Traced FUTS loops for flow_1160 scheduling."""

from __future__ import annotations

import difflib

from implementation import futs
from implementation.job_shop_era.logger import ExperimentLogger, NodeRecord
from implementation.flow_1160_era.executor import Flow1160Executor
from implementation.flow_1160_era.seed import baseline_candidate_code


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


def _evaluation_rows(
    nodes: list[futs.Node], raw_evaluations: dict[int, object]
) -> dict[int, dict]:
  return {
      node.index: _evaluation_row(node, raw_evaluations[node.index])
      for node in nodes
  }


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
  head = code[: limit // 2]
  tail = code[-limit // 2 :]
  return head + "\n\n# ... middle of candidate omitted for prompt budget ...\n\n" + tail


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
  if len(diff) <= limit:
    return diff
  return diff[: limit - 80] + "\n# ... diff truncated for prompt budget ..."


def _set_mutator_feedback(
    mutator,
    *,
    nodes: list[futs.Node],
    evaluations: dict[int, dict],
    parent: futs.Node,
    next_node_id: int,
    timeout_seconds: int,
) -> None:
  if not hasattr(mutator, "set_feedback_context"):
    return
  best = max(nodes, key=lambda node: node.score)
  recent_nodes = nodes[-5:]
  context = {
      "next_node_id": next_node_id,
      "timeout_seconds": timeout_seconds,
      "score_contract": (
          "Every node is executed and scored by Flow1160Executor. Feasible "
          "schedules receive score=-(makespan + elapsed_seconds/100); "
          "invalid, non-CP-SAT, crashing, or timeout candidates receive "
          "the worst score and remain in the FUTS tree as failed nodes."
      ),
      "parent": evaluations.get(parent.index),
      "best": evaluations.get(best.index),
      "lineage": [evaluations[node.index] for node in _lineage(parent, nodes)],
      "recent": [evaluations[node.index] for node in recent_nodes],
      "parent_code_summary": _code_summary(parent.solution.program),
  }
  if best.index != parent.index:
    context["best_code_summary"] = _code_summary(best.solution.program)
    context["parent_to_best_diff"] = _diff_summary(
        parent.solution.program, best.solution.program
    )
  failed_recent = [
      evaluations[node.index]
      for node in recent_nodes
      if not evaluations[node.index].get("feasible")
  ]
  if failed_recent:
    context["recent_failures"] = failed_recent
  mutator.set_feedback_context(context)


def run_futs(
    problem,
    mutator,
    num_iterations: int,
    logger: ExperimentLogger,
    initial_code: str | None = None,
    timeout_seconds: int = 30,
    c_puct: float = 1.0,
) -> tuple[futs.Solution, float]:
  executor = Flow1160Executor(timeout_seconds)
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_score = executor(problem, root_solution)
  nodes = [futs.Node(0, None, root_solution, root_score, num_visits=1)]
  raw_evaluations = {0: executor.last_evaluation}
  evaluations = _evaluation_rows(nodes, raw_evaluations)
  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  _record_node(logger, nodes[0], executor.last_evaluation)

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
    )
    solution = mutator(problem, parent.solution, parent.score)
    score = executor(problem, solution)
    child = futs.Node(
        index=len(nodes),
        parent_index=parent.index,
        solution=solution,
        score=score,
        num_visits=1,
    )
    nodes.append(child)
    raw_evaluations[child.index] = executor.last_evaluation
    evaluations = _evaluation_rows(nodes, raw_evaluations)
    futs.backpropagate_visit(nodes, child)
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    _record_node(logger, child, executor.last_evaluation, parent.solution.program)
    logger.write_tree(nodes)
    logger.write_puct_audit(nodes, c_puct)

  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  logger.write_tree(nodes)
  logger.write_puct_audit(nodes, c_puct)
  best = max(nodes, key=lambda node: node.score)
  return best.solution, best.score


def run_single_generation(
    problem,
    mutator,
    logger: ExperimentLogger,
    initial_code: str | None = None,
    timeout_seconds: int = 30,
) -> tuple[futs.Solution, float]:
  executor = Flow1160Executor(timeout_seconds)
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_score = executor(problem, root_solution)
  root = futs.Node(0, None, root_solution, root_score, num_visits=1)
  _record_node(logger, root, executor.last_evaluation)
  evaluations = _evaluation_rows([root], {0: executor.last_evaluation})
  _set_mutator_feedback(
      mutator,
      nodes=[root],
      evaluations=evaluations,
      parent=root,
      next_node_id=1,
      timeout_seconds=timeout_seconds,
  )

  candidate = mutator(problem, root_solution, root_score)
  candidate_score = executor(problem, candidate)
  child = futs.Node(1, 0, candidate, candidate_score, num_visits=1)
  _record_node(logger, child, executor.last_evaluation, root_solution.program)

  if candidate_score > root_score:
    return candidate, candidate_score
  return root_solution, root_score
