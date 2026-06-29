# flow_1160_era_v2 改进日志

日期：2026-06-26

## 目标

`flow_1160_era_v2` 是 `flow_1160_era` 的独立增强项目。v1 已经能在核心 task 模型上由 FUTS 达到 `145058s = 40.294h` 的最小 CP-SAT 理论最优；v2 不直接覆盖 v1，而是新增更贴近真实运行的 IR 层：

1. `material_edges`：从 `projectAllNodeList.materialData` 规范化板级物料流。
2. `logistics_events` / `buffers` / `logistics_resources`：表达堆栈、进板、退栈、扫码、转运等物流资源。
3. `rolling_state` 和 task 级 `run_status/duration_source/actual_start/actual_end`：为后续 fixed-prefix / rolling schedule 做准备。

## 当前实现

- v2 `problem.py` 先调用 v1 `flow_data_to_fjspb`，保持原 `jobs/tasks/machines/precedence_pairs/branch_priority_pairs` 可执行契约。
- 然后追加 v2 字段，不改变候选脚本返回格式：仍为 `{"assignments": [...]}`。
- `scorer` 仍复用 v1，不改变客观评分口径；v2 约束落地放在候选脚本和 `Flow1160V2Executor` 的执行前检查中。
- `executor.py/search.py` 已切到 v2：候选必须使用 CP-SAT，并显式读/建模 `material_edges`、`material_inventory_events/AddReservoirConstraint`、`logistics_events`、`buffers/buffer_ids`、`rolling_state/existing_machine_occupancy`、`AddNoOverlap`、`AddCumulative`，否则直接拒绝。
- `prompt.py/mutator.py/cli.py` 已切到 v2，引导 LLM 使用 v2 metadata，但要求保留 v1 hard constraints。
- 冷启动 seed 仍是 v1 的空 CP-SAT skeleton，不内置手写参考候选；用于验证 FUTS 能否从失败根节点生成准确 v2 建模脚本。
- `audit_v2.py` 输出 v2 层计数、样例和 enforcement 分布。

## 分阶段约束策略

### A. material_edges

硬约束候选：

- `src_task_id -> dst_task_id` 物料边可转成 hard precedence。
- `barcode/material + quantity` 可转成守恒和转移量约束。
- 多入/多出可转成 merge/split 约束。
- 同板互斥操作可转成板级 NoOverlap。

当前状态：字段仍作为 IR metadata 暴露；v2 prompt 和参考/生成候选要求把 `hard_precedence_candidate=True` 且有 `src_task_id/dst_task_id` 的边建成 CP-SAT precedence。未改 scorer。

### A2. material_inventory_events

建模层级：

- 明确源任务、目标任务、正 quantity 的 material edge 生成 `material_inventory_events`。
- 候选按 `inventory_key` 分组，用 CP-SAT `AddReservoirConstraint` 表达库存非负：源任务结束 `+quantity`，目标任务开始 `-quantity`，`min_level=0`，`max_level=sum(group quantities)`。
- 这是真约束，但仍是保守的边级库存流约束；平台 raw rows 未明确总生产量时，不硬造完整 merge/split 产消平衡。

当前状态：`1160` 数据生成 `material_inventory_events=212`，分布为 `V0|pmix|unit=14`、`V1|1nut|unit=50`、`V0|antp|unit=44`、`V0|tmmb|unit=98`、`V4|micp|unit=6`。reference candidate 已加入 `AddReservoirConstraint` 并通过 smoke。

### B. logistics_events / buffers

建模层级：

- 稀缺动作：`transport_events`，未来用 `NoOverlap`。
- 容量位置：`buffers`，用 `Cumulative`；容量来自平台 `devicePosition` 按 `deviceName` 计数。
- 库存/消耗：未来用 `Reservoir`。
- 纯逻辑节点：只保留 precedence / audit。

当前状态：事件、资源、buffer 和 enforcement 建议已输出；v2 prompt 和参考/生成候选要求把 `audit_no_overlap_candidate` 且有 duration/resources 的事件建成固定存在的物流 interval，按 resource `AddNoOverlap`，按 `buffer_ids` 加入 buffer `AddCumulative` 容量日历，并把物流 event end 纳入 modeled makespan。未把 logistics event 放入返回 assignments。

### C. rolling/fixed

未来字段：

- task: `run_status/is_fixed/fixed_start/fixed_end/scheduled_machine`
- IR: `cur_ptr/existing_machine_occupancy/rolling_time_now`

当前状态：offline benchmark 不冻结历史记录，避免把项目 1160 的历史运行结果变成 replay；非 fixed task 从 `cur_ptr` 后重新排。`existing_machine_occupancy` 会作为固定 interval 插入机器 cumulative calendar。

## 2026-06-26 冷启动 FUTS 验证

- 实验目录：`/home/hehaochen/experiments/flow1160_v2_cold_futs_schema_fix_20iter_20260626`
- 命令：不传 `--initial-code`，`--iterations 20`，`--timeout-seconds 60`。
- 结果：`21` 个节点（根 + 20 iter），`20` 个可行候选，只有根节点因空 seed 缺少 v2 字段被 `Flow1160V2Executor` 拒绝。
- 最佳节点：`node_0013`，`makespan=145071s`，`score=-145071.013828453`。
- 所有可行候选 makespan 均为 `145071s`；相比 v1 核心 task 理论最优 `145058s` 增加 `13s`，说明 v2 物流/物料/rolling 约束已在候选模型中产生实际约束影响。
- 生成的 `best.py` 使用了：
  - `material_edges` + `hard_precedence_candidate` 生成物料 hard precedence；
  - `branch_priority_pairs` 的 dict schema：`higher_task_id/lower_task_id`，恢复 P1/P2/P3 start priority；
  - `logistics_events` 生成 resource `AddNoOverlap` interval，并把物流 end 纳入 `AddMaxEquality(makespan, ...)`；
  - `rolling_state.cur_ptr` 和 `existing_machine_occupancy`，并在 `AddCumulative` 前插入固定占用 interval。

## 2026-06-29 可复现 smoke

- 实验目录：`/home/hehaochen/experiments/flow1160_v2_cold_best_replay_20260629`
- 命令：`--no-llm --iterations 0 --initial-code /home/hehaochen/experiments/flow1160_v2_cold_futs_schema_fix_20iter_20260626/best.py`
- 结果：可行，`makespan=145071s`，`score=-145071.10568767838`。
- 结论：20 iter 冷启动 FUTS 产出的 `best.py` 离开生成过程后仍可独立通过 v2 executor 和原 v1 scorer；v2 scorer/seed 均未改动。

## 2026-06-29 buffer 容量约束修正

- 数据来源：平台 `devicePosition` 位置数；本数据集中 `StackRobotA=147`、`BufferA=4`、`BufferB=4`，v2 IR 共输出 `buffers=19`。
- IR 修正：`logistics_events` 增加 `buffer_ids`，例如 stack 事件映射到 `buffer:StackRobotA`。
- prompt/search 修正：要求候选读取 `buffers` 和 `logistics_events[*].buffer_ids`，将物流 interval 以 demand=1 加入 buffer `AddCumulative`，capacity 使用 `buffer["capacity"]`。
- executor 修正：缺少 `buffers/buffer_ids` 的候选会被拒绝；典型 `cur_ptr + duration` 未验证 fallback 会被拒绝。
- reference smoke：`/home/hehaochen/experiments/flow1160_v2_reference_buffer_capacity_20260629` 可行，`makespan=145071s`，`score=-145071.0146578902`。
- 旧 cold-start best guard check：`/home/hehaochen/experiments/flow1160_v2_old_best_guard_check_20260629` 被拒绝，原因是 `candidate rejected: v2 solver must explicitly model/read buffer_ids`。这说明旧脚本已不满足最新 v2 约束门槛。

## 2026-06-29 material reservoir 修正

- IR 修正：新增 `material_inventory_events`，只覆盖 `src_task_id/dst_task_id/quantity` 明确的 material edge，不覆盖外部供料或缺源任务的 rows。
- prompt/search 修正：要求候选按 `inventory_key` 建 `AddReservoirConstraint`，用源任务 end 做 `+quantity`、目标任务 start 做 `-quantity`，表达库存非负。
- executor 修正：缺少 `material_inventory_events` 或 `AddReservoirConstraint` 的候选会被拒绝。
- reference smoke：`/home/hehaochen/experiments/flow1160_v2_reference_inventory_reservoir_20260629` 可行，`makespan=145071s`，`score=-145071.04336176047`。
- 旧 cold-start best guard check：`/home/hehaochen/experiments/flow1160_v2_old_best_inventory_guard_20260629` 被拒绝，原因是 `candidate rejected: v2 solver must explicitly model/read material_inventory_events, buffer_ids`。
- 冷启动 1-iter smoke：`/home/hehaochen/experiments/flow1160_v2_cold_inventory_buffer_1iter_20260629` 中根节点按预期被拒绝；LLM 生成的 `node_0001.py` 可行，`makespan=145071s`，`score=-145071.0790431299`，并包含 `material_inventory_events`、`AddReservoirConstraint`、`buffer_ids`、buffer `AddCumulative`。
- 剩余边界：尚未做完整 merge/split 数量平衡和外部库存初始量守恒，因为当前平台 rows 没有稳定暴露每个分支源节点的总生产量与初始库存；这些继续保留在 audit metadata 中，避免伪约束。

## 2026-06-29 平台内置 AI 字段确认

- 已重新登录平台用户 `a_dongshimao`，刷新 `/tmp/les_token.txt`。
- 已询问 agent7 和 agent3 关于 `materialData`、初始库存、buffer 入出库方向、最小字段 schema。
- 长问题 WebSocket 和 `/api/ai/conversation/{cid}/messages` 多数只返回占位文本 `正在执行任务，请稍候...`。
- 改用短句后拿到可用交叉验证：
  - `quantityConsumeRule=1`：AI 回答“不确定”。
  - `plateOperType=1和2`：AI 未给出可验证枚举，只读取了通用湿实验文档。
  - `prePlateNums 是数量还是来源板标签`：AI 回答“标签”。
- 本地项目 1160 统计：
  - `materialData` 共 `665` 条 data items。
  - `quantityConsumeRule=1` 仅 `36` 条，其余 `629` 条缺失。
  - `plateOperType=2` 为 `309` 条，`plateOperType=1` 为 `100` 条，缺失 `256` 条。
  - `prePlateNums` 非空值为 `质粒板A1`、`产物1`、`挑菌产物板1` 等标签。
- IR 修正：新增 `material_lineage_links`，并在 `material_edges` 保留 `quantity_consume_rule`、`pre_plate_label`、`discard_by_self`、`plate_input_rack/level` 等原始字段。
- Prompt/reference/executor 修正：候选必须读取 `material_lineage_links`，但不能把 `prePlateNums` 当数值列表，也不能用未确认的 `quantityConsumeRule`/`plateOperType` 枚举硬推 consume/copy/transfer 规则。
- 审计结果：`material_lineage_links=597`、`pre_plate_label_count=211`、`quantityConsumeRule None=629/1=36`、`plateOperType 1=100/2=309/None=256`。
- reference smoke：`/home/hehaochen/experiments/flow1160_v2_reference_lineage_20260629` 可行，`makespan=145071s`，`score=-145071.03310050775`。
- 冷启动 1-iter smoke：`/home/hehaochen/experiments/flow1160_v2_cold_lineage_1iter_20260629` 中 root 按预期被拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.11345417783`。生成脚本包含 `material_lineage_links`、`material_inventory_events/AddReservoirConstraint`、`logistics_events/buffer_ids`、`AddNoOverlap`、`AddCumulative`，未出现 `cur_ptr + duration` fallback。
- 因此新增本地字段需求文档：`REALISTIC_DATA_REQUIREMENTS.md`。该文档基于项目 1160 缓存字段实测，列出：
  - 当前可硬建的边级库存非负、buffer 容量、物流资源互斥；
  - 当前不能硬建的完整 merge/split 数量平衡、初始库存、入出库方向；
  - 平台需要新增/导出的最小 JSON schema。

## 2026-06-29 剩余真实落地边界设计

- 新增 `constraint_realization_boundaries`，作为 FUTS 候选能否把剩余语义升级成硬约束的边界来源。
- 边界已从静态结论改成接口/随机种子控制：
  - `--boundary-profile conservative|seeded_audit|seeded_experimental`
  - `--boundary-seed <int>`
  - 默认 `conservative` 不随机、不放开未确认语义。
  - `seeded_audit` 只对 audit 项生成可复现反馈采样状态。
  - `seeded_experimental` 只对 blocked 项生成可复现实验开关，仍保持 `hard_constraint=false`。
- `hard_ready` 当前只包含 5 类：
  - `task_and_material_precedence`
  - `edge_inventory_nonnegative`
  - `logistics_resource_no_overlap`
  - `buffer_capacity`
  - `rolling_existing_occupancy`
- `audit_only` 当前包含：
  - `plate_lineage_labels`
  - `quantity_consume_rule_enum`
  - `plate_oper_type_enum`
- `blocked_missing_fields` 当前包含：
  - `full_merge_split_balance`
  - `initial_material_stock`
  - `position_in_out_inventory`
  - `plate_identity_no_overlap`
- Prompt/executor/reference 已接入该字段。候选必须读取 `constraint_realization_boundaries.interface/state`；只有 `state.required_hard_constraints` 能硬建，`audit_controls/blocked_controls/experimental_controls` 不允许被私自硬建。
- scorer 仍未修改，边界通过 IR、prompt、executor guard 和候选 CP-SAT 约束落地。
- 验证：
  - `py_compile` 通过。
  - `audit_v2 --boundary-profile conservative --boundary-seed 1160` 输出 `required_hard_constraints=5`、`experimental_controls=0`。
  - `audit_v2 --boundary-profile seeded_experimental --boundary-seed 42` 输出 `required_hard_constraints=5`、`experimental_controls=4`，且实验项均为 `hard_constraint=false`。
  - reference smoke `flow1160_v2_reference_boundary_interface_conservative_20260629` 可行，`best_score=-145071.0489310927`。
  - reference smoke `flow1160_v2_reference_boundary_interface_seed42_20260629` 可行，`best_score=-145071.04582498112`。

## 2026-06-29 FUTS 可行性验证

- reference no-LLM：
  - `flow1160_v2_futs_feas_ref_conservative_20260629` 可行，`best_score=-145071.05760580176`。
  - `flow1160_v2_futs_feas_ref_seeded_20260629` 可行，`best_score=-145071.0507582959`。
- cold-start FUTS 1 iter：
  - `flow1160_v2_futs_feas_cold_conservative_1iter_20260629`：root 被 executor 按预期拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.07570983254`。
  - `flow1160_v2_futs_feas_cold_seeded_1iter_20260629`：root 被 executor 按预期拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.06470787735`。
- 两个 cold-start 生成脚本均读取 `constraint_realization_boundaries.interface/state`，并包含 `material_inventory_events/AddReservoirConstraint`、`logistics_events/buffer_ids`、`AddNoOverlap`、`AddCumulative`。
- 结论：在默认保守边界和 seed 控制的实验边界下，FUTS 最小闭环均可行。

## 2026-06-29 strict cold-start 历史数据隔离

- 参考 `multi_bot_era` no-incumbent 接口原则，新增 `history_policy`：
  - 默认 `strict_cold_start`：候选可见 IR 不暴露运行态 `startTime/endTime`，不从历史 span 推物流/任务时长。
  - 显式 `historical_replay`：保留旧的历史复盘/audit 行为。
- CLI/audit 新增 `--history-policy strict_cold_start|historical_replay`，默认 strict。
- v2 在 strict 模式下先给 v1 adapter 传入移除 `startTime/endTime` 的项目副本，防止 v1 的 `runtime_span_by_node` fallback 泄漏历史结果。
- 设备 capacity 不再用历史时间重叠推导；改用非时间戳结构信息：同一 `nodeId` 的计划实例数恢复保守设备容量，本项目得到 `Smart8A=8 / CytomatA=6 / QPixA=2 / TecanA=1 / TemperatureModuleA=1`。
- strict 模式下：
  - task `actual_start/actual_end/observed_machine_name` 保持 `None`；
  - logistics `duration=0`，`duration_source=missing_planning_duration_no_history`；
  - 原本有历史 span 的物流节点只标记 `historical_span_hidden=true` 作为 audit，不进入 CP-SAT 时长。
- 当前运送/上下料时长建模结论：strict cold-start 下没有独立规划耗时字段，因此不建正时长物流 interval；只保留 `StackRobotA` 资源、`buffer:StackRobotA`、前后继拓扑和数据需求。若要恢复正时长物流约束，需要平台导出独立的 `moveDuration/transferDuration`、from/to position 路径模型，或显式工艺参数。
- 验证：
  - `py_compile` 通过。
  - strict audit：`duration_source_counts={'planned': 65, 'missing_default_no_history': 6}`，`logistics_enforcement_counts={'precedence_only': 51}`，无非空 `actual_start/actual_end/observed_machine_name`。
  - historical_replay audit 仍可复现旧行为：`span_fallback=6`、`audit_no_overlap_candidate=24`。
  - strict reference no-LLM 可行：`flow1160_v2_strict_no_history_reference_20260629`，`best_score=-145860.06363340342`。

## 2026-06-29 当前定版口径

- 新实验默认写入 `/home/era/experiments`；`--output-dir` 仅用于临时覆盖。
- 当前默认建模口径为 `history_policy=strict_cold_start`，候选不可见历史运行开始/结束时间，也不可用历史 span 推导物流或任务时长。
- 边界由 `constraint_realization_boundaries` 统一承载，并由 `--boundary-profile` 与 `--boundary-seed` 控制；候选脚本不得硬编码边界开关。
- 当前可硬建并进入候选 CP-SAT 的核心约束为：
  - task duration、eligible machine、frequency、required capacity；
  - `precedence_pairs` 与 `min_wait`；
  - `material_edges[*].hard_precedence_candidate`；
  - strict 模式下零时长 logistics 拓扑前序；
  - `branch_priority_pairs` 表达 P1/P2/P3 分路开始优先级；
  - 机器 `AddCumulative`/容量为 1 时 `AddNoOverlap`；
  - `material_inventory_events` 的边级库存非负 `AddReservoirConstraint`；
  - 有独立非历史规划时长的 logistics/resource/buffer 约束。
- 当前 blocked 约束仍不能私自硬建：完整 merge/split 数量平衡、初始库存、入出库方向、plate identity no-overlap。它们需要平台提供独立且可验证的字段。
- 新增最优性证明脚本 `/home/era/scripts/prove_flow1160_v2_seed_optimal.py`。该脚本构造最小 CP-SAT 松弛模型，保留 hard precedence、零时长 logistics 拓扑、P1/P2/P3 start priority 和机器 capacity；若松弛模型被 CP-SAT 证明 `OPTIMAL` 且下界等于 FUTS 可行解 makespan，则该 makespan 是当前 IR/seed/history-policy 口径下的全局最优。
- FUTS 结果解释规则：makespan 是首要排程目标；当 makespan 已被证明最优后，后续 score 改善主要代表候选脚本求解速度/稳定性改善，而不是更短排程。
