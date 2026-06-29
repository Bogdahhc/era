# flow_1160_era 改进日志

日期：2026-06-25

> 当前状态索引（2026-06-26 17:10）：下方早期段落保留调研历史，若与本索引冲突，以本索引和第八节为准。
>
> - 当前 IR：`71 tasks / 14 machines / 76 precedence_pairs / 28 branch_groups / 14 branch_priority_pairs`。
> - 真 task 白名单：`{温控模块, 移液工作站, 培养箱, 酶标仪, 挑单克隆仪}`；温控模块 4度/42度/4度 是真实可排程 task。
> - `duration` 正值按计划工艺时长（分钟）转秒；`duration=0` 但有有效 `startTime/endTime` 时用 span 临时兜底，后续应补 `duration_source` 标记。
> - task-bearing 分支默认全执行；P1/P2/P3 只建首 task 开始优先级，不建互斥选择或完成顺序。
> - `minWaitTime` 是硬约束；`maxWaitTime` 是软约束/惩罚项候选，不强制。
> - makespan 参照：最小 CP-SAT `145058s = 40.294h`；真实运行锚点约 `43.1h`；保守串行 smoke 约 `354219s = 98.394h`。
> - v2 重点：`materialData` 板级物料守恒/转移量约束、非 task 物流节点的轻量资源/缓冲占用、rolling/fixed schedule。

本文档记录 `implementation/flow_1160_era`（从 `multi_bot_era` 派生）在把「智能调度系统」项目流程图数据接入 FUTS/ERA 前的调研发现与设计决策。目标是让 FUTS 进化出针对调度系统项目排程的 CP-SAT 求解脚本，第一步做最小 smoke：项目 1160 → FJSPB IR → 跑通 era 框架。

## 目标

把智能调度系统（`http://172.16.223.65:8082`，RuoYi 框架）的项目流程图（flowData）转换成 era 的 FJSPB IR，复用 multi_bot_era 的 FUTS 框架（seed/scorer/executor/search）让 LLM 变异出 CP-SAT 排程脚本。本分支与 multi_bot_era 的区别只在 `problem.py`（数据来源从 SQLite 改为调度系统 HTTP API + flowData 适配），其余文件基本照搬。

## 一、调研日志

### 1. 智能调度系统接口（已验证可拉取）

系统是 Vue + ElementUI SPA，后端 Java SpringBoot（RuoYi 框架，`captchaOnOff/captchaImage/uuid` 是其特征）。

**登录**：算术验证码（非字符码）。
- `GET /api/captchaImage` → `{uuid, img(base64 JPEG), captchaOnOff:'True'}`，图片是算术题（如 `7+9=?`）。
- OCR 识别表达式 → 求值（如 16）→ `POST /api/login {username, password(明文), code, uuid}` → `{code:200, token}`。
- 无 SM2 加密、无 ukey 强制。后续请求带 `Authorization: Bearer <token>`。
- 自动登录已实现于 `/home/hehaochen/les_client.py`：`LES_PWD=*** python3 les_client.py autologin <user>`，密码走环境变量不落盘，token 存 `/tmp/les_token.txt`（约 30 分钟有效）。

**数据接口清单**：

| 接口 | 用途 | 规模 |
|---|---|---|
| `GET /api/material/tool/project/flowData?id=1160` | **项目流程图（节点+连线）** | 127 节点 / 132 连线 |
| `GET /api/material/tool/device/list` | 设备主数据 | 56 台 |
| `GET /api/material/tool/devicePosition/list` | 设备料位/容量/温区/频率 | 262 条 |
| `GET /api/design/proCenter/deviceMaterial/list?projectId=1160` | 项目耗材装载 | 17 条 |
| `GET /api/material/tool/projectNode/list?projectId=1160` | 结果节点（挑菌/酶活/OD） | 24 条 |
| `GET /api/material/tool/projectResult/list` | 检测结果 CSV 索引 | 24 文件 |
| `GET /api/material/tool/devicetype/list`、`deviceSecondaryType/list` | 类型字典 | 28 / 41 |
| `GET /api/material/tool/barcodeManage/list` | 条码规格库 | 366 |
| `GET /api/material/tool/project/list` | 项目列表 | 130 |

> 注：`projectNode` 是流程图里"产出检测结果文件"的节点（24 个，关联 fileId），不是完整流程图节点；完整流程图节点在 `project/flowData`。

### 2. 项目 1160 数据结构（实测）

**flowData（核心）** — `{nodeList:[127], lineList:[132]}`：

- **节点字段**：`{id:'node_X', nodeId:X(数字), nodeType, name, nodeName, top, left, workstationType, workstationTypeName, secondaryType, deviceType, code}`。`id='node_X'` ↔ `nodeId=X` 一一对应。
- **nodeType**：`0`=操作/设备/条件(122)、`1`=判断(3)、`3`=开始、`4`=结束。
- **真 task = 68 个**（`nodeType=0 且 workstationTypeName ∈ {移液工作站, 培养箱, 酶标仪, 挑单克隆仪}`）。
- **非 task**：`GLabHotelRS堆栈`×24（物料源，only-out 上料）、温度条件×3（4度/42度，ws=温控模块）、判断×3（nodeType=1 但**实测单入单出直通，无真分支**）、起止×2。
- **连线字段**：`{from:'node_X', to:'node_Y', label, order, lineType:'Flowchart', nextNodeId, nodeId, logicDirection}`。
- **label/order = 多出边的并行序号**（不是 if/else 分支）；`logicDirection=1` 仅 3 条（判断直通出边）。
- **整体是有向无环偏序图**：25 节点多出度（并行下游）、27 节点多入度（扇入汇聚），靠多入多出表达并行/同步。

⭐ **关键结论：1160 流程图没有真正的条件分支**。所谓"条件判断"节点实测都是单入单出直通。因此新分支**不需要扩展 IR 支持 judge 分支**，直接把 DAG 拓扑展平成 FJSPB jobs/tasks + precedence 即可。

**设备主数据（device/list 56 台）**：

- 1160 用到的 6 个 workstationType 在设备库**都有候选设备**：温控模块 7、移液工作站 4（Smart8A/S8-B/C/D）、培养箱 3（CytomatA/B/培养箱A）、堆栈 1（StackRobotA）、挑单克隆仪 1（QPixA）、酶标仪 2（TecanA/B）。
- 可用约束字段（非空率）：`workstationType`(100%)、`runProtocolType`(1:43/0:13)、`bufferDirection/scanDirection`(44%，恒=1)、`needRobotOpenDoor`(全 False)。
- 几乎空（不可作约束）：`station`/`location`/`specificParameters`/`calibrationExpiry`。

**设备料位（devicePosition 262 条）**：

- **capacity 来源**：device/list 无 capacity 字段，用 devicePosition 按 `deviceName` 聚合的料位数近似（StackRobotA=147、Smart8A=30、CytomatA=21、培养箱A=20…）。
- **温区**：`minTemperature/maxTemperature`（56 料位有，4℃ 区×45 等）→ 温控约束来源。
- **频率**：`minFrequency/maxFrequency`（58 料位，摇床位 200~800rpm）→ 振荡约束来源。

**已知数据缺口**：

- flowData **无 duration 字段**（必须用占位表）。
- 具体设备分配不在 flowData（只有 workstationType 类别，运行时决策；结果 CSV 文件名 `[TecanA]_...` 是回溯实际用机的痕迹）。

### 3. ERA 框架契约（multi_bot_era 探索）

新分支需 8+1 文件：`problem/seed/scorer/prompt/executor/sandbox/mutator/search/cli` + `__init__`。复用共享模块：`implementation.futs`、`implementation.llm`、`implementation.job_shop_era.logger`。

**`dataset["fjspb"]` 目标 schema**（multi_bot_era/problem.py:286-355）：

```
{source_sqlite_file, cur_ptr,
 machines: {<machine_code>: <capacity>},
 jobs: [{job_id, expr_no, expr_name,
         tasks: [{task_id, step_id, name, machines:[候选], nominal_machine,
                  duration, parameters, detail, fixed_start, fixed_end,
                  is_fixed, has_existing_schedule,
                  flags:{odd,put,take,start, electronic_dripping,test,recycle,
                         xrd_dripping,test,recycle}}]}],
 output_schema: {assignments:[{job_id,task_id,machine,start,end}]},
 constraint_contract: [人类可读约束]}
```

- **score = -(makespan + elapsed_seconds/100)**；`WORST_SCORE=-inf`。
- scorer 12 条约束：唯一性 / 候选机∈task.machines / duration 精确(end-start==duration) / fixed 锁定 / non-fixed≥cur_ptr / job 内 task_id 递增 precedence / 容量 / batch 同步 / 化学 dripping-test-recycle 互斥+背靠背 / 温度互斥 / 离心偶数 / 同 expr_no 首任务同步。
- `is_fixed = start_time is not None and start_time < cur_ptr`。
- seed = 故意弱的 CP-SAT 骨架，返回空 assignments（cold-start，root 预期失败）。
- executor 静态安检：必须含 `ortools.sat.python/cp_model/CpModel(/CpSolver(`，反 greedy shortcut。

## 二、设计方案：flow_1160_era

### 文件清单（`/home/era/implementation/flow_1160_era/`）

| 文件 | 处理 | 说明 |
|---|---|---|
| `__init__.py` | 新建 | docstring |
| `problem.py` | **新写** | `fetch_project(pid,token)` + `flow_data_to_fjspb` adapter（核心） |
| `seed.py` | 照搬 | cold-start 骨架不变 |
| `scorer.py` | 照搬 | fjspb 契约一致；MVP flags 全 false → 化学验证自动过 |
| `sandbox.py` | 照搬 | 子进程运行不变 |
| `executor.py` | 改 import | `multi_bot_era`→`flow_1160_era`，类名 MultiBot→Flow1160 |
| `mutator.py` | 改 import | 同上 |
| `search.py` | 改 import | 同上 |
| `cli.py` | 改 import + 默认 dataset | `--dataset` 默认指向 1160 缓存 |
| `prompt.py` | 精简 | 减化学约束，强调单 job 流 precedence |

### problem.py adapter 数据流（flowData → fjspb）

- **A. `fetch_project(project_id, token)`**：拉 flowData + device/list + devicePosition，缓存到 `/home/era/experiments/flow_1160_cache/{project_id}.json`（避免每次登录）。`load_problem` 接受 project_id 或缓存路径。
- **B. 筛 task**：保留 `nodeType=0 且 workstationTypeName ∈ {移液工作站,培养箱,酶标仪,挑单克隆仪}` 的 68 节点。
- **C. 建图**：连线 `from→to`，非 task 节点做传递闭包跳过（如 `4度→42度→转化` 收敛成 `转化` 的入边）。
- **D. 拓扑排序** task → `task_id`（1..68）。
- **E. jobs**：**单 job**（`job_id="proj_1160"`）——实测单连通分量 + 单根，拆分会破坏 precedence 同步点。
- **F. 候选机器**：task 的 `workstationType` → device/list 同 ws 的设备 code 列表。
- **G. machines capacity**：用 devicePosition 按 deviceName 聚合的料位数，缺省 1。
- **H. duration**：占位表 `DEFAULT_DURATION_BY_WS`（移液 1800 / 培养 7200 / 酶标 600 / 挑克隆 1200 / 缺省 900 秒）。⭐ 已知简化。
- **I.** `is_fixed` 全 false、`cur_ptr=0`、`flags` 全 false、`parameters` 空。
- **J. constraint_contract**：精简到 MVP（唯一性 / 候选机 / duration / job 内 precedence / 容量）；化学约束保留文案但 MVP 数据无 flags。

### 三个关键决策

1. **单 job**：实测单连通分量 + 单根，拆分会破坏 precedence 同步点。
2. **duration 占位表**：flowData 无时长；占位仅让 scorer 的 `end-start==duration` 检查通过；因 `score=-(makespan+elapsed/100)`，绝对量级不影响可行性或 FUTS 相对排序。
3. **precedence 用拓扑 task_id 序（MVP）**：scorer 的"job 内 task_id 递增"检查传递性强制无反向边，但对并行兄弟偏弱。MVP 可接受（seed 空返回本就不可行，首个可行节点需 LLM 生成）。强修复（IR 加 `precedence_pairs` + scorer 加 `_validate_explicit_precedence`）留 v2。

## 三、验证步骤

```bash
# 1. 登录拿 token
LES_PWD=*** python3 /home/hehaochen/les_client.py autologin <user>
# 2. smoke（cold-start seed 预期不可行，但不报错）
cd /home/era && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/era \
  python -m implementation.flow_1160_era.cli --mode futs --iterations 0 --no-llm --timeout-seconds 10
# 期望：打印 experiment_dir=，写 nodes.jsonl + best.py，不抛异常
# 3. 手工构造贪心 schedule 喂 validate_schedule，断言 feasible=True（验证 IR 合法）
```

通过判据：步骤 2 不抛异常 + 产出 nodes.jsonl/best.py；步骤 3 打印 `feasible: True`。

## 四、已知简化与风险

**MVP 简化**：duration 占位 / 无化学 flags（全 false）/ precedence 用 task_id 序（并行弱）/ 单 job / is_fixed 全 false / 未用稳定性、batch、温度频率约束。

**风险**：

1. precedence（task_id 序）对 DAG 并行表达弱 → FUTS 可能排出"可行但串行化并行兄弟"的 schedule。seed 空返回本就不可行，首个可行需 LLM，可接受；v2 加 `precedence_pairs`。
2. duration 占位使 makespan 无真实绝对意义（FUTS 相对排序仍有效）。
3. 设备 capacity 用料位数近似（StackRobotA=147 偏大，可能需 cap 上限）。

## 四-补、2026-06-26：接入 projectAllNodeList 真实参数 + 四项修补完成

### 关键发现：真实参数在 projectAllNodeList
`GET /api/material/tool/projectRunning/projectAllNodeList?projectId=<id>` 返回**运行态全部节点**（1160：221 条 = 127 流程节点 × 多板实例），含 flowData 缺失的真实参数：

- `duration`（秒）：真实耗时——复苏培养 45、固体培养 1200、诱导培养 240、挑菌产物 480、转化 5、涂布 20、OD 检测 2
- `temperature`：真实温度——37℃（培养）×28、4℃、42℃（修正了之前 flowData 温度继承只得 4℃ 的错误）
- `frequency`：真实振荡频率 220rpm×19
- `apsLoadingTime`/`priority`/`maxWaitTime`/`deviceName`（运行时实际设备）

`fetch_project` 已拉 allNodeList 并缓存；adapter 按 nodeId 取真实值，占位表/override 仅兜底。

### 四项修补状态
1. ✅ **precedence_pairs**：73 条 task 间显式前后边（flowData 连线传递闭包）+ scorer `_validate_explicit_precedence` 强校验，解决拓扑 task_id 序对并行兄弟表达弱的问题。
2. ✅ **温区约束**：温度优先取 allNodeList.temperature（真实 37/4/42）+ scorer `_validate_temperature_mutex` 通用化（去 muffle/dryer 限制，任一机器不同温度重叠即冲突）。
3. ✅ **真实 duration**：优先取 allNodeList.duration（真实），duration_override.json + 占位表仅兜底。
4. ✅ **频率约束**：devicePosition 频率 → `machine_frequencies`；task 频率优先取 allNodeList.frequency（真实 220）+ scorer `_validate_frequency_match`（频率须在分配机器的频率范围内）。

### 效果
makespan：占位 **51.5 小时**（185400s）→ 真实参数 **9.1 小时**（32817s），排程有了真实意义。端到端 cli smoke 通过（cold-start seed 预期不可行，无异常）。

### 数据限制说明（用户确认）
- 真实 duration/temperature/frequency 全部来自 `projectAllNodeList`（运行态），而非 device/list 的 `occupyTime`/`specificParameters`（这俩字段存在但全空）。
- 方向 `bufferDirection/scanDirection`（44% 填充且恒=1）、开门 `needRobotOpenDoor`（全 False）确无信息，未接入。

## 五、后续扩展（v2+）

- `precedence_pairs` + 显式 precedence 验证（解决并行兄弟弱表达）。
- 真实 duration（从结果 CSV 时间戳反推，或建工艺库）。
- 化学约束（若新项目 flowData 含 flags）。
- 温度/频率约束（接 devicePosition 的 minTemperature/maxTemperature、minFrequency/maxFrequency）。
- 多 job 拆分（若出现多连通分量项目）。
- batch + 稳定性（借鉴 multi_bot_online_era 的 rolling plan + stability penalty）。

## 六、2026-06-26：数据驱动三大修正 + 内置 AI 对接

### 三大修正（运行态数据确凿，非 AI 推断）

1. **duration 单位 = 分钟（非秒）**：实测 `4度`dur=20→实际 1202 秒(20 分)、`复苏`45→2704 秒(45 分)、`挑菌产物`480→28818 秒(8h)、`诱导`240→14400 秒(4h)。problem.py 原把分钟当秒 → makespan 低估 60 倍。已改 `int(float(nd))*60`（allNodeList 真实值）；override/占位表兜底仍为秒。

2. **capacity = 真实并发（非料位数）**：从 all_nodes 同设备同时运行的最大实例数算（运行态实测）。Smart8A=8 / CytomatA=6 / QPixA=2 / TecanA/温控=1。料位数（30/21）是存储位 ≠ 可同时处理的并发数。已用 `dev_capacity_by_name` 替换 `code_to_cap`。

3. **多实例并行 → cumulative scheduling**：同 nodeId 多实例在真实运行中**同设备同时段并行**（涂布A1-A6 8 实例全部 19:00:25→19:16:12 在 Smart8A）。task 加 `required_capacity = 实例数`，scorer 的 capacity 检查从"计数+batch同步"改为 **cumulative**（同设备任意时刻重叠 task 的 required_capacity 之和 ≤ cap）。candidates 过滤掉 cap < required 的机器（涂布 req8 只剩 Smart8A）。实例分布：1×28 / 2×22 / 4×12 / 7×3 / 8×1 / 6×1 / 3×1，**无超容**（inst>cap = 0/68，全部一批搞定）。

4. **minWaitTime / maxWaitTime 单位 = 分钟**（与 duration 同）：minWait=最短静置（涂布 minWait=5）、maxWait=最长可等待（复苏 maxWait=15、固体培养 maxWait=240=4h）。当前 IR 未建模（留 v2 时间窗约束）。

**真实 makespan = 43.1 小时**（155160 秒，2025-12-22 17:05 → 12-24 12:11）。串行上界 104.5h，FUTS 优化目标 ≈ 43h。

### 内置 AI 对接发现（附带）

- 系统 AI（`#/ai/chat`）协议：`POST /ai/conversation/{cid}/message {content,role:USER,targetAgentIds:[...]}` 发消息 + `WS ws://172.16.223.65:8082/api/ai/chat/{cid}?role=user&token=` 收流式（type: message/status/stream/plan）。客户端 `/home/hehaochen/ai_chat.py`。
- **GUI"连接问题"精准定位（2026-06-26 复核）**：8005 服务本身**健康**——GET `/health`=200 `{status:ok,agentId:3,agentName:AI科学家}`；POST `/api/agent/chat` 带完整字段(conversationId/messageId/wsEndpoint)返回 200 `"已接收"`。它是**异步**的：接收请求后通过 wsEndpoint 指定的 WS 回调推送结果。agent3(远干实验Agent/BioAgent-5090)卡在**请求接收后的处理阶段**（LLM/agent 执行）——status=RUNNING 后出占位 stream"正在执行任务"再无实质回复，超时→会话出错。报修方向：查 8005 执行日志（LLM 调用/模型超时/API key）、wsCallbackHost `ws://172.16.223.65:8001/api` 推送是否正常。换 agent7（deepagents/8000）秒回可用。

### 物料流转复核（2026-06-26，修正此前"无数据"判断）

allNodeList 的 `transRelateNode/transVolume` 确实全空，但**流转数据在 `materialData`**：`preNodeId` 给出 **101 条板流转边**（板从来源节点→当前工序，含数量），如 `复苏(12)→涂布(13)×8`、`涂布(13)→进培养箱(214)×36`、`挑菌产物(19)→传代1(20)×14`；另有 `plateOperType`(1=进板×100/2=出板×309)、`pushType`(0×596/1×69)、`quantity`。deviceMaterial/list 也有 `volume/count/putType/rack/startWell`（设备物料装载）。

precedence_pairs 已覆盖节点顺序，物料流转对可行性边际有限，是 **v2 精度增强**（板级物料守恒/转移量约束），**非"无数据可做"**——此前判断记错，已修正。

### minWait/maxWait 时间窗建模（2026-06-26）

数据语义验证（真实排程间隔 vs 字段，48 条有窗口的边）：
- **minWaitTime = 硬约束**（后继须在前驱 end + min_wait 后开始，静置/稳定）：涂布 minWait=5 分→后继 gap 1102/967 秒 ≥300 ✓，仅 1 条边界违反（34/48 在窗口内，1 条 <minWait）。
- **maxWaitTime = 软约束/时效期望**：真实排程 **13/48 违反**（设备排队超时是常态，如 42度→4度 gap108>max60、传代→振荡 gap1558>max900、添加裂解液→预混 gap2592>max120）。不强制，否则大量真实排程会不可行。

建模：
- task 加 `min_wait`（=minWaitTime×60 秒，**硬**）、`max_wait`（=maxWaitTime×60 秒，**软/信息**）。
- scorer `_validate_explicit_precedence` 加 min_wait 硬校验：对 precedence_pairs(a,b)，`b.start >= a.end + a.min_wait`。
- prompt 说明 min_wait 硬、max_wait 软（真实排程常超 max_wait，尽量满足但不强制）。
- 验证：紧贴排程(buf=0)被拒 `min_wait 3->4 violated: need 300s after end, gap 0s`；buf=600 满足 → feasible。
- agent7 机器有 `/.claude/skills/wet-handoff/SKILL.md`（SelfDrivingLab Team v4.3.0），记录 APS 排产 / projectAllNodeList / simulateStatus 流程——是**流程类**权威文档，但不含字段单位语义（字段单位靠运行态数据实测）。
- **业务字段语义可信度优先级**：运行态数据实测 > 工艺人员 > AI/文档。agent3（酶挖掘/实验数据处理）修好后最对口。

## 七、2026-06-26：真 LLM FUTS 暴露「task_id 全序链」bug

### 现象
首次真 LLM FUTS（8 轮，iterations=8 timeout=30s）：LLM **第 1 轮就从空 seed 产出可行 CP-SAT 求解器**（8/8 feasible，模型含 `AddCumulative` + `Minimize(makespan)`，链路完全打通）。但 **makespan=376320s=104.5h=串行上界**，8 轮完全一致，CP-SAT 0 秒返回（视为最优）。

### 根因
best.py 把 prompt 的「Tasks in each job follow increasing task_id precedence」**字面实现成了相邻全序链**：68 个 task 按 task_id 排序后 `model.Add(end[i] <= start[i+1])` 相邻全连（best.py:163-168）。这条链把整个 job 锁成串行，cumulative 允许并行也没用 → makespan 恒为串行上界。

**这不是 LLM 建错，是 prompt/契约的描述缺陷**：「job 内 task_id 递增」本该只是 scorer 的兜底（防反向边），不该进 CP-SAT 模型。真正的并行只该由 `precedence_pairs`（73 条显式边）+ cumulative 决定。

> cold-start smoke（空 seed）看不出此 bug——只有真 LLM 照 prompt 实现才暴露。**跑真 LLM FUTS 的价值正在于此**。

### 修正
prompt.py 明确：task_id 递增**只是兜底，禁止建模成相邻链**；只用 precedence_pairs 作前后约束，并行来自 cumulative。重跑验证 makespan 应从 104.5h 大幅降到接近真实 43h。

### 教训（写进 era_modeling reference）
- scorer 的兜底约束（task_id 递增）和 CP-SAT 要建的约束必须分清，prompt 要显式说「哪些不要建模」。
- 验证建模正确性不能只看 feasible，要看 **makespan 是否在合理量级**（feasible 但=串行上界 = 模型有全序锁死）。

## 八、2026-06-26：分支/物料语义复核 + FUTS 回归验证

### 内置 AI 短问复核（agent7）

长上下文问题会停在占位 stream `正在执行任务，请稍候...`，已修 `scripts/ai_chat.py`：占位文本不再触发提前退出。拆成短问后，agent7 给出的结论与数据驱动判断一致：

- `nodeType=1` 不能仅凭字段推断互斥/可选/循环。项目 1160 的条件判断节点 `123/180/197` 均为单出边，`logicDirection=1,label/order=1`，没有多路 selector 证据。
- task-bearing 多出边分支在 `projectAllNodeList` 均有运行记录，应默认全执行。
- P1/P2/P3 更像分支启动优先级/展示顺序；不应建成互斥选择，也不能强推为完成顺序。
- `duration` 正值应作为计划工艺时长主字段；历史 `startTime/endTime` span 用于校验、异常识别和兜底，不应直接替代正 duration。
- `duration=0` 且存在有效 span 时，可以临时用 span 兜底，但必须进入 QC，建议后续在 task 上写入 `duration_source = planned | span_fallback | missing`。
- `minWaitTime` 可作硬约束；`maxWaitTime` 更适合作软约束/惩罚项，因为真实运行存在超 maxWait 但仍完成。
- `materialData` 应进入 v2 板级物料守恒/转移量约束；只用 `precedence_pairs` 会遗漏流向、quantity、合并/拆分、`plateOperType`、`pushType`。
- 堆栈/进板/退栈/扫码/转运等非 task 物流节点不作为 v1 主 task 可以，但 v2 应保留轻量 resource/buffer/transport 事件，避免完全丢失物流瓶颈。

### 审计验证

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era.audit_modeling \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --solve-minimal --timeout-seconds 30
```

结果：

- raw counts：`127 nodes / 132 lines / 221 all_nodes / 56 devices / 262 positions`
- IR counts：`71 tasks / 14 machines / 76 precedence_pairs`
- branch metadata：`28 branch_groups`，kind 分布 `required_experimental_branches=13 / condition_node=3 / side_effect_or_material_branch=12`
- `branch_priority_pairs=14`
- runtime capacities：`TemperatureModuleA=1, Smart8A=8, CytomatA=6, QPixA=2, TecanA=1`
- duration fallback：6 个 `duration=0` task 使用 span 兜底（进/回培养箱与添加诱导剂）
- conservative serial smoke：`354219s = 98.394h`
- minimal CP-SAT：`OPTIMAL objective=145058s = 40.294h`，scorer validate 通过

### Reference candidate smoke

命令在 `/home/hehaochen` 下运行，使 `experiments/` 写入可写目录：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --mode futs --iterations 0 --timeout-seconds 30 --no-llm \
  --initial-code /home/era/implementation/flow_1160_era/reference_cpsat_candidate.py \
  --experiment-name flow1160_reference_candidate_smoke_20260626
```

结果目录：`/home/hehaochen/experiments/flow1160_reference_candidate_smoke_20260626`

结果：root reference candidate feasible，`makespan=145058`，`best_score=-145058.01468518126`。

### 真 LLM FUTS 2 轮验证

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/flow1160_pycache PYTHONPATH=/home/era \
python -m implementation.flow_1160_era.cli \
  --dataset /home/era/experiments/flow_1160_cache/1160.json \
  --mode futs --iterations 2 --timeout-seconds 60 \
  --experiment-name flow1160_llm_futs_2iter_20260626_net
```

结果目录：`/home/hehaochen/experiments/flow1160_llm_futs_2iter_20260626_net`

节点结果：

| node | parent | feasible | makespan | score | 说明 |
|---:|---:|---|---:|---:|---|
| 0 | - | false | - | -inf | cold-start skeleton，missing assignments，预期失败 |
| 1 | 0 | true | 145058 | -145058.02509055837 | LLM 从空 seed 生成完整 CP-SAT，达到最小 CP-SAT 量级 |
| 2 | 1 | true | 145058 | -145058.02471786327 | 继续保持最优量级，runtime 略优 |

候选代码检查：

- node1/node2 均使用 `AddCumulative`、`precedence_pairs`、`branch_priority_pairs`。
- 未发现按相邻 `task_id` 建全 job 全序链的旧 bug。
- `end_vars <= start_vars` 命中来自温度互斥条件排序，不是 job 串行化。

结论：当前 prompt/scorer/IR 已能让 LLM FUTS 从 cold-start 生成可行 CP-SAT 解，并稳定落在 `145058s = 40.294h` 最优量级，修复了此前 `104.5h` 全序链问题。

### 后续补齐项

1. 给 task 增加 `duration_source`，区分 `planned`、`span_fallback`、`missing/default`，并让 audit 输出 QC 统计。
2. 把 `materialData` 解析成 v2 `material_edges`，至少包含 `from_node_id/to_node_id/quantity/plateOperType/pushType/materialName/barcodeName`。
3. 为堆栈/进板/退栈/扫码/转运等非 task 节点建立轻量物流事件，后续接 robot/buffer/stack capacity。
4. 加自动回归测试：固定 `71/76/28/14` 计数、minimal CP-SAT `145058`、reference candidate smoke，以及 capacity/min_wait/branch_priority 负例。
5. 长跑 FUTS 可在当前 2 轮 smoke 之后进行，重点观察是否能在不同 LLM 变异中持续避免全序链和 greedy fallback。

## 参考文件

- `/home/era/implementation/multi_bot_era/problem.py`（fjspb schema、`_load_sqlite_fjspb`、`_summarize_fjspb`）
- `/home/era/implementation/multi_bot_era/scorer.py`（`validate_fjsp_schedule` 契约）
- `/home/era/implementation/multi_bot_era/executor.py`（`_uses_cp_sat` / `_disallowed_solver_shortcut`）
- `/home/hehaochen/les_client.py`（token 来源、autologin 模式）
- `/home/hehaochen/proj1160_flowData.json`、`devices_1160_full.json`、`device_positions.json`（已缓存的 1160 数据）

> (注：部分调研结论由 AI 辅助分析接口与数据结构得出，请结合实际复核。）
