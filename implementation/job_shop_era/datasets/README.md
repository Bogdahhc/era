# job_shop_era datasets

This directory stores the full set of benchmark instances currently exposed by
the installed `job_shop_lib` package.

Files under `benchmarks/` are JSON exports from:

```python
job_shop_lib.benchmarking.load_all_benchmark_instances()
```

The runtime loader still uses `job_shop_lib` by benchmark name, so these files
are primarily raw-data references for GitHub readers and offline inspection.
`benchmarks/manifest.json` records the benchmark count, instance names, sizes,
metadata, and source API.

The checked-in export currently contains 162 benchmark JSON files, including
the common Fisher-Thompson (`ft*`), Lawrence (`la*`), Adams-Balazs-Zawack
(`abz*`), Storer-Wu-Vaccari (`swv*`), Taillard (`ta*`), and Yamada-Nakano
(`yn*`) families.

The runtime loader still uses `job_shop_lib` by benchmark name, so these files
serve as raw-data references for GitHub readers, reproducibility checks, and
offline inspection.
