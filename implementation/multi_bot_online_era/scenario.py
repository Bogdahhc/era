"""Online command scenarios for dynamic multi-bot scheduling candidates."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import random


@dataclass(frozen=True)
class ScheduleCheck:
  event_index: int
  request_id: str
  dataset: dict


@dataclass(frozen=True)
class OnlineScenario:
  commands: list[dict]
  checks: list[ScheduleCheck]
  metadata: dict


def build_online_scenario(
    dataset: dict,
    *,
    scenario_seed: int = 0,
    insertion_count: int = 1,
    inserted_jobs: int = 2,
    inserted_task_count: int = 4,
    insert_window_ratio: tuple[float, float] = (0.10, 0.60),
    insert_times: list[int] | None = None,
    enforce_even_centrifuge_inserts: bool = False,
) -> OnlineScenario:
  """Builds a seeded online rescheduling scenario from one snapshot.

  The default values are tuned for 4_experiments-style FJSPB snapshots: insert
  a small number of short jobs at a reproducible pseudo-random time after the
  initial schedule has started. Non-FJSPB datasets still receive a single
  reschedule command and are validated by the legacy scorer.
  """
  if "fjspb" not in dataset:
    command = {"type": "reschedule", "now": 0, "request_id": "initial"}
    return OnlineScenario(
        commands=[command],
        checks=[ScheduleCheck(0, "initial", copy.deepcopy(dataset))],
        metadata={"scenario_seed": scenario_seed, "kind": "single_reschedule"},
    )

  rng = random.Random(scenario_seed)
  base = copy.deepcopy(dataset)
  fjspb = base["fjspb"]
  base_now = int(fjspb.get("cur_ptr") or 0)
  resolved_insert_times = (
      _explicit_insert_times(insert_times, base_now=base_now)
      if insert_times is not None
      else _random_insert_times(
          fjspb,
          rng,
          base_now=base_now,
          insertion_count=insertion_count,
          insert_window_ratio=insert_window_ratio,
      )
  )

  commands = [{"type": "reschedule", "now": base_now, "request_id": "initial"}]
  checks = [ScheduleCheck(0, "initial", base)]
  rolling_dataset = copy.deepcopy(base)
  insertion_metadata = []

  for insertion_index, insert_now in enumerate(resolved_insert_times):
    new_jobs = _build_inserted_jobs(
        fjspb,
        current_fjspb=rolling_dataset["fjspb"],
        rng=rng,
        scenario_seed=scenario_seed,
        insertion_index=insertion_index,
        inserted_jobs=inserted_jobs,
        inserted_task_count=inserted_task_count,
        enforce_even_centrifuge=enforce_even_centrifuge_inserts,
    )
    rolling_dataset = copy.deepcopy(rolling_dataset)
    rolling_dataset["fjspb"]["cur_ptr"] = insert_now
    rolling_dataset["fjspb"].setdefault("jobs", []).extend(copy.deepcopy(new_jobs))

    commands.append({"type": "tick", "time": insert_now})
    commands.append(
        {
            "type": "insert_jobs",
            "now": insert_now,
            "insert_time": insert_now,
            "jobs": new_jobs,
            "request_id": f"insert_jobs_{insertion_index + 1}",
        }
    )
    reschedule_index = len(commands)
    request_id = f"after_insert_{insertion_index + 1}"
    commands.append({"type": "reschedule", "now": insert_now, "request_id": request_id})
    commands.append(
        {
            "type": "dispatch_until",
            "time": insert_now,
            "request_id": f"dispatch_{insertion_index + 1}",
        }
    )
    checks.append(ScheduleCheck(reschedule_index, request_id, copy.deepcopy(rolling_dataset)))
    insertion_metadata.append(
        {
            "index": insertion_index + 1,
            "insert_now": insert_now,
            "inserted_jobs": len(new_jobs),
            "inserted_task_count": inserted_task_count,
        }
    )

  return OnlineScenario(
      commands=commands,
      checks=checks,
      metadata={
          "scenario_seed": scenario_seed,
          "kind": (
              "rolling_explicit_small_insertions"
              if insert_times is not None
              else "rolling_random_small_insertions"
          ),
          "insertion_count": len(resolved_insert_times),
          "insertions": insertion_metadata,
          "insert_now": resolved_insert_times[-1] if resolved_insert_times else base_now,
          "inserted_jobs_per_event": inserted_jobs,
          "inserted_task_count": inserted_task_count,
          "insert_window_ratio": list(insert_window_ratio),
          "explicit_insert_times": list(resolved_insert_times)
          if insert_times is not None
          else None,
          "enforce_even_centrifuge_inserts": enforce_even_centrifuge_inserts,
      },
  )


def _explicit_insert_times(insert_times: list[int], *, base_now: int) -> list[int]:
  times = sorted(int(value) for value in insert_times)
  if not times:
    raise ValueError("insert_times must contain at least one time")
  if any(value < base_now for value in times):
    raise ValueError("insert_times must be at or after the dataset cur_ptr")
  if len(set(times)) != len(times):
    raise ValueError("insert_times must be unique")
  return times


def _random_insert_times(
    fjspb: dict,
    rng: random.Random,
    *,
    base_now: int,
    insertion_count: int,
    insert_window_ratio: tuple[float, float],
) -> list[int]:
  count = max(1, int(insertion_count or 1))
  low_ratio, high_ratio = insert_window_ratio
  low_ratio = max(0.0, min(1.0, low_ratio))
  high_ratio = max(low_ratio, min(1.0, high_ratio))
  horizon_hint = max(1, _duration_horizon_hint(fjspb))
  low = base_now + int(horizon_hint * low_ratio)
  high = base_now + max(low + 1, int(horizon_hint * high_ratio))
  if count == 1:
    return [rng.randint(low, high)]
  span = max(1, high - low)
  if span + 1 >= count:
    return sorted(rng.sample(range(low, high + 1), count))
  times = []
  for idx in range(count):
    left = low + int(span * idx / count)
    right = low + int(span * (idx + 1) / count)
    times.append(rng.randint(left, max(left, right)))
  return sorted(times)


def _duration_horizon_hint(fjspb: dict) -> int:
  total = 0
  max_fixed_end = int(fjspb.get("cur_ptr") or 0)
  for job in fjspb.get("jobs", []):
    for task in job.get("tasks", []):
      total += int(task.get("duration") or 1)
      if task.get("fixed_end") is not None:
        max_fixed_end = max(max_fixed_end, int(task["fixed_end"]))
  machine_count = max(1, len(fjspb.get("machines", {})))
  return max(max_fixed_end, total // machine_count)


def _build_inserted_jobs(
    fjspb: dict,
    *,
    current_fjspb: dict,
    rng: random.Random,
    scenario_seed: int,
    insertion_index: int,
    inserted_jobs: int,
    inserted_task_count: int,
    enforce_even_centrifuge: bool = False,
) -> list[dict]:
  jobs = fjspb.get("jobs", [])
  if not jobs:
    return []
  count = max(1, min(inserted_jobs, len(jobs)))
  templates = _select_insert_templates(
      jobs,
      current_fjspb=current_fjspb,
      rng=rng,
      count=count,
      inserted_task_count=inserted_task_count,
      enforce_even_centrifuge=enforce_even_centrifuge,
  )
  inserted = []
  expr_no = f"online_inserted_seed_{scenario_seed}_event_{insertion_index + 1}"
  existing_ids = {str(job.get("job_id")) for job in jobs}
  for index, template in enumerate(templates):
    job = copy.deepcopy(template)
    base_id = str(template.get("job_id", f"template_{index}"))
    job_id = f"online_seed_{scenario_seed}_event_{insertion_index + 1}_{index}_{base_id}"
    while job_id in existing_ids:
      job_id = f"online_seed_{scenario_seed}_event_{insertion_index + 1}_{index}_{job_id}"
    existing_ids.add(job_id)
    job["job_id"] = job_id
    job["expr_no"] = expr_no
    job["expr_name"] = f"online_inserted_seed_{scenario_seed}_event_{insertion_index + 1}"
    task_count = max(1, min(inserted_task_count, len(job.get("tasks", []))))
    job["tasks"] = copy.deepcopy(job.get("tasks", [])[:task_count])
    for new_task_id, task in enumerate(job.get("tasks", [])):
      task["task_id"] = new_task_id
      if "step_index" in task:
        task["step_index"] = new_task_id
      task["is_fixed"] = False
      task["fixed_start"] = None
      task["fixed_end"] = None
      task["scheduled_machine"] = None
      task["next_scheduled_machine"] = None
      task["has_existing_schedule"] = False
    inserted.append(job)
  return inserted


def _select_insert_templates(
    jobs: list[dict],
    *,
    current_fjspb: dict,
    rng: random.Random,
    count: int,
    inserted_task_count: int,
    enforce_even_centrifuge: bool,
) -> list[dict]:
  if len(jobs) < count:
    return jobs[:]
  if not enforce_even_centrifuge:
    return rng.sample(jobs, count)

  current_counts = _centrifuge_group_counts(current_fjspb.get("jobs", []))
  attempts = min(2000, max(100, len(jobs) * len(jobs)))
  for _ in range(attempts):
    templates = rng.sample(jobs, count)
    increment = _centrifuge_group_counts(templates, task_limit=inserted_task_count)
    if _keeps_centrifuge_even(current_counts, increment):
      return templates

  raise ValueError(
      "could not sample inserted jobs that keep centrifuge task counts even "
      f"for inserted_jobs={count}, inserted_task_count={inserted_task_count}"
  )


def _keeps_centrifuge_even(
    current_counts: dict[tuple[str, int], int],
    increment: dict[tuple[str, int], int],
) -> bool:
  keys = set(current_counts) | set(increment)
  return all((current_counts.get(key, 0) + increment.get(key, 0)) % 2 == 0 for key in keys)


def _centrifuge_group_counts(
    jobs: list[dict],
    *,
    task_limit: int | None = None,
) -> dict[tuple[str, int], int]:
  counts = {}
  for job in jobs:
    tasks = job.get("tasks", [])
    if task_limit is not None:
      tasks = tasks[: max(1, min(task_limit, len(tasks)))]
    for task in tasks:
      group = _centrifuge_group(task)
      if group is not None:
        counts[group] = counts.get(group, 0) + 1
  return counts


def _centrifuge_group(task: dict) -> tuple[str, int] | None:
  machines = [str(machine) for machine in task.get("machines", [])]
  flags = task.get("flags") or {}
  text = " ".join(
      [
          str(task.get("name", "")),
          str(task.get("nominal_machine", "")),
          str(task.get("scheduled_machine", "")),
      ]
      + machines
  ).lower()
  if "centrifug" not in text and not flags.get("centrifuge"):
    return None
  machine = next(
      (machine for machine in machines if "centrifug" in machine.lower()),
      machines[0] if machines else "centrifuge",
  )
  return machine, int(task.get("duration") or task.get("time") or 1)


def render_command_sender_script(scenario: OnlineScenario) -> str:
  """Renders a small seed-generated command sender script.

  This is an external training driver artifact: it may contain the seeded
  insertion time. Candidate scheduler code must still read insertion time from
  command fields instead of hard-coding it.
  """
  import pprint

  commands_literal = pprint.pformat(scenario.commands, width=88, sort_dicts=False)
  metadata_literal = pprint.pformat(scenario.metadata, width=88, sort_dicts=False)
  return f'''"""Seed-generated online insertion command sender."""

SCENARIO_METADATA = {metadata_literal}

COMMANDS = {commands_literal}


def send_commands(scheduler):
    """Send the seeded command stream to a DynamicScheduler instance."""
    events = []
    for command in COMMANDS:
        response = scheduler.handle_command(command)
        events.append({{"command": command, "response": response}})
    return {{"events": events}}


def insertion_time():
    """Return the seeded insertion time used by this command stream."""
    return SCENARIO_METADATA.get("insert_now")
'''
