# exact_job_shop_era Version Log

This document records the current differences between
`implementation/exact_job_shop_era` and `implementation/job_shop_era`.

## 目标变化

`job_shop_era` 是开放式 Python solver 搜索：每个 FUTS node 生成一个
`solve(instance)` 脚本，脚本可以使用任意自包含启发式、局部搜索或其他合法
Python 逻辑。

`exact_job_shop_era` 当前版本被改成 CP-SAT-code FUTS：每个 node 仍然输出
完整可运行的 Python solver 脚本，但搜索目标从“一般启发式 solver”收窄为
“可复用的 CP-SAT 建模/搜索控制脚本”。目标不是生成 JSON 参数，也不是只调
CP-SAT 参数，而是让 LLM 直接变异可维护、可复用的 Python 求解代码。

## Node 输出形式

相对旧版 `exact_job_shop_era` 的 JSON spec 搜索，当前版本已经改为：

- 每个 node 写入 `candidates/node_XXXX.py`。
- 候选脚本必须定义 `solve(instance)`。
- `solve(instance)` 必须返回 `job_shop_lib.Schedule`。
- `best.py` 保存当前实验中 makespan 最低的候选脚本。

这与 `job_shop_era` 的输出形式保持一致，避免只留下不可复用的 JSON 配置。

## 变异机制

`job_shop_era` 的变异是开放式代码变异，prompt 允许模型自由构造 job-shop
求解器。

`exact_job_shop_era` 的变异由 `ExactCodeMutator` 负责，核心变化是：

- 父节点内容完整传入 prompt，LLM 基于父脚本做增量变异。
- 反馈上下文包含 selected parent、best so far、recent nodes、timeout。
- 反馈内容包含 makespan、score、elapsed、feasible、error 等客观结果。
- prompt 要求每次做一到两个具体 solver-code 改动，避免纯格式重写。
- 如果父节点失败，prompt 明确要求优先修复失败。
- 如果父节点可行，prompt 明确要求优先改进建模或搜索策略。

当前 FUTS 的节点选择仍由 score/PUCT 驱动：

```python
parent = max(nodes, key=lambda node: node.puct)
```

也就是说，变异方向受到 prompt 引导，但节点选择没有被人工规则覆盖。

## Prompt 改进

`exact_job_shop_era/prompt.py` 当前 prompt 相对 `job_shop_era` 增加了这些
明确要求：

- 返回完整 Python 代码，不返回 JSON。
- 必须保留公开 API：`def solve(instance): ... return schedule`。
- 必须使用 `from ortools.sat.python import cp_model`。
- 必须返回合法 `job_shop_lib.Schedule`。
- 不允许读写文件。
- 不允许硬编码 instance name、optimum 或 benchmark answer。
- 鼓励可复用 CP-SAT 建模改进：
  - tighter horizons
  - redundant constraints
  - symmetry breaking
  - decision strategies
  - hints
  - decomposition
  - repair phases
  - CP-SAT-guided large-neighborhood search

需要注意：这些“建模改进方向”目前主要是 prompt 约束，不是静态代码检查。
硬性执行约束主要来自 sandbox、返回类型检查和调度可行性评分。

## 执行与评分

`exact_job_shop_era` 使用 `ExactJobShopExecutor` 执行候选脚本，但底层复用了
`implementation.job_shop_era.sandbox.run_candidate`：

- 在子进程中加载候选 `node_XXXX.py`。
- 构造 `JobShopInstance`。
- 调用 `solve(instance)`。
- 检查返回值是否为 `job_shop_lib.Schedule`。
- 用 `score_schedule` 检查可行性并计算 makespan。

评分规则保持客观：

```text
score ~= -makespan - elapsed_seconds * 1e-6
```

因此 FUTS 选择更偏向 makespan 更低的节点，耗时只作为极小 tie-breaker。
失败、timeout 或非法 schedule 会得到 worst score。

当前版本还支持一个显式的后最优搜索模式：

```bash
python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --optimize-runtime-after-optimum
```

开启 `--optimize-runtime-after-optimum` 后，FUTS 在首次发现
`makespan <= optimum` 的可行节点之前仍使用原始 makespan 评分；首次达到理论
最优后不会早停，而是把所有可行节点重算为：

```text
score = -(100 * makespan + elapsed_seconds)
```

其中 `100` 可用 `--runtime-score-makespan-weight` 调整。这个阶段仍然保留
makespan 的主导地位，同时在同等或接近最优质量下推动脚本更快返回结果。
`nodes.jsonl` 中的 `score_mode` 字段会标记节点记录使用的是 `makespan` 还是
`runtime_after_optimum`。

## 约束边界

当前版本的硬约束包括：

- 候选必须是 Python 文件。
- 候选必须能被子进程 import。
- 候选必须定义并执行 `solve(instance)`。
- 返回对象必须是 `job_shop_lib.Schedule`。
- schedule 必须通过 `score_schedule` 可行性检查。
- 外层 executor timeout 会限制每个 node 的总运行时间。

当前版本的软约束包括：

- 鼓励使用 CP-SAT。
- 鼓励做 reusable solver-code 改进。
- 鼓励使用父节点中有效内容。
- 鼓励修复失败原因而不是重写无关代码。

其中“必须使用 CP-SAT”写在 prompt 中，但目前没有 AST/import 级别的强校验。
如果后续需要严格保证，可增加静态检查：拒绝没有 `cp_model` import 或没有
`CpModel/CpSolver` 使用痕迹的候选。

## 日志与产物

相对 `job_shop_era`，`exact_job_shop_era` 增加或强化了这些记录：

- `nodes.jsonl`：记录 node_id、parent_id、score、makespan、elapsed、error、
  visits、rank_score、puct。
- `versions.jsonl`：记录每个版本的摘要信息。
- `version_summary.csv`：便于快速查看 node 与 parent/root 的 makespan 差异。
- `tree.json`：保存 FUTS 树结构。
- `run_manifest.json`：记录实例、CLI 参数、root candidate、架构信息和代码状态。
- `candidates/node_XXXX.py`：每个 node 的完整候选脚本。
- `best.py`：当前最佳可复用脚本。
- `breakthrough.png`：best-so-far makespan 曲线。
- `tree_branches.png`：二维树分支图。
- `tree_branches_3d.png`：三维树分支图。

## 自动绘图

当前 CLI 正常结束时会自动写：

- `best.py`
- `breakthrough.png`
- `tree_branches.png`
- `tree_branches_3d.png`

如果进程被手动 kill、系统 OOM kill、外层异常退出，收尾绘图不会执行。这种
情况下需要用 `implementation.exact_job_shop_era.plot` 的三个函数对
`nodes.jsonl` 手动补图。

## 早停系统

当前版本已增加 `--early-stop-at-optimum`：

```bash
python -m implementation.exact_job_shop_era.cli \
  --instance ta31 \
  --iterations 50 \
  --timeout-seconds 300 \
  --early-stop-at-optimum
```

当 benchmark metadata 中存在 `optimum`，并且某个 node 的 `makespan <= optimum`
时，FUTS 会停止继续生成新 node。停止后仍走正常 CLI 收尾流程，写出 best
script 和绘图。

如果同时开启 `--early-stop-at-optimum` 和
`--optimize-runtime-after-optimum`，后者优先：达到最优后继续训练，用运行时间
优化最优脚本，而不是停止。

## 当前已知限制

- CP-SAT 使用是 prompt 层约束，不是静态硬校验。
- 大规模实例上，全量 CP-SAT 加 pairwise order literals 可能导致内存过高。
- 候选脚本没有中间 incumbent 日志，长时间求解时只能等 `Solve()` 返回。
- 复用能力仍取决于训练评分集合；只在单个实例训练会产生实例偏置。
- 当前 scoring 只看单实例 makespan，尚未把跨规模泛化 gap 纳入 FUTS 评分。

## 推荐后续改进

- 增加 CP-SAT 使用静态校验，拒绝不含 `cp_model` 的候选。
- 增加多实例评分模式，用平均 gap 或 worst gap 驱动泛化。
- 为大规模实例增加 memory-aware prompt 和 candidate constraints。
- 支持 CP-SAT progress logging 或 callback，用于长时间测试监控 incumbent。
- 增加 resume/continue 能力，避免手动中断后只能重新开实验。
- 在实验异常退出后提供 standalone finalize 命令，补 `best.py` 和所有图。
