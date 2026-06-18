# multi_bot_era 改进日志

日期：2026-06-16

本文档记录 `implementation/multi_bot_era` 在参考 `exact_job_shop_era` 后，为了让 FUTS 生成可复用 OR-Tools/CP-SAT 排程脚本而做的针对性改动。重点是：让候选脚本面对一个清晰、可验证、不会泄露非固定任务 incumbent 排程答案的数据接口，并通过 prompt、seed、executor、scorer、search 的配合推动 FUTS 做真实迭代优化。

## 目标

`multi_bot_era` 的目标不是一次性手工求解某个 SQLite 文件，而是让 FUTS 节点不断变异出更有效、可复用的完整求解脚本。为此当前结构遵循以下原则：

- 候选脚本必须使用 OR-Tools CP-SAT。
- 每个 node 仍然通过客观分数进入 FUTS 树。
- scorer 只做可行性和 makespan 验证，不做主观代码质量判断。
- 数据接口不向候选脚本暴露非固定任务的已排好答案，避免 FUTS 学到 replay。
- prompt 向子节点传递父节点、best 节点、近期失败、score contract、代码摘要和 diff，让变异有可继承信息。

## 从 exact_job_shop_era 借鉴的结构

`exact_job_shop_era` 的有效点主要不是某个具体模型，而是几个结构性约束：

1. 候选脚本面对的是问题实例，而不是带完整答案的排程结果。
2. prompt 明确要求使用 CP-SAT、返回标准 schedule、禁止 hard-code benchmark answer。
3. executor/scorer 只接受可验证结果，失败、timeout、非法 schedule 给 worst score。
4. FUTS 父节点会把客观反馈传给子节点，而不是只传一句自然语言建议。
5. 达到相同 makespan 后，runtime 作为 tie-breaker，但 makespan 仍是主目标。

这些思路迁移到 `multi_bot_era` 后，对应为：

- SQLite 被转换为 FJSPB IR，而不是 JSON 临时文件。
- IR 中只保留必要问题定义和 fixed 历史任务，不暴露非固定任务 incumbent。
- 候选脚本返回 `{"assignments": [...]}`。
- scorer 校验 FJSPB 约束。
- prompt 明确要求完整 CP-SAT 模型和约束覆盖。

## 当前数据接口

入口函数仍是：

```python
def solve(dataset):
    ...
    return schedule
```

对于 SQLite 输入，`dataset["fjspb"]` 是主接口。主要字段如下：

- `source_sqlite_file`：原始 SQLite 路径。
- `cur_ptr`：当前时间指针，非固定任务必须从此之后开始。
- `machines`：`machine_code -> capacity`。
- `jobs`：job 列表。
- `constraint_contract`：scorer 执行的约束说明。
- `output_schema`：返回 assignments 的结构说明。

每个 job 包含：

- `job_id`：来自 SQLite 的 `b_id`。
- `expr_no` / `expr_name`：实验分组信息。
- `tasks`：有序 task 列表。

每个 task 包含：

- `task_id`：FJSPB index。
- `duration`：任务持续时间。
- `machines`：候选机器列表。
- `nominal_machine`：原始步骤机器类型或名义机器。
- `parameters` / `detail`：参数和物料信息。
- `flags`：化学流程特殊约束标记。
- `is_fixed`：是否为历史固定任务。

只有 `is_fixed=True` 的任务会暴露：

- `fixed_start`
- `fixed_end`
- `scheduled_machine`
- `next_scheduled_machine`

`is_fixed=False` 的非固定任务不会暴露 SQLite 中的 `start_time`、`end`、`ws_code_fjspb`、`next_step_ws_code_fjspb`。这是当前最重要的数据接口限制。

## 为什么不在 scorer 中判定 replay

曾短暂加入过 scorer replay 检测：如果所有非固定任务完全匹配 SQLite incumbent，就判为无效。这个方法可以止血，但不是干净结构，原因是：

- replay 判定会越来越复杂，候选脚本可以轻微扰动时间或机器绕过。
- scorer 会混入“行为意图识别”，偏离纯约束验证。
- 每新增一种数据泄露形式，都要继续补判定规则。
- 这和 `exact_job_shop_era` 的设计不一致；exact 的根本优势是输入本身没有答案表。

因此最终采用数据接口隔离：

- `problem.py` 在构造 FJSPB IR 时移除非固定任务 incumbent 字段。
- scorer 不再判断 replay，只验证排程本身。
- prompt 告诉候选脚本非固定 incumbent 不存在，必须从 CP-SAT 变量值导出 assignments。

## problem.py 改进

`problem.py` 当前负责直接读取 SQLite，并生成两层数据：

- legacy `task_list`：保留旧 JSON 风格兼容。
- `fjspb`：SQLite/FJSPB 主接口。

关键改动：

- 支持 `.sqlite` / `.db` / `.sqlite3` 直接加载。
- 读取 `ws_info` 为机器容量。
- 读取 `robot_info` 为 robot 列表。
- 读取 `global_ptr_info.cur_ws_ptr` 为 `cur_ptr`。
- 读取 `task_scheduled` 构造 job/task。
- 从 `ws_arr` 和 `ws_code_fjspb` 推导候选机器，但非固定任务不暴露已选机器。
- 从 `parameters` / `detail` 解析 JSON 参数。
- 构造 `constraint_contract`，将 scorer 约束显式传给 prompt。
- `prompt_dataset` 使用摘要形式，减少 token 消耗，同时保留 route patterns、特殊约束计数、容量样本和 sample jobs。

当前 fixed 规则：

```python
is_fixed = row["start_time"] is not None and int(row["start_time"]) < cur_ptr
```

只有满足该条件的历史任务会把原始排程作为硬约束暴露给候选脚本。

## scorer.py 改进

`scorer.py` 现在包含两套验证：

- legacy `operations` 验证，用于非 SQLite 旧数据。
- FJSPB `assignments` 验证，用于 SQLite 主路径。

FJSPB scorer 验证内容：

- 每个 `(job_id, task_id)` 正好出现一次。
- assignment 的 machine 必须属于 `task["machines"]`。
- assignment duration 必须等于 `task["duration"]`。
- 时间必须有限、非负。
- 非固定任务 `start >= cur_ptr`。
- fixed task 必须保持 `fixed_start`、`fixed_end`、`scheduled_machine`。
- job 内 task 按 task_id 顺序满足 precedence。
- 机器容量不超限。
- capacity > 1 的 batch overlap 必须同步：同 duration 才允许同 start/end；不同 duration 不允许 overlap。
- electronic / XRD dripping-test-recycle 资源互斥。
- dripping/test/recycle 在同 job 内必须 back-to-back。
- muffle furnace / dryer 不同温度不能 overlap。
- centrifugation 机器任意事件时刻 active count 必须为偶数。
- 同一 `expr_no` 的 first task 必须同步开始。

score 规则：

```text
score = -(makespan + elapsed_seconds / 100)
```

不可行、异常、timeout 或 executor 拒绝的候选返回 worst score。

## prompt.py 改进

prompt 面向生成完整 CP-SAT 求解脚本，核心要求包括：

- 返回纯 Python code，不返回 Markdown。
- 必须定义 `solve(dataset)`。
- SQLite 输入必须使用 `dataset["fjspb"]`。
- FJSPB 输出应为 `{"assignments": [...]}`。
- 必须使用 `from ortools.sat.python import cp_model`。
- 必须构建 CP-SAT 模型、调用 `CpSolver`，并从 solver variable values 导出非固定 assignments。
- greedy 只能作为 fallback、hint、bound、repair 或 CP-SAT-guided LNS 的辅助，不能替代 CP-SAT。
- 禁止 file I/O、network、multiprocessing、external service。
- 禁止 hard-code 当前数据集答案、makespan 或 start/end table。
- 明确说明非固定任务不暴露 SQLite incumbent start/end/machine。
- fixed task 才能保持 fixed_start/fixed_end/scheduled_machine。

prompt 同时提供：

- `problem.description`
- dataset 摘要
- parent code
- parent score
- selected parent evaluation
- best candidate evaluation
- lineage
- recent node results
- recent failures
- best code summary
- parent-to-best diff
- score contract
- timeout 信息

这样子节点不仅知道父节点代码，还知道哪些改动有效、哪些失败原因需要避免。

## seed.py 改进

seed 是 root candidate，也是 FUTS 的初始可变异脚本。当前默认 seed 已改为冷启动骨架：它只保留最小 OR-Tools CP-SAT 调用，故意不提供可用排程模型，返回空 `assignments` 并由 scorer 记录失败节点。

禁用原有强 seed 的原因：

- 原强 seed 已经手写了完整 CP-SAT 求解器，在合并数据上可直接给出强可行结果。
- 这会把 FUTS 变成“从可用求解器做局部变异”，背离从纯语言需求、设备清单和约束描述中长出求解脚本的测试目标。
- 默认冷启动要求第一个 LLM 子节点根据 prompt、FJSPB IR 摘要、失败反馈和 scorer 约束生成完整 OR-Tools 模型。

当前 seed 只做：

- `from ortools.sat.python import cp_model`
- 构建一个最小 `CpModel/CpSolver` 骨架，满足静态 CP-SAT 检查。
- 返回空 `{"assignments": []}`，让 root 客观失败。

如需从历史可用脚本继续实验，必须显式传入 `--initial-code /path/to/best.py`。默认 CLI 不再提供完整求解器 root。

## executor.py 改进

executor 负责运行候选代码并评分。关键限制：

- 候选必须静态包含 OR-Tools CP-SAT 相关符号：
  - `ortools.sat.python`
  - `cp_model`
  - `CpModel`
  - `CpSolver`
- 冷启动后新增 shortcut 拒绝：
  - 不接受 `_build_greedy_schedule` 这类先完整 greedy 排程再包装 CP-SAT 的候选。
  - 不接受 `return {"assignments": greedy}` 的 greedy fallback。
  - 不接受把 CP-SAT `start/end` 变量直接固定到预计算排程 `ass["start"]/ass["end"]` 的候选。
- 通过 sandbox 运行候选。
- 外层 `timeout_seconds` 是候选脚本整体运行时间限制。
- 运行结果交给 scorer 验证。

这保证 FUTS 变异不会退化为纯 greedy 或直接返回拼装结果。

## search.py 改进

search 保留 FUTS 选择逻辑，但加强了父子信息传递：

- `_set_mutator_feedback` 给 mutator 注入结构化反馈。
- 反馈包括 parent、best、lineage、recent、recent_failures。
- 传递 score contract 和 timeout。
- 传递 parent code summary。
- 如果 best 不是 parent，传递 best code summary 和 parent-to-best diff。
- 每个 node 都记录 code diff、score、feasible、makespan、elapsed、PUCT。

这相当于给子节点提供 exact_job_shop_era 中“父节点向子节点传递全面信息”的环节。

## cli.py 改进

CLI 当前支持：

- `--dataset`
- `--mode single|futs`
- `--iterations`
- `--timeout-seconds`
- `--experiment-name`
- `--no-llm`
- `--c-puct`
- `--initial-code`

新增 `--initial-code` 的原因：

- 可以从已有 `best.py` 继续做更大规模 FUTS。
- 避免每次 50 轮都从 seed root 重新找到已知好结构。
- 更符合“长期积累可复用脚本”的目标。

示例：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 50 \
  --timeout-seconds 450 \
  --initial-code /home/era/experiments/multi_bot_5exp_x2_no_incumbent_futs_10_nodes_450s_gpt55/best.py \
  --experiment-name multi_bot_5exp_x2_no_incumbent_futs_50_iters_450s_gpt55_continue
```

## 数据集和运行方式

当前主要复杂测试数据：

```text
/home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite
```

生成方式：

- 从 `database_paper/5_experiments.sqlite` 复制。
- 复制一份 job/task 作为第二批。
- 对第二批修改 `b_id`、`expr_no`、`expr_name`、`step_id`。
- 第二批时间整体后移，保证数据库原排程仍可用于离线对比。
- 按已有峰值收紧部分 workstation capacity。

在 no-incumbent 接口下，候选脚本看不到非固定任务的 shifted incumbent 时间。

## 当前边界和风险

1. 默认 seed 不是可行求解器。
   - 它是冷启动骨架，root 预期失败。
   - 可行完整模型应由 LLM/FUTS 子节点生成。

2. scorer 是最终约束真值。
   - prompt 和 seed 只是引导。
   - 候选是否被接受，最终取决于 scorer。

3. 数据接口隐藏非固定 incumbent 后，候选若要可行必须真实建模求解。
   - 默认 root 不再承担求解职责。
   - 复杂数据上的耗时来自生成出的候选 CP-SAT 模型，而不是 seed 内置强模型。

4. fixed 任务仍暴露原排程。
   - 这是必要约束，不是 replay。
   - fixed 定义为 `start_time < cur_ptr`。

5. 若未来数据中的 `cur_ptr` 较大，fixed/non-fixed 分界会影响模型难度。
   - 需要在实验日志中记录每个数据集 fixed/non-fixed 数量。

## 后续建议

1. 将 x2 数据生成脚本纳入正式工具目录，而不是临时脚本。
2. 为 FJSPB IR 增加独立 schema 文档或 dataclass。
3. 为 scorer 增加单元测试，覆盖每个 constraint_contract。
4. 将 `constraint_contract` 和 scorer 的具体错误类型对齐，方便 prompt 精准修复。
5. 将 FUTS 结果中的 best.py 自动回灌为下一轮 `--initial-code`。
6. 增加跨数据集评分，避免脚本只适配单个 SQLite。
7. 对 best.py 增加离线 replay 审计：确认非固定任务字段在输入中不可见，而不是靠代码自律。

## 命令行运行指南

以下命令默认在 `/home/era` 下执行，确保输出进入 `/home/era/experiments`：

```bash
cd /home/era
```

推荐统一带上：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era
```

如果使用 LLM，需要环境中存在：

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.5
```

`OPENAI_MODEL` 未设置时，CLI 默认使用 `gpt-5.5`。

### 1. SQLite root smoke

用于确认直接 SQLite 读取、FJSPB IR、seed、executor、scorer 能跑通。当前默认 cold-start seed 预期不可行；`--no-llm` 会重复 root candidate，不调用 API。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/multi-bot-coordinator_licko/multi-robot-multi-task_scheduling/simulation_methods/database_paper/4_experiments.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 450 \
  --no-llm \
  --experiment-name multi_bot_4exp_no_incumbent_root_smoke
```

预期输出：

- `experiments/<experiment-name>/nodes.jsonl`
- `experiments/<experiment-name>/best.py`
- 若有可行节点，会生成 `breakthrough.png`、`tree_branches.png`、`tree_branches_3d.png`

### 2. 复杂 x2 数据 root smoke

用于检查复杂压力数据在 no-incumbent 接口下是否有可行 root。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 450 \
  --no-llm \
  --experiment-name multi_bot_5exp_x2_no_incumbent_root_smoke
```

### 3. 10-node LLM FUTS

`--iterations 9` 表示 root 之外生成 9 个 child，总计 10 个 node。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 9 \
  --timeout-seconds 450 \
  --experiment-name multi_bot_5exp_x2_no_incumbent_futs_10_nodes_450s_gpt55
```

### 4. 从已有 best.py 继续 FUTS

`--initial-code` 会把已有候选脚本作为新实验 root。适合从一个已知好脚本继续 50 轮或更长训练。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 50 \
  --timeout-seconds 450 \
  --initial-code /home/era/experiments/multi_bot_5exp_x2_no_incumbent_futs_10_nodes_450s_gpt55/best.py \
  --experiment-name multi_bot_5exp_x2_no_incumbent_futs_50_iters_450s_gpt55_continue
```

注意：

- `--iterations 50` 会产生 root + 50 个 child，即 51 个节点。
- 每个候选脚本外层最多运行 `--timeout-seconds` 秒。
- 该 timeout 是候选脚本整体执行时间限制；当前 sandbox 同时通过 `ERA_CANDIDATE_TIMEOUT_SECONDS` 传给候选脚本，根脚本和 prompt 要求 CP-SAT 内部时间略低于该外层上限。

### 5. 单次变异模式

`--mode single` 会生成并评估 root 的一个 child，适合快速看 prompt/LLM 输出是否稳定。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode single \
  --timeout-seconds 450 \
  --experiment-name multi_bot_single_generation_probe
```

### 6. 补生成二维/三维图

如果实验被中断、kill、异常退出，CLI 收尾绘图可能没有执行。可以用独立绘图 CLI 补图：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name> \
  --plot all
```

只生成三维树图：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name> \
  --plot tree3d
```

输出文件：

- `breakthrough.png`
- `tree_branches.png`
- `tree_branches_3d.png`

### 7. 查看运行状态

查看 ERA/FUTS 进程：

```bash
ps -efww | grep -E 'implementation.multi_bot_era.cli|multi_bot_'
```

查看某个 PID：

```bash
ps -p <PID> -o pid,ppid,user,stat,etime,pcpu,pmem,cmd
```

查看节点进度：

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

### 8. 停止运行中的 FUTS

停止前必须按 PID 确认目标进程：

```bash
ps -efww | grep -E 'implementation.multi_bot_era.cli|<experiment-name>'
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
kill <PID>
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
```

## 图表轴含义

`multi_bot_era` 的图表均从实验目录的 `nodes.jsonl` 读取数据。每个 node 记录包括 `node_id`、`parent_id`、`score`、`feasible`、`makespan`、`elapsed_seconds`、`error`、`rank_score` 和 `puct`。这些图用于判断 FJSPB/SQLite no-incumbent FUTS 是否在真实改善排程，而不是只优化脚本运行时间。

### breakthrough.png

`breakthrough.png` 展示每个 node 的 score 和 best-so-far score。

- x 轴：`node_id`，即 FUTS 节点生成顺序。
- y 轴：node score，按 `-(makespan + elapsed_seconds / 100)` 计算；值越大表示越好。
- 散点：每个有有限 score 的 node。timeout、crash、不可行节点通常没有有限 score，不会作为正常分数点参与曲线。
- 绿色阶梯线：从 root 到当前 node 的历史最佳 score。
- 颜色：按 score 映射，颜色越深表示 score 越好。
- 注释框：当前 best node，显示 node id、score 和 makespan。

在 multi-bot 实验中，makespan 是主目标；同 makespan 下，`elapsed_seconds / 100` 是 tie-breaker。因此曲线大幅上升通常表示 makespan 改善，小幅上升通常表示相同 makespan 下脚本更快。

### tree_branches.png

`tree_branches.png` 是二维 FUTS 树结构图。

- x 轴：`node_id` / expansion order，表示节点生成顺序。
- y 轴：tree depth，root 深度为 0。
- 灰色线：parent-child 边，来自 `parent_id`。
- 散点：FUTS node。
- 颜色：按 score 映射，颜色越深表示 score 越好。
- 红色星标：当前 best node。
- 注释框：best node 的 node id、score、makespan。

这张图可以看出 FUTS 是否持续选择高分父节点扩展。例如 50-iteration continuation 中，大量节点从 best 附近的父节点继续变异，说明 PUCT 选择正在围绕高分候选开发。

### tree_branches_3d.png

`tree_branches_3d.png` 在二维树图上增加压缩后的 makespan gap 维度。

- x 轴：`node_id` / expansion order。
- y 轴：tree depth。
- z 轴：makespan gap to best，即 `node_makespan - best_makespan`，但使用 30% ceil scale 显示。
- z 轴刻度：底部为 best gap `0`；顶部为当前图中最大 gap；从顶部往下每一格为上一格的 `ceil(30%)`，直到接近 0。节点真实 gap 会映射到相邻 tick 之间的位置。
- 灰色线：parent-child 边。
- 点颜色：按 score 映射，颜色越深表示 score 越好。
- 红色星标：当前 best node，通常 z=0。

对 multi-bot/FJSPB 来说，三维图最适合检查两类现象：

- 是否存在持续改善链：子节点 z 值沿深度下降。
- 是否出现局部平台：多个节点 makespan 相同，z 维度接近，score 差异主要来自 elapsed。

如果二维树显示持续扩展某个分支，但三维 z 轴没有下降，说明当前变异主要在优化 runtime 或做无效探索；如果 z 轴明显下降，说明变异确实在改善排程质量。

如果进程没有退出，再使用：

```bash
kill -TERM <PID>
sleep 2
kill -KILL <PID>
```

不要按模糊命令名直接 kill；同一机器上可能同时有多个 ERA/FUTS 任务。

### 9. 输出目录结构

每次运行会写入：

```text
/home/era/experiments/<experiment_name>/
  best.py
  nodes.jsonl
  tree.json
  puct_audit.json
  breakthrough.png
  tree_branches.png
  tree_branches_3d.png
  candidates/
    node_0000.py
    node_0001.py
    ...
```

`nodes.jsonl` 是最重要的监控文件；`best.py` 是当前可复用脚本产物。

## 本地运行命令速查

以下命令默认在 `/home/era` 下执行：

```bash
cd /home/era
```

统一环境前缀：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era
```

### Root smoke

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 450 \
  --no-llm \
  --experiment-name multi_bot_5exp_x2_no_incumbent_root_smoke
```

### 10-node FUTS

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 9 \
  --timeout-seconds 450 \
  --experiment-name multi_bot_5exp_x2_no_incumbent_futs_10_nodes_450s_gpt55
```

### 50-iteration continuation

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/5_experiments_x2_capacity_tight.sqlite \
  --mode futs \
  --iterations 50 \
  --timeout-seconds 450 \
  --initial-code /home/era/experiments/multi_bot_5exp_x2_no_incumbent_futs_10_nodes_450s_gpt55/best.py \
  --experiment-name multi_bot_5exp_x2_no_incumbent_futs_50_iters_450s_gpt55_continue
```

### 补图

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.plot_tree_cli \
  --experiment-dir /home/era/experiments/<experiment_name> \
  --plot all
```

### 查看状态

```bash
ps -efww | grep -E 'implementation.multi_bot_era.cli|<experiment-name>'
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

### 按 PID 停止

```bash
ps -efww | grep -E 'implementation.multi_bot_era.cli|<experiment-name>'
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
kill <PID>
ps -p <PID> -o pid,ppid,user,stat,etime,cmd
```

## e1-e5 合并版数据接口

新增脚本：

- `/home/era/scripts/build_merged_fjspb_sqlite.py`：从原仓库 `database_paper/e1.sqlite` 到 `e5.sqlite` 构造合并 FJSPB SQLite，稳定前缀化 `b_id`、`expr_no`、`expr_name`，避免主键和首任务同步分组冲突。
- `/home/era/scripts/run_fespb_reference.py`：在 SQLite 副本上运行原仓库 `fespb.fespb_ortools.fespb` 参考求解器。本地环境缺少 `docplex`，所以没有直接运行 CPLEX 版 `fespb.py`；wrapper 禁用了 OR-Tools 版本的旧排程 hint 层，因为合并数据上该辅助 hint 会产生重复 AddHint 并导致 `MODEL_INVALID`。

数据集：

```bash
python /home/era/scripts/build_merged_fjspb_sqlite.py
```

输出到 `/home/era/experiments/fjspb_capacity_stress/`，并可由
`multi_bot_era` loader 直接读取为 FJSPB IR。loader 必须保证非固定任务不暴露旧
`fixed_start/fixed_end/scheduled_machine`，只保留 fixed 任务所需的硬约束信息。

原仓库参考：

```bash
PYTHONDONTWRITEBYTECODE=1 python /home/era/scripts/run_fespb_reference.py \
  --input /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --output /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged_original_fespb_ortools.sqlite \
  --cur-ptr 3 \
  --time-limit 450
```

参考求解脚本只用于离线校验和对照，不作为 FUTS 训练 prompt 的参考内容。

Timeout 语义修正：

- `--timeout-seconds` 是候选脚本进程的外层运行上限。
- 现在 sandbox 会把该值写入候选进程环境变量 `ERA_CANDIDATE_TIMEOUT_SECONDS`。
- 根候选脚本读取该环境变量，并将 `solver.parameters.max_time_in_seconds` 设置为外层 timeout 减 5 秒，避免继续写死 60 秒。
- prompt 也要求 LLM 变异脚本读取同一环境变量设置 CP-SAT 内部时间。

Root smoke 命令模板：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 450 \
  --no-llm \
  --experiment-name multi_bot_e1_e2_e3_e4_e5_merged_root_smoke_450s_env_timeout_fix2
```

LLM FUTS 命令模板：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --mode futs \
  --iterations 9 \
  --timeout-seconds 450 \
  --experiment-name multi_bot_e1_e2_e3_e4_e5_merged_futs_10_nodes_450s_gpt55
```

## Cold-start 默认 seed 约束

默认 `seed.py` 已禁用强可行 CP-SAT baseline，改为 cold-start skeleton。默认 root 预期失败，强可行脚本只能通过 `--initial-code` 显式输入。

默认 cold seed smoke 命令模板：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --mode futs \
  --iterations 0 \
  --timeout-seconds 450 \
  --no-llm \
  --experiment-name multi_bot_e1_e5_merged_default_cold_seed_smoke
```

为防止不合格的 greedy-wrapped CP-SAT，executor 已新增 shortcut 拒绝，
prompt 也禁止先用启发式排程、再把 CP-SAT 变量固定到该排程的模式。

Cold-start FUTS 命令模板：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --mode futs \
  --iterations 5 \
  --timeout-seconds 450 \
  --experiment-name multi_bot_e1_e5_merged_cold_start_5_iter_gpt55_strict
```

相关 prompt 限制：

- 明确不要调用 `model.AddMapDomain`，如确需映射使用 `model.add_map_domain` 或直接使用 presence bool。
- 明确 capacity > 1 batch 的成对规则：不同 duration 必须二选一非重叠；相同 duration 只能非重叠或完全对齐 start/end。

从已有候选继续 FUTS 的命令模板：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era python -m implementation.multi_bot_era.cli \
  --dataset /home/era/experiments/fjspb_capacity_stress/e1_e2_e3_e4_e5_merged.sqlite \
  --mode futs \
  --iterations 5 \
  --timeout-seconds 450 \
  --initial-code /home/era/experiments/multi_bot_e1_e5_merged_cold_start_3_iter_gpt55_batch_api_prompt/best.py \
  --experiment-name multi_bot_e1_e5_merged_cold_start_continue_5_iter_gpt55
```

当前结论：默认强 seed 已禁用；cold-start 训练应依赖 prompt、FJSPB IR、
objective feedback 和 scorer 约束推动子节点生成完整 CP-SAT 模型，而不是从
hidden incumbent 或手写强 baseline 出发。

## 2026-06-18: FUTS mutation prompt strengthened for explicit modeling analysis

针对 cold-start 变异容易退化为“能跑但不可审计”的短 CP-SAT 脚本，补强
`implementation/multi_bot_era/prompt.py`：

- 要求候选在代码结构中体现对 FJSPB 场景的分析：jobs、ordered tasks、eligible machines、fixed tasks、machine capacities、batch/synchronization machines、chemistry conflicts、robot/device resources、makespan objective。
- 要求使用语义化变量和按实体索引的数据结构，例如 `task_key`、`machine_code`、`presence[(task_key, machine)]`、`start_vars`、`end_vars`、`interval_vars`、`machine_to_intervals`、`job_to_tasks`、`makespan`，避免生成难以判断约束归属的匿名变量。
- 明确列出该问题应优先掌握和使用的 OR-Tools CP-SAT 专业工具：`NewIntVar`、`NewBoolVar`、`NewOptionalIntervalVar`、`AddExactlyOne`、`AddImplication`、`OnlyEnforceIf`、`AddBoolOr`、`AddNoOverlap`、`AddCumulative`、`AddMaxEquality`、`Minimize`、solver time limits、solution hints、decision strategies、CP-SAT-guided LNS。

这次改动保持候选输出仍为纯 Python 代码，不要求额外 Markdown 或 JSON 说明；目标是让 FUTS 变异更可能产生完整、可维护、可复用的 OR-Tools 模型，而不是把约束判定复杂性继续推给 scorer。

验证：

```bash
python -B -c "from pathlib import Path; p=Path('/home/era/implementation/multi_bot_era/prompt.py'); compile(p.read_text(), str(p), 'exec'); print('syntax ok')"
```
