# job_shop_era datasets

This directory stores a small checked-in snapshot of benchmark instances used by
the `job_shop_era` examples and smoke tests.

Files under `benchmarks/` are JSON exports from:

```python
job_shop_lib.benchmarking.load_benchmark_instance(name).to_dict()
```

The runtime loader still uses `job_shop_lib` by benchmark name, so these files
are primarily raw-data references for GitHub readers and offline inspection.
`benchmarks/manifest.json` records the included instance names, sizes, metadata,
and source API.

Included instances:

- `ft06`, `ft10`: small Fisher-Thompson smoke-test instances.
- `ta21`, `ta31`: medium Taillard instances used in FUTS runs.
- `ta51`, `ta71`: larger Taillard stress instances.

