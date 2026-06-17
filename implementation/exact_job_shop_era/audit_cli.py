"""Backfills version audit files for an existing exact_job_shop_era run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from implementation.exact_job_shop_era.logger import ExactExperimentLogger


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--experiment-dir", required=True)
  args = parser.parse_args()

  experiment_dir = Path(args.experiment_dir)
  nodes_path = experiment_dir / "nodes.jsonl"
  candidates_path = experiment_dir / "candidates"
  legacy_specs_path = experiment_dir / "specs"
  specs_path = candidates_path if candidates_path.exists() else legacy_specs_path
  if not nodes_path.exists():
    raise SystemExit(f"missing nodes file: {nodes_path}")
  if not specs_path.exists():
    raise SystemExit(
        f"missing candidates/specs dir: {candidates_path} or {legacy_specs_path}"
    )

  logger = ExactExperimentLogger(experiment_dir.parent, experiment_dir.name)
  manifest_path = experiment_dir / "run_manifest.json"
  if manifest_path.exists():
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    logger.instance_name = manifest.get("problem", {}).get("instance_name")
  logger.versions_path.unlink(missing_ok=True)
  logger.summary_path.unlink(missing_ok=True)

  with nodes_path.open("r", encoding="utf-8") as f:
    for line in f:
      if not line.strip():
        continue
      row = json.loads(line)
      node_id = int(row["node_id"])
      spec_file = specs_path / f"node_{node_id:04d}.py"
      if not spec_file.exists():
        spec_file = specs_path / f"node_{node_id:04d}.json"
      if not spec_file.exists():
        raise SystemExit(f"missing spec file: {spec_file}")
      spec_json = spec_file.read_text(encoding="utf-8")
      logger.spec_hash_by_node[node_id] = row.get("spec_hash") or logger.hash_spec(
          spec_json
      )
      logger.spec_by_node[node_id] = _load_json_or_raw(spec_json)
      logger.record_by_node[node_id] = row
      version_row = logger._build_version_row(
          node_id, row, logger.spec_by_node[node_id]
      )
      with logger.versions_path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(version_row, sort_keys=True) + "\n")

  logger.write_summary()
  print(f"wrote {logger.versions_path}")
  print(f"wrote {logger.summary_path}")


def _load_json_or_raw(text: str) -> dict:
  try:
    data = json.loads(text)
  except json.JSONDecodeError:
    return {"_raw": text}
  return data if isinstance(data, dict) else {"_raw": data}


if __name__ == "__main__":
  main()
