# job_shop_era

This package adapts `job_shop_lib` scheduling benchmarks to the generic FUTS
interface in `implementation/futs.py`.

## FUTS Interface

`implementation/futs.search` needs:

```python
generate_fn(problem, parent_solution, parent_score) -> futs.Solution
execute_fn(problem, solution) -> float
```

For job-shop scheduling:

- `problem` is a `JobShopProblem` containing a serialized
  `job_shop_lib.JobShopInstance`.
- `solution.program` is Python code that must define:

```python
def solve(instance):
  ...
  return schedule
```

- `schedule` must be a `job_shop_lib.Schedule`.
- `execute_fn` runs the code in a subprocess sandbox, checks feasibility with
  `job_shop_lib.Schedule.check_schedule`, and returns `-makespan`.
- FUTS maximizes score, so lower makespan becomes a higher score.

## Minimal Usage

No LLM smoke test:

```python
from implementation import futs
from implementation.job_shop_era import build_components

components = build_components(instance_name="ft06", timeout_seconds=30)
best_solution, best_score = futs.search(
    problem=components.problem,
    initial_solution=components.initial_solution,
    initial_score=components.initial_score,
    generate_fn=components.generate_fn,
    execute_fn=components.execute_fn,
    num_iterations=1,
    c_puct=1.0,
)
```

OpenAI-backed generation:

```python
from implementation import futs
from implementation.job_shop_era import build_components, make_openai_generate_fn

generate_fn = make_openai_generate_fn()
components = build_components(
    instance_name="ft06",
    generate_fn=generate_fn,
    timeout_seconds=30,
)
best_solution, best_score = futs.search(
    problem=components.problem,
    initial_solution=components.initial_solution,
    initial_score=components.initial_score,
    generate_fn=components.generate_fn,
    execute_fn=components.execute_fn,
    num_iterations=50,
    c_puct=1.0,
)
```

Private API settings are loaded from `~/.config/era/openai.env` when present.
They are not stored in this repository.

## Benchmark Runs

The CLI hides benchmark reference values from the LLM prompt by default. The
full instance metadata is still kept on the `JobShopProblem` object for
external scoring, breakthrough plots, and optional optimum early stopping.

List instances larger than `ft10`:

```bash
python -m implementation.job_shop_era.cli \
  --list-benchmarks \
  --min-operations 400
```

Run a no-LLM smoke test on a larger instance:

```bash
python -m implementation.job_shop_era.cli \
  --mode futs \
  --instance ta21 \
  --iterations 1 \
  --timeout-seconds 20 \
  --no-llm \
  --experiment-name ta21_no_llm_smoke
```

Run an OpenAI-backed FUTS search and stop when a known optimum is reached:

```bash
python -m implementation.job_shop_era.cli \
  --mode futs \
  --instance ta21 \
  --iterations 50 \
  --timeout-seconds 45 \
  --early-stop-at-optimum \
  --experiment-name ta21_futs_50
```

Continue an existing FUTS experiment in place:

```bash
python -m implementation.job_shop_era.resume_cli \
  --experiment-dir experiments/ta21_futs_50 \
  --instance ta21 \
  --iterations 10 \
  --timeout-seconds 45 \
  --early-stop-at-optimum
```

The resume command reads `nodes.jsonl`, `tree.json`, and
`candidates/node_XXXX.py` from the experiment directory, appends new FUTS nodes,
then rewrites `tree.json`, `puct_audit.json`, `best.py`, and
`breakthrough.png` in the same directory. The breakthrough plot uses node id on
the x-axis and `-log(-best score)` on the y-axis. For job-shop scoring this is
`-log(best makespan)`, so improvements still appear as an upward step curve.
The plot starts at node 3, and the final best makespan is annotated on the last
point.

Plot the FUTS tree branches for an experiment:

```bash
python -m implementation.job_shop_era.plot_tree_cli \
  --experiment-dir experiments/ta21_futs_50
```

This writes `tree_branches.png` in the experiment directory. The plot starts at
node 3. The x-axis is node id / expansion order, the y-axis is tree depth, edges
show parent-child expansions, and the best node is marked with a star.

To include makespan as a z-axis instead of adding another 2D encoding:

```bash
python -m implementation.job_shop_era.plot_tree_cli \
  --experiment-dir experiments/ta21_futs_50 \
  --three-d
```

This writes `tree_branches_3d.png` with x = node id / expansion order,
y = tree depth, and z = makespan.

Recommended next instances:

- `ta21`, `ta24`, `ta28`, `yn1`: 20 jobs, 20 machines, 400 operations.
- `ta31`, `ta35`, `ta36`, `ta37`, `ta38`, `ta39`: 450 operations.
- `swv11`, `swv13`-`swv20`: 500 operations.
- `ta51`-`ta70`: 750-1000 operations.
- `ta71`-`ta80`: 2000 operations.
