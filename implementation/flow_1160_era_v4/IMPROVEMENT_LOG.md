# flow_1160_era_v4 创建记录

2026-07-01 补充：新增多培养板 seed 和 v4 松弛最优性证明。

本轮落地：

- 新增 `default_seeds/multi_dish_3_enzyme_activity.json`：
  - `initial_units.count=3`
  - `expand_initial_units=true`
  - 三个物理 96 孔培养板展开成三套独立 task/material traversal 实例。
- `seed_instance.py` 支持 plate instance 展开：
  - 单板 25 个任务展开为 3 个 job / 75 个任务；
  - 每个实例使用唯一 task id：`10001..10064`、`20001..20064`、`30001..30064`；
  - 设备、机器人、buffer、position 不复制，作为共享资源被 CP-SAT 竞争使用；
  - 多板 job 的 `expr_no` 区分为 `proj_1160:plate_001` 等，避免 v1 scorer 的 first-task-sync 旧假设把多板误判为必须同步。
- `prompt.py`、`executor.py`、`reference_v4_cpsat_candidate.py` 已读取 `plate_instances`。
- 新增 `/home/era/scripts/prove_flow1160_v4_relaxed_optimal.py`，支持 `--seed` / `--no-seed-instance`，用于 v4 task-level 松弛最优性证明。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --mode futs --iterations 0 --timeout-seconds 120 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v4/reference_v4_cpsat_candidate.py \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160 \
  --output-dir /home/hehaochen/experiments \
  --experiment-name flow1160_v4_multi_dish3_reference_smoke_rerun
# feasible=true, makespan=147425

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python /home/era/scripts/prove_flow1160_v4_relaxed_optimal.py \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160 \
  --known-upper-bound 147425 \
  --include-machine-capacity --logistics-mode conditional \
  --timeout-seconds 60 --workers 8
# tasks=75, material_transfer_edges=207, branch_priority_constraints=6
# relaxed_cp_sat_status=OPTIMAL
# relaxed_cp_sat_objective=147425
# relaxed_cp_sat_best_bound=147425
# proof=OPTIMAL: relaxed lower bound equals known feasible upper bound
```

2026-07-01 补充：按用户修正，v4 seed-specific 实例层不应只从目标任务反查祖先，而应遍历每一份初始原料的任务/物料流程，并保留设备释放后的跨原料阶段交错优化空间。

本轮追加：

- `seed_instance.py` 改为 `material_traversals` 口径：从每条匹配的外部初始物料 edge 出发，沿 material/task graph 向下游遍历；默认 seed 设置 `traverse_all_initial_materials=true`，再与目标可达关系裁剪到本次实例。
- `seed_instance["flow_parallelism_hints"]` 显式记录：
  - 设备在某份原料阶段结束后释放，可立即被另一份原料的其他阶段竞争使用；
  - 不允许把 selected task id、单份原料、或 P1/P2/P3 priority 错建成全局串行链；
  - 多个 P1 上游物流同时导入某设备、或产物/废料同时从某设备导出，是并行机会，只有显式 precedence、设备/机器人/孔位容量和 motion monitor 才能限制它们。
- `load_compatibility_report` 汇总每份 required initial material 是否有设备负载、孔位负载或 hard initial inventory 证据。
- `prompt.py` 和 `executor.py` 要求候选读取 `material_traversals`、`load_compatibility_report`、`flow_parallelism_hints`。
- `executor.py` 将 Isaac/motion monitor 的 conflict/deadlock 从扣分升级为候选不可行：只要 command monitor 或 Isaac/motion monitor 发现冲突/死锁，该候选直接 rejected。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m compileall -q /home/era/implementation/flow_1160_era_v4

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.audit_v4 \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160
# material_traversal_count=101, selected_task_count=25,
# initial_device_load_count=11, initial_position_load_count=16,
# load_parameter_binding_count=27

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --mode futs --iterations 0 --timeout-seconds 60 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v4/reference_v4_cpsat_candidate.py \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160 \
  --output-dir /home/hehaochen/experiments \
  --experiment-name flow1160_v4_material_traversal_isaac_gate_smoke
# experiment_dir=/home/hehaochen/experiments/flow1160_v4_material_traversal_isaac_gate_smoke
# best_score=-143525.01416267117
```

2026-07-01：按 `era-flow-1160` skill 中对 v3 的校准，创建独立
`/home/era/implementation/flow_1160_era_v4`。v4 不再只默认调度 1160
全流程图，而是在 v3 task/material/logistics/command IR 之上新增
seed-specific 实例层。

本轮落地：

- 从 v3 独立复制为 v4，模块引用切到 `implementation.flow_1160_era_v4`。
- 新增 `default_seeds/sample1_enzyme_activity.json`，默认以样本 1 到
  `酶活检测1` 为目标构造一个 seed-specific benchmark。
- 新增 `seed_instance.py`：生成 `fjspb["seed_instance"]`，包含
  `initial_materials`、`target_outputs`、`selected_task_ids`、
  `selected_material_edges`、`disabled_task_reason`、
  `seed_realization_boundaries`。
- 按用户校正，初始原料对排程的影响显式体现在设备/孔位等负载参数：
  `required_initial_materials`、`initial_device_loads`、
  `initial_position_loads`、`load_parameter_bindings`。这些字段暴露
  `device_name/rack/start_well/remaining_count/quantity/volume` 以及
  `device_name/rack/level/plate_barcode/inner_or_out/robot_interaction_flag`。
  默认仍为 audit-only，除非 seed 明确提供 stable stock identity、
  quantity 和 initial_position_id。
- `cli.py` 和 `audit_v4.py` 增加 `--seed`、`--no-seed-instance`，支持
  seed-specific v4 和 full-flow 对照。
- `prompt.py` 和 `executor.py` 要求候选读取 `seed_instance` 及负载参数，
  但禁止把 audit-only 初始库存/孔位私自升级为硬约束。
- `reference_v4_cpsat_candidate.py` 已读取 v4 seed/load 字段，并继续只把
  hard-ready 约束落地。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m compileall -q /home/era/implementation/flow_1160_era_v4

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.audit_v4 \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160
# 默认 seed: tasks=25, selected_task_count=25, disabled_task_count=46,
# initial_device_load_count=11, initial_position_load_count=16,
# load_parameter_binding_count=27

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --mode futs --iterations 0 --timeout-seconds 60 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v4/reference_v4_cpsat_candidate.py \
  --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160 \
  --output-dir /home/hehaochen/experiments \
  --experiment-name flow1160_v4_seed_instance_reference_smoke
# experiment_dir=/home/hehaochen/experiments/flow1160_v4_seed_instance_reference_smoke
# best_score=-143525.08951587736
```

# flow_1160_era_v3 创建记录

## 2026-06-30 初始 scaffold

- 从 `flow_1160_era_v2` 独立复制为 `flow_1160_era_v3`，保留 strict cold-start、boundary profile、material/logistics/rolling no-history 口径。
- 新增 `command_ir.py`，在 `dataset["fjspb"]` 中生成 `device_commands`、`positions`、`plate_states`、`robot_resources`、`command_templates`、`command_realization_boundaries`。
- 当前 command IR 是可验证子集：71 个 `device_run` task command + 51 个 strict cold-start 零时长 logistics topology command；缺机械臂移动时长、from/to 路径、稳定 plate identity、在线重排状态的语义均进入 blocked boundaries。
- 新增 `audit_v3.py` command 统计；`Flow1160V3Executor` 要求候选读取 command IR 并返回非空 `command_assignments`，拒绝 task-only 伪 v3。
- 更新 `prompt.py/search.py`，要求 FUTS 生成 command-aware CP-SAT，并继续禁止历史 span、猜测常量或 missing-field 语义硬建。
- 新增 `reference_v3_cpsat_candidate.py`，继续使用 v2/v1 task 约束和 scorer，同时返回每个 task run 的 command assignment。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era python -m compileall -q /home/era/implementation/flow_1160_era_v3

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era python -m implementation.flow_1160_era_v3.audit_v3   --dataset /home/era/experiments/flow_1160_cache/1160.json   --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160

PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era python -m implementation.flow_1160_era_v3.cli   --dataset /home/era/experiments/flow_1160_cache/1160.json   --mode futs --iterations 0 --timeout-seconds 60 --no-llm   --initial-code /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py   --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160   --output-dir /home/hehaochen/experiments --experiment-name flow1160_v3_reference_smoke
```

Reference smoke: `best_score=-145860.03013417555`.

---

## 2026-07-01 平台真实化字段接入

- 用户提供临时 Bearer token 后，已直接访问智能调度平台接口并确认一批对 v3 真实化有用的字段。
- `/home/era/implementation/flow_1160_era/problem.py::fetch_project` 和技能脚本 `era-flow-1160/scripts/les_client.py` 已扩展缓存字段：
  - `device_materials`
  - `barcode_manage`
  - `barcode_settings`
  - `material_settings`
  - `device_inner_settings`
  - `well_global`
  - `device_running`
  - `dispatch_node_queue`
- v3 新增 `fjspb["platform_realism_sources"]`，版本 `platform_realism_sources_v1`，集中暴露：
  - `device_material_loads`：设备装载/耗材候选，只作 initial load audit；
  - `aps_loading_time_candidates`：`apsLoadingTime/apsUnloadingTime` 候选，只作 audit，避免未验证单位或 double-count；
  - `material_catalog` / `barcode_catalog`：目录/几何/体积元数据；
  - `device_position_stock_candidates`：有 `plateBarcode` 的板位候选；
  - `device_running_status`、`dispatch_node_queue`：在线状态 audit。
- `prompt.py` 和 `executor.py` 已要求候选读取 `platform_realism_sources`；`reference_v3_cpsat_candidate.py` 已保留该字段引用。
- `audit_v3.py` 已输出平台真实化端点计数、APS loading 值分布、deviceMaterial materialCode 分布和样本行。
- 边界判断：本轮没有新增 hard-ready 约束。`deviceMaterial` 提升初始库存 audit，但缺 stable `stock_item_id`/position binding；`apsLoadingTime` 是最重要的工时候选，但需验证单位和是否已包含在 task duration 中；`devicePosition.transferPoseList` 当前为空，因此仍没有平台机器人路径/姿态时间。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m py_compile \
  /home/era/implementation/flow_1160_era/problem.py \
  /home/era/implementation/flow_1160_era_v3/problem.py \
  /home/era/implementation/flow_1160_era_v3/audit_v3.py \
  /home/era/implementation/flow_1160_era_v3/prompt.py \
  /home/era/implementation/flow_1160_era_v3/executor.py \
  /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v3.audit_v3 \
  --dataset 1160 --live \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160
```

实际运行时先刷新默认缓存：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python /home/hehaochen/.codex/skills/era-flow-1160/scripts/les_client.py fetch 1160
```

缓存输出：`/home/era/experiments/flow_1160_cache/1160.json`。

audit 关键结果：

```text
platform_realism_endpoint_counts {"all_nodes_with_aps_loading_fields": 221, "barcode_manage": 366, "barcode_settings": 78, "device_inner_settings": 0, "device_materials": 17, "device_running": 56, "dispatch_node_queue": 0, "material_settings": 67, "positions": 262, "positions_with_plate_barcode": 16, "positions_with_transfer_pose_list": 0, "well_global": 0}
platform_realism_aps_loading_counts {"0": 94, "1": 8, "2": 25, "3": 2, "4": 48, "6": 28, "7": 6, "9": 10}
```

reference smoke：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v3.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --mode futs --iterations 0 --timeout-seconds 60 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160 \
  --experiment-name flow1160_v3_platform_realism_sources_smoke
```

结果：`experiment_dir=/home/era/experiments/flow1160_v3_platform_realism_sources_smoke`，`best_score=-149745.1091003246`。

---

## 2026-07-01 平台 AI 查询与自填报候选

按短对话方式继续询问平台 AI：

- `apsLoadingTime` 单位是什么，是否已包含在 `duration` 中；
- `deviceMaterial.remainingCount/quantity` 能否作为初始库存硬约束；
- `devicePosition.plateBarcode` 是否是跨 `materialData` 稳定孔板 ID。

结果：

- AI chat 的执行环境没有项目 1160 缓存/数据字典，`apsLoadingTime` 查询只能要求补充样例；
- `deviceMaterial` 和 `plateBarcode` 查询没有找到项目文件，并触发 429 request limit；
- 未得到可验证字段语义，因此不新增默认 hard-ready 约束。

已在 `platform_realism_sources` 中新增 `ai_query_status` 与 `self_filled_assumption_profiles`：

- `aps_loading_time_minutes_pre_task_device_setup`：中等置信，假设 `apsLoadingTime` 是分钟级独立前置 setup/loading interval；默认不硬建，显式启用后预计 makespan 非下降。
- `device_material_initial_load_by_material_code`：低置信，作为初始装载候选；因缺 stable stock item/position binding，默认不硬建。
- `device_position_plate_barcode_initial_occupancy`：低置信，作为部分初始板位候选；因覆盖率低且不贯穿 materialData，默认不硬建。

这些 profile 给后续显式实验 profile 或人工确认后的 hard-ready 升级使用，当前 strict cold-start 默认 makespan 不变。

---

# flow_1160_era_v3 改进日志

日期：2026-06-26

## 目标

`flow_1160_era_v3` 是 `flow_1160_era` 的独立增强项目。v1 已经能在核心 task 模型上由 FUTS 达到 `145058s = 40.294h` 的最小 CP-SAT 理论最优；v3 不直接覆盖 v1，而是新增更贴近真实运行的 IR 层：

1. `material_edges`：从 `projectAllNodeList.materialData` 规范化板级物料流。
2. `logistics_events` / `buffers` / `logistics_resources`：表达堆栈、进板、退栈、扫码、转运等物流资源。
3. `rolling_state` 和 task 级 `run_status/duration_source/actual_start/actual_end`：为后续 fixed-prefix / rolling schedule 做准备。

## 当前实现

- v3 `problem.py` 先调用 v1 `flow_data_to_fjspb`，保持原 `jobs/tasks/machines/precedence_pairs/branch_priority_pairs` 可执行契约。
- 然后追加 v3 字段，不改变候选脚本返回格式：仍为 `{"assignments": [...]}`。
- `scorer` 仍复用 v1，不改变客观评分口径；v3 约束落地放在候选脚本和 `Flow1160V3Executor` 的执行前检查中。
- `executor.py/search.py` 已切到 v3：候选必须使用 CP-SAT，并显式读/建模 `material_edges`、`material_inventory_events/AddReservoirConstraint`、`logistics_events`、`buffers/buffer_ids`、`rolling_state/existing_machine_occupancy`、`AddNoOverlap`、`AddCumulative`，否则直接拒绝。
- `prompt.py/mutator.py/cli.py` 已切到 v3，引导 LLM 使用 v3 metadata，但要求保留 v1 hard constraints。
- 冷启动 seed 仍是 v1 的空 CP-SAT skeleton，不内置手写参考候选；用于验证 FUTS 能否从失败根节点生成准确 v3 建模脚本。
- `audit_v3.py` 输出 v3 层计数、样例和 enforcement 分布。

## 分阶段约束策略

### A. material_edges

硬约束候选：

- `src_task_id -> dst_task_id` 物料边可转成 hard precedence。
- `barcode/material + quantity` 可转成守恒和转移量约束。
- 多入/多出可转成 merge/split 约束。
- 同板互斥操作可转成板级 NoOverlap。

当前状态：字段仍作为 IR metadata 暴露；v3 prompt 和参考/生成候选要求把 `hard_precedence_candidate=True` 且有 `src_task_id/dst_task_id` 的边建成 CP-SAT precedence。未改 scorer。

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

当前状态：事件、资源、buffer 和 enforcement 建议已输出；v3 prompt 和参考/生成候选要求把 `audit_no_overlap_candidate` 且有 duration/resources 的事件建成固定存在的物流 interval，按 resource `AddNoOverlap`，按 `buffer_ids` 加入 buffer `AddCumulative` 容量日历，并把物流 event end 纳入 modeled makespan。未把 logistics event 放入返回 assignments。

### C. rolling/fixed

未来字段：

- task: `run_status/is_fixed/fixed_start/fixed_end/scheduled_machine`
- IR: `cur_ptr/existing_machine_occupancy/rolling_time_now`

当前状态：offline benchmark 不冻结历史记录，避免把项目 1160 的历史运行结果变成 replay；非 fixed task 从 `cur_ptr` 后重新排。`existing_machine_occupancy` 会作为固定 interval 插入机器 cumulative calendar。

## 2026-06-26 冷启动 FUTS 验证

- 实验目录：`/home/hehaochen/experiments/flow1160_v3_cold_futs_schema_fix_20iter_20260626`
- 命令：不传 `--initial-code`，`--iterations 20`，`--timeout-seconds 60`。
- 结果：`21` 个节点（根 + 20 iter），`20` 个可行候选，只有根节点因空 seed 缺少 v3 字段被 `Flow1160V3Executor` 拒绝。
- 最佳节点：`node_0013`，`makespan=145071s`，`score=-145071.013828453`。
- 所有可行候选 makespan 均为 `145071s`；相比 v1 核心 task 理论最优 `145058s` 增加 `13s`，说明 v3 物流/物料/rolling 约束已在候选模型中产生实际约束影响。
- 生成的 `best.py` 使用了：
  - `material_edges` + `hard_precedence_candidate` 生成物料 hard precedence；
  - `branch_priority_pairs` 的 dict schema：`higher_task_id/lower_task_id`，恢复 P1/P2/P3 start priority；
  - `logistics_events` 生成 resource `AddNoOverlap` interval，并把物流 end 纳入 `AddMaxEquality(makespan, ...)`；
  - `rolling_state.cur_ptr` 和 `existing_machine_occupancy`，并在 `AddCumulative` 前插入固定占用 interval。

## 2026-06-29 可复现 smoke

- 实验目录：`/home/hehaochen/experiments/flow1160_v3_cold_best_replay_20260629`
- 命令：`--no-llm --iterations 0 --initial-code /home/hehaochen/experiments/flow1160_v3_cold_futs_schema_fix_20iter_20260626/best.py`
- 结果：可行，`makespan=145071s`，`score=-145071.10568767838`。
- 结论：20 iter 冷启动 FUTS 产出的 `best.py` 离开生成过程后仍可独立通过 v3 executor 和原 v1 scorer；v3 scorer/seed 均未改动。

## 2026-06-29 buffer 容量约束修正

- 数据来源：平台 `devicePosition` 位置数；本数据集中 `StackRobotA=147`、`BufferA=4`、`BufferB=4`，v3 IR 共输出 `buffers=19`。
- IR 修正：`logistics_events` 增加 `buffer_ids`，例如 stack 事件映射到 `buffer:StackRobotA`。
- prompt/search 修正：要求候选读取 `buffers` 和 `logistics_events[*].buffer_ids`，将物流 interval 以 demand=1 加入 buffer `AddCumulative`，capacity 使用 `buffer["capacity"]`。
- executor 修正：缺少 `buffers/buffer_ids` 的候选会被拒绝；典型 `cur_ptr + duration` 未验证 fallback 会被拒绝。
- reference smoke：`/home/hehaochen/experiments/flow1160_v3_reference_buffer_capacity_20260629` 可行，`makespan=145071s`，`score=-145071.0146578902`。
- 旧 cold-start best guard check：`/home/hehaochen/experiments/flow1160_v3_old_best_guard_check_20260629` 被拒绝，原因是 `candidate rejected: v3 solver must explicitly model/read buffer_ids`。这说明旧脚本已不满足最新 v3 约束门槛。

## 2026-06-29 material reservoir 修正

- IR 修正：新增 `material_inventory_events`，只覆盖 `src_task_id/dst_task_id/quantity` 明确的 material edge，不覆盖外部供料或缺源任务的 rows。
- prompt/search 修正：要求候选按 `inventory_key` 建 `AddReservoirConstraint`，用源任务 end 做 `+quantity`、目标任务 start 做 `-quantity`，表达库存非负。
- executor 修正：缺少 `material_inventory_events` 或 `AddReservoirConstraint` 的候选会被拒绝。
- reference smoke：`/home/hehaochen/experiments/flow1160_v3_reference_inventory_reservoir_20260629` 可行，`makespan=145071s`，`score=-145071.04336176047`。
- 旧 cold-start best guard check：`/home/hehaochen/experiments/flow1160_v3_old_best_inventory_guard_20260629` 被拒绝，原因是 `candidate rejected: v3 solver must explicitly model/read material_inventory_events, buffer_ids`。
- 冷启动 1-iter smoke：`/home/hehaochen/experiments/flow1160_v3_cold_inventory_buffer_1iter_20260629` 中根节点按预期被拒绝；LLM 生成的 `node_0001.py` 可行，`makespan=145071s`，`score=-145071.0790431299`，并包含 `material_inventory_events`、`AddReservoirConstraint`、`buffer_ids`、buffer `AddCumulative`。
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
- reference smoke：`/home/hehaochen/experiments/flow1160_v3_reference_lineage_20260629` 可行，`makespan=145071s`，`score=-145071.03310050775`。
- 冷启动 1-iter smoke：`/home/hehaochen/experiments/flow1160_v3_cold_lineage_1iter_20260629` 中 root 按预期被拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.11345417783`。生成脚本包含 `material_lineage_links`、`material_inventory_events/AddReservoirConstraint`、`logistics_events/buffer_ids`、`AddNoOverlap`、`AddCumulative`，未出现 `cur_ptr + duration` fallback。
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
  - `audit_v3 --boundary-profile conservative --boundary-seed 1160` 输出 `required_hard_constraints=5`、`experimental_controls=0`。
  - `audit_v3 --boundary-profile seeded_experimental --boundary-seed 42` 输出 `required_hard_constraints=5`、`experimental_controls=4`，且实验项均为 `hard_constraint=false`。
  - reference smoke `flow1160_v3_reference_boundary_interface_conservative_20260629` 可行，`best_score=-145071.0489310927`。
  - reference smoke `flow1160_v3_reference_boundary_interface_seed42_20260629` 可行，`best_score=-145071.04582498112`。

## 2026-06-29 FUTS 可行性验证

- reference no-LLM：
  - `flow1160_v3_futs_feas_ref_conservative_20260629` 可行，`best_score=-145071.05760580176`。
  - `flow1160_v3_futs_feas_ref_seeded_20260629` 可行，`best_score=-145071.0507582959`。
- cold-start FUTS 1 iter：
  - `flow1160_v3_futs_feas_cold_conservative_1iter_20260629`：root 被 executor 按预期拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.07570983254`。
  - `flow1160_v3_futs_feas_cold_seeded_1iter_20260629`：root 被 executor 按预期拒绝；`node_0001` 可行，`makespan=145071s`，`score=-145071.06470787735`。
- 两个 cold-start 生成脚本均读取 `constraint_realization_boundaries.interface/state`，并包含 `material_inventory_events/AddReservoirConstraint`、`logistics_events/buffer_ids`、`AddNoOverlap`、`AddCumulative`。
- 结论：在默认保守边界和 seed 控制的实验边界下，FUTS 最小闭环均可行。

## 2026-06-29 strict cold-start 历史数据隔离

- 参考 `multi_bot_era` no-incumbent 接口原则，新增 `history_policy`：
  - 默认 `strict_cold_start`：候选可见 IR 不暴露运行态 `startTime/endTime`，不从历史 span 推物流/任务时长。
  - 显式 `historical_replay`：保留旧的历史复盘/audit 行为。
- CLI/audit 新增 `--history-policy strict_cold_start|historical_replay`，默认 strict。
- v3 在 strict 模式下先给 v1 adapter 传入移除 `startTime/endTime` 的项目副本，防止 v1 的 `runtime_span_by_node` fallback 泄漏历史结果。
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
  - strict reference no-LLM 可行：`flow1160_v3_strict_no_history_reference_20260629`，`best_score=-145860.06363340342`。

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
- 新增最优性证明脚本 `/home/era/scripts/prove_flow1160_v3_seed_optimal.py`。该脚本构造最小 CP-SAT 松弛模型，保留 hard precedence、零时长 logistics 拓扑、P1/P2/P3 start priority 和机器 capacity；若松弛模型被 CP-SAT 证明 `OPTIMAL` 且下界等于 FUTS 可行解 makespan，则该 makespan 是当前 IR/seed/history-policy 口径下的全局最优。
- FUTS 结果解释规则：makespan 是首要排程目标；当 makespan 已被证明最优后，后续 score 改善主要代表候选脚本求解速度/稳定性改善，而不是更短排程。

## 2026-06-30 Isaac-motion 冲突扣分

- 新增 `isaac_motion.py`：从 `material_edges + assignments` 自动生成保守机械臂动作层，包含 `pick/move/place/drop/safety_gap`，默认转运时间 `1140s`。
- `v3_ir_to_events.py` 现在输出 `robot_actions`、`plate_transfers`、`motion_timing`、`motion_monitor`，供 Isaac Sim 回放/复核使用。
- `monitor_cli.py` 同时输出 command monitor 和 Isaac-motion monitor，可通过 `--pick-seconds/--move-seconds/--place-seconds/--drop-seconds/--safety-gap-seconds` 调整保守转运时间。
- `Flow1160V3Executor` 在 v1 task makespan score 后追加 Isaac-motion penalty：
  - `100000 * motion_conflict_count`
  - `1000000 * motion_deadlock_count`
  - `1000000 * len(schedule.get("isaac_conflicts", []))`
- penalty error 会记录 `penalized_task_ids` 和首个冲突，例如转运到达晚于后继 task start。外部 Isaac Sim 若检测到碰撞，可把 `isaac_conflicts` 放进候选返回结果，字段可含 `task_id/src_task_id/dst_task_id/task_ids`，executor 会把这些任务纳入扣分。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era python -m implementation.flow_1160_era_v3.cli   --dataset /home/era/experiments/flow_1160_cache/1160.json   --mode futs --iterations 0 --timeout-seconds 60 --no-llm   --initial-code /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py   --history-policy strict_cold_start --boundary-profile conservative --boundary-seed 1160   --output-dir /home/hehaochen/experiments --experiment-name flow1160_v3_isaac_penalty_reference_smoke
```

结果：`best_score=-18745860.036175147`。该 reference 仍满足 task-level scorer，但 motion monitor 检出 `182` 个保守机械臂转运迟到冲突，因此被显著降分。

---

## 2026-06-30 图距离物流矩阵与松弛最优性证明

- `problem.py` 的 `device_transfer_times` 改为图论自洽的 shortest-path 矩阵：`rectilinear_layout_graph_shortest_path_v1`。图由合成设备 layout 的 x/y 坐标诱导，路径为 rectilinear graph shortest path；不再用全局上限把远距离全部截断成固定 gap。
- 物流矩阵 row 记录 `distance_m`、`direct_distance_m`、`distance_model`、`motion_class`、`move_seconds`、`transfer_seconds` 和 `duration_source=synthetic_graph_distance_model_not_historical_runtime`。
- `isaac_motion.py`、`monitor_cli.py`、`v3_ir_to_events.py`、`problem.py` 的默认动作时间已缩为原 1/3：pick `30s`、default move `300s`、place `30s`、drop `10s`、safety `10s`、near rotate `40s`、far move base `100s`、far move per meter `15s`。
- 当前 strict/conservative/seed 1160 下，矩阵范围验证为约 `100s~570s`；same-device transfer 为 `100s`。
- `adaptive_futs.py` 与 `adaptive_logistics_gap.py` 不再 flatten/cap 矩阵，只发布验证 gap 状态：`gap_policy=adaptive_validate_graph_distance`，row 标记 `adaptive_policy=preserve_graph_distance_no_cap`。

短 FUTS 运行：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v3.cli \
  --dataset 1160 \
  --mode futs --iterations 10 --timeout-seconds 45 \
  --initial-code /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160 \
  --adaptive-logistics \
  --adaptive-logistics-isaac-headless \
  --adaptive-logistics-min-gap 80 \
  --adaptive-logistics-step 60 \
  --adaptive-logistics-isaac-timeout-seconds 90 \
  --experiment-name flow1160_v3_graph_distance_futs10_20260630
```

- 实验目录：`/home/era/experiments/flow1160_v3_graph_distance_futs10_20260630`。
- 该运行按用户要求在 node 2 后手动停止，实际 `nodes.jsonl` 有 3 条记录：node 0、1、2 均可行，makespan 均为 `149745s`。
- Isaac/headless report：root 尝试 gap `380/320/260/200/140/80` 均 `ok=true`；node 1 与 node 2 的 gap `80` report 均 `ok=true`，`motion_monitor.conflict_count=0`、`deadlock_count=0`，`timeline_meta.makespan_seconds=149745`。
- 运行观察：node 2 增加了 resource capacity map、资源 cumulative、device_run command 绑定和基于矩阵的 hint/decision strategy，但没有降低 makespan。

松弛最优性证明：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python /home/era/scripts/prove_flow1160_v3_relaxed_optimal.py \
  --dataset 1160 \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160 \
  --known-upper-bound 149745 \
  --include-machine-capacity \
  --logistics-mode conditional \
  --timeout-seconds 180 --workers 8
```

结果：

```text
tasks=71
machines=17
material_transfer_edges=212
conditional_transfer_edges=212
include_machine_capacity=True
logistics_mode=conditional
override_transfer_cap=None
relaxed_cp_sat_status=OPTIMAL
relaxed_cp_sat_objective=149745
relaxed_cp_sat_best_bound=149745
critical_path_lower_bound_with_min_transfers=143637
known_feasible_upper_bound=149745
proof=OPTIMAL: relaxed lower bound equals known feasible upper bound
```

解释：

- 证明脚本输入的是未赋值的当前 v3 IR，不读取 FUTS assignments 固定变量；CP-SAT 自行选择每个 task 的 start/end 和 machine。
- `known-upper-bound=149745` 只用于与松弛下界比较，不进入模型固定解。
- 与旧无图松弛脚本的差异是：当前脚本以 `logistics-mode=conditional` 对每条 material transfer 根据被选择的源/目的设备启用 `device_transfer_times[(src_machine,dst_machine)]`，而不是把 `material_edges` 当作零时长拓扑边。
- 该证明只覆盖 task-level + graph-distance transfer matrix + machine capacity 口径；仍是完整 Isaac/command 物理问题的松弛，未 hard-model 单机器人全局日历、plate position 状态机、真实碰撞几何和路径避障。

---

## 2026-06-30 物料守恒真实化边界

- 尝试通过系统内置 AI chat 获取项目 1160 物料守恒相关字段：`/api/ai/conversation` 返回 `401`，当前环境没有 `LES_PWD`，无法自动刷新 token。因此本轮以已有平台缓存 `/home/era/experiments/flow_1160_cache/1160.json` 的字段实测为依据。
- 缓存复核结果：`materialData` 共 `665` 条 data rows；`495` 条有 `preNodeId`，`170` 条无 `preNodeId`；`212` 条可映射为 task-to-task 物料边；`665` 条都有正 `quantity`、`materialCode`、`barcodeType`；`483` 条有 `plateAlias`；`211` 条有 `prePlateNums`；`488` 条有 `plateInputRack/plateInputLevel`。
- 新增 `fjspb["material_conservation_model"]`，版本 `material_conservation_model_v1`。该结构集中暴露：
  - `field_counts`：字段覆盖率；
  - `hard_ready`：当前只允许 `edge_inventory_nonnegative`，来源为 `material_inventory_events`，候选用 `AddReservoirConstraint`；
  - `initial_stock_candidates`：无 `preNodeId` 的外部输入候选，只作 audit；
  - `merge_split_quantity_audit`：merge/split 数量组只作 audit；
  - `blocked_full_hard_constraints`：`full_merge_split_balance`、`initial_material_stock_level`、`position_in_out_inventory`、`stable_plate_identity_no_overlap`。
- `prompt.py` 已要求候选先读取 `material_conservation_model`，不得把 `plateOperType/pushType/quantityConsumeRule/prePlateNums` 私自升级为完整守恒语义。
- `executor.py` guard 已要求候选显式读取 `material_conservation_model`。
- `reference_v3_cpsat_candidate.py` 已读取该字段；求解逻辑仍只把 `material_inventory_events` 建成 `AddReservoirConstraint`，不虚构完整 merge/split 或初始库存。

验证：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m py_compile \
  /home/era/implementation/flow_1160_era_v3/problem.py \
  /home/era/implementation/flow_1160_era_v3/prompt.py \
  /home/era/implementation/flow_1160_era_v3/executor.py \
  /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py
```

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v3_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v3.cli \
  --dataset 1160 \
  --mode futs --iterations 0 --timeout-seconds 60 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160 \
  --experiment-name flow1160_v3_material_conservation_model_smoke
```

结果：`experiment_dir=/home/era/experiments/flow1160_v3_material_conservation_model_smoke`，`best_score=-149745.128545367`。

---

## 2026-07-06 v4 口径记录：task-level 排程到 motion/Isaac 事件流的时间偏移来源

用户指出，实际实验室里任意两台设备前后配合的耗时方差可能很大。如果把每一次设备间转移 gap 都作为精确硬约束写入 CP-SAT，会让模型快速复杂化，并且对真实波动非常脆弱。v4 后续建模应保持分层口径：

- 硬约束优先表达结构性可行性：工序依赖、设备/孔位容量、机械臂互斥、设备端口/板位互斥、buffer 容量、不可达或禁止转移。
- 高方差转移耗时应优先作为风险/余量/鲁棒性评分，或按 profile 使用 p50/p90/p95 等统计边界，而不是默认把每次真实耗时精确硬建。
- Isaac/motion 发现的 `robot_transfer_late` 默认属于 transfer slack/gap 证据；只有 `robot_collision`、`device_port_collision`、`plate_motion_collision`、`device_swap_no_buffer` 等显性资源/死锁冲突才应优先回灌为求解器侧硬约束。

关于当前 node 生成方案到模拟端的偏移，明确两类来源：

1. 机械臂动作在 motion 层被重新排队。

   当前候选 CP-SAT 多数仍以 task/device 粒度为主，通常只保证：

   ```text
   end(prev_task) + device_transfer_times[src,dst] <= start(next_task)
   ```

   以及设备 capacity/cumulative 等任务级资源约束。若候选没有把每一条物料边展开成 `pick/move/place/drop/safety` 机械臂动作 interval，并对 `robot:StackRobotA` 加完整 `NoOverlap`，则多个 transfer 在 CP-SAT 中可能都“看起来来得及”。motion 层生成真实动作序列时会按单机械臂日历串行化：

   ```text
   transfer.start = max(planned_transfer_start, robot_available_time)
   ```

   前面的 transfer 占用机械臂后，后续 transfer 会被顺延；如果顺延后的到达时间晚于后继 task start，就形成 `robot_transfer_late`。这说明 node 没有完整建机械臂动作日历，或只用转移 gap 近似了机械臂资源。

2. 设备 task end 不等于物理释放完成。

   CP-SAT 的 `assignments` 是 task-level 摘要：`task_id / machine / start / end`。这里的 `task end` 表示设备工序运行结束，但模拟可执行性需要检查物料如何离开前序设备并进入后继设备。motion/Isaac 因此会把一条 `material_edges` 物料边展开为隐含执行动作：

   ```text
   prev task end
   -> pick from previous device
   -> move
   -> place into next device or buffer
   -> drop/safety
   -> next task may start
   ```

   这些动作不是实验流程外新增任务，而是 task-level 排程中被抽象掉的设备级/物流级执行动作。若候选没有显式返回这些 command interval，模拟端只能根据 `material_edges + assignments + device_transfer_times + isaac_motion_timing` 自动展开来复核。由此产生的时间偏移，本质是 task-level 计划表和 command/action-level 执行时间线粒度不一致。

后续若要减少这类偏移，不应简单把所有 gap 写死为更大常数，而应逐步让求解器显式建模关键 command：

```text
cmd:task:<task_id>:run
cmd:transfer:<edge_id>:pick
cmd:transfer:<edge_id>:move
cmd:transfer:<edge_id>:place
cmd:transfer:<edge_id>:drop
```

并加结构性约束：

```text
pick.start >= prev_task.end
move.start >= pick.end
place.start >= move.end
drop.start >= place.end
next_task.start >= drop.end

NoOverlap(robot pick/move/place/drop intervals)
NoOverlap(device port pick/place/drop intervals when port identity is hard-ready)
NoOverlap(plate motion intervals when stable plate identity is hard-ready)
Cumulative(buffer occupancy intervals, capacity)
```

在平台缺少真实路径、端口、板位、夹爪、动作模板或统计耗时分布时，上述 command 层仍应以 `command_realization_boundaries` 控制升级边界：字段 hard-ready 才转为硬约束；缺字段时保留为 audit/Isaac 验证和风险评分，避免凭历史 span 或常数假设制造不可解释的硬约束。

### 运输碰撞/冲突监测边界

当前 v4 已经监测一部分运输相关冲突，但这些属于调度级/资源级冲突，不等价于完整真实几何碰撞检测：

- `robot_transfer_late`：物料/培养板转运到达晚于后继 task start。
- `robot_collision`：同一机械臂动作 interval 时间重叠。
- `device_port_collision`：同一设备口在同一时间被多个 pick/place/drop 动作占用。
- `plate_motion_collision`：同一培养板在同一时间出现多个移动动作。
- `device_swap_no_buffer`：两台设备发生双向换板且没有可用 buffer，存在死锁风险。

这些冲突适合回灌到 CP-SAT/FUTS：迟到类作为 transfer slack/gap 证据；资源互斥、端口互斥、板位互斥、buffer 死锁类作为硬约束升级候选。

但当前实现还不是完整 Isaac 物理碰撞仿真。尚未 hard-model：

- 真实机械臂关节轨迹规划；
- 实验室 CAD 几何碰撞体；
- 路径避障和动态障碍；
- 夹爪姿态、抓取点和抓取失败；
- 设备门、伸缩台、托盘、孔位的真实几何占用；
- 多机器人运动学级协调。

因此当前 `motion_ok=true` 的含义应解释为：在当前抽象运动/资源模型下未发现运输调度冲突；不能直接声明真实实验室几何碰撞一定安全。后续若引入真实 CAD、关节轨迹、控制器状态或传感器反馈，应先作为验证层记录冲突证据，再判断哪些冲突能升级为 v4 IR/CP-SAT 的硬约束，哪些只进入风险评分或执行层在线重排。

### 2026-07-06 v4 运行改进：Isaac timeout 默认值与增量绘图

本轮根据 `flow1160_v4_multi_dish3_coldstart_futs10_explicit_feedback_20260706` 的运行现象更新运行侧工具：

- 外部 Isaac headless replay 在 `120s` 内经常已经写出 events/stdout，但没有写出 report，因此 adaptive 层会把内部 motion 可行节点标成 `timeout after 120s` 并额外扣 `1_000_000` 分。该 timeout 不是 CP-SAT 失败，也不是内部 motion 失败，而是 `AdaptiveLogisticsTightener` 调用外部 `isaac_twin.py` 的验证超时。
- `cli.py`、`adaptive_futs.py`、`search.py` 的默认 `adaptive_logistics_isaac_timeout_seconds` 已从 `240` 放宽为 `300`。若命令行显式传 `--adaptive-logistics-isaac-timeout-seconds 120`，仍以显式值为准。
- 新增 `flow_1160_era_v4.plot.write_incremental_futs_plots(experiment_dir)`，每个 node 完成评估后由 `search._record_node()` 自动刷新：
  - `v4_node_progress.png`
  - `v4_node_progress.csv`
  - `v4_node_progress_summary.json`
- 中断任务也可以离线补图：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.plot \
  /path/to/experiment_dir
```

绘图口径：

- `csv/summary` 保留所有已评估/待评估 node 的状态，用于诊断失败原因。
- 主图只画模拟可行节点：`feasible=True` 且状态属于 `isaac_ok`、`motion_ok`、`motion_ok_isaac_timeout`。
- 模拟失败节点不进入主图曲线，例如 `motion_rejected`、`schema_rejected`、`guard_rejected`、`pending` 均被排除。
- `motion_ok_isaac_timeout` 表示内部 motion monitor 已通过，但外部 Isaac headless report 未在 timeout 内确认；该状态可用于观察可行候选演进，但不能等同于完整 Isaac headless 通过。

对当前 interrupted/partial 目录离线绘图验证通过：

```text
/home/hehaochen/experiments/flow1160_v4_multi_dish3_coldstart_futs10_explicit_feedback_20260706/v4_node_progress.png
/home/hehaochen/experiments/flow1160_v4_multi_dish3_coldstart_futs10_explicit_feedback_20260706/v4_node_progress.csv
/home/hehaochen/experiments/flow1160_v4_multi_dish3_coldstart_futs10_explicit_feedback_20260706/v4_node_progress_summary.json
```

---

## 2026-07-07 v4 FUTS 目标函数与物流 padding 策略修正

根据 multi-dish-3 FUTS 对比结果，当前 v4 生成候选不应采用“先全局加保守 padding 再找可行解”的默认方向。统一把 `adaptive_current_gap`、`adaptive_min_gap`、validation gap、`transfer_safety_padding` 或 `pair_padding` 叠加到所有 hard `material_edges` 会把仿真验证状态误当成额外工艺时间，直接抬高 CP-SAT 下界，并容易让 FUTS 在较长 makespan 的可行区域内反复微调。

已更新 `prompt.py`、`search.py` 和 `executor.py`：

- hard material transfer 的基础约束应保持为：

```text
start[dst] >= end[src] + max(src.min_wait, device_transfer_times[src_machine,dst_machine])
```

- `isaac_motion_timing["transfer_seconds"]` 仅作为缺失 pair 的 fallback，不是全局额外 padding。
- 禁止候选把 adaptive gap/min gap/validation gap 统一加到每条 material edge。
- 推荐词典序目标：先最小化 `makespan`，再在同 makespan 下最小化 selected-pair `transfer_cost`，例如：

```text
model.Minimize(makespan * (transfer_cost_upper_bound + 1) + transfer_cost)
```

- `robot_transfer_late` 只作为 transfer-time/slack evidence；若使用反馈，应定位到具体 `transfer_id`、`edge_id`、task pair 或 device pair，优先作为局部 soft preference 或二级 tie-break。只有 `robot_collision`、`device_port_collision`、`plate_motion_collision`、`device_swap_no_buffer` 等显性资源/死锁冲突才应回灌为硬资源/位置/buffer 约束。

---

## 2026-07-01 方向校准：从全流程图复现转向 seed-specific 初始原料实例

用户指出当前 v3/FUTS 优化已经偏离最初设想：现有模型主要把智能平台 1160 的整张流程图转换成 task-level 排程，再给每个 task 绑定平台运行时长、设备候选、物流矩阵和 Isaac/headless 监测。这样优化对象更像“复现并压缩原平台全流程图”，而不是“给定某次实验初始投入，判断本次应执行哪些流程并优化运行方案”。

当前事实复盘：

- `flow_1160_era_v3.problem.load_problem()` 仍默认调度 1160 中全部 task-bearing branches。branch_groups 只用于分支优先级/审计，不会根据某个输入原料 seed 选择或禁用流程分支。
- 初始/反应原料当前有两类候选输入，但都不是 hard 初始库存：
  - `platform_realism_sources.device_material_loads` 来自平台 `deviceMaterial/list`，当前 17 行，例如 Smart8A 上的 r10 水、r15 引物A、r23 含抗卡那、r28 裂解液、r3 诱导剂、1tip/2tip/5tip 等，`enforcement=audit_only_initial_load_candidate`。
  - `material_conservation_model.initial_stock_candidates` 来自 `projectAllNodeList.materialData` 中无 `preNodeId` 的外部输入行，例如 `r10|水|unit=6`、`r15|引物A|unit=6`、`r23|含抗卡那|unit=21`、`r28|裂解液|unit=12`、`r3|诱导剂|unit=12`、tips 和 V0/V1 输入等，`enforcement=audit_only`。
- 当前唯一 hard-ready 的物料守恒是 `material_inventory_events` 的 task-to-task 边级库存非负：候选使用 `AddReservoirConstraint(+quantity at source end, -quantity at destination start, min_level=0)`。这不等价于 seed 初始库存，也不会裁剪本次实验任务。
- 因此当前 makespan 优化主要发生在 task start/machine choice/conditional device_transfer_times 上；给定反应原料的数量、初始位置、目标产物和可达流程并未成为排程实例的定义变量。

下一轮 v3 应优先补 seed-specific 实例层，而不是继续只调全流程图：

1. 新增 seed 输入结构，例如 `flow_1160_era_v3/default_seeds/seed_001.json`：

```json
{
  "seed_id": "seed_001",
  "initial_materials": [
    {"material_code": "r10", "name": "水", "quantity": 6, "unit": "unit"},
    {"material_code": "r15", "name": "引物A", "quantity": 6, "unit": "unit"},
    {"material_code": "r23", "name": "含抗卡那", "quantity": 21, "unit": "unit"}
  ],
  "target_outputs": [],
  "initial_positions": [],
  "branch_policy": "derive_from_material_reachability"
}
```

2. 新增 `seeds.py` / `seed_instance.py`：
   - 从 `deviceMaterial/list`、`materialData` 无 `preNodeId` 行、或人工 JSON 生成 seed。
   - 用 seed 的 `initial_materials` 和可选 `target_outputs` 在 `material_edges` 上做 reachability/反推，得到 `selected_material_edges`、`selected_task_ids` 和 `disabled_task_reason`。
   - 把 seed 声明的初始库存写成 `hard_initial_inventory`，不要再把 audit-only `initial_stock_candidates` 自动升级为硬约束。
   - 根据数量实例化或缩放 task multiplicity / `required_capacity` 的规则必须显式记录；如果无法从平台字段确认消耗/复制/分流语义，则写入 `seed_realization_boundaries.blocked_controls`，不要伪造完整质量守恒。

3. `load_problem()` / CLI 增加 seed 参数：
   - 建议参数：`--seed-file` 或 `--seed-id`。
   - 输出 `dataset["fjspb"]["seed_instance"]`，包括 `seed_id`、`initial_materials`、`target_outputs`、`selected_task_ids`、`selected_material_edges`、`hard_initial_inventory`、`seed_realization_boundaries`。
   - FUTS 默认应优化 seed 实例；仅显式传 `--full-flow` 或无 seed 时才回退当前全流程图 benchmark。

4. prompt/executor/reference candidate 更新：
   - prompt 要求候选读取 `seed_instance`，只调度 `selected_task_ids`，并对 `hard_initial_inventory` 建 reservoir 初始水位/库存约束。
   - executor guard 增加 `seed_instance` / `hard_initial_inventory` token 检查。
   - scorer 要能识别候选调度了 disabled task 或漏调 selected task。

5. 下轮验证目标：
   - 先用一个短 seed smoke 验证 selected task 数量小于 71，makespan 随 seed 改变。
   - 再运行短轮次 FUTS，观察节点是否改变物料可达流程、设备选择和物流路径，而不是只在固定全图上复现相同 makespan。
   - full-flow v3 benchmark 和 seed-specific v3 benchmark 应分开命名，避免结果解释混淆。

---
