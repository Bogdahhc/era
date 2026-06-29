#!/usr/bin/env python3
"""Build merged FJSPB SQLite benchmarks from existing experiment databases."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


SOURCE_DIR = Path(
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods/database_paper"
)
DEFAULT_OUTPUT = Path(
    "/home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite"
)


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _copy_schema(template: Path, output: Path) -> None:
    if output.exists():
        output.unlink()
    src = sqlite3.connect(template)
    dst = sqlite3.connect(output)
    try:
        for (sql,) in src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ):
            dst.execute(sql)
        dst.commit()
    finally:
        src.close()
        dst.close()


def _insert_rows(
    dst: sqlite3.Connection,
    table: str,
    rows: list[sqlite3.Row],
    transforms: dict[str, object] | None = None,
    ignore: bool = False,
) -> int:
    transforms = transforms or {}
    columns = _table_columns(dst, table)
    placeholders = ",".join("?" for _ in columns)
    verb = "INSERT OR IGNORE" if ignore else "INSERT"
    sql = f"{verb} INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
    inserted = 0
    for row in rows:
        values = []
        for column in columns:
            value = row[column]
            transform = transforms.get(column)
            if callable(transform):
                value = transform(value)
            elif column in transforms:
                value = transform
            values.append(value)
        dst.execute(sql, values)
        inserted += 1
    return inserted


def _prefix_value(tag: str, value: object) -> object:
    if value in (None, ""):
        return value
    return f"{tag}-{value}"


def build_merged_sqlite(sources: list[str], output: Path, cur_ptr: int | None) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    source_paths = [SOURCE_DIR / f"{name}.sqlite" for name in sources]
    missing = [str(path) for path in source_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing source sqlite files: {missing}")

    _copy_schema(source_paths[0], output)
    dst = sqlite3.connect(output)
    dst.row_factory = sqlite3.Row
    summary = {
        "output": str(output),
        "sources": [],
        "cur_ptr": cur_ptr,
        "jobs": 0,
        "task_rows": 0,
        "workstations": 0,
        "robots": 0,
    }
    try:
        stem_counts = {
            stem: sum(1 for path in source_paths if path.stem == stem)
            for stem in {path.stem for path in source_paths}
        }
        stem_seen: dict[str, int] = {}
        for source_path in source_paths:
            stem = source_path.stem
            stem_seen[stem] = stem_seen.get(stem, 0) + 1
            tag = f"{stem}_{stem_seen[stem]}" if stem_counts[stem] > 1 else stem
            src = sqlite3.connect(source_path)
            src.row_factory = sqlite3.Row
            try:
                _insert_rows(
                    dst,
                    "ws_info",
                    src.execute("SELECT * FROM ws_info").fetchall(),
                    ignore=True,
                )
                _insert_rows(
                    dst,
                    "robot_info",
                    src.execute("SELECT * FROM robot_info").fetchall(),
                    ignore=True,
                )
                bottle_rows = src.execute("SELECT * FROM bottle_info").fetchall()
                task_rows = src.execute("SELECT * FROM task_scheduled").fetchall()
                _insert_rows(
                    dst,
                    "bottle_info",
                    bottle_rows,
                    {
                        "vials_no": lambda v, tag=tag: _prefix_value(tag, v),
                        "expr_no": lambda v, tag=tag: _prefix_value(tag, v),
                        "expr_name": lambda v, tag=tag: _prefix_value(tag, v),
                    },
                )
                _insert_rows(
                    dst,
                    "task_scheduled",
                    task_rows,
                    {
                        "b_id": lambda v, tag=tag: _prefix_value(tag, v),
                        "expr_no": lambda v, tag=tag: _prefix_value(tag, v),
                        "expr_name": lambda v, tag=tag: _prefix_value(tag, v),
                    },
                )
                for record_table in ("bottle_record", "bottle_record_real"):
                    rows = src.execute(f"SELECT * FROM {record_table}").fetchall()
                    if rows:
                        _insert_rows(
                            dst,
                            record_table,
                            rows,
                            {
                                "vials_no": lambda v, tag=tag: _prefix_value(tag, v),
                                "expr_no": lambda v, tag=tag: _prefix_value(tag, v),
                            },
                        )
                jobs = src.execute(
                    "SELECT COUNT(DISTINCT b_id) FROM task_scheduled"
                ).fetchone()[0]
                summary["sources"].append(
                    {
                        "name": tag,
                        "jobs": jobs,
                        "task_rows": len(task_rows),
                        "bottles": len(bottle_rows),
                    }
                )
            finally:
                src.close()

        if cur_ptr is None:
            cur_ptr = sqlite3.connect(source_paths[0]).execute(
                "SELECT value FROM global_ptr_info WHERE name='cur_ws_ptr'"
            ).fetchone()[0]
        dst.execute(
            "INSERT OR REPLACE INTO global_ptr_info (name, value) VALUES (?, ?)",
            ("cur_ws_ptr", int(cur_ptr)),
        )
        dst.commit()

        summary["cur_ptr"] = int(cur_ptr)
        summary["jobs"] = dst.execute(
            "SELECT COUNT(DISTINCT b_id) FROM task_scheduled"
        ).fetchone()[0]
        summary["task_rows"] = dst.execute(
            "SELECT COUNT(*) FROM task_scheduled"
        ).fetchone()[0]
        summary["workstations"] = dst.execute("SELECT COUNT(*) FROM ws_info").fetchone()[0]
        summary["robots"] = dst.execute("SELECT COUNT(*) FROM robot_info").fetchone()[0]
        summary["fixed_rows"] = dst.execute(
            "SELECT COUNT(*) FROM task_scheduled WHERE start_time IS NOT NULL AND start_time < ?",
            (int(cur_ptr),),
        ).fetchone()[0]
    finally:
        dst.close()
    output.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", nargs="+", default=["e1", "e2", "e3", "e4", "e5"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cur-ptr", type=int, default=None)
    args = parser.parse_args()
    summary = build_merged_sqlite(args.sources, args.output, args.cur_ptr)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
