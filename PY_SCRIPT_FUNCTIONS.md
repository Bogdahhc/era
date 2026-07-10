# /home/era/implementation Python 脚本功能清单

- 范围：仅 `/home/era/implementation/**/*.py`，共 152 个。
- 已排除：`experiments` 生成候选、`.agents`、顶层 `scripts`。
- 数据来源按子项目列一次；逐脚本表不再重复数据路径。

## 子项目数据来源

- `implementation`：通用模块无固定调度原始数据；`playground_s3e1.py` 使用 `/home/era/implementation/data/playground-series-s3e1/*.csv`。
- `implementation/job_shop_era`：`job_shop_lib` 内置 benchmark；本地镜像在 `/home/era/implementation/job_shop_era/datasets/benchmarks/*.json`，默认 `ft06`。
- `implementation/exact_job_shop_era`：`job_shop_lib` 内置 benchmark；本地镜像同 `job_shop_era/datasets/benchmarks/*.json`，默认 `ft06`。
- `implementation/multi_bot_era`：默认 `/home/era/implementation/multi_bot_era/datasets/json/era_mixed_scheduling_benchmark.json`；也支持 `datasets/json/*.json` 和 `datasets/sqlite/*.sqlite`。
- `implementation/multi_bot_online_era`：默认复用 `/home/era/implementation/multi_bot_era/datasets/sqlite/4_experiments.sqlite`；也支持 `multi_bot_era` 的 JSON/SQLite 数据集。
- `implementation/flow_1160_era`：默认 `/home/era/implementation/flow_1160_era/datasets/project_1160/cache/1160.json`；原始响应在 `raw/*.json`；工时覆盖 `/home/era/implementation/flow_1160_era/duration_override.json`；项目 id 会回退实时 API 并缓存到 `/home/era/experiments/flow_1160_cache/<id>.json`。
- `implementation/flow_1160_era_v2`：沿用 Flow 1160 cache `implementation/flow_1160_era/datasets/project_1160/cache/1160.json`，可回退 `/home/era/experiments/flow_1160_cache/<id>.json` 或实时 API。
- `implementation/flow_1160_era_v3`：沿用 Flow 1160 cache；可回退 experiments cache 或实时 API；事件回放默认 `/tmp/events1160.json`。
- `implementation/flow_1160_era_v4`：沿用 Flow 1160 cache；v4 seed 输入在 `/home/era/implementation/flow_1160_era_v4/default_seeds/*.json`；可回退 experiments cache 或实时 API；事件回放默认 `/tmp/events1160.json`。

## 逐脚本清单

### `implementation`

| 脚本 | 功能 |
| --- | --- |
| `implementation/futs.py` | 通用 FUTS 核心。 |
| `implementation/futs_test.py` | FUTS 单元测试。 |
| `implementation/llm.py` | LLM 客户端封装。 |
| `implementation/playground_s3e1.py` | California Housing 示例问题。 |
| `implementation/sandbox.py` | 候选脚本沙箱/子进程运行。 |

### `implementation/exact_job_shop_era`

| 脚本 | 功能 |
| --- | --- |
| `implementation/exact_job_shop_era/__init__.py` | 包初始化。 |
| `implementation/exact_job_shop_era/audit_cli.py` | 审计 exact job-shop 生成求解器/实验结果。 |
| `implementation/exact_job_shop_era/backends.py` | exact job-shop 后端接口。 |
| `implementation/exact_job_shop_era/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/exact_job_shop_era/cp_sat_solver.py` | OR-Tools CP-SAT job-shop 求解器。 |
| `implementation/exact_job_shop_era/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/exact_job_shop_era/json_llm.py` | LLM JSON 规格解析/校验。 |
| `implementation/exact_job_shop_era/logger.py` | 实验节点、tree、best、audit 等产物记录。 |
| `implementation/exact_job_shop_era/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/exact_job_shop_era/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/exact_job_shop_era/plot_tree_cli.py` | 实验搜索树绘图 CLI。 |
| `implementation/exact_job_shop_era/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/exact_job_shop_era/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/exact_job_shop_era/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/exact_job_shop_era/seed.py` | 根节点/初始候选模板。 |
| `implementation/exact_job_shop_era/spec.py` | exact job-shop 求解器生成规格。 |

### `implementation/flow_1160_era`

| 脚本 | 功能 |
| --- | --- |
| `implementation/flow_1160_era/__init__.py` | 包初始化。 |
| `implementation/flow_1160_era/audit_modeling.py` | 审计 Flow 1160 初版建模、缓存和约束覆盖。 |
| `implementation/flow_1160_era/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/flow_1160_era/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/flow_1160_era/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/flow_1160_era/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/flow_1160_era/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/flow_1160_era/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/flow_1160_era/reference_cpsat_candidate.py` | Flow 1160 参考 CP-SAT 候选。 |
| `implementation/flow_1160_era/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/flow_1160_era/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/flow_1160_era/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/flow_1160_era/seed.py` | 根节点/初始候选模板。 |

### `implementation/flow_1160_era_v2`

| 脚本 | 功能 |
| --- | --- |
| `implementation/flow_1160_era_v2/__init__.py` | 包初始化。 |
| `implementation/flow_1160_era_v2/audit_v2.py` | 审计 Flow 1160 v2 建模与边界配置。 |
| `implementation/flow_1160_era_v2/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/flow_1160_era_v2/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/flow_1160_era_v2/isaac_twin.py` | Isaac Sim 事件回放/截图。 |
| `implementation/flow_1160_era_v2/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/flow_1160_era_v2/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/flow_1160_era_v2/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/flow_1160_era_v2/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/flow_1160_era_v2/reference_v2_cpsat_candidate.py` | Flow 1160 v2 参考 CP-SAT 候选。 |
| `implementation/flow_1160_era_v2/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/flow_1160_era_v2/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/flow_1160_era_v2/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/flow_1160_era_v2/seed.py` | 根节点/初始候选模板。 |
| `implementation/flow_1160_era_v2/twin_render_matplotlib.py` | Matplotlib 事件/孪生回放图。 |
| `implementation/flow_1160_era_v2/twin_replay_text.py` | 事件序列文本回放。 |
| `implementation/flow_1160_era_v2/v2_ir_to_events.py` | v2 assignment 转事件序列。 |

### `implementation/flow_1160_era_v3`

| 脚本 | 功能 |
| --- | --- |
| `implementation/flow_1160_era_v3/__init__.py` | 包初始化。 |
| `implementation/flow_1160_era_v3/adaptive_futs.py` | 自适应 FUTS 搜索。 |
| `implementation/flow_1160_era_v3/adaptive_logistics_gap.py` | 搜索/分析物流转运间隔。 |
| `implementation/flow_1160_era_v3/audit_v3.py` | 审计 Flow 1160 v3 物流、物料和孪生元数据。 |
| `implementation/flow_1160_era_v3/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/flow_1160_era_v3/command_ir.py` | 构造命令级 IR。 |
| `implementation/flow_1160_era_v3/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/flow_1160_era_v3/isaac_motion.py` | Isaac/孪生运动时序。 |
| `implementation/flow_1160_era_v3/isaac_twin.py` | Isaac Sim 事件回放/截图。 |
| `implementation/flow_1160_era_v3/monitor_cli.py` | 排程监控 CLI。 |
| `implementation/flow_1160_era_v3/monitor_smoke.py` | 监控 smoke test。 |
| `implementation/flow_1160_era_v3/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/flow_1160_era_v3/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/flow_1160_era_v3/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/flow_1160_era_v3/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py` | Flow 1160 v3 参考 CP-SAT 候选。 |
| `implementation/flow_1160_era_v3/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/flow_1160_era_v3/schedule_monitor.py` | 监控设备占用、转运和安全间隔违规。 |
| `implementation/flow_1160_era_v3/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/flow_1160_era_v3/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/flow_1160_era_v3/seed.py` | 根节点/初始候选模板。 |
| `implementation/flow_1160_era_v3/twin_render_matplotlib.py` | Matplotlib 事件/孪生回放图。 |
| `implementation/flow_1160_era_v3/twin_replay_text.py` | 事件序列文本回放。 |
| `implementation/flow_1160_era_v3/v3_ir_to_events.py` | v3 assignment 转事件序列。 |

### `implementation/flow_1160_era_v4`

| 脚本 | 功能 |
| --- | --- |
| `implementation/flow_1160_era_v4/__init__.py` | 包初始化。 |
| `implementation/flow_1160_era_v4/adaptive_futs.py` | 自适应 FUTS 搜索。 |
| `implementation/flow_1160_era_v4/adaptive_logistics_gap.py` | 搜索/分析物流转运间隔。 |
| `implementation/flow_1160_era_v4/audit_v4.py` | 审计 Flow 1160 v4 seed instance、动态和边界配置。 |
| `implementation/flow_1160_era_v4/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/flow_1160_era_v4/command_ir.py` | 构造命令级 IR。 |
| `implementation/flow_1160_era_v4/dynamic_executor.py` | v4 动态调度候选执行。 |
| `implementation/flow_1160_era_v4/dynamic_sandbox.py` | v4 动态候选沙箱。 |
| `implementation/flow_1160_era_v4/dynamic_scenario.py` | v4 在线插入/重调度场景。 |
| `implementation/flow_1160_era_v4/dynamic_scenario_cli.py` | v4 动态场景 CLI。 |
| `implementation/flow_1160_era_v4/dynamic_scorer.py` | v4 动态调度评分。 |
| `implementation/flow_1160_era_v4/dynamic_search.py` | v4 动态 FUTS 搜索。 |
| `implementation/flow_1160_era_v4/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/flow_1160_era_v4/isaac_motion.py` | Isaac/孪生运动时序。 |
| `implementation/flow_1160_era_v4/isaac_twin.py` | Isaac Sim 事件回放/截图。 |
| `implementation/flow_1160_era_v4/monitor_cli.py` | 排程监控 CLI。 |
| `implementation/flow_1160_era_v4/monitor_smoke.py` | 监控 smoke test。 |
| `implementation/flow_1160_era_v4/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/flow_1160_era_v4/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/flow_1160_era_v4/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/flow_1160_era_v4/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/flow_1160_era_v4/reference_v4_cpsat_candidate.py` | Flow 1160 v4 参考 CP-SAT 候选。 |
| `implementation/flow_1160_era_v4/reference_v4_dynamic_candidate.py` | v4 动态参考候选。 |
| `implementation/flow_1160_era_v4/reference_v4_dynamic_serial_candidate.py` | v4 动态串行参考/root 候选。 |
| `implementation/flow_1160_era_v4/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/flow_1160_era_v4/schedule_monitor.py` | 监控设备占用、转运和安全间隔违规。 |
| `implementation/flow_1160_era_v4/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/flow_1160_era_v4/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/flow_1160_era_v4/seed.py` | 根节点/初始候选模板。 |
| `implementation/flow_1160_era_v4/seed_instance.py` | 加载/应用 v4 seed instance。 |
| `implementation/flow_1160_era_v4/twin_render_matplotlib.py` | Matplotlib 事件/孪生回放图。 |
| `implementation/flow_1160_era_v4/twin_replay_text.py` | 事件序列文本回放。 |
| `implementation/flow_1160_era_v4/v4_ir_to_events.py` | v4 assignment 转事件序列。 |

### `implementation/job_shop_era`

| 脚本 | 功能 |
| --- | --- |
| `implementation/job_shop_era/__init__.py` | 包初始化。 |
| `implementation/job_shop_era/benchmarks.py` | job-shop benchmark 列表和过滤。 |
| `implementation/job_shop_era/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/job_shop_era/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/job_shop_era/futs_adapter.py` | job_shop_era 到通用 FUTS 的适配。 |
| `implementation/job_shop_era/logger.py` | 实验节点、tree、best、audit 等产物记录。 |
| `implementation/job_shop_era/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/job_shop_era/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/job_shop_era/plot_tree_cli.py` | 实验搜索树绘图 CLI。 |
| `implementation/job_shop_era/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/job_shop_era/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/job_shop_era/resume_cli.py` | 恢复并续跑 job_shop_era 实验。 |
| `implementation/job_shop_era/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/job_shop_era/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/job_shop_era/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/job_shop_era/seed.py` | 根节点/初始候选模板。 |

### `implementation/multi_bot_era`

| 脚本 | 功能 |
| --- | --- |
| `implementation/multi_bot_era/__init__.py` | 包初始化。 |
| `implementation/multi_bot_era/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/multi_bot_era/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/multi_bot_era/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/multi_bot_era/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/multi_bot_era/plot_tree_cli.py` | 实验搜索树绘图 CLI。 |
| `implementation/multi_bot_era/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/multi_bot_era/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/multi_bot_era/render_simulation_schedule.py` | 渲染多机器人调度结果。 |
| `implementation/multi_bot_era/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/multi_bot_era/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/multi_bot_era/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/multi_bot_era/seed.py` | 根节点/初始候选模板。 |

### `implementation/multi_bot_online_era`

| 脚本 | 功能 |
| --- | --- |
| `implementation/multi_bot_online_era/__init__.py` | 包初始化。 |
| `implementation/multi_bot_online_era/cli.py` | 命令行入口，加载数据并运行 single/FUTS/动态模式。 |
| `implementation/multi_bot_online_era/executor.py` | 候选脚本执行、超时、结果捕获。 |
| `implementation/multi_bot_online_era/mutator.py` | 构造 prompt 并生成候选变异。 |
| `implementation/multi_bot_online_era/plot.py` | 绘图：调度、搜索树或指标。 |
| `implementation/multi_bot_online_era/plot_tree_cli.py` | 实验搜索树绘图 CLI。 |
| `implementation/multi_bot_online_era/problem.py` | 加载原始输入并构造候选可见 problem/dataset。 |
| `implementation/multi_bot_online_era/prompt.py` | LLM 候选生成 prompt。 |
| `implementation/multi_bot_online_era/render_simulation_schedule.py` | 渲染多机器人调度结果。 |
| `implementation/multi_bot_online_era/sandbox.py` | 候选脚本沙箱/子进程运行。 |
| `implementation/multi_bot_online_era/scenario.py` | online 多机器人插入/重调度场景。 |
| `implementation/multi_bot_online_era/scenario_cli.py` | online 场景 CLI。 |
| `implementation/multi_bot_online_era/scorer.py` | 验证候选输出并计算分数。 |
| `implementation/multi_bot_online_era/search.py` | FUTS 搜索循环和结果落盘。 |
| `implementation/multi_bot_online_era/seed.py` | 根节点/初始候选模板。 |
