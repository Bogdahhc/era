# ERA: 面向调度优化的经验型软件协同写作 AI 系统

[![arXiv](https://img.shields.io/badge/arXiv-2509.06503-b31b1b.svg)](https://arxiv.org/abs/2509.06503)
[![Project Page](https://img.shields.io/badge/Project%20Page-google--research.github.io%2Fera-blue)](https://google-research.github.io/era/)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](./LICENSE)

本仓库是 Google ERA 的本地化扩展分支。它保留上游 ERA 的
Flat UCB Tree Search (FUTS) 框架，并把“生成代码 -> 执行代码 -> 客观评分
-> 继续变异”的闭环落地到作业车间、多机器人、湿实验流程图和在线滚动调度。

当前重点不只是生成一次性答案，而是让 FUTS 逐步产生可复用、可运行、可审计的
调度脚本。

## 当前成果

- 保留上游 ERA/FUTS 核心实现：`implementation/futs.py`、`implementation/llm.py`、
  `implementation/sandbox.py`。
- 新增六个调度应用分支：
  `job_shop_era`、`exact_job_shop_era`、`multi_bot_era`、
  `multi_bot_online_era`、`flow_1160_era`、`flow_1160_era_v2`。
- `flow_1160_era_v2` 已接入项目 1160 的流程图、运行态节点、物料流、物流节点、
  buffer 容量、P1/P2/P3 分路优先级和 rolling/fixed 调度接口。
- v2 默认使用 `history_policy=strict_cold_start`：候选不可见历史开始/结束时间，
  不能用历史 span 推导物流或任务时长，避免把历史运行结果当答案 replay。
- v2 当前可硬建的约束包括 task duration、eligible machine、frequency、
  required capacity、precedence、min wait、物料边级库存非负、物流拓扑、
  buffer 容量、机器 cumulative/no-overlap、rolling existing occupancy。
- v2 当前 blocked 约束包括完整 merge/split 数量平衡、初始库存、入出库方向、
  plate identity no-overlap；这些需要平台补充独立且可验证的字段。
- `multi_bot_online_era` 已从一次性 `solve(dataset)` 扩展为
  `DynamicScheduler(dataset).handle_command(command)`，支持 tick、insert_jobs、
  reschedule、dispatch_until 的在线命令流评测。

## 方法概览

`implementation/futs.py` 是上游论文 Algorithm 1 的通用单线程参考实现。调用方
只需要提供两个函数：

- `generate_fn(problem, parent_solution, parent_score)`：基于问题、父节点代码和反馈
  生成新候选脚本，通常由 LLM 完成。
- `execute_fn(problem, solution)`：在沙箱中执行候选脚本，并返回一个客观分数。

FUTS 最大化 score。调度任务通常把 makespan 转成负分：

```text
score = -(makespan + elapsed_seconds / 100)
```

因此 makespan 越短，score 越高。当某些分支已证明 makespan 全局最优后，后续
score 改善主要代表候选脚本求解速度或稳定性改善，而不是更短排程。

## 仓库结构

```text
era/
├── implementation/
│   ├── futs.py / futs_test.py
│   ├── llm.py
│   ├── sandbox.py
│   ├── playground_s3e1.py
│   ├── notebooks/
│   ├── job_shop_era/
│   ├── exact_job_shop_era/
│   ├── multi_bot_era/
│   ├── multi_bot_online_era/
│   ├── flow_1160_era/
│   └── flow_1160_era_v2/
├── scripts/
│   ├── build_fjspb_capacity_variant.py
│   ├── build_merged_fjspb_sqlite.py
│   ├── monitor_multi_bot_futs.py
│   └── prove_flow1160_v2_seed_optimal.py
├── experiments/
├── docs/
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

`experiments/` 保存本地实验产物。仓库中只保留已经入库的代表性结果；大量 smoke、
cache、agent 状态、日志和临时输出不作为源码的一部分上传。

## 环境

推荐 Python 3.10+。

```bash
pip install pandas numpy scikit-learn openai job-shop-lib ortools
```

LLM 配置默认从 `~/.config/era/openai.env` 或环境变量读取。常用环境变量包括：

```bash
export OPENAI_API_KEY="..."
export OPENAI_MODEL="..."
```

所有应用均支持 `--no-llm` 用于复现实验、跑已知候选或做 smoke test。

## 快速开始

### 原版 ERA 示例

```bash
cd /home/era/implementation
python playground_s3e1.py
```

上游科学任务 notebook 位于
[`implementation/notebooks`](./implementation/notebooks)。

### 自由变异 job-shop

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --instance ft06 \
  --mode futs \
  --iterations 50 \
  --timeout-seconds 30
```

候选脚本定义 `solve(instance)` 并返回 `job_shop_lib.Schedule`。算法形式不限，评分
只看可行性与 makespan。详见
[`implementation/job_shop_era/README.md`](./implementation/job_shop_era/README.md)。

### CP-SAT job-shop

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ft06 \
  --iterations 10 \
  --timeout-seconds 30 \
  --early-stop-at-optimum
```

候选仍返回 `job_shop_lib.Schedule`，但 prompt 要求使用 OR-Tools CP-SAT 建模，并
禁止 hard-code 实例答案。详见
[`implementation/exact_job_shop_era/FREE_MUTATION_COMPARISON.md`](./implementation/exact_job_shop_era/FREE_MUTATION_COMPARISON.md)。

### 离线多机器人调度

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /path/to/fjspb.sqlite \
  --mode futs \
  --iterations 20 \
  --timeout-seconds 450
```

候选脚本应使用 CP-SAT，并返回 `{"assignments": [...]}`。默认 root 是故意失败的
cold-start skeleton，用于测试 LLM/FUTS 能否从语言需求和反馈中生成完整可复用模型。

### 在线滚动多机器人调度

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

候选接口是：

```python
class DynamicScheduler:
    def __init__(self, dataset):
        ...

    def handle_command(self, command):
        ...
```

评测器逐条发送 `reschedule`、`tick`、`insert_jobs`、`dispatch_until`。候选只能看到
当前命令，不能假设未来插入事件或命令流长度。评分最大化：

```text
-(average_checked_makespan + cumulative_stability_penalty + elapsed_seconds / 100)
```

可用 `scenario_cli.py` 预览或导出确定性插入命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_online_era.scenario_cli \
  --scenario-seed 7 \
  --insertion-count 3 \
  --inserted-jobs 2 \
  --inserted-task-count 4 \
  --emit-command-script
```

### 项目 1160 流程图调度 v1

`flow_1160_era` 从智能调度系统项目 1160 的 flowData 和 projectAllNodeList 构造
FJSPB IR，接入真实 duration、temperature、frequency、capacity、precedence_pairs
和 P1/P2/P3 开始优先级。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.flow_1160_era.cli \
  --mode futs \
  --iterations 0 \
  --no-llm \
  --timeout-seconds 10
```

更多建模记录见
[`implementation/flow_1160_era/IMPROVEMENT_LOG.md`](./implementation/flow_1160_era/IMPROVEMENT_LOG.md)。

### 项目 1160 流程图调度 v2

`flow_1160_era_v2` 是当前最新分支。它保留 v1 的核心 scoring contract，并新增：

- `material_edges`
- `material_inventory_events`
- `material_lineage_links`
- `logistics_events`
- `buffers`
- `rolling_state`
- `constraint_realization_boundaries`
- `history_policy`

默认口径是 strict cold-start：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.flow_1160_era_v2.cli \
  --mode futs \
  --iterations 1 \
  --timeout-seconds 60 \
  --no-llm \
  --boundary-profile conservative \
  --boundary-seed 1160 \
  --history-policy strict_cold_start
```

审计 IR：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.flow_1160_era_v2.audit_v2 \
  --boundary-profile conservative \
  --boundary-seed 1160 \
  --history-policy strict_cold_start
```

证明当前 IR/seed/history-policy 口径下的 makespan 最优性：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python scripts/prove_flow1160_v2_seed_optimal.py
```

v2 数据落地边界见
[`REALISTIC_DATA_REQUIREMENTS.md`](./implementation/flow_1160_era_v2/REALISTIC_DATA_REQUIREMENTS.md)，
完整改进日志见
[`IMPROVEMENT_LOG.md`](./implementation/flow_1160_era_v2/IMPROVEMENT_LOG.md)。

## 应用对比

| 分支 | 候选脚本接口 | 主要约束 | 评分口径 |
| --- | --- | --- | --- |
| `job_shop_era` | `solve(instance) -> Schedule` | job-shop 可行性 | `-makespan` |
| `exact_job_shop_era` | `solve(instance) -> Schedule` | CP-SAT、禁止 hard-code、optimum 早停 | makespan + runtime tie-break |
| `multi_bot_era` | `solve(dataset) -> {"assignments": [...]}` | FJSPB、机器容量、precedence、fixed task | `-(makespan + elapsed/100)` |
| `multi_bot_online_era` | `DynamicScheduler.handle_command` | 在线插入、rolling fixed、稳定性 | 平均 makespan + 稳定性惩罚 |
| `flow_1160_era` | `solve(dataset) -> {"assignments": [...]}` | 项目 1160 task IR、真实 duration/capacity/frequency | `-(makespan + elapsed/100)` |
| `flow_1160_era_v2` | 同上 | v1 + 物料/物流/buffer/rolling/边界接口 | strict cold-start makespan + runtime |

## 项目 1160 当前建模口径

当前 v2 默认只把已经能从平台字段独立验证的内容作为硬约束：

- task duration、eligible machine、frequency、required capacity；
- `precedence_pairs`、`minWaitTime`、P1/P2/P3 start priority；
- `material_edges[*].hard_precedence_candidate`；
- `material_inventory_events` 的边级库存非负；
- strict 模式下零时长 logistics 拓扑前序；
- buffer capacity 与机器 cumulative/no-overlap；
- rolling existing occupancy。

以下内容只做 audit 或 blocked metadata，不允许候选私自硬建：

- 完整 merge/split 数量平衡；
- 初始库存；
- 入出库方向；
- plate identity no-overlap；
- 未确认的 `quantityConsumeRule` / `plateOperType` 枚举语义。

## 实验与产物

常见产物包括：

- `best.py`
- `nodes.jsonl`
- `versions.jsonl`
- `candidates/node_XXXX.py`
- `tree_branches.png`
- `tree_branches_3d.png`
- `manifest.json`

本地运行会产生大量 experiment/cache/log/agent 文件。上传源码时默认只提交可复用代码、
脚本、文档和代表性实验资料，不提交 `.claude`、`.agents`、`__pycache__`、日志、
临时 cache 或大批运行输出。

## 引用

如使用了本仓库的代码或数据，请引用上游 ERA 论文：

```bibtex
@misc{aygun2025aihelpscientistswrite,
      title={An AI system to help scientists write expert-level empirical software},
      author={Eser Aygün and Anastasiya Belyaeva and Gheorghe Comanici and Marc Coram and Hao Cui and Jake Garrison and Renee Johnston and Anton Kast and Cory Y. McLean and Peter Norgaard and Zahra Shamsi and David Smalling and James Thompson and Subhashini Venugopalan and Brian P. Williams and Chujun He and Sarah Martinson and Martyna Plomecka and Lai Wei and Yuchen Zhou and Qian-Ze Zhu and Matthew Abraham and Erica Brand and Anna Bulanova and Jeffrey A. Cardille and Chris Co and Scott Ellsworth and Grace Joseph and Malcolm Kane and Ryan Krueger and Johan Kartiwa and Dan Liebling and Jan-Matthis Lueckmann and Paul Raccuglia and Xuefei Wang and Katherine Chou and James Manyika and Yossi Matias and John C. Platt and Lizzie Dorfman and Shibl Mourad and Michael P. Brenner},
      year={2025},
      eprint={2509.06503},
      archivePrefix={arXiv},
      primaryClass={cs.AI},
      url={https://arxiv.org/abs/2509.06503}
}
```

## 许可证

Apache License 2.0，详见 [`LICENSE`](./LICENSE)。

本项目并非 Google 官方支持的产品。
