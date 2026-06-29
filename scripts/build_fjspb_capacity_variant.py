#!/usr/bin/env python3
"""Build random-capacity variants of an FJSPB SQLite dataset.

The script copies a source SQLite file and changes ws_info.capacity using a
reproducible random seed. It keeps capacities high enough for already-fixed
(start_time < cur_ws_ptr) intervals, so generated variants do not inherit the
structural fixed-task infeasibility seen in naive duplicated datasets.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sqlite3
from pathlib import Path


DEFAULT_SOURCE = Path(
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods/database_paper/4_experiments.sqlite"
)
DEFAULT_OUTPUT_DIR = Path("/home/era/experiments/fjspb_capacity_variants")


def _table_has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _load_cur_ptr(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT value FROM global_ptr_info WHERE name='cur_ws_ptr'"
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _scheduled_capacity_floor(
    conn: sqlite3.Connection, cur_ptr: int, mode: str
) -> dict[str, int]:
    if mode == "fixed":
        where_clause = "start_time IS NOT NULL AND start_time < ?"
        params = (cur_ptr,)
    elif mode == "scheduled":
        where_clause = "start_time IS NOT NULL AND end IS NOT NULL"
        params = ()
    else:
        raise ValueError("floor mode must be 'fixed' or 'scheduled'")

    rows = conn.execute(
        f"""
        SELECT ws_code_fjspb, start_time, end
        FROM task_scheduled
        WHERE {where_clause}
          AND ws_code_fjspb IS NOT NULL
        """,
        params,
    ).fetchall()
    by_machine: dict[str, list[tuple[int, int]]] = {}
    for machine, start, end in rows:
        if machine is None or start is None or end is None:
            continue
        by_machine.setdefault(str(machine), []).append((int(start), int(end)))

    floors: dict[str, int] = {}
    for machine, intervals in by_machine.items():
        events: list[tuple[int, int]] = []
        for start, end in intervals:
            events.append((start, 1))
            events.append((end, -1))
        active = 0
        peak = 0
        for _time, delta in sorted(events, key=lambda item: (item[0], item[1])):
            active += delta
            peak = max(peak, active)
        floors[machine] = peak
    return floors


def _capacity_from_seed(
    code: str,
    base_capacity: int,
    rng: random.Random,
    min_scale: float,
    max_scale: float,
    floor: int,
    include_robots: bool,
    expand_single: bool,
) -> int:
    base_raw = int(base_capacity)
    if base_raw <= 0 and floor <= 0:
        return base_raw

    base = max(1, base_raw)
    is_robot = code.startswith("robot_") or code == "robot_platform"
    if is_robot and not include_robots:
        return max(base, floor)

    if base <= 1:
        candidate = 2 if expand_single and rng.random() < 0.25 else 1
    else:
        factor = rng.uniform(min_scale, max_scale)
        candidate = max(1, int(round(base * factor)))

    return max(candidate, floor, 1)


def _capacity_floor_violations(
    conn: sqlite3.Connection,
    capacities: dict[str, int],
    cur_ptr: int,
    floor_mode: str,
) -> list[dict]:
    floors = _scheduled_capacity_floor(conn, cur_ptr, floor_mode)
    violations = []
    for machine, peak in sorted(floors.items()):
        cap = max(1, int(capacities.get(machine, 1)))
        if peak > cap:
            violations.append({"machine": machine, "capacity_floor": peak, "capacity": cap})
    return violations


def build_variant(
    source: Path,
    output: Path,
    seed: int,
    min_scale: float,
    max_scale: float,
    include_robots: bool,
    expand_single: bool,
    fixed_slack: int,
    floor_mode: str,
) -> dict:
    if not source.exists():
        raise FileNotFoundError(source)
    if min_scale <= 0 or max_scale <= 0 or min_scale > max_scale:
        raise ValueError("expected 0 < min_scale <= max_scale")

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    shutil.copy2(source, output)

    rng = random.Random(seed)
    conn = sqlite3.connect(output)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_has_column(conn, "ws_info", "capacity"):
            raise RuntimeError("ws_info.capacity column not found")
        cur_ptr = _load_cur_ptr(conn)
        fixed_floor = _scheduled_capacity_floor(conn, cur_ptr, floor_mode)
        rows = conn.execute(
            "SELECT code, capacity FROM ws_info WHERE code IS NOT NULL ORDER BY code"
        ).fetchall()

        changes = []
        capacities: dict[str, int] = {}
        for row in rows:
            code = str(row["code"])
            base = 1 if row["capacity"] is None else int(row["capacity"])
            floor = max(0, fixed_floor.get(code, 0) + int(fixed_slack))
            new_capacity = _capacity_from_seed(
                code,
                base,
                rng,
                min_scale,
                max_scale,
                floor,
                include_robots,
                expand_single,
            )
            capacities[code] = new_capacity
            conn.execute(
                "UPDATE ws_info SET capacity=? WHERE code=?",
                (int(new_capacity), code),
            )
            if new_capacity != base:
                changes.append(
                    {
                        "code": code,
                        "old_capacity": base,
                        "new_capacity": new_capacity,
                        "fixed_floor": fixed_floor.get(code, 0),
                    }
                )
        conn.commit()

        violations = _capacity_floor_violations(conn, capacities, cur_ptr, floor_mode)
        if violations:
            raise RuntimeError(
                "fixed-task capacity violations after update: "
                + json.dumps(violations, ensure_ascii=False)
            )

        job_count = conn.execute(
            "SELECT COUNT(DISTINCT b_id) FROM task_scheduled"
        ).fetchone()[0]
        task_count = conn.execute("SELECT COUNT(*) FROM task_scheduled").fetchone()[0]
        summary = {
            "source": str(source),
            "output": str(output),
            "seed": seed,
            "min_scale": min_scale,
            "max_scale": max_scale,
            "include_robots": include_robots,
            "expand_single": expand_single,
            "fixed_slack": fixed_slack,
            "floor_mode": floor_mode,
            "cur_ptr": cur_ptr,
            "jobs": int(job_count),
            "tasks": int(task_count),
            "changed_workstations": len(changes),
            "changes": changes,
            "fixed_capacity_floor": fixed_floor,
        }
    finally:
        conn.close()

    output.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=20260623)
    parser.add_argument("--min-scale", type=float, default=0.55)
    parser.add_argument("--max-scale", type=float, default=1.35)
    parser.add_argument("--include-robots", action="store_true")
    parser.add_argument("--expand-single", action="store_true")
    parser.add_argument("--fixed-slack", type=int, default=0)
    parser.add_argument(
        "--floor-mode",
        choices=["scheduled", "fixed"],
        default="scheduled",
        help="scheduled guarantees the existing complete schedule remains capacity-feasible; fixed only protects already-started tasks.",
    )
    args = parser.parse_args()

    output = args.output
    if output is None:
        output = DEFAULT_OUTPUT_DIR / f"4_experiments_capacity_seed_{args.seed}.sqlite"

    summary = build_variant(
        args.source,
        output,
        args.seed,
        args.min_scale,
        args.max_scale,
        args.include_robots,
        args.expand_single,
        args.fixed_slack,
        args.floor_mode,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
