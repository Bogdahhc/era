"""Best-of-N and traced FUTS loops for job-shop scheduling."""

from __future__ import annotations

import json
import math
from pathlib import Path

from implementation import futs
from implementation.job_shop_era.executor import JobShopExecutor
from implementation.job_shop_era.logger import ExperimentLogger, NodeRecord
from implementation.job_shop_era.seed import baseline_candidate_code


def _record_node(
    logger: ExperimentLogger,
    node: futs.Node,
    evaluation,
    parent_code: str | None = None,
) -> None:
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


def _reached_optimum(problem, evaluation) -> bool:
  optimum = getattr(problem, "optimum", None)
  return (
      optimum is not None
      and evaluation is not None
      and evaluation.makespan is not None
      and evaluation.makespan <= optimum
  )


def run_best_of_n(
    problem,
    mutator,
    num_iterations: int,
    logger: ExperimentLogger,
    initial_code: str | None = None,
    timeout_seconds: int = 30,
    early_stop_at_optimum: bool = False,
) -> tuple[futs.Solution, float]:
  """Runs the stage-1 Best-of-N baseline."""
  executor = JobShopExecutor(timeout_seconds)
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_score = executor(problem, root_solution)
  best_solution = root_solution
  best_score = root_score
  root = futs.Node(0, None, root_solution, root_score, num_visits=1)
  _record_node(logger, root, executor.last_evaluation)
  if early_stop_at_optimum and _reached_optimum(problem, executor.last_evaluation):
    return best_solution, best_score

  for node_id in range(1, num_iterations + 1):
    solution = mutator(problem, root_solution, root_score)
    score = executor(problem, solution)
    node = futs.Node(node_id, 0, solution, score, num_visits=1)
    _record_node(logger, node, executor.last_evaluation, root_solution.program)
    if score > best_score:
      best_solution = solution
      best_score = score
    if early_stop_at_optimum and _reached_optimum(problem, executor.last_evaluation):
      break

  return best_solution, best_score


def run_single_generation(
    problem,
    mutator,
    logger: ExperimentLogger,
    initial_code: str | None = None,
    timeout_seconds: int = 30,
) -> tuple[futs.Solution, float]:
  """Runs one generate -> execute -> score pass without FUTS selection."""
  executor = JobShopExecutor(timeout_seconds)
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_score = executor(problem, root_solution)
  root = futs.Node(0, None, root_solution, root_score, num_visits=1)
  _record_node(logger, root, executor.last_evaluation)

  candidate = mutator(problem, root_solution, root_score)
  candidate_score = executor(problem, candidate)
  child = futs.Node(1, 0, candidate, candidate_score, num_visits=1)
  _record_node(logger, child, executor.last_evaluation, root_solution.program)

  if candidate_score > root_score:
    return candidate, candidate_score
  return root_solution, root_score


def run_futs(
    problem,
    mutator,
    num_iterations: int,
    logger: ExperimentLogger,
    initial_code: str | None = None,
    timeout_seconds: int = 30,
    c_puct: float = 1.0,
    early_stop_at_optimum: bool = False,
) -> tuple[futs.Solution, float]:
  """Runs FUTS while preserving node-level records for plots and review."""
  executor = JobShopExecutor(timeout_seconds)
  root_solution = futs.Solution(initial_code or baseline_candidate_code())
  root_score = executor(problem, root_solution)
  nodes = [futs.Node(0, None, root_solution, root_score, num_visits=1)]
  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  _record_node(logger, nodes[0], executor.last_evaluation)
  if early_stop_at_optimum and _reached_optimum(problem, executor.last_evaluation):
    logger.write_tree(nodes)
    logger.write_puct_audit(nodes, c_puct)
    return root_solution, root_score

  for _ in range(num_iterations):
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    parent = max(nodes, key=lambda node: node.puct)
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
    futs.backpropagate_visit(nodes, child)
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    _record_node(logger, child, executor.last_evaluation, parent.solution.program)
    logger.write_tree(nodes)
    logger.write_puct_audit(nodes, c_puct)
    if early_stop_at_optimum and _reached_optimum(problem, executor.last_evaluation):
      break

  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  logger.write_tree(nodes)
  logger.write_puct_audit(nodes, c_puct)
  best = max(nodes, key=lambda node: node.score)
  return best.solution, best.score


def load_nodes_from_experiment(experiment_dir: str | Path) -> list[futs.Node]:
  """Reconstructs FUTS nodes from an existing job_shop_era experiment."""
  experiment_path = Path(experiment_dir)
  nodes_path = experiment_path / "nodes.jsonl"
  candidates_path = experiment_path / "candidates"
  if not nodes_path.exists():
    raise FileNotFoundError(f"Missing nodes log: {nodes_path}")

  records = []
  with nodes_path.open("r", encoding="utf-8") as f:
    for line in f:
      if line.strip():
        records.append(json.loads(line))
  if not records:
    raise ValueError(f"No nodes found in {nodes_path}")

  tree_by_id = {}
  tree_path = experiment_path / "tree.json"
  if tree_path.exists():
    with tree_path.open("r", encoding="utf-8") as f:
      tree_by_id = {row["node_id"]: row for row in json.load(f)}

  nodes = []
  for record in records:
    node_id = record["node_id"]
    code_path = candidates_path / f"node_{node_id:04d}.py"
    if not code_path.exists():
      raise FileNotFoundError(f"Missing candidate code: {code_path}")
    score = record.get("score")
    if score is None:
      score = float("-inf")
    tree_row = tree_by_id.get(node_id, {})
    nodes.append(
        futs.Node(
            index=node_id,
            parent_index=record["parent_id"],
            solution=futs.Solution(code_path.read_text(encoding="utf-8")),
            score=score,
            num_visits=tree_row.get("visits", record.get("visits", 1)),
            rank_score=tree_row.get("rank_score", record.get("rank_score", 0.5)),
            puct=tree_row.get("puct", record.get("puct", 0.5)),
        )
    )

  expected_ids = list(range(len(nodes)))
  actual_ids = [node.index for node in nodes]
  if actual_ids != expected_ids:
    raise ValueError(
        "Resume requires contiguous node ids starting at 0; "
        f"found {actual_ids[:5]}...{actual_ids[-5:]}"
    )
  return nodes


def run_futs_from_nodes(
    problem,
    mutator,
    nodes: list[futs.Node],
    num_iterations: int,
    logger: ExperimentLogger,
    timeout_seconds: int = 30,
    c_puct: float = 1.0,
    early_stop_at_optimum: bool = False,
) -> tuple[futs.Solution, float]:
  """Continues a traced FUTS run from reconstructed experiment nodes."""
  if not nodes:
    raise ValueError("Cannot resume FUTS with no existing nodes.")

  executor = JobShopExecutor(timeout_seconds)
  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)

  for _ in range(num_iterations):
    parent = max(nodes, key=lambda node: node.puct)
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
    futs.backpropagate_visit(nodes, child)
    futs.compute_rank_scores(nodes)
    futs.compute_pucts(nodes, c_puct)
    _record_node(logger, child, executor.last_evaluation, parent.solution.program)
    if early_stop_at_optimum and _reached_optimum(problem, executor.last_evaluation):
      break

  futs.compute_rank_scores(nodes)
  futs.compute_pucts(nodes, c_puct)
  logger.write_tree(nodes)
  logger.write_puct_audit(nodes, c_puct)
  best = max(nodes, key=lambda node: node.score if math.isfinite(node.score) else -math.inf)
  return best.solution, best.score
