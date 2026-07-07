"""Plot utilities for flow_1160_era_v4 FUTS runs.

The legacy tree plots are re-exported from flow_1160_era.plot. V4 adds an
incremental progress plot that can be refreshed after every evaluated node and
can also be generated for interrupted experiment directories.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from implementation.flow_1160_era.plot import *  # noqa: F401,F403


def write_incremental_futs_plots(experiment_dir: str | Path) -> dict[str, str]:
  """Write per-node FUTS progress plots for a partial or complete v4 run."""

  root = Path(experiment_dir)
  root.mkdir(parents=True, exist_ok=True)
  nodes = _read_jsonl(root / "nodes.jsonl")
  pending = _read_jsonl(root / "pending_nodes.jsonl")
  adaptive = _read_json(root / "adaptive_logistics.json")
  adaptive_rows = adaptive.get("rows") or []

  outputs = {}
  outputs["progress_png"] = str(root / "v4_node_progress.png")
  outputs["progress_csv"] = str(root / "v4_node_progress.csv")
  outputs["summary_json"] = str(root / "v4_node_progress_summary.json")

  rows = _progress_rows(nodes, pending, adaptive_rows)
  plot_rows = _simulation_feasible_rows(rows)
  _write_progress_csv(Path(outputs["progress_csv"]), rows)
  _write_progress_summary(Path(outputs["summary_json"]), rows, adaptive, plot_rows)
  _plot_progress(Path(outputs["progress_png"]), plot_rows)
  return outputs


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
  if not path.exists():
    return []
  rows = []
  for line in path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
      continue
    try:
      value = json.loads(line)
    except Exception:
      continue
    if isinstance(value, dict):
      rows.append(value)
  return rows


def _read_json(path: Path) -> dict[str, Any]:
  if not path.exists():
    return {}
  try:
    value = json.loads(path.read_text(encoding="utf-8"))
  except Exception:
    return {}
  return value if isinstance(value, dict) else {}


def _progress_rows(
    nodes: list[dict[str, Any]],
    pending: list[dict[str, Any]],
    adaptive_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
  adaptive_by_node: dict[int, dict[str, Any]] = {}
  for row in adaptive_rows:
    if not isinstance(row, dict) or row.get("node_id") is None:
      continue
    adaptive_by_node[int(row["node_id"])] = row

  pending_ids = {
      int(row["node_id"])
      for row in pending
      if isinstance(row, dict) and row.get("node_id") is not None
  }
  evaluated_ids = {
      int(row["node_id"])
      for row in nodes
      if isinstance(row, dict) and row.get("node_id") is not None
  }

  result = []
  for row in nodes:
    if row.get("node_id") is None:
      continue
    node_id = int(row["node_id"])
    adaptive = adaptive_by_node.get(node_id, {})
    motion_feedback = adaptive.get("motion_feedback") or {}
    error = str(row.get("error") or adaptive.get("error") or adaptive.get("isaac_error") or "")
    result.append(
        {
            "node_id": node_id,
            "parent_id": row.get("parent_id"),
            "status": _status(row, adaptive, error),
            "feasible": bool(row.get("feasible")),
            "makespan": _num(row.get("makespan")),
            "score": _num(row.get("score")),
            "motion_safe": adaptive.get("motion_safe"),
            "isaac_ok": adaptive.get("isaac_ok"),
            "gap_seconds": adaptive.get("gap_seconds"),
            "motion_conflicts": _conflict_count(error),
            "explicit_conflicts": _num(
                motion_feedback.get("explicit_conflict_count", adaptive.get("explicit_conflict_count")),
                default=0,
            ),
            "timing_conflicts": _num(
                motion_feedback.get("timing_conflict_count", adaptive.get("timing_conflict_count")),
                default=0,
            ),
            "error": error,
        }
    )

  for node_id in sorted(pending_ids - evaluated_ids):
    result.append(
        {
            "node_id": node_id,
            "parent_id": None,
            "status": "pending",
            "feasible": False,
            "makespan": None,
            "score": None,
            "motion_safe": None,
            "isaac_ok": None,
            "gap_seconds": None,
            "motion_conflicts": None,
            "explicit_conflicts": None,
            "timing_conflicts": None,
            "error": "generated_pending_evaluation",
        }
    )
  return sorted(result, key=lambda row: row["node_id"])


def _status(row: dict[str, Any], adaptive: dict[str, Any], error: str) -> str:
  if row.get("feasible") and adaptive.get("isaac_ok") is True:
    return "isaac_ok"
  if row.get("feasible") and adaptive.get("motion_safe") is True:
    if "timeout" in error:
      return "motion_ok_isaac_timeout"
    return "motion_ok"
  if "robot_transfer_late" in error or "Isaac/motion monitor" in error:
    return "motion_rejected"
  if "command_assignments" in error:
    return "schema_rejected"
  if "must explicitly model/read" in error:
    return "guard_rejected"
  if "timeout" in error:
    return "timeout"
  return "rejected" if error else "unknown"


def _num(value: Any, default: float | int | None = None):
  try:
    if value is None:
      return default
    if isinstance(value, bool):
      return int(value)
    number = float(value)
    if math.isnan(number) or math.isinf(number):
      return default
    if number.is_integer():
      return int(number)
    return number
  except Exception:
    return default


def _conflict_count(error: str) -> int:
  marker = "conflicts="
  if marker not in error:
    return 0
  tail = error.split(marker, 1)[1]
  token = tail.split(None, 1)[0].split(",", 1)[0]
  try:
    return int(token)
  except Exception:
    return 0


def _write_progress_csv(path: Path, rows: list[dict[str, Any]]) -> None:
  fields = [
      "node_id",
      "parent_id",
      "status",
      "feasible",
      "makespan",
      "score",
      "motion_safe",
      "isaac_ok",
      "gap_seconds",
      "motion_conflicts",
      "explicit_conflicts",
      "timing_conflicts",
      "error",
  ]
  lines = [",".join(fields)]
  for row in rows:
    values = []
    for field in fields:
      text = "" if row.get(field) is None else str(row.get(field))
      values.append('"%s"' % text.replace('"', '""') if "," in text or '"' in text else text)
    lines.append(",".join(values))
  path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_progress_summary(
    path: Path,
    rows: list[dict[str, Any]],
    adaptive: dict[str, Any],
    plot_rows: list[dict[str, Any]],
) -> None:
  evaluated = [row for row in rows if row["status"] != "pending"]
  simulation_feasible = plot_rows
  feasible = [row for row in simulation_feasible if row.get("makespan") is not None]
  payload = {
      "node_count": len(evaluated),
      "pending_count": sum(1 for row in rows if row["status"] == "pending"),
      "status_counts": dict(Counter(row["status"] for row in rows)),
      "plotted_node_ids": [row["node_id"] for row in simulation_feasible],
      "plot_filter": "only nodes with feasible=True and status in {isaac_ok, motion_ok, motion_ok_isaac_timeout}",
      "best_by_makespan": min(feasible, key=lambda row: row["makespan"]) if feasible else None,
      "best_by_score": max(feasible, key=lambda row: row["score"] if row.get("score") is not None else -10**99) if feasible else None,
      "adaptive_current_gap": adaptive.get("current_gap"),
      "adaptive_isaac_timeout_seconds": adaptive.get("isaac_timeout_seconds"),
  }
  path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _simulation_feasible_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
  allowed = {"isaac_ok", "motion_ok", "motion_ok_isaac_timeout"}
  return [
      row
      for row in rows
      if row.get("feasible") and row.get("status") in allowed
  ]


def _plot_progress(path: Path, rows: list[dict[str, Any]]) -> None:
  if not rows:
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.text(0.5, 0.5, "No simulation-feasible nodes yet", ha="center", va="center")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return

  x = [row["node_id"] for row in rows]
  makespan = [row.get("makespan") for row in rows]
  conflicts = [row.get("motion_conflicts") for row in rows]
  timing = [row.get("timing_conflicts") for row in rows]
  explicit = [row.get("explicit_conflicts") for row in rows]

  fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=True)
  status_colors = {
      "isaac_ok": "#2ca02c",
      "motion_ok": "#1f77b4",
      "motion_ok_isaac_timeout": "#9467bd",
      "motion_rejected": "#d62728",
      "schema_rejected": "#ff7f0e",
      "guard_rejected": "#8c564b",
      "timeout": "#7f7f7f",
      "pending": "#bcbd22",
      "rejected": "#e377c2",
      "unknown": "#c7c7c7",
  }
  colors = [status_colors.get(row["status"], "#c7c7c7") for row in rows]

  axes[0].scatter(x, [v if v is not None else math.nan for v in makespan], c=colors, s=55)
  axes[0].plot(x, [v if v is not None else math.nan for v in makespan], color="#999999", linewidth=1)
  axes[0].set_ylabel("makespan (s)")
  axes[0].grid(True, alpha=0.25)

  axes[1].bar(x, [v or 0 for v in conflicts], color="#d62728", alpha=0.75, label="all motion conflicts")
  axes[1].bar(x, [v or 0 for v in timing], color="#ff9896", alpha=0.75, label="timing conflicts")
  axes[1].plot(x, [v or 0 for v in explicit], marker="o", color="#111111", label="explicit conflicts")
  axes[1].set_ylabel("conflicts")
  axes[1].legend(loc="upper right")
  axes[1].grid(True, axis="y", alpha=0.25)

  y = list(range(len(rows)))
  axes[2].scatter(x, y, c=colors, s=70)
  axes[2].set_yticks(y)
  axes[2].set_yticklabels([row["status"] for row in rows], fontsize=8)
  axes[2].set_xlabel("node id")
  axes[2].set_ylabel("status")
  axes[2].grid(True, axis="x", alpha=0.25)

  fig.suptitle("flow_1160_era_v4 FUTS node progress")
  fig.tight_layout()
  fig.savefig(path, dpi=160)
  plt.close(fig)


def main() -> None:
  parser = argparse.ArgumentParser(description="Render v4 FUTS progress plots for a complete or interrupted run.")
  parser.add_argument("experiment_dir")
  args = parser.parse_args()
  outputs = write_incremental_futs_plots(args.experiment_dir)
  print(json.dumps(outputs, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
