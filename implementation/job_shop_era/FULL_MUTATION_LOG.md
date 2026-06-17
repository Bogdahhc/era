# job_shop_era 全变异版本日志

日期：2026-06-17

本文档记录 `implementation/job_shop_era` 作为 ERA 中“全变异/自由变异”版本的定位、接口、运行方式和与后续受限版本的差异。这里的“全变异”指每个 FUTS node 生成完整 Python solver 脚本，算法形式不被限制为 CP-SAT、MILP 或某个固定模板；只要候选能返回合法 `job_shop_lib.Schedule` 并通过 scorer，就可以进入 FUTS 树。

## 定位

`job_shop_era` 是最开放的 job-shop FUTS 代码搜索版本。它的目标是验证：

- LLM 是否能直接生成可运行 solver 脚本。
- FUTS 是否能基于 node score/PUCT 选择有潜力的父节点。
- 父节点代码经过自由变异后能否产生更低 makespan。
- 每次实验能否留下完整候选代码、节点日志和可视化产物。

与 `exact_job_shop_era` 不同，`job_shop_era` 不要求候选必须使用 CP-SAT。与 `multi_bot_era` 不同，它面对的是标准 `job_shop_lib` benchmark instance，而不是实验室 SQLite/FJSPB 任务接口。

## Candidate 接口

每个候选脚本必须定义：

```python
def solve(instance):
    ...
    return schedule
```

其中：

- `instance` 是 `job_shop_lib.JobShopInstance`。
- `schedule` 必须是 `job_shop_lib.Schedule`。
- executor 会在子进程 sandbox 中 import 候选脚本并调用 `solve(instance)`。
- scorer 会调用 `score_schedule(schedule)` 检查可行性和 makespan。

候选可以使用：

- `Schedule.from_job_sequences(instance, job_sequences)`
- `instance.jobs`
- `instance.num_jobs`
- `instance.num_machines`
- `instance.num_operations`
- 任意自包含 Python 启发式、局部搜索、排序规则、修复逻辑等。

候选不应依赖外部文件、网络服务或交互输入。

## 与受限版本的主要差异

| 维度 | job_shop_era 全变异 | exact_job_shop_era | multi_bot_era |
| --- | --- | --- | --- |
| 问题类型 | 标准 job-shop benchmark | 标准 job-shop benchmark | 多机器人/多任务 SQLite FJSPB |
| 候选脚本 | 自由 Python solver | CP-SAT-code solver | CP-SAT FJSPB solver |
| 输出 | `job_shop_lib.Schedule` | `job_shop_lib.Schedule` | `{"assignments": [...]}` |
| CP-SAT 要求 | 无硬要求 | prompt 层要求 | executor 静态 gate 要求 |
| 数据接口 | benchmark instance | benchmark instance | `dataset["fjspb"]` |
| 答案泄露风险 | reference values 默认从 prompt 隐藏 | 禁止 hard-code optimum/answer | 非固定 incumbent 字段不暴露 |
| 主要目标 | 探索自由变异能力 | 可复用精确求解脚本 | 可复用实验室排程脚本 |

## Prompt 行为

`job_shop_era/prompt.py` 的核心要求是：

- 返回完整 Python 代码。
- 定义 `solve(instance)`。
- 返回合法 `job_shop_lib.Schedule`。
- 优化 makespan。
- 使用可用的 job-shop API。

相对受限版本，它不会要求：

- 必须使用 OR-Tools。
- 必须构建 CP-SAT 模型。
- 必须从 solver variable values 导出结果。
- 必须覆盖某套领域约束 contract。

这种宽松 prompt 让 LLM 可以尝试更多启发式结构，但也更容易产生一次性脚本或实例特化规则。

## Scorer 和 Score

`job_shop_era/scorer.py` 只做客观 schedule 验证：

- 返回对象是否为 `Schedule`。
- `Schedule.check_schedule()` 是否通过。
- makespan 是否能计算。

score 以 makespan 为核心。FUTS maximizes score，因此 makespan 越低分数越高。不可行、异常、timeout 候选得到 worst score。

## FUTS 搜索模式

CLI 支持三种模式：

- `single`：root 生成一个 child，适合快速检查 LLM 输出。
- `bon`：Best-of-N，从 root 独立生成多个候选，不做树扩展。
- `futs`：标准 FUTS，根据 PUCT 选择父节点继续扩展。

FUTS 会记录：

- `nodes.jsonl`
- `candidates/node_XXXX.py`
- `tree.json`
- `puct_audit.json`
- `best.py`
- `breakthrough.png`

`resume_cli.py` 支持从已有实验目录继续追加 FUTS 节点。

## Benchmark Reference Values

默认情况下，CLI 会从 prompt 中隐藏 benchmark metadata 中的 reference values：

- optimum
- lower_bound
- upper_bound

这样做是为了减少候选 hard-code reference answer 的风险。完整 metadata 仍保留在 `JobShopProblem` 对象中，用于外部评分、画图和 `--early-stop-at-optimum`。

如果确实需要把 reference values 放进 prompt，可显式使用：

```bash
--include-reference-values-in-prompt
```

该选项应谨慎使用，因为它会增加 LLM 记住或硬编码 benchmark 信息的风险。

## 当前风险

全变异版本的优势是搜索空间大，风险也来自搜索空间大：

1. 候选可能变成不可维护的一次性启发式。
2. 候选可能过度适配单一 benchmark。
3. 没有 CP-SAT gate，无法保证产物是精确/可证明模型。
4. 只看单实例 makespan 时，泛化能力没有被评分。
5. 若 reference values 被暴露给 prompt，存在 hard-code 风险。

因此，`job_shop_era` 更适合作为自由探索基线；当目标变成“留下可复用精确求解脚本”时，应使用 `exact_job_shop_era`；当目标变成“实验室 SQLite/FJSPB 排程”时，应使用 `multi_bot_era`。

## 本地运行命令

以下命令默认在 `/home/era` 下执行：

```bash
cd /home/era
```

推荐统一带上：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era
```

### 列出 benchmark

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --list-benchmarks \
  --min-operations 400
```

### No-LLM smoke

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --mode futs \
  --instance ta21 \
  --iterations 1 \
  --timeout-seconds 20 \
  --no-llm \
  --experiment-name ta21_no_llm_smoke
```

### 单次 LLM 变异

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --mode single \
  --instance ft10 \
  --timeout-seconds 45 \
  --experiment-name ft10_single_generation
```

### Best-of-N

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --mode bon \
  --instance ta21 \
  --iterations 20 \
  --timeout-seconds 45 \
  --experiment-name ta21_bon_20
```

### FUTS

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.cli \
  --mode futs \
  --instance ta21 \
  --iterations 50 \
  --timeout-seconds 45 \
  --early-stop-at-optimum \
  --experiment-name ta21_futs_50
```

### 继续已有实验

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.resume_cli \
  --experiment-dir /home/era/experiments/ta21_futs_50 \
  --instance ta21 \
  --iterations 10 \
  --timeout-seconds 45 \
  --early-stop-at-optimum
```

### 补二维树图

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/ta21_futs_50
```

### 补三维树图

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.job_shop_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/ta21_futs_50 \
  --three-d
```

### 查看运行进程

```bash
ps -efww | grep -E 'implementation.job_shop_era.cli|implementation.job_shop_era.resume_cli'
```

### 查看节点进度

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path('/home/era/experiments/<experiment_name>/nodes.jsonl')
rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
print('count', len(rows))
finite = [row for row in rows if row.get('score') is not None]
if finite:
    best = max(finite, key=lambda row: row['score'])
    print('best', best['node_id'], best['makespan'], best['elapsed_seconds'], best['score'])
for row in rows[-10:]:
    print(row['node_id'], row['parent_id'], row['feasible'], row['makespan'], row['elapsed_seconds'], row.get('error'))
PY
```

### 按 PID 停止任务

```bash
ps -efww | grep -E 'implementation.job_shop_era.cli|<experiment-name>'
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
kill <PID>
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
```

