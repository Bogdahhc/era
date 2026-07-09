# multi_bot_era datasets

This directory stores raw datasets needed to run the public `multi_bot_era`
examples without relying on machine-local absolute paths.

## JSON examples

`json/era_mixed_scheduling_benchmark.json` is the default CLI dataset. The other
JSON files are local parallel multi-experiment examples used in earlier FUTS
runs:

- `json/simulation_4_experiments_parallel.json`
- `json/real_e1_e2_e3_e4_parallel.json`

Run the default smoke path:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 20 \
  --no-llm
```

## SQLite source

`sqlite/4_experiments.sqlite` is the original SQLite-style FJSPB source used by
the current `dataset["fjspb"]` loader path. It exercises machine capacity,
fixed-task hiding, batching, resource, and chemistry-specific scorer checks.

Example:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/implementation/multi_bot_era/datasets/sqlite/4_experiments.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 20 \
  --no-llm
```

`manifest.json` records each checked-in file and its original local source path.

