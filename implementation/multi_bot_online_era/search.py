"""Traced FUTS loops for multi-bot online scheduling."""

from __future__ import annotations

import difflib

from implementation import futs
from implementation.job_shop_era.logger import ExperimentLogger, NodeRecord
from implementation.multi_bot_online_era.executor import MultiBotOnlineExecutor
from implementation.multi_bot_online_era.seed import baseline_candidate_code


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
    scenario_config: dict | None = None,
) -> None:
  if not hasattr(mutator, "set_feedback_context"):
    return
  best = max(nodes, key=lambda node: node.score)
  recent_nodes = nodes[-5:]
  context = {
      "next_node_id": next_node_id,
      "timeout_seconds": timeout_seconds,
      "score_contract": (
          "Every node is executed and scored by MultiBotOnlineExecutor against "
          "an online command stream. Candidates must expose DynamicScheduler "
          "with handle_command(command), return valid schedules after initial "
          "and post-insertion reschedule commands, and receive score="
          "-(post_insert_makespan + stability_penalty + elapsed_seconds/100). "
          "Invalid interfaces, non-CP-SAT code, infeasible schedules, crashes, "
          "or timeouts receive the worst score and remain in the FUTS tree as "
          "failed nodes."
      ),
      "parent": evaluations.get(parent.index),
      "best": evaluations.get(best.index),
      "lineage": [evaluations[node.index] for node in _lineage(parent, nodes)],
      "recent": [evaluations[node.index] for node in recent_nodes],
      "parent_code_summary": _code_summary(parent.solution.program),
  }
  if scenario_config:
    context["scenario_config"] = scenario_config
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
    scenario_seed: int = 0,
    insertion_count: int = 1,
    inserted_jobs: int = 2,
    inserted_task_count: int = 4,
    insert_window_ratio: tuple[float, float] = (0.10, 0.60),
    insert_times: list[int] | None = None,
    enforce_even_centrifuge_inserts: bool = False,
) -> tuple[futs.Solution, float]:
  scenario_config = {
      "scenario_seed": scenario_seed,
      "insertion_count": insertion_count,
      "inserted_jobs": inserted_jobs,
      "inserted_task_count": inserted_task_count,
      "insert_window_ratio": list(insert_window_ratio),
      "insert_times": list(insert_times) if insert_times is not None else None,
      "enforce_even_centrifuge_inserts": enforce_even_centrifuge_inserts,
  }
  executor = MultiBotOnlineExecutor(
      timeout_seconds,
      scenario_seed=scenario_seed,
      insertion_count=insertion_count,
      inserted_jobs=inserted_jobs,
      inserted_task_count=inserted_task_count,
      insert_window_ratio=insert_window_ratio,
      insert_times=insert_times,
      enforce_even_centrifuge_inserts=enforce_even_centrifuge_inserts,
  )
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
        scenario_config=scenario_config,
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
    scenario_seed: int = 0,
    insertion_count: int = 1,
    inserted_jobs: int = 2,
    inserted_task_count: int = 4,
    insert_window_ratio: tuple[float, float] = (0.10, 0.60),
    insert_times: list[int] | None = None,
    enforce_even_centrifuge_inserts: bool = False,
) -> tuple[futs.Solution, float]:
  scenario_config = {
      "scenario_seed": scenario_seed,
      "insertion_count": insertion_count,
      "inserted_jobs": inserted_jobs,
      "inserted_task_count": inserted_task_count,
      "insert_window_ratio": list(insert_window_ratio),
      "insert_times": list(insert_times) if insert_times is not None else None,
      "enforce_even_centrifuge_inserts": enforce_even_centrifuge_inserts,
  }
  executor = MultiBotOnlineExecutor(
      timeout_seconds,
      scenario_seed=scenario_seed,
      insertion_count=insertion_count,
      inserted_jobs=inserted_jobs,
      inserted_task_count=inserted_task_count,
      insert_window_ratio=insert_window_ratio,
      insert_times=insert_times,
      enforce_even_centrifuge_inserts=enforce_even_centrifuge_inserts,
  )
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
      scenario_config=scenario_config,
  )

  candidate = mutator(problem, root_solution, root_score)
  candidate_score = executor(problem, candidate)
  child = futs.Node(1, 0, candidate, candidate_score, num_visits=1)
  _record_node(logger, child, executor.last_evaluation, root_solution.program)

  if candidate_score > root_score:
    return candidate, candidate_score
  return root_solution, root_score
