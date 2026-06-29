"""Problem loading for multi-bot online scheduling JSON and SQLite datasets."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import copy
import json
import sqlite3
from pathlib import Path


DEFAULT_DATASET = (
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods/examples/era_mixed_scheduling_benchmark.json"
)


@dataclass(frozen=True)
class MultiBotOnlineProblem:
  instance_name: str
  description: str
  dataset: dict
  prompt_dataset: dict
  optimum: int | None = None


def _step_duration(step: dict) -> int:
  return int(step["time"]) if step.get("time") is not None else 3


def _summarize_dataset(dataset: dict) -> dict:
  if "fjspb" in dataset:
    return _summarize_fjspb(dataset["fjspb"])
  tasks = dataset.get("task_list", [])
  task_summaries = [
      {
          "name": task.get("name"),
          "expr_no": task.get("expr_no"),
          "vials_count": task.get("vials_count"),
          "steps": [
              {
                  "step_index": step.get("index"),
                  "workstation": step.get("workstation"),
                  "duration": _step_duration(step),
              }
              for step in task.get("steps", [])
          ],
      }
      for task in tasks
  ]
  result = {
      "workstations": [
          {
              "code": ws.get("code"),
              "type": ws.get("workstationType"),
              "capacity": int(ws.get("bottleSlotCount") or 1),
          }
          for ws in dataset.get("workstation_list", [])
      ],
      "robots": [
          robot.get("code")
          for robot in dataset.get("robot_list", [])
          if robot.get("isRobot")
      ],
      "task_count": len(tasks),
      "step_count": sum(len(task.get("steps", [])) for task in tasks),
  }
  if len(tasks) <= 12:
    result["tasks"] = task_summaries
    return result

  route_counts = Counter(
      tuple(
          (step.get("workstation"), _step_duration(step))
          for step in task.get("steps", [])
      )
      for task in tasks
  )
  result["route_patterns"] = [
      {
          "count": count,
          "steps": [
              {
                  "workstation": workstation,
                  "duration": duration,
              }
              for workstation, duration in route
          ],
      }
      for route, count in route_counts.most_common()
  ]
  result["sample_tasks"] = task_summaries[: min(6, len(task_summaries))]
  return result


def _summarize_fjspb(fjspb: dict) -> dict:
  jobs = fjspb.get("jobs", [])
  tasks = [task for job in jobs for task in job.get("tasks", [])]
  machine_counts = Counter(tuple(task.get("machines", [])) for task in tasks)
  special_counts = Counter()
  for task in tasks:
    for key, value in task.get("flags", {}).items():
      if value:
        special_counts[key] += 1
  return {
      "problem_type": "fjspb_sqlite",
      "job_count": len(jobs),
      "task_count": len(tasks),
      "machine_count": len(fjspb.get("machines", {})),
      "cur_ptr": fjspb.get("cur_ptr", 0),
      "machine_route_patterns": [
          {"count": count, "machines": list(machines)}
          for machines, count in machine_counts.most_common(12)
      ],
      "special_constraint_counts": dict(special_counts),
      "machine_capacity_sample": dict(list(fjspb.get("machines", {}).items())[:20]),
      "sample_jobs": jobs[: min(3, len(jobs))],
  }


def _load_sqlite_dataset(path: Path) -> dict:
  conn = sqlite3.connect(path)
  conn.row_factory = sqlite3.Row
  try:
    workstations = _load_sqlite_workstations(conn)
    robots = _load_sqlite_robots(conn)
    tasks = _load_sqlite_tasks(conn, path)
    fjspb = _load_sqlite_fjspb(conn, path)
  finally:
    conn.close()

  return {
      "name": path.stem,
      "source_sqlite_file": str(path),
      "workstation_list": workstations,
      "robot_list": robots,
      "task_list": tasks,
      "fjspb": fjspb,
  }


def _load_sqlite_workstations(conn: sqlite3.Connection) -> list[dict]:
  rows = conn.execute(
      """
      SELECT code, workstationType, name, capacity, section, channel,
             channel_code, exist, remark
      FROM ws_info
      ORDER BY code
      """
  ).fetchall()
  return [
      {
          "code": row["code"],
          "workstationType": row["workstationType"] or row["code"],
          "name": row["name"] or row["code"],
          "bottleSlotCount": int(row["capacity"] or 1),
          "section": row["section"],
          "channel": row["channel"],
          "channel_code": row["channel_code"],
          "exist": row["exist"],
          "remark": row["remark"],
      }
      for row in rows
      if row["code"]
  ]


def _load_sqlite_robots(conn: sqlite3.Connection) -> list[dict]:
  rows = conn.execute(
      """
      SELECT code, name, status, electricityQuantity
      FROM robot_info
      ORDER BY code
      """
  ).fetchall()
  robots = [
      {
          "code": row["code"],
          "name": row["name"] or row["code"],
          "workstationType": "robot",
          "isRobot": 1,
          "status": row["status"],
          "electricityQuantity": row["electricityQuantity"],
          "bottleSlotCount": 40,
      }
      for row in rows
      if row["code"]
  ]
  return robots or [
      {
          "code": "robot_0",
          "name": "robot_0",
          "workstationType": "robot",
          "isRobot": 1,
          "bottleSlotCount": 40,
      }
  ]


def _load_sqlite_tasks(conn: sqlite3.Connection, path: Path) -> list[dict]:
  rows = conn.execute(
      """
      SELECT name, b_id, fjspb_index, expr_name, expr_no, step_id, step_index,
             branch_code, ws_code, ws_arr, ws_code_fjspb, time, step_raw_time,
             duration, job_length, detail, parameters, put_robot, take_robot
      FROM task_scheduled
      ORDER BY b_id, fjspb_index
      """
  ).fetchall()
  grouped: dict[str, list[sqlite3.Row]] = {}
  for row in rows:
    grouped.setdefault(row["b_id"], []).append(row)

  tasks = []
  for b_id, task_rows in sorted(grouped.items()):
    ordered = sorted(task_rows, key=lambda row: int(row["fjspb_index"]))
    first = ordered[0]
    expr_name = first["expr_name"] or path.stem
    expr_no = first["expr_no"] or b_id
    tasks.append(
        {
            "name": f"{expr_name}:{b_id}",
            "expr_no": b_id,
            "source_sqlite": str(path),
            "source_expr_name": expr_name,
            "source_expr_no": expr_no,
            "source_b_id": b_id,
            "vials_count": 1,
            "steps": [_sqlite_step(row) for row in ordered],
        }
    )
  return tasks


def _sqlite_step(row: sqlite3.Row) -> dict:
  duration = row["time"]
  if duration is None:
    duration = row["step_raw_time"]
  if duration is None:
    duration = row["duration"]
  return {
      "id": row["step_id"],
      "index": int(row["fjspb_index"]) + 1,
      "source_step_index": row["step_index"],
      "source_fjspb_index": row["fjspb_index"],
      "workstation": row["ws_code"],
      "candidate_workstations": _candidate_machines(row),
      "scheduled_workstation": row["ws_code_fjspb"],
      "time": int(duration) if duration is not None else 3,
      "source_step_name": row["name"],
      "branch_code": row["branch_code"],
      "job_length": row["job_length"],
      "detail": row["detail"],
      "parameters": row["parameters"],
      "put_robot": row["put_robot"],
      "take_robot": row["take_robot"],
  }


def _parse_json_or_none(text):
  if text in (None, ""):
    return None
  try:
    return json.loads(text)
  except Exception:
    return None


def _candidate_machines(row: sqlite3.Row) -> list[str]:
  raw = row["ws_arr"] if "ws_arr" in row.keys() else None
  candidates = []
  if raw:
    parsed = _parse_json_or_none(raw)
    if isinstance(parsed, list):
      candidates = [str(item) for item in parsed if item]
    else:
      candidates = [part.strip() for part in str(raw).split(",") if part.strip()]
  if not candidates and row["ws_code"]:
    candidates = [row["ws_code"]]
  if row["ws_code_fjspb"] and row["ws_code_fjspb"] not in candidates:
    candidates.append(row["ws_code_fjspb"])
  return candidates or ["unknown_workstation"]


def _load_sqlite_fjspb(conn: sqlite3.Connection, path: Path) -> dict:
  ws_rows = conn.execute(
      "SELECT code, capacity FROM ws_info ORDER BY code"
  ).fetchall()
  machines = {
      row["code"]: max(1, int(row["capacity"] or 1))
      for row in ws_rows
      if row["code"]
  }
  ptr_row = conn.execute(
      "SELECT value FROM global_ptr_info WHERE name='cur_ws_ptr'"
  ).fetchone()
  cur_ptr = int(ptr_row["value"]) if ptr_row and ptr_row["value"] is not None else 0
  rows = conn.execute(
      """
      SELECT name, b_id, fjspb_index, expr_name, expr_no, step_id, step_index,
             branch_code, ws_code, ws_arr, ws_code_fjspb, next_step_ws_code_fjspb,
             time, step_raw_time, duration, job_length, detail, parameters,
             start_time, end, has_scheduled, odd, put, take, start,
             electronic_dripping, electronic_test, electronic_recycle,
             xrd_dripping, xrd_test, xrd_recycle
      FROM task_scheduled
      ORDER BY b_id, fjspb_index
      """
  ).fetchall()
  grouped: dict[str, list[sqlite3.Row]] = {}
  for row in rows:
    grouped.setdefault(row["b_id"], []).append(row)
  jobs = []
  for b_id, task_rows in sorted(grouped.items()):
    ordered = sorted(task_rows, key=lambda row: int(row["fjspb_index"]))
    first = ordered[0]
    jobs.append(
        {
            "job_id": b_id,
            "expr_no": first["expr_no"] or b_id,
            "expr_name": first["expr_name"] or path.stem,
            "tasks": [_fjspb_task(row, cur_ptr) for row in ordered],
        }
    )
  return {
      "source_sqlite_file": str(path),
      "cur_ptr": cur_ptr,
      "machines": machines,
      "jobs": jobs,
      "output_schema": {
          "assignments": [
              {
                  "job_id": "string b_id",
                  "task_id": "integer fjspb_index",
                  "machine": "one candidate machine code",
                  "start": "integer >= 0",
                  "end": "integer start + duration",
              }
          ]
      },
      "constraint_contract": [
          "Each (job_id, task_id) appears exactly once.",
          "Assigned machine must be in task.machines.",
          "Tasks in each job follow increasing task_id precedence.",
          "Non-fixed tasks start at or after cur_ptr.",
          "Fixed tasks with start_time < cur_ptr keep exact start/end/machine.",
          "Machine capacity comes from machines[machine].",
          "Capacity>1 batch overlaps must either be non-overlapping or have aligned start/end when durations match.",
          "Dripping/test/recycle intervals for electrochemical and XRD resources are mutually exclusive and consecutive inside each job.",
          "Muffle furnace and dryer intervals with different temperatures cannot overlap on the same machine.",
          "Centrifugation active count at each event time must be even.",
          "First task of jobs with the same expr_no starts together.",
      ],
  }


def _fjspb_task(row: sqlite3.Row, cur_ptr: int) -> dict:
  duration = row["time"]
  if duration is None:
    duration = row["step_raw_time"]
  if duration is None:
    duration = row["duration"]
  parameters = _parse_json_or_none(row["parameters"]) or []
  flags = {
      "odd": bool(row["odd"]),
      "put": bool(row["put"]),
      "take": bool(row["take"]),
      "start": bool(row["start"]),
      "electronic_dripping": bool(row["electronic_dripping"]),
      "electronic_test": bool(row["electronic_test"]),
      "electronic_recycle": bool(row["electronic_recycle"]),
      "xrd_dripping": bool(row["xrd_dripping"]),
      "xrd_test": bool(row["xrd_test"]),
      "xrd_recycle": bool(row["xrd_recycle"]),
  }
  is_fixed = row["start_time"] is not None and int(row["start_time"]) < cur_ptr
  return {
      "task_id": int(row["fjspb_index"]),
      "step_id": row["step_id"],
      "step_index": row["step_index"],
      "name": row["name"],
      "machines": _candidate_machines(row),
      "nominal_machine": row["ws_code"],
      "scheduled_machine": row["ws_code_fjspb"] if is_fixed else None,
      "next_scheduled_machine": (
          row["next_step_ws_code_fjspb"] if is_fixed else None
      ),
      "duration": int(duration) if duration is not None else 3,
      "parameters": parameters,
      "detail": _parse_json_or_none(row["detail"]) or row["detail"],
      "fixed_start": row["start_time"] if is_fixed else None,
      "fixed_end": row["end"] if is_fixed else None,
      "is_fixed": is_fixed,
      "has_existing_schedule": bool(row["has_scheduled"]),
      "flags": flags,
  }


def _load_dataset(path: Path) -> dict:
  suffix = path.suffix.lower()
  if suffix in {".sqlite", ".db", ".sqlite3"}:
    return _load_sqlite_dataset(path)
  return json.loads(path.read_text(encoding="utf-8"))


def load_problem(dataset_path: str = DEFAULT_DATASET) -> MultiBotOnlineProblem:
  path = Path(dataset_path)
  dataset = _load_dataset(path)
  summary = _summarize_dataset(dataset)
  num_tasks = int(summary["task_count"])
  num_steps = int(summary.get("step_count", summary["task_count"]))
  description = (
      f"Build an online multi-bot chemistry scheduler for dataset {path.name}. "
      f"It has {num_tasks} schedulable operations across {num_steps} ordered "
      "legacy steps. For SQLite inputs, use dataset['fjspb'] as the primary "
      "FJSPB IR: choose one candidate machine per task, enforce job "
      "precedence, machine capacities, batching/synchronization, fixed-task "
      "rules, and chemistry-specific constraints. The generated script must "
      "accept runtime commands, insert jobs, reschedule without changing fixed "
      "tasks, and minimize post-insertion makespan with limited disruption."
  )
  return MultiBotOnlineProblem(
      instance_name=path.stem,
      description=description,
      dataset=dataset,
      prompt_dataset=copy.deepcopy(summary),
  )
