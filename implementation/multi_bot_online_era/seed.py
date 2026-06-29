"""Cold-start root candidate for online multi-bot/FJSPB FUTS."""

from __future__ import annotations


def baseline_candidate_code() -> str:
  """Returns a minimal online CP-SAT skeleton, not a usable scheduler.

  The default root is intentionally weak. FUTS should grow a complete reusable
  dynamic OR-Tools model from the prompt, dataset IR, command feedback, and
  failed-node diagnostics, rather than starting from a hand-built FJSPB solver.
  """
  return r'''
from ortools.sat.python import cp_model


class DynamicScheduler:
    def __init__(self, dataset):
        self.dataset = dataset
        self.now = 0

    def handle_command(self, command):
        if command.get("type") in ("tick", "dispatch_until"):
            self.now = int(command.get("time", self.now))
            return {"ok": True, "now": self.now}
        if command.get("type") == "insert_jobs":
            self.now = int(command.get("insert_time", command.get("now", self.now)))
            self.dataset.setdefault("fjspb", {}).setdefault("jobs", []).extend(
                command.get("jobs", [])
            )
            return {"ok": True, "inserted": len(command.get("jobs", []))}
        if command.get("type") == "reschedule":
            self.now = int(command.get("now", self.now))
            model = cp_model.CpModel()
            marker = model.NewBoolVar("cold_start_marker")
            model.Add(marker == 1)
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 1.0
            solver.Solve(model)
            return {"ok": True, "schedule": {"assignments": []}}

        return {"ok": False, "error": "unknown command"}
'''.strip()
