"""Subprocess execution for generated multi-bot scheduler scripts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run_candidate(code: str, dataset: dict, timeout_seconds: int = 30) -> dict:
  runner = textwrap.dedent(
      """
      import importlib.util
      import json
      import sys
      from pathlib import Path

      code_path = Path(sys.argv[1])
      dataset_path = Path(sys.argv[2])
      spec = importlib.util.spec_from_file_location("candidate", code_path)
      module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(module)

      with dataset_path.open("r", encoding="utf-8") as f:
        dataset = json.load(f)
      schedule = module.solve(dataset)
      print(json.dumps(schedule, ensure_ascii=False))
      """
  )
  with tempfile.TemporaryDirectory(prefix="era_multibot_") as tmp_dir:
    tmp_path = Path(tmp_dir)
    code_path = tmp_path / "candidate.py"
    dataset_path = tmp_path / "dataset.json"
    runner_path = tmp_path / "runner.py"
    code_path.write_text(code, encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    runner_path.write_text(runner, encoding="utf-8")

    try:
      proc = subprocess.run(
          [sys.executable, str(runner_path), str(code_path), str(dataset_path)],
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
      return {"ok": True, "schedule": json.loads(proc.stdout)}
    except json.JSONDecodeError as exc:
      return {"ok": False, "error": f"invalid JSON output: {exc}"}

