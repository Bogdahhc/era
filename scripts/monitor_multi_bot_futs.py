#!/usr/bin/env python3
"""Periodic monitor for multi_bot_era FUTS experiments."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path


EXPERIMENTS_ROOT = Path("/home/era/experiments")

DEFAULT_ORIGINAL = (
    EXPERIMENTS_ROOT
    / "multi_bot_4_experiments_cold_start_futs_20_nodes_19iter_450s_gpt55_restored_20260622_1814"
)
DEFAULT_X2 = (
    EXPERIMENTS_ROOT
    / "multi_bot_4_experiments_x2_cold_start_futs_50_nodes_49iter_450s_gpt55_restored_20260622_1814"
)
DEFAULT_REFERENCE = (
    EXPERIMENTS_ROOT / "multi_bot_e1_e5_merged_pure_cold_start_20_iter_modeling_prompt"
)
DEFAULT_OUTPUT = EXPERIMENTS_ROOT / "monitor_multi_bot_restored_20260622_1815"

TOKENS = [
    "cp_model",
    "CpModel",
    "CpSolver",
    "NewIntVar",
    "NewBoolVar",
    "NewIntervalVar",
    "AddNoOverlap",
    "AddCumulative",
    "OnlyEnforceIf",
    "AddMaxEquality",
    "Minimize",
    "Solve",
    "assignments",
    "dataset[\"fjspb\"]",
    "cur_ptr",
    "fixed",
    "is_fixed",
    "batch",
    "temperature",
    "centrifuge",
    "recycle",
    "duration",
    "machines",
]


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--interval-seconds", type=int, default=1800)
  parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
  parser.add_argument("--original-dir", type=Path, default=DEFAULT_ORIGINAL)
  parser.add_argument("--x2-dir", type=Path, default=DEFAULT_X2)
  parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE)
  parser.add_argument("--once", action="store_true")
  args = parser.parse_args()

  args.output_dir.mkdir(parents=True, exist_ok=True)
  while True:
    snapshot = collect_snapshot(args)
    write_snapshot(args.output_dir, snapshot)
    if args.once:
      return
    time.sleep(args.interval_seconds)


def collect_snapshot(args: argparse.Namespace) -> dict:
  now = time.strftime("%Y-%m-%d %H:%M:%S %z")
  runs = {
      "original_4_experiments_20_nodes": summarize_experiment(args.original_dir),
      "x2_4_experiments_50_nodes": summarize_experiment(args.x2_dir),
      "reference_e1_e5_cold_start": summarize_experiment(args.reference_dir),
  }
  reference_script = select_script(args.reference_dir)
  comparisons = {
      "original_vs_reference": compare_scripts(
          select_script(args.original_dir), reference_script
      ),
      "x2_vs_reference": compare_scripts(select_script(args.x2_dir), reference_script),
  }
  return {
      "timestamp": now,
      "processes": find_processes(),
      "runs": runs,
      "comparisons": comparisons,
  }


def summarize_experiment(path: Path) -> dict:
  rows = read_nodes(path / "nodes.jsonl")
  finite = [row for row in rows if row.get("score") is not None]
  feasible = [row for row in rows if row.get("feasible")]
  best = max(finite, key=lambda row: row["score"], default=None)
  candidates = sorted((path / "candidates").glob("node_*.py"))
  selected = select_script(path)
  return {
      "path": str(path),
      "exists": path.exists(),
      "node_count": len(rows),
      "candidate_count": len(candidates),
      "feasible_count": len(feasible),
      "best": compact_node(best),
      "latest_nodes": [compact_node(row) for row in rows[-5:]],
      "selected_script": str(selected) if selected else None,
      "selected_script_bytes": selected.stat().st_size if selected else None,
      "run_log_tail": tail_text(path / "run.log", 4000),
  }


def read_nodes(path: Path) -> list[dict]:
  if not path.exists():
    return []
  rows = []
  for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
      continue
    try:
      rows.append(json.loads(line))
    except json.JSONDecodeError:
      rows.append({"parse_error": line[:200]})
  return rows


def compact_node(row: dict | None) -> dict | None:
  if row is None:
    return None
  return {
      "node_id": row.get("node_id"),
      "parent_id": row.get("parent_id"),
      "feasible": row.get("feasible"),
      "makespan": row.get("makespan"),
      "score": row.get("score"),
      "elapsed_seconds": row.get("elapsed_seconds"),
      "error": shorten(row.get("error")),
  }


def select_script(exp_dir: Path) -> Path | None:
  best = exp_dir / "best.py"
  if best.exists():
    return best
  candidates = sorted((exp_dir / "candidates").glob("node_*.py"))
  return candidates[-1] if candidates else None


def compare_scripts(left: Path | None, right: Path | None) -> dict:
  if left is None or right is None:
    return {
        "left": str(left) if left else None,
        "right": str(right) if right else None,
        "available": False,
      }
  left_text = left.read_text(encoding="utf-8", errors="replace")
  right_text = right.read_text(encoding="utf-8", errors="replace")
  diff = "\n".join(
      difflib.unified_diff(
          right_text.splitlines(),
          left_text.splitlines(),
          fromfile=str(right),
          tofile=str(left),
          lineterm="",
          n=3,
      )
  )
  return {
      "left": str(left),
      "right": str(right),
      "available": True,
      "same_sha256": sha256(left_text) == sha256(right_text),
      "left_summary": code_summary(left_text),
      "right_summary": code_summary(right_text),
      "diff_line_count": len(diff.splitlines()) if diff else 0,
      "diff_preview": diff[:12000],
  }


def code_summary(text: str) -> dict:
  imports = re.findall(r"^(?:from\s+\S+\s+import\s+.+|import\s+.+)$", text, re.M)
  defs = re.findall(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M)
  return {
      "bytes": len(text.encode("utf-8", errors="replace")),
      "lines": len(text.splitlines()),
      "sha256": sha256(text),
      "imports": imports[:20],
      "defs": defs[:40],
      "token_counts": {token: text.count(token) for token in TOKENS},
  }


def find_processes() -> list[dict]:
  pattern = re.compile(
      r"implementation\.multi_bot_era\.cli|runner\.py|candidate\.py|era_multibot|multi_bot_4_experiments"
  )
  output = subprocess.run(
      ["ps", "-efww"], check=False, text=True, capture_output=True
  ).stdout
  rows = []
  for line in output.splitlines():
    if "monitor_multi_bot_futs.py" in line:
      continue
    if pattern.search(line):
      rows.append({"raw": line})
  return rows


def write_snapshot(output_dir: Path, snapshot: dict) -> None:
  latest_json = output_dir / "latest.json"
  latest_json.write_text(
      json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8"
  )
  append_log(output_dir / "monitor.log", snapshot)
  for name, comparison in snapshot["comparisons"].items():
    diff_preview = comparison.get("diff_preview") or ""
    (output_dir / f"{name}.latest.diff").write_text(diff_preview, encoding="utf-8")


def append_log(path: Path, snapshot: dict) -> None:
  lines = []
  lines.append("=" * 88)
  lines.append(f"timestamp: {snapshot['timestamp']}")
  lines.append("processes:")
  for proc in snapshot["processes"] or [{"raw": "none"}]:
    lines.append(f"  {proc['raw']}")
  lines.append("runs:")
  for name, run in snapshot["runs"].items():
    best = run.get("best") or {}
    lines.append(
        "  "
        + f"{name}: nodes={run['node_count']} candidates={run['candidate_count']} "
        + f"feasible={run['feasible_count']} best_node={best.get('node_id')} "
        + f"best_makespan={best.get('makespan')} best_score={best.get('score')} "
        + f"script={run.get('selected_script')}"
    )
    for row in run.get("latest_nodes", []):
      lines.append(
          "    "
          + f"node={row.get('node_id')} parent={row.get('parent_id')} "
          + f"feasible={row.get('feasible')} makespan={row.get('makespan')} "
          + f"score={row.get('score')} error={row.get('error')}"
      )
  lines.append("script comparisons:")
  for name, comparison in snapshot["comparisons"].items():
    lines.append(
        "  "
        + f"{name}: available={comparison.get('available')} "
        + f"same_sha256={comparison.get('same_sha256')} "
        + f"diff_lines={comparison.get('diff_line_count')} "
        + f"left={comparison.get('left')} right={comparison.get('right')}"
    )
    left = comparison.get("left_summary") or {}
    right = comparison.get("right_summary") or {}
    if left and right:
      lines.append(
          "    "
          + f"left bytes={left.get('bytes')} lines={left.get('lines')} "
          + f"defs={left.get('defs')[:8]}"
      )
      lines.append(
          "    "
          + f"right bytes={right.get('bytes')} lines={right.get('lines')} "
          + f"defs={right.get('defs')[:8]}"
      )
      token_delta = {
          token: left["token_counts"].get(token, 0)
          - right["token_counts"].get(token, 0)
          for token in TOKENS
      }
      lines.append(f"    token_delta_left_minus_right={token_delta}")
  lines.append("")
  with path.open("a", encoding="utf-8") as handle:
    handle.write("\n".join(lines))


def tail_text(path: Path, limit: int) -> str:
  if not path.exists():
    return ""
  text = path.read_text(encoding="utf-8", errors="replace")
  return text[-limit:]


def sha256(text: str) -> str:
  return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def shorten(value, limit: int = 240) -> str | None:
  if value is None:
    return None
  text = str(value).replace("\n", " ")
  return text if len(text) <= limit else text[: limit - 3] + "..."


if __name__ == "__main__":
  main()
