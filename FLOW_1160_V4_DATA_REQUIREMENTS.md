# Flow 1160 V4 Data Requirements

本文记录 `flow_1160_era_v4` 当前建模口径下还需要向实验室或智能调度平台补齐的数据与参数。目标是把目前只能作为 `audit/context` 的字段，逐步升级为 CP-SAT、executor、motion monitor 可以硬校验的约束。

## 1. 当前建模状态

v4 已经把项目 1160 从“整张流程图默认排一次”改成了 seed-specific 排程：初始输入是 1 个或 n 个物理培养皿/培养板，每份初始原料展开成自己的任务/物料流程实例，设备、机器人、buffer、孔位等资源共享。

当前 hard-ready 约束主要包括：

- task duration、eligible machine、required capacity、frequency、temperature；
- explicit precedence、`minWaitTime`、P1/P2/P3 分路首任务开始优先级；
- 设备 cumulative capacity；
- 明确 `src_task_id -> dst_task_id` 的物料 precedence；
- `material_inventory_events` 的边级库存非负；
- 有明确资源和容量的 logistics/buffer 约束；
- 设备间 transfer matrix 口径的条件化转移时间；
- Isaac/motion monitor 对冲突和死锁的硬拒绝。

当前还不是完整实验室数字孪生。缺字段的内容仍必须留在 `audit_only` 或 `blocked_missing_fields`，不能让候选脚本私自硬建。

## 2. 最高优先级数据

### 2.1 初始培养板 / 培养皿身份

需要补齐：

- 每个初始培养板或培养皿的唯一 ID：`plate_id`、`barcode` 或 `stock_item_id`。
- 初始所在设备：`device_name`、`device_code`。
- 初始孔位：`rack`、`level`、`slot`、`well`、`position_id`。
- 初始物料类型：样本、质粒、培养基、试剂、产物、废料等。
- 初始数量：板数、孔数、体积、浓度、剩余量。
- 初始可用时间：实验开始即在位，还是某个时间后才可用。

为什么需要：

- v4 的 `initial_device_loads`、`initial_position_loads`、`load_parameter_bindings` 当前主要是 audit/context。
- 没有稳定身份和初始位置，就不能硬建“这份原料从这个孔位开始”。
- 多培养板排队时，plate identity 是避免同一物理板同时出现在两个位置的基础。

补齐后可升级：

- `hard_initial_inventory`
- 初始 position occupancy
- plate-level no-overlap
- seed-specific 起点约束

### 2.2 物料产消和分流规则

需要补齐：

- 每个任务的输入物料、输出物料、废料列表。
- 每条 `materialData` 边的 `quantity` 单位：板数、孔数、体积、批次数或其他。
- `plateOperType` 的确定枚举语义。
- `quantityConsumeRule` 的确定枚举语义。
- `pushType` 的确定枚举语义。
- `prePlateNums` 是来源标签、数量、孔位集合还是其他身份字段。
- 多入 merge 的数量规则。
- 多出 split 的数量规则。
- 产物和废料是否同时产生，以及分别占用什么容器/孔位。

为什么需要：

- 当前只有边级库存非负，能防止“下游先消耗上游还没产生的物料”。
- 这还不是完整物料守恒，不能证明所有输入、产物、废料的数量闭合。
- merge/split、复制、消耗、废弃的规则不明确时，硬建完整守恒会制造伪约束。

补齐后可升级：

- full merge/split balance；
- 完整输入/输出/废料守恒；
- 按 plate/material identity 的库存状态机；
- 产物和废料同步出板约束。

### 2.3 上下料与转移时长语义

需要补齐：

- `apsLoadingTime` 的单位。
- `apsUnloadingTime` 的单位。
- `apsLoadingTime/apsUnloadingTime` 是否已经包含在 `duration` 中。
- 独立 `transferDuration` 或 `moveDuration`。
- from-device / to-device 的转移矩阵。
- from-position / to-position 的转移矩阵。
- pick、place、扫码、开门、关门、门锁等待、drop、safety gap 的动作时长。

为什么需要：

- 当前 v4 已有 transfer matrix 口径，但仍有合成或保守估计成分。
- 如果 `duration` 已包含上下料，再额外加入 `apsLoadingTime` 会 double count。
- 如果 `duration` 不包含上下料，但未补独立时长，排程会低估真实资源占用。

补齐后可升级：

- 正时长 logistics interval；
- robot/resource `AddNoOverlap`；
- task-command 对齐；
- 更可靠的 motion monitor 前置约束。

## 3. 设备与孔位数据

### 3.1 设备真实并发能力

需要补齐：

- 每台设备的真实并发处理能力。
- 每类任务占用几个处理位、通道或模块。
- Smart8、Cytomat、QPix、Tecan 等设备是否存在子模块并发。
- 设备维护、故障、校准过期、不可用时间窗。
- 在线重排时设备已有占用区间。

为什么需要：

- 当前 capacity 采用数据驱动和保守结构恢复，但仍需要实验室确认。
- 多培养板并行优化依赖设备释放后能否被另一份原料阶段复用。

补齐后可升级：

- 更准确的 `machines` capacity；
- task demand；
- rolling existing occupancy；
- 在线插单和重排约束。

### 3.2 孔位 / 料位 / buffer 状态机

需要补齐：

- 每台设备的可用孔位列表。
- 每个孔位的容量。
- 每个孔位的可进入/可移出方向。
- 孔位是否可同时存储、处理、等待。
- 设备运行时孔板是否必须占用固定孔位。
- 任务结束后孔板留在设备、进入 buffer、还是立即转移。
- 产物位、废料位、临时 buffer 位、堆栈位的容量和可达性。

为什么需要：

- `devicePosition` 数量不能直接等同于设备并发 capacity。
- 但它是 plate position 状态机和物理冲突建模的基础。
- 缺少入出库方向时，只能检查冲突，不能完整规划合法动作链。

补齐后可升级：

- position occupancy；
- buffer capacity；
- plate move legality；
- 设备间换板和临时中转 deadlock 检测。

## 4. 机器人和 Isaac 数据

### 4.1 机器人资源

需要补齐：

- 机器人数量。
- 夹爪数量。
- 每个机器人可达设备和孔位。
- 是否允许多个机器人并行。
- 是否允许机器人持板等待。
- 持板最大等待时间。
- 机器人、设备门、孔板之间的互斥资源。

为什么需要：

- 当前 `robot_resources` 和 command IR 只能表达保守资源层。
- 多个上游物流同时导入某设备、产物和废料同时出设备，都需要真实机器人能力解释。

补齐后可升级：

- gripper `NoOverlap`；
- robot calendar；
- parallel transfer feasibility；
- deadlock prevention constraints。

### 4.2 Isaac / 数字孪生几何参数

需要补齐：

- 设备几何模型。
- 机器人几何模型。
- 孔板、夹爪、设备门、buffer 的碰撞体。
- 设备和孔位真实坐标系。
- pick/place 姿态。
- 开门/关门动作轨迹。
- 禁行区、避障区、共享通道。
- motion planning 失败类型到排程错误的映射。

为什么需要：

- Isaac/motion monitor 当前主要是 feasibility backstop。
- 如果几何和姿态不完整，它不能参与 CP-SAT 最优性证明，只能事后拒绝冲突方案。

补齐后可升级：

- command-level motion feasibility；
- 路径冲突硬校验；
- 可解释 deadlock 报告；
- 更可信的 physical execution schedule。

## 5. 任务级工艺参数

需要补齐：

- 每个 task 的协议名或 method ID。
- `duration` 是否只表示设备运行，还是包含 setup/loading/unloading。
- 前置 setup、预热、清洗、换枪头、换液、扫码是否需要独立动作。
- 同设备不同协议之间的切换时间。
- 同设备不同温度之间的恢复/冷却/清场时间。
- 任务是否可中断。
- 任务是否必须连续执行。
- 任务是否允许等待在设备内。

为什么需要：

- 当前 task duration 已按分钟转秒硬建。
- 但上下料、setup、清洗如果未独立表达，会影响设备真实占用。
- 若这些时长已包含在 duration 中，又重复建模会使排程过保守。

补齐后可升级：

- setup interval；
- protocol transition cost；
- task-command 精确对齐；
- 设备运行和设备占用分离建模。

## 6. 时间窗、优先级和目标函数

需要补齐：

- `maxWaitTime` 是否按任务配置为硬约束、软约束或仅 audit。
- 超过 `maxWaitTime` 的惩罚函数。
- 样本优先级。
- 任务优先级。
- deadline 或最晚完成时间。
- 插单规则。
- 多板同时竞争同设备时的业务优先级。
- P1/P2/P3 是否只限制开始时间，还是某些节点另有完成顺序要求。

为什么需要：

- 当前已确认 P1/P2/P3 是分路首任务开始优先级，不是互斥选择。
- `maxWaitTime` 当前不能默认硬建，因为真实运行存在违反。
- 若业务上要惩罚超时，需要明确目标函数，而不是混进硬可行性。

补齐后可升级：

- soft max-wait penalty；
- deadline penalty；
- weighted objective；
- online replanning stability cost。

## 7. 建议平台导出字段 Schema

### 7.1 初始物料

```json
{
  "stock_item_id": "stock-001",
  "plate_id": "plate-001",
  "barcode": "BC001",
  "material_code": "sample",
  "material_name": "样本1",
  "quantity": 1,
  "quantity_unit": "plate",
  "volume_ul": 100.0,
  "concentration": null,
  "initial_device_name": "StackRobotA",
  "initial_position_id": "StackRobotA:rack1:slot1",
  "rack": "rack1",
  "level": 1,
  "well": "A1",
  "available_from_seconds": 0
}
```

### 7.2 物料边

```json
{
  "edge_id": "edge-001",
  "src_node_id": 12,
  "dst_node_id": 13,
  "src_task_id": 10012,
  "dst_task_id": 10013,
  "plate_id": "plate-001",
  "material_code": "sample",
  "quantity": 8,
  "quantity_unit": "well",
  "operation": "transfer",
  "consume_rule": "move",
  "produces_waste": false,
  "waste_material_code": null
}
```

### 7.3 设备位置

```json
{
  "position_id": "CytomatA:rack1:slot01",
  "device_name": "CytomatA",
  "kind": "incubator_slot",
  "capacity": 1,
  "can_input": true,
  "can_output": true,
  "reachable_by_robot": ["StackRobotA"],
  "coordinate_frame": "lab",
  "pose": {"x": 0.0, "y": 0.0, "z": 0.0, "rx": 0.0, "ry": 0.0, "rz": 0.0}
}
```

### 7.4 设备指令模板

```json
{
  "task_node_id": 13,
  "template_id": "Smart8A_spread_plate",
  "commands": [
    {"kind": "pick", "resource": "StackRobotA", "duration_seconds": 30},
    {"kind": "move", "resource": "StackRobotA", "duration_seconds": 120},
    {"kind": "place", "resource": "StackRobotA", "duration_seconds": 30},
    {"kind": "device_run", "resource": "Smart8A", "duration_source": "task.duration"},
    {"kind": "pick", "resource": "StackRobotA", "duration_seconds": 30}
  ]
}
```

## 8. 补数后的建模升级顺序

建议按以下顺序推进：

1. 先确认 `plate_id/barcode/initial_position/initial_quantity`，把 v4 seed 从 audit 输入升级为真实物理输入。
2. 再确认 `apsLoadingTime/apsUnloadingTime/transferDuration` 与 `duration` 的关系，防止上下料时间 double count。
3. 再确认 `plateOperType/quantityConsumeRule/pushType/quantity_unit`，把边级库存非负升级为完整产消守恒。
4. 再补孔位状态机和机器人动作模板，把 motion monitor 从事后拒绝逐步前移到 CP-SAT 约束。
5. 最后补 Isaac 几何、姿态和路径数据，用于更严格的物理执行验证。

## 9. 当前不能做的假设

在缺少上述字段前，候选脚本和文档都不应声称：

- `devicePosition` 数量等于设备并发 capacity。
- `deviceMaterial.remainingCount` 一定是可硬建初始库存。
- `plateBarcode` 一定是跨 `materialData` 稳定 plate identity。
- `apsLoadingTime` 一定是分钟，也一定不包含在 task duration 中。
- `quantity` 一定是板数或孔数。
- `plateOperType=1/2` 一定分别代表固定进板/出板语义。
- 所有 merge/split 都满足简单数量相加。
- Isaac 当前能证明全局最优。

这些假设只能在字段语义被平台文档、实验人员和运行态数据共同验证后升级。
