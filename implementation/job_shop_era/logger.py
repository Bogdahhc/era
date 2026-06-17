"""Experiment logging for job-shop FUTS runs."""

from __future__ import annotations

import dataclasses
import difflib
import json
import math
import time
from pathlib import Path


@dataclasses.dataclass
class NodeRecord:
  node_id: int
  parent_id: int | None
  score: float
  feasible: bool
  makespan: int | None
  elapsed_seconds: float
  visits: int
  rank_score: float
  puct: float
  error: str | None = None
  code_diff: str | None = None


def _json_ready(record: NodeRecord) -> dict:
  row = dataclasses.asdict(record)
  if not math.isfinite(row["score"]):
    row["score"] = None
  return row


def _expected_rank_scores(nodes) -> dict[int, float]:
  if len(nodes) == 1:
    return {nodes[0].index: 0.5}
  sorted_nodes = sorted(nodes, key=lambda node: node.score)
  expected_ranks = {}
  rank = 0
  while rank < len(sorted_nodes):
    next_rank = rank + 1
    while (
        next_rank < len(sorted_nodes)
        and sorted_nodes[next_rank].score == sorted_nodes[rank].score
    ):
      next_rank += 1
    average_rank = (rank + next_rank - 1) / 2
    rank_score = average_rank / (len(sorted_nodes) - 1)
    for node in sorted_nodes[rank:next_rank]:
      expected_ranks[node.index] = rank_score
    rank = next_rank
  return expected_ranks


class ExperimentLogger:
  """Writes nodes, candidates, and diffs under experiments/."""

  def __init__(self, root: str | Path, experiment_name: str | None = None):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    self.path = Path(root) / (experiment_name or f"job_shop_{stamp}")
    self.nodes_path = self.path / "nodes.jsonl"
    self.candidates_path = self.path / "candidates"
    self.candidates_path.mkdir(parents=True, exist_ok=True)

  def record(
      self,
      record: NodeRecord,
      code: str,
      parent_code: str | None = None,
  ) -> None:
    code_path = self.candidates_path / f"node_{record.node_id:04d}.py"
    code_path.write_text(code, encoding="utf-8")
    if parent_code is not None:
      record.code_diff = "\n".join(
          difflib.unified_diff(
              parent_code.splitlines(),
              code.splitlines(),
              fromfile="parent.py",
              tofile=f"node_{record.node_id:04d}.py",
              lineterm="",
          )
      )
    with self.nodes_path.open("a", encoding="utf-8") as f:
      f.write(json.dumps(_json_ready(record)) + "\n")

  def write_tree(self, nodes) -> None:
    """Writes a final tree snapshot with current visits, ranks, and PUCTs."""
    rows = []
    for node in nodes:
      score = node.score if math.isfinite(node.score) else None
      rows.append(
          {
              "node_id": node.index,
              "parent_id": node.parent_index,
              "score": score,
              "visits": node.num_visits,
              "rank_score": node.rank_score,
              "puct": node.puct,
          }
      )
    (self.path / "tree.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

  def write_puct_audit(self, nodes, c_puct: float) -> None:
    """Writes an audit of rank normalization and the PUCT formula."""
    expected_ranks = _expected_rank_scores(nodes)
    prior = 1 / len(nodes)
    total_visits = sum(node.num_visits for node in nodes)
    rows = []
    max_rank_error = 0.0
    max_puct_error = 0.0
    for node in nodes:
      expected_rank = expected_ranks[node.index]
      expected_puct = expected_rank + c_puct * prior * math.sqrt(
          total_visits
      ) / (1 + node.num_visits)
      rank_error = abs(node.rank_score - expected_rank)
      puct_error = abs(node.puct - expected_puct)
      max_rank_error = max(max_rank_error, rank_error)
      max_puct_error = max(max_puct_error, puct_error)
      rows.append(
          {
              "node_id": node.index,
              "score": node.score if math.isfinite(node.score) else None,
              "visits": node.num_visits,
              "rank_score": node.rank_score,
              "expected_rank_score": expected_rank,
              "rank_error": rank_error,
              "puct": node.puct,
              "expected_puct": expected_puct,
              "puct_error": puct_error,
          }
      )
    audit = {
        "num_nodes": len(nodes),
        "c_puct": c_puct,
        "prior": prior,
        "total_visits": total_visits,
        "max_rank_error": max_rank_error,
        "max_puct_error": max_puct_error,
        "passes": max_rank_error < 1e-12 and max_puct_error < 1e-12,
        "nodes": rows,
    }
    (self.path / "puct_audit.json").write_text(
        json.dumps(audit, indent=2),
        encoding="utf-8",
    )
