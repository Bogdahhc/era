"""Scoring adapter for job_shop_lib schedules."""

from __future__ import annotations


WORST_SCORE = float("-inf")
SCORE_RUNTIME_DIVISOR = 100.0


def score_schedule(schedule) -> tuple[float, bool, int | None, str | None]:
  """Returns (score, feasible, makespan, error)."""
  try:
    from job_shop_lib import Schedule
  except ImportError as exc:
    return WORST_SCORE, False, None, f"missing job_shop_lib: {exc}"

  try:
    if not isinstance(schedule, Schedule):
      return WORST_SCORE, False, None, "solve() did not return a Schedule"
    Schedule.check_schedule(schedule.schedule)
    if not schedule.is_complete():
      return WORST_SCORE, False, None, "schedule is incomplete"
    makespan = schedule.makespan()
    return -float(makespan), True, int(makespan), None
  except Exception as exc:
    return WORST_SCORE, False, None, str(exc)
