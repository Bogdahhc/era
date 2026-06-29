"""Render a multi_bot_online_era best schedule with simulation_methods plotting code."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path


SIMULATION_DIR = Path(
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods"
)
BASE_SQLITE = SIMULATION_DIR / "database_paper/4_experiments.sqlite"


def _load_solver(path: Path):
  spec = importlib.util.spec_from_file_location("era_best_schedule", path)
  if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import solver from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  if hasattr(module, "DynamicScheduler"):
    def solve(dataset):
      now = int(dataset.get("fjspb", {}).get("cur_ptr") or 0)
      scheduler = module.DynamicScheduler(dataset)
      response = scheduler.handle_command(
          {"type": "reschedule", "now": now, "request_id": "render"}
      )
      if isinstance(response, dict) and "schedule" in response:
        return response["schedule"]
      return response

    return solve
  if not hasattr(module, "solve"):
    raise RuntimeError(f"{path} does not define DynamicScheduler or solve(dataset)")
  return module.solve


def _operations(schedule) -> list[dict]:
  if isinstance(schedule, dict):
    operations = schedule.get("operations")
  else:
    operations = schedule
  if not isinstance(operations, list):
    raise TypeError("schedule must be a list or a dict with an operations list")
  return operations


def _source_expr_no(expr_no: str, source_b_id: str) -> str:
  suffix = f"_{source_b_id}"
  if expr_no.endswith(suffix):
    return expr_no[: -len(suffix)]
  return source_b_id.rsplit("_", 1)[0]


def write_schedule_sqlite(dataset_path: Path, best_path: Path, base_sqlite: Path, output_sqlite: Path) -> None:
  dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
  solve = _load_solver(best_path)
  schedule = solve(dataset)
  operations = _operations(schedule)

  output_sqlite.parent.mkdir(parents=True, exist_ok=True)
  shutil.copy2(base_sqlite, output_sqlite)

  task_meta: dict[tuple[str, int], tuple[str, int, str]] = {}
  for task in dataset.get("task_list", []):
    source_b_id = task.get("source_b_id")
    if not source_b_id:
      continue
    source_expr_no = task.get("source_expr_no") or _source_expr_no(task["expr_no"], source_b_id)
    for step in task.get("steps", []):
      task_meta[(task["expr_no"], int(step["index"]))] = (
          source_b_id,
          int(step["index"]) - 1,
          source_expr_no,
      )

  conn = sqlite3.connect(output_sqlite)
  try:
    cur = conn.cursor()
    cur.execute("UPDATE task_scheduled SET start_time=NULL, end=NULL, duration=NULL, has_scheduled=0")
    for op in operations:
      key = (op.get("expr_no"), int(op.get("step_index")))
      if key not in task_meta:
        raise KeyError(f"operation has no source SQL row: {key}")
      b_id, fjspb_index, source_expr_no = task_meta[key]
      start = int(round(float(op["start"])))
      end = int(round(float(op["end"])))
      duration = end - start
      cur.execute(
          """
          UPDATE task_scheduled
          SET start_time=?, end=?, duration=?, has_scheduled=1
          WHERE b_id=? AND fjspb_index=? AND expr_no=?
          """,
          (start, end, duration, b_id, fjspb_index, source_expr_no),
      )
      if cur.rowcount != 1:
        raise RuntimeError(f"failed to update {b_id=} {fjspb_index=} {source_expr_no=}")
    conn.commit()
  finally:
    conn.close()


def render_with_simulation_script(sqlite_path: Path, output_png: Path) -> None:
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  spec = importlib.util.spec_from_file_location(
      "draw_schedule_comp_4_exprs",
      SIMULATION_DIR / "draw_schedule_comp_4_exprs.py",
  )
  if spec is None or spec.loader is None:
    raise RuntimeError("cannot import draw_schedule_comp_4_exprs.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  module.database_dir = str(sqlite_path.parent)

  fig, ax = plt.subplots(1, 1, figsize=(8, 3.2))
  bottle_table, _ws_table, makespan = module.plot_bottle_db(fig, ax, 0, 0, f"/{sqlite_path.name}")
  ax.set_yticklabels([])
  ax.set_yticks(range(len(bottle_table)))
  ax.set_ylim(ymin=-0.5, ymax=len(bottle_table) - 0.5)
  ax.axvline(makespan, color="r", linestyle="--")
  ax.set_xlim([0, makespan])
  ax.set_xticks([0, makespan])
  ax.set_xticklabels([0, makespan], fontsize=14)
  output_png.parent.mkdir(parents=True, exist_ok=True)
  fig.tight_layout()
  fig.savefig(output_png, dpi=200)
  plt.close(fig)


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--dataset", required=True)
  parser.add_argument("--best", required=True)
  parser.add_argument("--output-sqlite", required=True)
  parser.add_argument("--output-png", required=True)
  parser.add_argument("--base-sqlite", default=str(BASE_SQLITE))
  args = parser.parse_args()

  write_schedule_sqlite(
      Path(args.dataset),
      Path(args.best),
      Path(args.base_sqlite),
      Path(args.output_sqlite),
  )
  render_with_simulation_script(Path(args.output_sqlite), Path(args.output_png))
  print(f"sqlite={args.output_sqlite}")
  print(f"png={args.output_png}")


if __name__ == "__main__":
  main()
