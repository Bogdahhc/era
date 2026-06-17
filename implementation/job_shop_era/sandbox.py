"""Subprocess execution for generated job-shop solvers."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run_candidate(code: str, instance_dict: dict, timeout_seconds: int = 30) -> dict:
  """Runs candidate code and returns {'ok': bool, ...}."""
  runner = textwrap.dedent(
      """
      import importlib.util
      import json
      import sys
      from pathlib import Path

      from job_shop_lib import JobShopInstance, Schedule

      code_path = Path(sys.argv[1])
      instance_path = Path(sys.argv[2])
      spec = importlib.util.spec_from_file_location("candidate", code_path)
      module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(module)

      with instance_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

      instance = JobShopInstance.from_matrices(
          duration_matrix=data["duration_matrix"],
          machines_matrix=data["machines_matrix"],
          name=data.get("name", "job_shop_instance"),
          metadata=data.get("metadata", {}),
      )
      schedule = module.solve(instance)
      if not isinstance(schedule, Schedule):
        raise TypeError("solve() did not return a job_shop_lib.Schedule")
      print(json.dumps(schedule.to_dict()))
      """
  )

  with tempfile.TemporaryDirectory(prefix="era_jssp_") as tmp_dir:
    tmp_path = Path(tmp_dir)
    code_path = tmp_path / "candidate.py"
    instance_path = tmp_path / "instance.json"
    runner_path = tmp_path / "runner.py"
    code_path.write_text(code, encoding="utf-8")
    instance_path.write_text(json.dumps(instance_dict), encoding="utf-8")
    runner_path.write_text(runner, encoding="utf-8")

    try:
      proc = subprocess.run(
          [sys.executable, str(runner_path), str(code_path), str(instance_path)],
          check=False,
          capture_output=True,
          text=True,
          timeout=timeout_seconds,
      )
    except subprocess.TimeoutExpired:
      return {"ok": False, "error": f"timeout after {timeout_seconds}s"}

    if proc.returncode != 0:
      return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}

    try:
      return {"ok": True, "schedule_dict": json.loads(proc.stdout)}
    except json.JSONDecodeError as exc:
      return {"ok": False, "error": f"invalid JSON output: {exc}"}

