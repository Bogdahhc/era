# exact_job_shop_era

This package is a CP-SAT-code variant of `job_shop_era`.

Each FUTS node is now a Python candidate solver, saved under
`candidates/node_XXXX.py`. The candidate must define `solve(instance)` and
return a valid `job_shop_lib.Schedule`. Candidates are encouraged to use
OR-Tools CP-SAT, but FUTS mutates the actual Python modeling/search code rather
than a small JSON parameter spec.

The intended search target is a reusable solver script: CP-SAT model variants,
redundant constraints, hints, decomposition, repair phases, or hybrid
CP-SAT-guided search strategies.

## Usage

No-LLM smoke test:

```bash
python -m implementation.exact_job_shop_era.cli \
  --instance ft06 \
  --iterations 1 \
  --timeout-seconds 10 \
  --root-time-seconds 5 \
  --no-llm \
  --experiment-name exact_code_ft06_smoke
```

LLM-backed CP-SAT-code search:

```bash
python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 20 \
  --timeout-seconds 300 \
  --experiment-name exact_code_ta31_futs_20
```

Outputs are written under `experiments/<name>/`:

- `nodes.jsonl`: node score, makespan, feasibility, elapsed time, and PUCT fields
- `candidates/node_XXXX.py`: generated Python candidate solvers
- `tree.json`: final FUTS tree snapshot
- `best.py`: best generated candidate
- `breakthrough.png`: best-so-far makespan curve
- `tree_branches.png` and `tree_branches_3d.png` when enough nodes exist
