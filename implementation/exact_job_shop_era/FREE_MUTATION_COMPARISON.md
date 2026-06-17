# exact_job_shop_era 相对自由变异的改动记录

日期：2026-06-17

本文档记录 `implementation/exact_job_shop_era` 相对自由 Python 代码变异模式做出的限制、结构化改动和工程取舍。这里的“自由变异”指候选脚本可以任意实现 `solve(instance)`，只要最终返回合法 schedule 并通过 scorer；它可以是启发式、局部搜索、贪心、随机修复或其他自包含 Python 逻辑。

`exact_job_shop_era` 的目标不是限制 FUTS 的探索价值，而是把探索空间收束到“能留下可复用精确/可验证求解脚本”的方向。

## 总体差异

| 维度 | 自由变异 | exact_job_shop_era 当前做法 |
| --- | --- | --- |
| 候选形态 | 任意 Python solver | 完整 Python solver，但 prompt 要求 CP-SAT 建模 |
| 输出对象 | 合法 `job_shop_lib.Schedule` | 同样返回合法 `job_shop_lib.Schedule` |
| 搜索目标 | 可行且 makespan 低即可 | 可行、makespan 低，并倾向可复用 CP-SAT 模型代码 |
| 变异内容 | 任意算法逻辑 | CP-SAT 变量、约束、hint、branching、repair、LNS 等 |
| 失败反馈 | 通常只知道分数/错误 | 传递 parent/best/recent/failure 结构化反馈 |
| 理论最优 | 不一定关注 bound/optimum | 支持 optimum 早停和达到 optimum 后继续优化运行时间 |
| 产物 | best.py 和节点候选 | best.py、nodes、versions、manifest、二维/三维图 |

## 为什么要限制自由变异

自由变异在小实例上能快速产生可行启发式，但有几个问题：

- 容易学到实例特化规则，而不是通用求解器结构。
- 候选脚本可能变成难维护的一次性贪心/修补代码。
- 失败原因难以迁移到下一代，因为缺少明确建模语义。
- 同等 makespan 下，运行时间优化可能压倒模型质量。
- 如果训练目标接近最优，继续自由变异的收益常变成微小代码技巧。

`exact_job_shop_era` 的限制目的，是让 FUTS 变异集中在可解释、可移植的 CP-SAT 模型改进上。

## Prompt 层改动

自由变异 prompt 通常只要求：

- 定义 `solve(instance)`。
- 返回合法 schedule。
- 尽量降低 makespan。

`exact_job_shop_era/prompt.py` 增加了以下要求：

- 返回完整 Python 代码，不返回 Markdown 或 JSON。
- 保留公开 API：`def solve(instance): ... return schedule`。
- 使用 OR-Tools CP-SAT：`from ortools.sat.python import cp_model`。
- 返回 `job_shop_lib.Schedule`。
- 不读写文件。
- 不 hard-code instance name、optimum 或 benchmark answer。
- 优先尝试可复用建模改动：
  - tighter horizons
  - redundant constraints
  - symmetry breaking
  - decision strategies
  - hints
  - decomposition
  - repair phases
  - CP-SAT-guided large-neighborhood search

这些要求把 LLM 的自由度从“任意 solver”收束为“CP-SAT 求解脚本变异”。

## 父子节点信息传递

自由变异通常只把父节点代码和一个分数交给 LLM。当前 `exact_job_shop_era` 会传递更完整的上下文：

- selected parent 的 node id、score、makespan、elapsed、feasible、error。
- 当前 best 节点的客观结果。
- 最近若干节点的结果。
- 最近失败节点的错误摘要。
- 当前 executor timeout。
- parent code。

这样做的原因是：FUTS 的树选择仍由 PUCT/score 驱动，但 LLM 生成子节点时需要知道“为什么父节点值得扩展”和“近期哪些变异失败了”。

## Executor 和 Scorer 层改动

自由变异只要返回一个可验证 schedule 就能得分。`exact_job_shop_era` 仍保持客观评分，但执行路径更加规范：

- 使用子进程 sandbox 运行候选。
- 调用候选 `solve(instance)`。
- 将返回对象转为 `Schedule`。
- 使用 `score_schedule(schedule)` 验证可行性。
- 可行节点按 makespan 和 elapsed 评分。
- crash、timeout、非法 schedule 返回 worst score。

当前标准分数为：

```text
score = -(makespan + elapsed_seconds / 100)
```

这保持了 makespan 主导，同时允许同等 makespan 下更快脚本胜出。

## Root Seed 改动

自由变异 root 可以是简单启发式，也可以是任何 baseline。`exact_job_shop_era/seed.py` 使用 CP-SAT interval model 作为 root：

- 每个 operation 建 start/end/interval。
- job 内 precedence。
- machine 上 `AddNoOverlap`。
- makespan 目标。
- solver 失败时返回按 job sequence 构造的 fallback schedule。

这个 root 的作用不是一次性最强，而是给 FUTS 一个可读、可变异的 CP-SAT 模型骨架。

## Optimum 相关改动

自由变异一般只跑固定 iterations。`exact_job_shop_era` 增加了两个与理论最优相关的模式：

### `--early-stop-at-optimum`

当 benchmark metadata 提供 `optimum`，且某个节点达到 `makespan <= optimum`，FUTS 停止继续生成新节点。

用途：

- 已达到理论最优时避免继续浪费 token。
- 适合只想找最优可行脚本的实验。

### `--optimize-runtime-after-optimum`

达到 optimum 后不早停，继续训练脚本运行速度。当前代码中保留兼容参数 `--runtime-score-makespan-weight`，但实际评分仍使用标准：

```text
score = -(makespan + elapsed_seconds / 100)
```

用途：

- 适合 makespan 已不可再改善，但仍希望获得更快、更稳定的最优脚本。

## 日志和审计改动

相对自由变异，当前 exact 版本更重视可追踪性：

- `nodes.jsonl`：节点分数、可行性、makespan、elapsed、error、visits、rank_score、puct。
- `candidates/node_XXXX.py`：每个候选的完整代码。
- `best.py`：当前最佳脚本。
- `tree.json`：最终树结构。
- `puct_audit.json`：PUCT/rank 计算审计。
- `versions.jsonl`：版本摘要。
- `version_summary.csv`：parent/root 差异摘要。
- `run_manifest.json`：实例、参数、root candidate 和环境信息。
- `breakthrough.png`：score/best-so-far 曲线。
- `tree_branches.png`：二维树结构。
- `tree_branches_3d.png`：三维树结构与 makespan gap。

这些文件让一次 FUTS 运行不仅留下结果，还能复盘“哪些变异有效、哪些失败、树如何扩展”。

## 当前仍然保留的自由度

虽然 prompt 要求 CP-SAT，但当前 exact 版本并没有完全封死所有自由度：

- 候选仍是完整 Python 文件，不是 JSON 参数。
- 候选可以加入 hint、repair、decomposition、LNS 等混合策略。
- 候选可以改变变量建模、约束顺序、目标、solver 参数。
- 候选可以使用启发式生成 warm start，只要最终返回合法 schedule。

也就是说，限制的是“问题求解范式”，不是只允许调几个固定参数。

## 当前硬限制和软限制

硬限制：

- 必须能 import。
- 必须定义 `solve(instance)`。
- 必须返回可转换的 `job_shop_lib.Schedule`。
- schedule 必须通过 scorer 可行性验证。
- 每个候选受外层 timeout 限制。

软限制：

- 必须使用 CP-SAT。
- 不 hard-code optimum 或 benchmark answer。
- 改动应是可复用建模/搜索改进。
- 失败后优先修复失败原因。

注意：CP-SAT 使用目前主要是 prompt 层要求，不是静态 gate。若要进一步接近 `multi_bot_era` 的执行限制，可在 executor 中增加静态检查，拒绝不包含 `cp_model`、`CpModel`、`CpSolver` 的候选。

## 常用命令

No-LLM smoke：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ft06 \
  --iterations 1 \
  --timeout-seconds 10 \
  --root-time-seconds 5 \
  --no-llm \
  --experiment-name exact_code_ft06_smoke
```

普通 LLM FUTS：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 20 \
  --timeout-seconds 300 \
  --experiment-name exact_code_ta31_futs_20
```

达到最优即早停：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --early-stop-at-optimum \
  --experiment-name exact_ta31_stop_at_optimum
```

达到最优后继续优化 runtime：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --optimize-runtime-after-optimum \
  --experiment-name exact_ta31_runtime_after_optimum
```

给已有实验补二维/三维树图：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name> \
  --three-d
```

## 后续建议

1. 增加 CP-SAT 静态 gate，使 prompt 软限制变成 executor 硬限制。
2. 增加 `--initial-code`，支持从已有 best.py 继续 FUTS。
3. 增加 finalize CLI，在异常退出后补写 best.py、manifest 和所有图。
4. 增加多实例评分，减少单 benchmark 过拟合。
5. 将 solver 的 `BestObjectiveBound()`、relative gap 写入 node log，方便判断理论最优证明状态。

## 本地运行命令

以下命令默认在 `/home/era` 下执行：

```bash
cd /home/era
```

推荐统一带上：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era
```

### No-LLM smoke

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ft06 \
  --iterations 1 \
  --timeout-seconds 10 \
  --root-time-seconds 5 \
  --no-llm \
  --experiment-name exact_code_ft06_smoke
```

### 普通 CP-SAT-code FUTS

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 20 \
  --timeout-seconds 300 \
  --experiment-name exact_code_ta31_futs_20
```

### 达到 benchmark optimum 后早停

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --early-stop-at-optimum \
  --experiment-name exact_ta31_stop_at_optimum
```

### 达到 optimum 后继续优化运行时间

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --optimize-runtime-after-optimum \
  --experiment-name exact_ta31_runtime_after_optimum
```

### 补二维树图

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name>
```

### 补三维树图

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.exact_job_shop_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name> \
  --three-d
```

### 查看运行状态

```bash
ps -efww | grep -E 'implementation.exact_job_shop_era.cli|<experiment-name>'
```

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
ps -efww | grep -E 'implementation.exact_job_shop_era.cli|<experiment-name>'
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
kill <PID>
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
```

## 图表轴含义

`exact_job_shop_era` 的图表基于 `nodes.jsonl`，用于复盘 CP-SAT-code FUTS 的节点质量、树结构和 makespan 改善路径。

### breakthrough.png

`breakthrough.png` 展示每个 node 的 score 和截至该 node 的 best-so-far score。

- x 轴：`node_id`，即 FUTS 节点生成顺序。
- y 轴：node score，当前按 `-(makespan + elapsed_seconds / 100)` 计算；值越大越好。
- 散点：每个有有限 score 的 node。
- 绿色阶梯线：best-so-far score，表示搜索过程中历史最佳值如何变化。
- 颜色：按 score 映射，颜色越深表示 score 越好。
- 注释框：当前最高 score 的 node，包含 node id、score 和 makespan。

如果某个节点 makespan 降低，曲线会明显上跳；如果 makespan 相同但运行时间变短，曲线只会小幅上升。

### tree_branches.png

`tree_branches.png` 是二维 FUTS 树分支图。

- x 轴：`node_id` / expansion order，表示节点生成顺序。
- y 轴：tree depth，root 深度为 0，子节点深度比父节点多 1。
- 灰色线：由 `parent_id` 定义的 parent-child 边。
- 散点：FUTS node。
- 颜色：按 score 映射，颜色越深表示 score 越好。
- 红色星标：当前 best node。
- 注释框：best node 的 node id、score、makespan。

这张图用于判断 FUTS 是在持续开发同一条高分链，还是在多个分支之间探索。

### tree_branches_3d.png

`tree_branches_3d.png` 是三维树图，在二维树结构基础上加入 makespan gap。

- x 轴：`node_id` / expansion order。
- y 轴：tree depth。
- z 轴：makespan gap to best，即 `node_makespan - best_makespan`。
- z 轴裁剪：图中 z 值会按 focus window 裁剪，避免极差节点压缩近优节点的视觉差异。
- 灰色线：parent-child 边。
- 点颜色：按 score 映射，颜色越深表示 score 越好。
- 红色星标：当前 best node，通常位于 z=0。

在 exact 版本中，这张图特别适合观察 CP-SAT 建模变异是否沿父子链稳定降低 makespan，以及达到已知 optimum 后是否主要转向运行时间优化。
