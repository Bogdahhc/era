#!/usr/bin/env python3
"""Run the original repository FJSPB reference solver on a SQLite copy."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import types
from pathlib import Path


SIM_METHODS = Path(
    "/home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/"
    "simulation_methods"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cur-ptr", type=int, default=3)
    parser.add_argument("--time-limit", type=int, default=450)
    parser.add_argument(
        "--solver",
        choices=["ortools"],
        default="ortools",
        help="Reference solver available in this local environment.",
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.input, args.output)

    sys.path.insert(0, str(SIM_METHODS))
    if "colorama" not in sys.modules:
        colorama = types.ModuleType("colorama")
        colorama.init = lambda *args, **kwargs: None
        colorama.Fore = types.SimpleNamespace()
        colorama.Style = types.SimpleNamespace()
        sys.modules["colorama"] = colorama
    import fespb.fespb_ortools as fespb_module

    # The local OR-Tools drop-in adds schedule hints that can duplicate fixed
    # constant variables on merged datasets. The CPLEX fespb.py does not use
    # these hints, so disable only this auxiliary hint layer for reference runs.
    fespb_module._add_existing_schedule_hints = lambda *args, **kwargs: None
    fespb = fespb_module.fespb

    conn = sqlite3.connect(args.output)
    try:
        makespan, machines, capacities = fespb(
            args.cur_ptr, conn, time_limit=args.time_limit
        )
    finally:
        conn.close()

    summary = {
        "input": str(args.input),
        "output": str(args.output),
        "solver": "original_repo_fespb_ortools",
        "cur_ptr": args.cur_ptr,
        "time_limit": args.time_limit,
        "makespan": makespan,
        "machine_count": len(machines),
        "capacities": capacities,
    }
    summary_path = args.output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
