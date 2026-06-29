"""Subprocess execution for generated dynamic multi-bot scheduler scripts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def run_candidate(
    code: str,
    dataset: dict,
    commands: list[dict],
    timeout_seconds: int = 30,
) -> dict:
  runner = textwrap.dedent(
      """
      import importlib.util
      import json
      import sys
      from pathlib import Path

      code_path = Path(sys.argv[1])
      dataset_path = Path(sys.argv[2])
      commands_path = Path(sys.argv[3])
      spec = importlib.util.spec_from_file_location("candidate", code_path)
      module = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(module)

      with dataset_path.open("r", encoding="utf-8") as f:
        dataset = json.load(f)
      with commands_path.open("r", encoding="utf-8") as f:
        commands = json.load(f)

      scheduler_cls = getattr(module, "DynamicScheduler", None)
      if scheduler_cls is None:
        raise TypeError("candidate must define class DynamicScheduler")
      scheduler = scheduler_cls(dataset)
      if not hasattr(scheduler, "handle_command"):
        raise TypeError("DynamicScheduler must expose handle_command(command)")

      events = []
      for command in commands:
        response = scheduler.handle_command(command)
        events.append({"command": command, "response": response})
      print(json.dumps({"events": events}, ensure_ascii=False))
      """
  )
  with tempfile.TemporaryDirectory(prefix="era_multibot_") as tmp_dir:
    tmp_path = Path(tmp_dir)
    code_path = tmp_path / "candidate.py"
    dataset_path = tmp_path / "dataset.json"
    commands_path = tmp_path / "commands.json"
    runner_path = tmp_path / "runner.py"
    code_path.write_text(code, encoding="utf-8")
    dataset_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    commands_path.write_text(json.dumps(commands, ensure_ascii=False), encoding="utf-8")
    runner_path.write_text(runner, encoding="utf-8")
    env = os.environ.copy()
    env["ERA_CANDIDATE_TIMEOUT_SECONDS"] = str(timeout_seconds)

    try:
      proc = subprocess.run(
          [
              sys.executable,
              str(runner_path),
              str(code_path),
              str(dataset_path),
              str(commands_path),
          ],
          check=False,
          capture_output=True,
          text=True,
          timeout=timeout_seconds,
          env=env,
      )
    except subprocess.TimeoutExpired:
      return {"ok": False, "error": f"timeout after {timeout_seconds}s"}

    if proc.returncode != 0:
      return {"ok": False, "error": proc.stderr.strip() or proc.stdout.strip()}
    try:
      return {"ok": True, "trace": json.loads(proc.stdout)}
    except json.JSONDecodeError as exc:
      return {"ok": False, "error": f"invalid JSON output: {exc}"}
