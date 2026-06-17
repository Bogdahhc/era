"""Experiment logging for exact-solver spec FUTS runs."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import platform
import subprocess
import time
from pathlib import Path


@dataclasses.dataclass
class ExactNodeRecord:
  node_id: int
  parent_id: int | None
  score: float
  feasible: bool
  makespan: int | None
  status: str | None
  elapsed_seconds: float
  best_bound: float | None
  relative_gap: float | None
  branches: int | None
  conflicts: int | None
  spec_hash: str
  parent_spec_hash: str | None
  visits: int
  rank_score: float
  puct: float
  error: str | None = None
  score_mode: str | None = None


def _json_ready(record: ExactNodeRecord) -> dict:
  row = dataclasses.asdict(record)
  if not math.isfinite(row["score"]):
    row["score"] = None
  return row


class ExactExperimentLogger:
  def __init__(self, root: str | Path, experiment_name: str | None = None):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    self.path = Path(root) / (experiment_name or f"exact_job_shop_{stamp}")
    self.nodes_path = self.path / "nodes.jsonl"
    self.versions_path = self.path / "versions.jsonl"
    self.summary_path = self.path / "version_summary.csv"
    self.manifest_path = self.path / "run_manifest.json"
    self.candidates_path = self.path / "candidates"
    self.specs_path = self.candidates_path
    self.instance_name: str | None = None
    self.spec_hash_by_node: dict[int, str] = {}
    self.spec_by_node: dict[int, dict] = {}
    self.record_by_node: dict[int, dict] = {}
    self.candidates_path.mkdir(parents=True, exist_ok=True)

  def record(self, record: ExactNodeRecord, spec_json: str) -> None:
    self.spec_hash_by_node[record.node_id] = record.spec_hash
    spec = _load_spec_dict(spec_json)
    self.spec_by_node[record.node_id] = spec
    (self.candidates_path / f"node_{record.node_id:04d}.py").write_text(
        spec_json,
        encoding="utf-8",
    )
    row = _json_ready(record)
    self.record_by_node[record.node_id] = row
    with self.nodes_path.open("a", encoding="utf-8") as f:
      f.write(json.dumps(row) + "\n")
    version_row = self._build_version_row(record.node_id, row, spec)
    with self.versions_path.open("a", encoding="utf-8") as f:
      f.write(json.dumps(version_row, sort_keys=True) + "\n")
    self.write_summary()

  def write_manifest(self, *, problem, args, root_candidate: str) -> None:
    self.instance_name = problem.instance_name
    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "experiment_dir": str(self.path),
        "problem": {
            "instance_name": problem.instance_name,
            "optimum": problem.optimum,
            "description": problem.description,
        },
        "cli_args": vars(args) if hasattr(args, "__dict__") else dict(args),
        "root_candidate": root_candidate,
        "architecture": {
            "name": "exact_job_shop_era",
            "node_representation": "Python CP-SAT solve(instance) candidate",
            "executor": "ExactJobShopExecutor",
            "backend": "candidate code may import ortools.sat.python.cp_model",
            "baseline_architecture": "implementation.job_shop_era generates unrestricted Python solve(instance) code",
        },
        "code_state": _code_state(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    self.manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

  def write_tree(self, nodes) -> None:
    rows = []
    for node in nodes:
      rows.append(
          {
              "node_id": node.index,
              "parent_id": node.parent_index,
              "score": node.score if math.isfinite(node.score) else None,
              "visits": node.num_visits,
              "rank_score": node.rank_score,
              "puct": node.puct,
              "spec_hash": self.spec_hash_by_node.get(node.index),
              "parent_spec_hash": (
                  self.spec_hash_by_node.get(node.parent_index)
                  if node.parent_index is not None
                  else None
              ),
          }
      )
    (self.path / "tree.json").write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )

  def write_summary(self) -> None:
    fields = [
        "node_id",
        "parent_id",
        "version_label",
        "makespan",
        "delta_makespan_vs_parent",
        "delta_makespan_vs_root",
        "score",
        "score_mode",
        "status",
        "best_bound",
        "relative_gap",
        "elapsed_seconds",
        "branches",
        "conflicts",
        "changed_fields",
        "candidate",
        "spec_hash",
        "parent_spec_hash",
    ]
    lines = [",".join(fields)]
    for node_id in sorted(self.record_by_node):
      row = self._build_version_row(
          node_id, self.record_by_node[node_id], self.spec_by_node[node_id]
      )
      lines.append(",".join(_csv_cell(row.get(field)) for field in fields))
    self.summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

  @staticmethod
  def hash_spec(spec_json: str) -> str:
    return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()[:16]

  def _build_version_row(
      self, node_id: int, node_record: dict, spec: dict
  ) -> dict:
    parent_id = node_record.get("parent_id")
    parent_spec = self.spec_by_node.get(parent_id, {}) if parent_id is not None else {}
    root_spec = self.spec_by_node.get(0, {})
    parent_record = (
        self.record_by_node.get(parent_id, {}) if parent_id is not None else {}
    )
    root_record = self.record_by_node.get(0, {})
    makespan = node_record.get("makespan")
    parent_makespan = parent_record.get("makespan")
    root_makespan = root_record.get("makespan")
    spec_delta_parent = _dict_diff(parent_spec, spec)
    spec_delta_root = _dict_diff(root_spec, spec)
    return {
        "node_id": node_id,
        "parent_id": parent_id,
        "version_label": f"node_{node_id:04d}",
        "spec_hash": node_record.get("spec_hash"),
        "parent_spec_hash": node_record.get("parent_spec_hash"),
        "candidate": f"candidates/node_{node_id:04d}.py",
        "score": node_record.get("score"),
        "feasible": node_record.get("feasible"),
        "makespan": makespan,
        "status": node_record.get("status"),
        "best_bound": node_record.get("best_bound"),
        "relative_gap": node_record.get("relative_gap"),
        "elapsed_seconds": node_record.get("elapsed_seconds"),
        "branches": node_record.get("branches"),
        "conflicts": node_record.get("conflicts"),
        "error": node_record.get("error"),
        "score_mode": node_record.get("score_mode"),
        "spec": spec,
        "changed_fields": sorted(spec_delta_parent),
        "spec_delta_parent": spec_delta_parent,
        "spec_delta_root": spec_delta_root,
        "delta_makespan_vs_parent": _delta(parent_makespan, makespan),
        "delta_makespan_vs_root": _delta(root_makespan, makespan),
        "improved_vs_parent": _improved(parent_makespan, makespan),
        "improved_vs_root": _improved(root_makespan, makespan),
    }


def _load_spec_dict(spec_json: str) -> dict:
  try:
    data = json.loads(spec_json)
  except json.JSONDecodeError:
    return {"_raw": spec_json}
  return data if isinstance(data, dict) else {"_raw": data}


def _dict_diff(before: dict, after: dict) -> dict:
  keys = sorted(set(before) | set(after))
  return {
      key: {"before": before.get(key), "after": after.get(key)}
      for key in keys
      if before.get(key) != after.get(key)
  }


def _delta(before, after):
  if before is None or after is None:
    return None
  return after - before


def _improved(before, after):
  if before is None or after is None:
    return None
  return after < before


def _csv_cell(value) -> str:
  if value is None:
    return ""
  if isinstance(value, (list, dict)):
    value = json.dumps(value, sort_keys=True)
  text = str(value)
  if any(char in text for char in ',\n"'):
    text = '"' + text.replace('"', '""') + '"'
  return text


def _code_state() -> dict:
  return {
      "git_head": _run_git(["rev-parse", "HEAD"]),
      "git_status_short": _run_git(["status", "--short"]),
      "tracked_diff_hash": hashlib.sha256(
          (_run_git(["diff"]) or "").encode("utf-8")
      ).hexdigest()[:16],
      "exact_module_file_hashes": _file_hashes(
          Path(__file__).resolve().parent
      ),
  }


def _run_git(args: list[str]) -> str | None:
  try:
    result = subprocess.run(
        ["git", "-c", "safe.directory=/home/era", "-C", "/home/era", *args],
        check=False,
        text=True,
        capture_output=True,
    )
  except OSError:
    return None
  if result.returncode != 0:
    return None
  return result.stdout.strip()


def _file_hashes(path: Path) -> dict[str, str]:
  hashes = {}
  for file_path in sorted(path.glob("*.py")):
    hashes[file_path.name] = hashlib.sha256(
        file_path.read_bytes()
    ).hexdigest()[:16]
  return hashes
