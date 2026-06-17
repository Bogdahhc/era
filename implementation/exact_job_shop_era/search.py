"""Traced FUTS loop for CP-SAT Python solver candidates."""

from __future__ import annotations

from implementation import futs
from implementation.exact_job_shop_era.executor import ExactJobShopExecutor
from implementation.exact_job_shop_era.logger import (
    ExactExperimentLogger,
    ExactNodeRecord,
)
from implementation.exact_job_shop_era.seed import baseline_cp_sat_candidate_code


def _record(
    logger: ExactExperimentLogger,
    node: futs.Node,
    evaluation,
    score_mode: str,
) -> None:
  parent_hash = None
  if node.parent_index is not None:
    parent_hash = logger.spec_hash_by_node.get(node.parent_index)
  logger.record(
      ExactNodeRecord(
          node_id=node.index,
          parent_id=node.parent_index,
          score=node.score,
          feasible=evaluation.feasible,
          makespan=evaluation.makespan,
          status=evaluation.status,
          elapsed_seconds=evaluation.elapsed_seconds,
          best_bound=evaluation.best_bound,
          relative_gap=evaluation.relative_gap,
          branches=evaluation.branches,
          conflicts=evaluation.conflicts,
          spec_hash=logger.hash_spec(node.solution.program),
          parent_spec_hash=parent_hash,
          visits=node.num_visits,
          rank_score=node.rank_score,
          puct=node.puct,
          error=evaluation.error,
          score_mode=score_mode,
      ),
      node.solution.program,
  )


def _evaluation_row(node: futs.Node, evaluation) -> dict:
  return {
      "node_id": node.index,
      "parent_id": node.parent_index,
      "score": node.score,
      "feasible": evaluation.feasible,
      "makespan": evaluation.makespan,
      "status": evaluation.status,
      "elapsed_seconds": evaluation.elapsed_seconds,
      "best_bound": evaluation.best_bound,
      "relative_gap": evaluation.relative_gap,
      "branches": evaluation.branches,
      "conflicts": evaluation.conflicts,
      "error": evaluation.error,
  }


def _reached_optimum(problem, evaluation) -> bool:
  optimum = getattr(problem, "optimum", None)
  return (
      optimum is not None
      and evaluation is not None
      and evaluation.makespan is not None
      and evaluation.makespan <= optimum
  )


def _runtime_weighted_score(evaluation, makespan_weight: float) -> float:
  del makespan_weight
  return evaluation.score


def _apply_score_mode(
    nodes: list[futs.Node],
    raw_evaluations: dict[int, object],
    *,
    score_mode: str,
    runtime_score_makespan_weight: float,
) -> None:
  for node in nodes:
    evaluation = raw_evaluations[node.index]
    if score_mode == "runtime_after_optimum":
      node.score = _runtime_weighted_score(
          evaluation, runtime_score_makespan_weight
      )
    else:
      node.score = evaluation.score


def _evaluation_rows(
    nodes: list[futs.Node], raw_evaluations: dict[int, object]
) -> dict[int, dict]:
  return {
      node.index: _evaluation_row(node, raw_evaluations[node.index])
      for node in nodes
  }


def _set_mutator_feedback(
    mutator,
    *,
    nodes: list[futs.Node],
    evaluations: dict[int, dict],
    parent: futs.Node,
    next_node_id: int,
    timeout_seconds: int,
    score_mode: str,
) -> None:
  if not hasattr(mutator, "set_feedback_context"):
    return
  best = max(nodes, key=lambda node: node.score)
  context = {
      "next_node_id": next_node_id,
      "timeout_seconds": timeout_seconds,
      "score_mode": score_mode,
      "parent": evaluations.get(parent.index),
      "best": evaluations.get(best.index),
      "recent": [evaluations[node.index] for node in nodes[-5:]],
  }
  mutator.set_feedback_context(context)


def run_futs(
    problem,
    mutator,
    num_iterations: int,
    logger: ExactExperimentLogger,
    initial_code: str | None = None,
    c_puct: float = 1.0,
    timeout_seconds: int = 30,
    early_stop_at_optimum: bool = False,
    optimize_runtime_after_optimum: bool = False,
    runtime_score_makespan_weight: float = 100.0,
) -> tuple[futs.Solution, float]:
  executor = ExactJobShopExecutor(timeout_seconds=timeout_seconds)
  root_solution = futs.Solution(
      initial_code or baseline_cp_sat_candidate_code(timeout_seconds)
  )
  root_score = executor(problem, root_solution)
  nodes = [futs.Node(0, None, root_solution, root_score, num_visits=1)]
  raw_evaluations = {0: executor.last_evaluation}
  score_mode = "makespan"
  optimum_found = _reached_optimum(problem, executor.last_evaluation)
  if optimize_runtime_after_optimum and optimum_found:
    score_mode = "runtime_after_optimum"
    _apply_score_mode(
        nodes,
        raw_evaluations,
        score_mode=score_mode,
        runtime_score_makespan_weight=runtime_score_makespan_weight,
    )
  evaluations = _evaluation_rows(nodes, raw_evaluations)
  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  _record(logger, nodes[0], executor.last_evaluation, score_mode)
  if (
      early_stop_at_optimum
      and not optimize_runtime_after_optimum
      and optimum_found
  ):
    logger.write_tree(nodes)
    return root_solution, root_score

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
        score_mode=score_mode,
    )
    child_solution = mutator(problem, parent.solution, parent.score)
    child_score = executor(problem, child_solution)
    child = futs.Node(
        index=len(nodes),
        parent_index=parent.index,
        solution=child_solution,
        score=child_score,
        num_visits=1,
    )
    nodes.append(child)
    raw_evaluations[child.index] = executor.last_evaluation
    if (
        optimize_runtime_after_optimum
        and not optimum_found
        and _reached_optimum(problem, executor.last_evaluation)
    ):
      optimum_found = True
      score_mode = "runtime_after_optimum"
    _apply_score_mode(
        nodes,
        raw_evaluations,
        score_mode=score_mode,
        runtime_score_makespan_weight=runtime_score_makespan_weight,
    )
    evaluations = _evaluation_rows(nodes, raw_evaluations)
    futs.backpropagate_visit(nodes, child)
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    _record(logger, child, executor.last_evaluation, score_mode)
    logger.write_tree(nodes)
    if (
        early_stop_at_optimum
        and not optimize_runtime_after_optimum
        and _reached_optimum(problem, executor.last_evaluation)
    ):
      break

  logger.write_tree(nodes)
  best = max(nodes, key=lambda node: node.score)
  return best.solution, best.score
