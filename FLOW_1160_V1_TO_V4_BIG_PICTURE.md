# ERA 1160 Scheduling: V1 to V4 Big Picture

本文用于讲清楚项目 1160 从智能调度平台到 ERA/FUTS 排程模型的整体逻辑，以及 `flow_1160_era` 到 `flow_1160_era_v4` 的建模演进。这里不记录具体实验结果数值；重点是数据怎样进入项目、依赖关系怎样还原、约束怎样被分层满足、每个版本解决了什么问题。

## 1. 一句话概括

项目 1160 的排程工作不是手工写一张固定甘特图，而是把智能调度平台中的流程图、运行态节点、设备、孔位、物料流和边界字段转换成 FJSPB/CP-SAT 可求解的 IR，再由 FUTS 生成和改进候选求解脚本；v4 进一步把“整张流程图排一次”改成“1 个或 n 个培养皿/培养板作为初始输入，展开成多个共享设备资源的实验实例”。

## 2. 系统数据怎样进入 ERA

数据源来自智能调度平台：

- 平台地址：`http://172.16.223.65:8082`
- 登录方式：RuoYi 算术验证码登录，验证码是算术题，不是字符 OCR。
- token：登录后以 Bearer token 请求接口，临时 token 存在 `/tmp/les_token.txt`。
- 本地缓存：`/home/era/experiments/flow_1160_cache/1160.json`

核心接口分成几类：

- 流程图：`/api/material/tool/project/flowData?id=1160&language=cn`
- 运行态全部节点：`/api/material/tool/projectRunning/projectAllNodeList?projectId=1160`
- 设备主数据：`/api/material/tool/device/list`
- 设备孔位/料位：`/api/material/tool/devicePosition/list`
- 项目设备物料装载：`/design/proCenter/deviceMaterial/list?projectId=1160`
- 条码、物料目录、设备运行状态等辅助接口：用于 v3/v4 的真实化 audit 和后续硬约束升级候选。

进入 ERA 的关键转换入口是各版本的 `problem.py`。它把平台 JSON 转成 `dataset["fjspb"]`，也就是候选脚本和 scorer 都能理解的调度 IR。后续版本并不推翻前一版，而是在同一个 IR 上追加更真实的物料、物流、设备指令和 seed-specific 层。

## 3. 平台字段语义怎样确认

1160 的建模原则是“字段语义必须数据驱动验证”，不能只看字段名猜含义。已经确认的关键语义如下：

- `duration` 的单位是分钟，进入 CP-SAT 前统一乘以 60 转成秒。
- 设备 `capacity` 表示真实并发处理能力，不等于 `devicePosition` 的孔位/料位数量。
- 同一个 `nodeId` 在 `projectAllNodeList` 中出现多条，表示同一工序的多实例并行批处理，应建成 cumulative demand，而不是去重成一个普通任务。
- `minWaitTime` 是硬下界，后继任务必须在前序结束加最小等待后才能开始。
- `maxWaitTime` 是时效信息或 audit/惩罚候选，不默认硬约束，因为真实运行中存在违反。
- 物料流转主要在 `materialData.preNodeId`，不是空的 `transRelateNode`。
- P1/P2/P3 是分路首任务的开始优先级，不是互斥路线，也不是“P1 完成后才能做 P2”。
- `task_id` 是拓扑编号，不是全序工艺链。把所有 task 按编号串起来会把并行流程锁死成线性排程。

这些结论直接决定了 CP-SAT 约束写法：必须用显式 `precedence_pairs`、容量累计约束、分路开始优先级和等待时间，而不是把整张流程图压成单条流水线。

## 4. 核心排程 IR

基础 IR 放在 `dataset["fjspb"]`。核心结构包括：

- `machines`：设备 code 到并发容量的映射。
- `jobs[*].tasks`：可排程任务，包含 `task_id`、候选设备、时长、容量需求、温度、频率、等待时间等。
- `precedence_pairs`：从平台流程图还原出的显式前后依赖。
- `branch_groups` 和 `branch_priority_pairs`：保留 P1/P2/P3 分路结构和开始优先级。
- `machine_frequencies`：设备频率范围，用于摇床类任务兼容性。
- `material_edges`、`material_inventory_events`、`logistics_events`、`buffers`、`rolling_state`：v2 起追加的真实化调度层。
- `device_commands`、`positions`、`plate_states`、`robot_resources`：v3 起追加的设备指令和物理资源层。
- `seed_instance`：v4 起追加的初始培养皿/培养板实例层。

候选脚本的输出仍以 task assignment 为主：

```python
{"assignments": [{"job_id": ..., "task_id": ..., "machine": ..., "start": ..., "end": ...}]}
```

v3/v4 还要求返回或显式建模 `command_assignments`，避免候选只给一个任务级甘特图却绕过设备指令和物理冲突校验。

## 5. 依赖关系怎样被满足

依赖关系分三层恢复。

第一层是流程图依赖。`flowData.lineList` 给出节点连线，非 task 节点会被穿透，最终得到 task 到 task 的 `precedence_pairs`。候选 CP-SAT 必须添加：

```python
start[dst] >= end[src]
```

第二层是等待时间。对有 `min_wait` 的前序任务，后继必须满足：

```python
start[dst] >= end[src] + min_wait[src]
```

第三层是物料依赖。`materialData.preNodeId` 解析成 `material_edges`。当物料边明确存在 `src_task_id` 和 `dst_task_id` 时，它可以作为 hard precedence 的补充；当数量和 key 足够明确时，v2 进一步生成 `material_inventory_events`，候选用 `AddReservoirConstraint` 表达边级库存非负。

重要边界是：目前不把缺少稳定库存 ID、初始位置和完整产消规则的字段升级为硬守恒。完整 merge/split 平衡、初始库存总量、板位入出库方向和稳定 plate identity 仍需要平台提供更明确字段。

## 6. 设备、孔位和负载约束怎样被满足

设备约束分为“处理能力”和“物理位置”两类。

设备处理能力来自 `machines`，本质是同时运行容量。CP-SAT 用 `AddCumulative` 或容量为 1 时的 `AddNoOverlap` 表达：

- 每个任务只分配到一个 eligible machine。
- 任务时长必须精确等于平台计划时长。
- 同一设备任意时刻的 `required_capacity` 之和不能超过 `machines[machine]`。
- 任务频率必须落在设备 `machine_frequencies` 范围内。
- 同设备重叠运行时温度必须兼容。

孔位/料位来自 `devicePosition`，但不能直接当成设备并发 capacity。它们在 v2/v3/v4 中主要用于：

- buffer 容量候选；
- 设备初始装载 audit；
- 有 `plateBarcode` 的初始板位候选；
- 后续 plate position 状态机的输入字段。

v4 中“初始原料对排程的影响”通过 `seed_instance` 的负载字段暴露：

- `required_initial_materials`
- `initial_device_loads`
- `initial_position_loads`
- `load_parameter_bindings`
- `load_compatibility_report`

这些字段让候选脚本知道某份初始培养板/培养皿对应哪些设备装载、孔位、rack、well、barcode 或数量信息。默认情况下，它们仍是 audit/context，只有 seed 明确声明稳定库存身份、数量和初始位置时，才可升级为硬初始库存或硬占位约束。

## 7. 版本演进

### v1：把平台流程图变成可排程 FJSPB

目录：`/home/era/implementation/flow_1160_era`

v1 的核心目标是跑通“平台数据到 FUTS”的闭环：

- 从 `flowData`、`projectAllNodeList`、`device/list`、`devicePosition/list` 构建 `dataset["fjspb"]`。
- 识别真正需要排程的 task：温控模块、移液工作站、培养箱、酶标仪、挑单克隆仪等。
- 还原显式 precedence、P1/P2/P3 分路开始优先级、真实 duration、设备 capacity、required capacity、温度和频率。
- 修正早期“把 task_id 当全序链”的问题，让并行 DAG 真正保留并行空间。
- scorer 用客观硬约束校验候选 assignments，目标是最小化 makespan，同时用运行耗时作很小的 tie-break。

v1 解决的是“平台流程图可以被求解器理解，并且不会被错误串行化”。

### v2：加入物料、物流、buffer 和 rolling 边界

目录：`/home/era/implementation/flow_1160_era_v2`

v2 不改变 v1 的任务级输出契约，而是在 IR 中追加真实运行层：

- `material_edges`：从 `materialData` 规范化板级物料边。
- `material_inventory_events`：能确认来源、目标和数量的边级库存事件。
- `logistics_events`、`logistics_resources`、`buffers`：表达堆栈、进出板、转运和 buffer 容量。
- `rolling_state`：为固定前缀、在线重排和已有设备占用准备接口。
- `constraint_realization_boundaries`：把 hard-ready、audit-only、blocked_missing_fields 分开，避免候选私自把不可靠字段硬建。

v2 还定下 strict cold-start 规则：候选默认看不到历史 `startTime/endTime`、历史实际设备选择和历史运行 span。物流如果没有独立规划时长，在 strict 模式下只作为拓扑/precedence，不用历史 span 猜移动耗时。

v2 解决的是“排程不只看工序，还能表达物料流、物流资源和可落地边界，同时避免历史 replay”。

### v3：加入设备指令和物理仿真可行性入口

目录：`/home/era/implementation/flow_1160_era_v3`

v3 的目标是从 task-level 甘特图迈向设备执行层：

- 新增 `device_commands`：设备运行、物流拓扑等指令级事件。
- 新增 `positions`、`plate_states`、`robot_resources`、`command_templates`。
- executor 要求候选读取 command IR 并返回非空 `command_assignments`，拒绝 task-only 伪 v3。
- 新增 `platform_realism_sources`，集中暴露设备物料装载、条码目录、物料目录、孔位 barcode、设备运行态等真实化字段。
- 新增设备转移时间矩阵，按源设备和目标设备条件化约束物流转移时间，而不是把物流 gap 压成一个常数。
- Isaac/motion monitor 作为物理可行性后盾：发现冲突或死锁时，候选不能被当成可执行排程。

v3 的关键边界是保守：`apsLoadingTime`、`deviceMaterial`、`plateBarcode` 等字段在语义未验证前只做 audit 或假设 profile，不默认硬建，避免重复计时或伪造库存。

v3 解决的是“排程结果要逐步面向设备指令和物理执行，而不是只在任务层看起来可行”。

### v4：从整图排程改成 seed-specific 多培养板实例排程

目录：`/home/era/implementation/flow_1160_era_v4`

v4 是一次方向校正：初始输入不应抽象成“整张 1160 流程图默认全部执行一次”，而应是 1 个或 n 个物理培养皿/培养板。每份初始原料都要遍历自己的任务/物料流程，但设备、机器人、buffer、孔位等资源共享。

v4 新增：

- `default_seeds/sample1_enzyme_activity.json`
- `default_seeds/multi_dish_3_enzyme_activity.json`
- `seed_instance.py`

`seed_instance` 表达：

- `seed_id`
- `initial_units`
- `initial_materials`
- `target_outputs`
- `selected_task_ids`
- `selected_material_edges`
- `material_traversals`
- `required_initial_materials`
- `initial_device_loads`
- `initial_position_loads`
- `load_parameter_bindings`
- `load_compatibility_report`
- `flow_parallelism_hints`
- `plate_instances`
- `seed_realization_boundaries`

多培养板展开时，每个 plate 获得自己的任务实例和 `expr_no`，但不复制设备资源。这正是排程优化的来源：某一份原料的 x 阶段结束释放设备后，该设备可以参与另一份原料的 y 阶段；只要显式 precedence、设备容量、机器人资源、孔位容量和 motion monitor 不冲突，就不应被线性全序锁住。

v4 解决的是“用多个真实初始培养板验证排程是否真的有并行优化空间，并为 FUTS/CP-SAT 最优性证明提供 seed-specific benchmark”。

## 8. FUTS 在这里做什么

FUTS 不直接输出一个手写答案，而是搜索候选 Python 求解脚本。根节点默认是弱的 cold-start CP-SAT skeleton，通常会失败；子节点由 LLM 根据 IR、prompt、父节点反馈和 scorer 错误生成更完整的 CP-SAT 脚本。

候选脚本必须：

- 读取 `dataset["fjspb"]`，不能硬编码某次答案。
- 建立 OR-Tools CP-SAT 模型。
- 从 solver 变量值导出 assignments。
- 显式建模当前版本要求的 hard-ready 约束。
- 不使用历史运行时间或历史设备选择来 replay。
- 不用完整 greedy/list schedule 固定变量后伪装成 CP-SAT。

executor 负责候选代码静态/运行时门禁，例如必须使用 CP-SAT、必须读取 v2/v3/v4 的新增字段、必须返回版本要求的输出面。scorer 负责客观可行性和目标评分。

## 9. CP-SAT 松弛证明的作用

除了 FUTS 搜索，还保留独立证明脚本，例如：

- `/home/era/scripts/prove_flow1160_v2_seed_optimal.py`
- `/home/era/scripts/prove_flow1160_v4_relaxed_optimal.py`

这些脚本不使用 FUTS 候选代码，而是直接从 IR 构造一个松弛 CP-SAT 模型。松弛模型通常保留：

- task duration；
- eligible machine；
- explicit precedence；
- min wait；
- branch priority；
- machine capacity；
- material/logistics topology；
- 条件化设备转移时间矩阵。

如果松弛模型的下界与某个可行候选上界相等，说明在该 IR、seed、history-policy 和 relaxation 口径下，makespan 已经达到全局最优。需要注意：这不是 Isaac/command/真实机器人路径层的完整最优性证明，而是 task-level 加当前 hard-ready 转移/容量约束下的证明。

## 10. Isaac / motion 可行性定位

Isaac 或 motion monitor 不是用来证明最优性的，而是用来防止“数学排程可行但物理执行冲突”的结果进入可行集。v4 的原则是：

- 没有死锁；
- 没有资源冲突；
- 设备、机器人、孔位占用不互相打架；
- 多个上游物流可以同时以 P1 优先级导入某设备，但必须受资源容量和运动冲突约束；
- 产物和废料可以同时从某设备走出，但必须有合法的 command、position、robot 资源解释。

因此 Isaac/motion 层是硬可行性门槛，不是用来缩短 makespan 的优化器。

## 11. 当前边界和后续需要的数据

当前 hard-ready：

- task 级 duration、eligible machine、capacity、frequency、temperature；
- explicit precedence、min_wait、branch start priority；
- 明确来源/目标的 material precedence；
- 边级库存非负；
- 有明确资源/容量的 logistics/buffer 约束；
- strict cold-start 下可确认的 rolling occupancy；
- v4 seed 明确声明的初始培养板实例展开。

当前 audit-only 或 blocked：

- `apsLoadingTime/apsUnloadingTime` 的单位和是否包含在 task duration 中；
- `deviceMaterial` 是否可作为稳定初始库存；
- `devicePosition.plateBarcode` 是否是跨物料流的稳定 plate identity；
- 完整 merge/split 数量守恒；
- 初始库存总量和初始位置；
- 孔位入/出方向和机器人路径姿态；
- 完整 Isaac 几何路径、避障和真实移动时间。

要把这些升级成硬约束，平台至少需要导出稳定 stock/plate ID、初始数量、初始位置、明确消耗/复制/分流规则、from/to position、独立 transfer/setup duration 或路径速度模型。

## 12. 常用入口

v4 audit：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.audit_v4 \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160
```

v4 reference candidate smoke：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --mode futs --iterations 0 --timeout-seconds 120 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era_v4/reference_v4_cpsat_candidate.py \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160
```

v4 cold-start FUTS 应省略 `--initial-code`：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era_v4.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --mode futs --iterations 10 --timeout-seconds 600 \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160
```

v4 松弛证明：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_v4_pycache PYTHONPATH=/home/era \
python /home/era/scripts/prove_flow1160_v4_relaxed_optimal.py \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --seed /home/era/implementation/flow_1160_era_v4/default_seeds/multi_dish_3_enzyme_activity.json \
  --history-policy strict_cold_start \
  --boundary-profile conservative --boundary-seed 1160 \
  --known-upper-bound <feasible_candidate_makespan> \
  --include-machine-capacity \
  --logistics-mode conditional \
  --timeout-seconds 600 --workers 8
```


