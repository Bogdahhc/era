"""Small deterministic smoke cases for the v3 schedule monitor."""

from __future__ import annotations

from implementation.flow_1160_era_v3.schedule_monitor import monitor_schedule


def _base_dataset(with_buffer: bool) -> dict:
  positions = [
      {"position_id": "pos:A", "device_name": "A", "kind": "device_slot", "capacity": 1},
      {"position_id": "pos:B", "device_name": "B", "kind": "device_slot", "capacity": 1},
  ]
  if with_buffer:
    positions.append({"position_id": "pos:BUF", "device_name": "BUF", "kind": "buffer_slot", "capacity": 1})
  return {
      "fjspb": {
          "machines": {"robot:1": 1},
          "device_commands": [
              {
                  "command_id": "cmd:swap:A_to_B",
                  "kind": "move",
                  "task_id": None,
                  "duration": 10,
                  "resource_ids": ["robot:1"],
                  "from_position_id": "pos:A",
                  "to_position_id": "pos:B",
                  "plate_id": "plate:A",
              },
              {
                  "command_id": "cmd:swap:B_to_A",
                  "kind": "move",
                  "task_id": None,
                  "duration": 10,
                  "resource_ids": ["robot:1"],
                  "from_position_id": "pos:B",
                  "to_position_id": "pos:A",
                  "plate_id": "plate:B",
              },
          ],
          "positions": positions,
          "plate_states": [
              {"plate_id": "plate:A", "initial_position_id": "pos:A"},
              {"plate_id": "plate:B", "initial_position_id": "pos:B"},
          ],
          "robot_resources": [{"resource_id": "robot:1", "capacity": 1, "reachable_positions": ["pos:A", "pos:B"]}],
      }
  }


def _swap_schedule() -> dict:
  return {
      "assignments": [],
      "command_assignments": [
          {
              "command_id": "cmd:swap:A_to_B",
              "resource_id": "robot:1",
              "start": 0,
              "end": 10,
              "from_position_id": "pos:A",
              "to_position_id": "pos:B",
              "plate_id": "plate:A",
          },
          {
              "command_id": "cmd:swap:B_to_A",
              "resource_id": "robot:1",
              "start": 10,
              "end": 20,
              "from_position_id": "pos:B",
              "to_position_id": "pos:A",
              "plate_id": "plate:B",
          },
      ],
  }


def main() -> None:
  no_buffer = monitor_schedule(_base_dataset(with_buffer=False), _swap_schedule())
  with_buffer = monitor_schedule(_base_dataset(with_buffer=True), _swap_schedule())
  if no_buffer["deadlock_count"] != 1:
    raise SystemExit("expected no-buffer swap deadlock, got %s" % no_buffer)
  if with_buffer["deadlock_count"] != 0:
    raise SystemExit("expected buffer case to avoid swap deadlock, got %s" % with_buffer)
  print("monitor_smoke_ok no_buffer_deadlocks=%d with_buffer_deadlocks=%d" % (no_buffer["deadlock_count"], with_buffer["deadlock_count"]))


if __name__ == "__main__":
  main()
