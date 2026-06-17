"""Plot helpers for multi-bot FJSPB FUTS runs."""

from __future__ import annotations

import json
import math
from pathlib import Path


BREAKTHROUGH_START_NODE_ID = 0
TREE_PLOT_START_NODE_ID = 0


def plot_breakthrough(nodes_jsonl: str | Path, output_path: str | Path) -> None:
  """Plots per-node score and best-so-far score."""
  import matplotlib.pyplot as plt

  rows = _load_node_rows(nodes_jsonl)
  score_rows = _finite_score_rows(rows, BREAKTHROUGH_START_NODE_ID)
  if not score_rows:
    raise ValueError(
        f"No finite score nodes with node_id >= {BREAKTHROUGH_START_NODE_ID}"
    )

  xs = [row["node_id"] for row in score_rows]
  scores = [_effective_score(row) for row in score_rows]
  best_so_far = []
  best_score = None
  for score in scores:
    best_score = score if best_score is None else max(best_score, score)
    best_so_far.append(best_score)
  best_row = max(score_rows, key=lambda row: _effective_score(row))
  best_row_score = _effective_score(best_row)

  fig, ax = plt.subplots(figsize=(8, 4.5))
  color_args, has_score_colors = _score_color_args(score_rows)
  scatter = ax.scatter(
      xs,
      scores,
      s=28,
      edgecolors="white",
      linewidths=0.4,
      alpha=0.88,
      label="node score",
      zorder=2,
      **color_args,
  )
  if has_score_colors:
    cbar = fig.colorbar(scatter, ax=ax, pad=0.015)
    cbar.set_label("-(makespan + elapsed/100), darker = better")
  ax.step(
      xs,
      best_so_far,
      where="post",
      color="#188038",
      linewidth=1.4,
      label="best so far",
  )
  ax.set_xlabel("Node")
  ax.set_ylabel("Node score (higher is better)")
  ax.set_title("Multi-bot FJSPB FUTS node scores")
  ax.grid(True, alpha=0.3)
  ax.annotate(
      (
          f"best node={best_row['node_id']}\n"
          f"score={best_row_score:.3g}\n"
          f"makespan={best_row.get('makespan')}"
      ),
      xy=(best_row["node_id"], best_row_score),
      xytext=(8, 8),
      textcoords="offset points",
      fontsize=9,
      bbox={"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.75},
      arrowprops={"arrowstyle": "->", "lw": 0.8},
  )
  ax.set_ylim(*_score_axis_limits(scores))
  ax.legend(loc="best")
  fig.tight_layout()
  fig.savefig(output_path, dpi=160)
  plt.close(fig)


def plot_tree_branches(nodes_jsonl: str | Path, output_path: str | Path) -> None:
  """Plots the multi-bot FUTS tree over expansion order and depth."""
  import matplotlib.pyplot as plt

  rows = _load_node_rows(nodes_jsonl)
  if not rows:
    raise ValueError(f"No nodes found in {nodes_jsonl}")

  depth = _node_depths(rows)
  plot_rows = [row for row in rows if row["node_id"] >= TREE_PLOT_START_NODE_ID]
  if not plot_rows:
    raise ValueError(f"No nodes with node_id >= {TREE_PLOT_START_NODE_ID}")
  valid = [row for row in plot_rows if _effective_score(row) is not None]
  best = max(valid, key=lambda row: _effective_score(row)) if valid else None

  width = max(9, min(18, 5 + 0.10 * len(plot_rows)))
  height = max(5, min(12, 4 + 0.25 * (max(depth.values()) + 1)))
  fig, ax = plt.subplots(figsize=(width, height))

  for row in rows:
    node_id = row["node_id"]
    parent_id = row["parent_id"]
    if (
        parent_id is None
        or node_id < TREE_PLOT_START_NODE_ID
        or parent_id < TREE_PLOT_START_NODE_ID
    ):
      continue
    ax.plot(
        [parent_id, node_id],
        [depth[parent_id], depth[node_id]],
        color="#9aa0a6",
        linewidth=0.8,
        alpha=0.75,
        zorder=1,
    )

  xs = [row["node_id"] for row in plot_rows]
  ys = [depth[row["node_id"]] for row in plot_rows]
  color_args, has_score_colors = _score_color_args(plot_rows)
  scatter = ax.scatter(
      xs,
      ys,
      s=42,
      edgecolors="white",
      linewidths=0.6,
      zorder=2,
      **color_args,
  )
  if has_score_colors:
    cbar = fig.colorbar(scatter, ax=ax, pad=0.015)
    cbar.set_label("-(makespan + elapsed/100), darker = better")

  if best is not None:
    best_id = best["node_id"]
    ax.scatter(
        [best_id],
        [depth[best_id]],
        marker="*",
        s=180,
        color="#d93025",
        edgecolors="white",
        linewidths=0.8,
        zorder=3,
    )
    ax.annotate(
        (
            f"best node={best_id}\n"
            f"score={_effective_score(best):.3g}\n"
            f"makespan={best.get('makespan')}"
        ),
        xy=(best_id, depth[best_id]),
        xytext=(10, 10),
        textcoords="offset points",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "alpha": 0.8},
        arrowprops={"arrowstyle": "->", "lw": 0.8},
    )

  ax.set_xlabel("Node id / expansion order")
  ax.set_ylabel("Tree depth")
  ax.set_title(
      f"Multi-bot FJSPB FUTS tree branches from node {TREE_PLOT_START_NODE_ID}"
  )
  ax.grid(True, alpha=0.25)
  if xs:
    ax.set_xlim(min(xs) - 1, max(xs) + 1)
  if ys:
    ax.set_ylim(-0.5, max(ys) + 1)
  fig.tight_layout()
  fig.savefig(output_path, dpi=180)
  plt.close(fig)


def plot_tree_branches_3d(nodes_jsonl: str | Path, output_path: str | Path) -> None:
  """Plots multi-bot FUTS branches in 3D: node id, depth, and makespan."""
  import matplotlib.pyplot as plt

  rows = _load_node_rows(nodes_jsonl)
  if not rows:
    raise ValueError(f"No nodes found in {nodes_jsonl}")

  by_id = {row["node_id"]: row for row in rows}
  depth = _node_depths(rows)
  plot_rows = [
      row
      for row in rows
      if row["node_id"] >= TREE_PLOT_START_NODE_ID
      and row.get("makespan") is not None
  ]
  if not plot_rows:
    raise ValueError(
        f"No feasible nodes with node_id >= {TREE_PLOT_START_NODE_ID}"
    )

  score_rows = [row for row in plot_rows if _effective_score(row) is not None]
  best = max(score_rows, key=lambda row: _effective_score(row)) if score_rows else min(
      plot_rows, key=lambda row: row["makespan"]
  )
  best_makespan = min(row["makespan"] for row in plot_rows)
  focus_window = _makespan_focus_window(plot_rows, best_makespan)
  width = max(9, min(18, 5 + 0.10 * len(plot_rows)))
  fig = plt.figure(figsize=(width, 7))
  ax = fig.add_subplot(111, projection="3d")

  for row in rows:
    node_id = row["node_id"]
    parent_id = row["parent_id"]
    if (
        parent_id is None
        or node_id < TREE_PLOT_START_NODE_ID
        or parent_id < TREE_PLOT_START_NODE_ID
        or row.get("makespan") is None
        or by_id[parent_id].get("makespan") is None
    ):
      continue
    ax.plot(
        [parent_id, node_id],
        [depth[parent_id], depth[node_id]],
        [
            _makespan_focus_z(
                by_id[parent_id]["makespan"], best_makespan, focus_window
            ),
            _makespan_focus_z(row["makespan"], best_makespan, focus_window),
        ],
        color="#9aa0a6",
        linewidth=0.8,
        alpha=0.75,
    )

  xs = [row["node_id"] for row in plot_rows]
  ys = [depth[row["node_id"]] for row in plot_rows]
  zs = [
      _makespan_focus_z(row["makespan"], best_makespan, focus_window)
      for row in plot_rows
  ]
  color_args, has_score_colors = _score_color_args(plot_rows)
  scatter = ax.scatter(
      xs,
      ys,
      zs,
      s=36,
      edgecolors="white",
      linewidths=0.5,
      depthshade=False,
      **color_args,
  )
  if has_score_colors:
    cbar = fig.colorbar(scatter, ax=ax, pad=0.08, shrink=0.72)
    cbar.set_label("-(makespan + elapsed/100), darker = better")

  best_id = best["node_id"]
  ax.scatter(
      [best_id],
      [depth[best_id]],
      [_makespan_focus_z(best["makespan"], best_makespan, focus_window)],
      marker="*",
      s=180,
      color="#d93025",
      edgecolors="white",
      linewidths=0.8,
      depthshade=False,
  )
  ax.text(
      best_id,
      depth[best_id],
      _makespan_focus_z(best["makespan"], best_makespan, focus_window),
      (
          f" best node={best_id}\n"
          f" score={_effective_score(best):.3g}\n"
          f" makespan={best['makespan']}"
      ),
      fontsize=9,
  )

  ax.set_xlabel("Node id / expansion order")
  ax.set_ylabel("Tree depth")
  ax.set_zlabel(f"makespan gap to best, clipped at {focus_window:g}")
  ax.set_title(
      f"Multi-bot FJSPB FUTS tree branches 3D from node {TREE_PLOT_START_NODE_ID}"
  )
  if xs:
    ax.set_xlim(min(xs) - 0.5, max(xs) + 0.5)
  if ys:
    ax.set_ylim(min(ys) - 0.5, max(ys) + 0.5)
  if zs:
    z_margin = max(0.1, focus_window * 0.05)
    ax.set_zlim(min(zs) - z_margin, max(zs) + z_margin)
  ax.view_init(elev=22, azim=-62)
  fig.tight_layout()
  fig.savefig(output_path, dpi=180)
  plt.close(fig)


def _load_node_rows(nodes_jsonl: str | Path) -> list[dict]:
  rows = []
  with Path(nodes_jsonl).open("r", encoding="utf-8") as f:
    for line in f:
      if line.strip():
        rows.append(json.loads(line))
  return rows


def _finite_score_rows(rows: list[dict], start_node_id: int) -> list[dict]:
  return [
      row for row in rows
      if row["node_id"] >= start_node_id
      and _effective_score(row) is not None
  ]


def _effective_score(row: dict) -> float | None:
  """Returns current plot score: -(makespan + elapsed_seconds / 100)."""
  makespan = row.get("makespan")
  elapsed_seconds = row.get("elapsed_seconds")
  if makespan is not None and elapsed_seconds is not None:
    score = -(float(makespan) + float(elapsed_seconds) / 100.0)
    return score if math.isfinite(score) else None
  score = row.get("score")
  return score if score is not None and math.isfinite(score) else None


def _score_axis_limits(values: list[float]) -> tuple[float, float]:
  if len(values) < 4:
    lower = min(values)
    upper = max(values)
  else:
    ordered = sorted(values)
    lower = ordered[max(0, int(0.02 * (len(ordered) - 1)))]
    upper = ordered[min(len(ordered) - 1, int(0.98 * (len(ordered) - 1)))]
    best = max(values)
    upper = max(upper, best)
  if lower == upper:
    margin = max(1.0, abs(lower) * 0.05)
  else:
    margin = (upper - lower) * 0.08
  return lower - margin, upper + margin


def _score_color_args(rows: list[dict]) -> tuple[dict, bool]:
  """Returns scatter color args where darker color means better current score."""
  scores = [_effective_score(row) for row in rows]
  scores = [score for score in scores if score is not None]
  if not scores:
    return {"color": "#c8cdd3"}, False
  best_score = max(scores)
  worst_score = min(scores)
  if best_score == worst_score:
    worst_score = best_score - 1.0
  return {
      "c": [
          score if (score := _effective_score(row)) is not None else worst_score
          for row in rows
      ],
      "cmap": "Blues",
      "vmin": worst_score,
      "vmax": best_score,
  }, True


def _node_depths(rows: list[dict]) -> dict[int, int]:
  depth = {0: 0}
  for row in rows:
    node_id = row["node_id"]
    if node_id == 0:
      continue
    parent_id = row["parent_id"]
    depth[node_id] = depth.get(parent_id, 0) + 1
  return depth


def _makespan_focus_window(rows: list[dict], best_makespan: float) -> float:
  gaps = sorted(
      max(0.0, float(row["makespan"]) - float(best_makespan))
      for row in rows
      if row.get("makespan") is not None
  )
  positive_gaps = [gap for gap in gaps if gap > 0]
  if not positive_gaps:
    return 1.0
  index = max(0, min(len(positive_gaps) - 1, math.ceil(len(positive_gaps) * 0.2) - 1))
  return max(1.0, positive_gaps[index])


def _makespan_focus_z(
    makespan: float, best_makespan: float, focus_window: float
) -> float:
  """Shows near-best makespan gaps linearly and clips far-away nodes."""
  gap = max(0.0, float(makespan) - float(best_makespan))
  return min(gap, focus_window)
