"""Structured exact-solver specs for job-shop search."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


ALLOWED_BACKENDS = frozenset(("ortools_cp_sat",))
ALLOWED_ENCODINGS = frozenset(("interval_variables",))
ALLOWED_BOUND_HINTS = frozenset(
    ("job_chain_lb", "machine_load_lb", "critical_path_lb")
)
ALLOWED_BRANCHING = frozenset(
    ("default", "min_slack_first", "critical_machine_first", "earliest_start")
)
ALLOWED_WARM_STARTS = frozenset(("none", "previous_incumbent"))


@dataclass(frozen=True)
class ExactSolverSpec:
  """A bounded search-space point for exact JSSP solving."""

  backend: str = "ortools_cp_sat"
  encoding: str = "interval_variables"
  max_time_in_seconds: float | None = 30.0
  log_search_progress: bool = False
  redundant_bounds: list[str] = field(default_factory=list)
  branching: str = "default"
  symmetry_breaking: bool = False
  warm_start: str = "none"
  notes: str = ""

  def to_json(self) -> str:
    return json.dumps(self.to_dict(), indent=2, sort_keys=True)

  def to_dict(self) -> dict[str, Any]:
    return {
        "backend": self.backend,
        "encoding": self.encoding,
        "max_time_in_seconds": self.max_time_in_seconds,
        "log_search_progress": self.log_search_progress,
        "redundant_bounds": list(self.redundant_bounds),
        "branching": self.branching,
        "symmetry_breaking": self.symmetry_breaking,
        "warm_start": self.warm_start,
        "notes": self.notes,
    }


def default_spec(max_time_in_seconds: float | None = 30.0) -> ExactSolverSpec:
  return ExactSolverSpec(max_time_in_seconds=max_time_in_seconds)


def parse_spec(text: str) -> ExactSolverSpec:
  """Parses and normalizes a JSON exact-solver spec."""
  data = json.loads(text)
  if not isinstance(data, dict):
    raise ValueError("spec must be a JSON object")

  backend = data.get("backend", "ortools_cp_sat")
  if backend not in ALLOWED_BACKENDS:
    raise ValueError(f"unsupported backend: {backend}")

  encoding = data.get("encoding", "interval_variables")
  if encoding not in ALLOWED_ENCODINGS:
    raise ValueError(f"unsupported encoding: {encoding}")

  max_time = data.get("max_time_in_seconds", 30.0)
  if max_time is not None:
    max_time = float(max_time)
    if max_time <= 0:
      raise ValueError("max_time_in_seconds must be positive or null")

  redundant_bounds = data.get("redundant_bounds", [])
  if not isinstance(redundant_bounds, list):
    raise ValueError("redundant_bounds must be a list")
  redundant_bounds = [
      value for value in redundant_bounds if value in ALLOWED_BOUND_HINTS
  ]

  branching = data.get("branching", "default")
  if branching not in ALLOWED_BRANCHING:
    branching = "default"

  warm_start = data.get("warm_start", "none")
  if warm_start not in ALLOWED_WARM_STARTS:
    warm_start = "none"

  return ExactSolverSpec(
      backend=backend,
      encoding=encoding,
      max_time_in_seconds=max_time,
      log_search_progress=bool(data.get("log_search_progress", False)),
      redundant_bounds=redundant_bounds,
      branching=branching,
      symmetry_breaking=bool(data.get("symmetry_breaking", False)),
      warm_start=warm_start,
      notes=str(data.get("notes", ""))[:500],
  )

