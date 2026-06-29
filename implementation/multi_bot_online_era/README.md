# multi_bot_online_era

`implementation.multi_bot_online_era` is an initial FUTS variant for dynamic
multi-bot lab scheduling.

The candidate script target is no longer a one-shot `solve(dataset)` function.
FUTS mutates scripts that expose:

```python
class DynamicScheduler:
    def __init__(self, dataset):
        ...

    def handle_command(self, command):
        ...
```

The evaluator sends an online command stream one command at a time:

- `reschedule`: solve the current scheduling snapshot with CP-SAT.
- `tick`: advance the in-memory clock.
- `insert_jobs`: send a newly inserted FJSPB task table without restarting the
  scheduler.
- `dispatch_until`: return dispatchable actions without changing fixed tasks.

For SQLite/FJSPB datasets, the scenario builder creates a deterministic task
insertion case. By default this is a seeded random small-task insertion over a
4_experiments-style background. With `--insertion-count N`, the scenario sends
N insertion events as separate runtime messages. The candidate never receives
the future insertion tables in one batch; it only sees each command when the
runner sends it.

The scorer validates every checked reschedule
with the existing FJSPB hard constraints, then maximizes:

```text
-(average_checked_makespan + cumulative_stability_penalty + elapsed_seconds / 100)
```

Each accepted reschedule overwrites the previous active plan. The stability
penalty discourages unnecessary changes between consecutive active plans. Tasks
from the previous active plan with `start < current_event_time` are treated as
runtime-fixed, so candidates cannot use hindsight to interrupt or rewrite work
that has already started.

Preview a 4_experiments insertion seed:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_online_era.scenario_cli \
  --scenario-seed 7 \
  --insertion-count 3 \
  --inserted-jobs 2 \
  --inserted-task-count 4
```

Emit the seed-generated external command sender script:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_online_era.scenario_cli \
  --scenario-seed 7 \
  --insertion-count 3 \
  --inserted-jobs 2 \
  --inserted-task-count 4 \
  --emit-command-script
```

The generated command sender may contain the seeded insertion time. Candidate
FUTS scripts must not hard-code that time; they must read `insert_time`, `now`,
or `tick` values from the command interface.

Smoke test:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_online_era.cli \
  --dataset /path/to/fjspb.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 30 \
  --no-llm \
  --scenario-seed 0 \
  --insertion-count 1 \
  --inserted-jobs 2 \
  --inserted-task-count 4 \
  --experiment-name multi_bot_online_root_smoke
```
