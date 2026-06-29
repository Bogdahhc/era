# flow_1160_era_v2 真实化数据需求

日期：2026-06-29

## 内置 AI 查询状态

- 已刷新平台 token，并分别询问 agent7 / agent3。
- 长问题 WebSocket 与 `/ai/conversation/{cid}/messages` 多数只返回 `正在执行任务，请稍候...`。
- 改用短句后有可用返回：
  - `quantityConsumeRule=1`：AI 回答“不确定”。
  - `prePlateNums 是数量还是来源板标签`：AI 回答“标签”。
  - `plateOperType=1和2`：AI 读取通用湿实验文档，未给出可验证枚举。
- 下面结论以本地缓存的项目 1160 平台字段实测为主，AI 只作为交叉验证。

## 项目 1160 字段实测

- `materialData` 共有 `665` 条 material rows / data items。
- `quantityConsumeRule`：`1` 出现 `36` 次，其余 `629` 条缺失；平台 AI 未确认含义，不能硬编码为全量/部分/复制。
- `plateOperType`：`2` 出现 `309` 次，`1` 出现 `100` 次，缺失 `256` 次；同一枚举值既可出现在有 `preNodeId` 的流转边，也可出现在外部输入行，不能单独当入库/出库方向。
- `prePlateNums`：非空值是 `质粒板A1`、`产物1`、`挑菌产物板1`、`样本1` 等来源板/产物标签；不是可求和的数值列表。
- 当前 IR 增补 `material_lineage_links` 暴露这些标签，但不把它们用于算术数量守恒。

## 当前已有字段能硬建的约束

### 1. 边级物料库存非负

可用字段：

- `projectAllNodeList[*].materialData[*].data[*].preNodeId`
- `projectAllNodeList[*].nodeId`
- `materialData[*].data[*].quantity`
- `materialData[*].materialCode`
- `materialData[*].barcodeType`
- `materialData[*].data[*].plateAlias`

可硬建：

- 对同时具备 `src_task_id`、`dst_task_id`、正 `quantity` 的物料边，建库存事件：
  - source task end: `+quantity`
  - destination task start: `-quantity`
  - `AddReservoirConstraint(min_level=0)`

当前实现：

- `material_inventory_events`
- `material_lineage_links` 保留 plate label 谱系，但不是数量约束。
- `reference_v2_cpsat_candidate.py` 使用 `AddReservoirConstraint`
- `Flow1160V2Executor` 要求候选包含 `material_inventory_events` 和 `AddReservoirConstraint`

### 2. Buffer/料位容量

可用字段：

- `devicePosition[*].deviceName`
- `devicePosition[*].rack`
- `devicePosition[*].level`
- `devicePosition[*].positionType`
- `devicePosition[*].plateBarcode`
- `devicePosition[*].innerOrOut`

可硬建：

- 以 `deviceName` 聚合 position 数作为容量。
- logistics event 通过 `buffer_ids` 映射到 `buffer:<deviceName>`。
- 对 event interval 加 `AddCumulative(demand=1, capacity=buffer.capacity)`。

当前实现：

- `buffers[*].capacity`
- `logistics_events[*].buffer_ids`
- reference candidate 使用 buffer `AddCumulative`
- executor 要求候选包含 `buffers` 和 `buffer_ids`

### 3. 物流资源互斥

可用字段：

- 非 task 流程节点 `nodeName`
- `workstationTypeName`
- 运行态 `deviceName`
- logistics node 的运行 span

可硬建：

- `audit_no_overlap_candidate` 且 `duration>0/resources非空` 的物流事件：
  - 建固定存在 interval
  - predecessor task end -> logistics start
  - logistics end -> successor task start
  - 按 resource `AddNoOverlap`
  - logistics end 纳入 makespan

## 当前不能硬建完整守恒的部分

### 1. 完整 merge/split 数量平衡

已有字段：

- `quantity`
- `preNodeId`
- `plateOperType`
- `prePlateNums`
- `quantityConsumeRule`
- `order`

缺口：

- 缺少稳定的“源节点总产出量”字段。
- 缺少每个 split 分支的显式分配比例/数量字段。
- `prePlateNums` 和 `quantityConsumeRule` 出现频率有限，不能覆盖全部 material rows。
- merge 场景里多条 rows 可表达多输入，但不能证明每条输入的消耗规则是否为全量消耗、部分消耗、复制、稀释或引用。

结论：

- 只能硬建当前的边级库存非负。
- 完整 merge/split 产消平衡继续保留 audit，直到平台导出更明确字段。

### 2. 初始库存与当前板位

已有字段：

- `devicePosition[*].plateBarcode`
- `devicePosition[*].rack`
- `devicePosition[*].level`
- `devicePosition[*].positionType`
- `devicePosition[*].innerOrOut`
- `materialData[*].data[*].plateInputRack`
- `materialData[*].data[*].plateInputLevel`
- `materialData[*].data[*].plateAlias`
- `materialData[*].barcodeType`

缺口：

- `devicePosition.plateBarcode` 只有物理条码，不直接提供 `materialCode/barcodeType/plateAlias` 映射。
- `plateInputRack/plateInputLevel` 不是全量存在。
- 缺少明确的 `positionId` 或 `(deviceName,rack,level)` 到 material identity 的绑定记录。

结论：

- 可以建 buffer 容量。
- 不能可靠建每种物料的初始库存数量，除非平台补充条码到物料身份的映射。

### 3. 入库/出库方向

可弱推断字段：

- `nodeName` 包含“上料/下料/堆栈”
- `plateOperType`
- `pushType`
- `preNodeId`
- `plateInputRack/plateInputLevel`
- `positionType`

缺口：

- 没有统一的 `movement_direction` 字段。
- `nodeName` 是文本，不能作为硬约束唯一来源。
- `plateOperType/pushType` 未经平台文档确认，不能直接等价为入/出库方向。

结论：

- 当前只把 logistics interval 当作资源占用和 buffer 容量占用。
- 真正的库存入/出方向需要平台显式导出。

## 最小新增/导出 JSON Schema

```json
{
  "material_stock_items": [
    {
      "stock_item_id": "string",
      "project_id": 1160,
      "material_code": "string",
      "barcode_type": "string",
      "plate_alias": "string|null",
      "plate_barcode": "string|null",
      "quantity": 1,
      "quantity_unit": "unit",
      "initial_position": {
        "device_name": "StackRobotA",
        "position_id": 102,
        "rack": 1,
        "level": 1,
        "position_type": 1,
        "inner_or_out": 0
      }
    }
  ],
  "material_flow_events": [
    {
      "event_id": "string",
      "src_node_id": 6,
      "dst_node_id": 7,
      "src_task_id": 1,
      "dst_task_id": 2,
      "stock_item_id": "string|null",
      "material_code": "string",
      "barcode_type": "string",
      "plate_alias": "string|null",
      "quantity": 1,
      "quantity_unit": "unit",
      "flow_role": "produce|consume|transfer|merge_input|merge_output|split_input|split_output|discard",
      "consume_rule": "all|partial|copy|dilute|unknown",
      "source_total_quantity": 1,
      "branch_allocated_quantity": 1
    }
  ],
  "position_occupancy_events": [
    {
      "event_id": "string",
      "node_id": 10,
      "task_id": "integer|null",
      "logistics_event_id": "log_10",
      "stock_item_id": "string",
      "direction": "in|out|move|hold",
      "from_position_id": 102,
      "to_position_id": 103,
      "start_time": "integer|null",
      "end_time": "integer|null",
      "duration": 8
    }
  ],
  "buffer_resources": [
    {
      "buffer_id": "buffer:StackRobotA",
      "device_name": "StackRobotA",
      "capacity": 147,
      "capacity_source": "devicePosition_count",
      "position_ids": [102, 103]
    }
  ]
}
```

## 建模策略

- 已有字段：继续硬建 precedence、边级 reservoir 非负、resource NoOverlap、buffer Cumulative。
- 新增字段到位前：不硬建完整 merge/split 平衡和初始库存守恒，避免伪约束。
- 新增字段到位后：
  - `material_stock_items` 提供初始 reservoir level。
  - `material_flow_events.flow_role/consume_rule/source_total_quantity/branch_allocated_quantity` 提供完整产消平衡。
  - `position_occupancy_events.direction/from/to` 提供 buffer 入出库库存变化。

## 自主设计的真实落地边界

当前 v2 IR 增加 `constraint_realization_boundaries`，作为 FUTS 候选可硬建约束的边界来源。

该边界现在不是静态写死结论，而是由建模接口和随机种子控制：

- CLI/API 参数：
  - `--boundary-profile conservative|seeded_audit|seeded_experimental`
  - `--boundary-seed <int>`
- 默认 `conservative`：生产安全状态，不随机，不放开任何未确认语义。
- `seeded_audit`：用 seed 对 audit 项生成可复现的反馈采样状态，但不变成硬约束。
- `seeded_experimental`：用 seed 对 blocked 项生成可复现实验开关，但 `hard_constraint=false`，只用于 prompt 探索和日志，不允许绕过缺失字段。
- FUTS 候选必须读取 `constraint_realization_boundaries.interface` 和 `constraint_realization_boundaries.state`。

### Hard-ready

这些可以直接建 CP-SAT 硬约束。候选应以 `state.required_hard_constraints` 为准：

- `task_and_material_precedence`：必须有 `src_task_id/dst_task_id/hard_precedence_candidate`。
- `edge_inventory_nonnegative`：必须有 `src_task_id/dst_task_id/quantity/inventory_key`，用 `AddReservoirConstraint`。
- `logistics_resource_no_overlap`：必须有 logistics `duration/resources`，用 interval + `AddNoOverlap`。
- `buffer_capacity`：必须有 `buffer.capacity` 与 `logistics_event.buffer_ids`，用 `AddCumulative`。
- `rolling_existing_occupancy`：只有明确 `machine/start/end/required_capacity` 的 rolling rows 才能作为固定占用 interval。

### Audit-only

这些只能读和记录，不能硬建。候选应以 `state.audit_controls` 为准：

- `plate_lineage_labels`：`prePlateNums/plateAlias/plateNum` 保留谱系，但不做数量求和。
- `quantity_consume_rule_enum`：`quantityConsumeRule=1` 未确认枚举含义，不能推导全量/部分/复制。
- `plate_oper_type_enum`：`plateOperType=1/2` 未确认枚举含义，不能推导入库/出库/转移。

### Blocked Until Platform Exports Fields

这些是剩余真实落地目标，但当前字段不足。候选应以 `state.blocked_controls` 和可选的 `state.experimental_controls` 为非硬约束上下文：

- `full_merge_split_balance`：需要 `flow_role/consume_rule/source_total_quantity/branch_allocated_quantity/loss_or_dilution_policy`。
- `initial_material_stock`：需要 `stock_item_id`、条码到物料身份绑定、初始数量、初始位置。
- `position_in_out_inventory`：需要 `direction/from_position_id/to_position_id/stock_item_id/position occupancy start/end`。
- `plate_identity_no_overlap`：需要全流程稳定的 `stock_item_id` 或 `plate_barcode`。

后续原则：只有 `constraint_realization_boundaries.state.required_hard_constraints` 中 `hard_constraint=true` 的项目可以变成硬约束；`audit_controls`、`blocked_controls` 和 `experimental_controls` 只能作为上下文、日志或后续数据需求，不能被 FUTS 生成脚本私自升级为硬约束。
