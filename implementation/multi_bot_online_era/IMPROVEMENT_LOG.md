# multi_bot_online_era 初始版本

本版本从 `implementation/multi_bot_era` 派生，目标是让 FUTS 进化出可作为
实验室滚动调度器使用的脚本，而不是一次性离线求解脚本。

## 主要变化

- 候选脚本接口改为 `DynamicScheduler(dataset).handle_command(command)`。
- 沙箱会在同一个候选实例上连续发送在线命令，保留内存状态。
- 新增确定性在线场景：初始重排、时间推进、插入 FJSPB jobs、再次重排、
  dispatch 查询。
- 在线场景支持随机种子：`--scenario-seed` 控制插入时间和小规模插入任务模板，
  `--insertion-count` 控制一次 online 评测中的插入信号次数，
  `--inserted-jobs` 控制每次插入 job 数，`--inserted-task-count` 控制每个
  插入 job 的最大 task 数。
- 插入任务表以真实运行时消息形式逐次发送；候选脚本只能通过
  `handle_command(command)` 接收当前信号，不能一次性拿到所有未来插入任务。
- 新增 `scenario_cli.py`，可在不启动 FUTS 的情况下预览 4_experiments 背景下
  某个 seed 生成的插入命令流。
- `scenario_cli.py --emit-command-script` 可以输出由 seed 生成的外部命令发送
  脚本；该脚本可以包含 seed 生成的插入时刻，但候选调度器必须通过命令接口读取
  `insert_time`/`now`，不能在候选代码中硬编码。
- 评分器验证初始和插入后的 schedule，并使用插入后的 makespan 作为主目标。
- 评分增加稳定性扣分，惩罚插入前已存在任务的时间大幅移动和换机。
- 插入后的验证会把初始计划中 `start < insert_now` 的已有任务动态转成 fixed，
  防止候选脚本在重排时中断已经开始执行的任务。
- 多次插入评分采用 rolling plan 覆盖：每次有效重排都会覆盖上一版规划，
  下一次评分基于上一版规划锁定已经开始的任务，禁止用回溯视角重排历史。
- prompt 明确要求 CP-SAT、fixed/non-fixed、`cur_ptr`、任务插入、不中断
  fixed task，以及不能用纯 greedy 或 replay 方式绕过求解。
- prompt 明确要求插入时间是接口值，不允许硬编码 4_experiments 的某个
  `insert_now`、场景 seed、插入 job id 或命令序列长度。
- prompt 明确禁止 retrospective/offline viewpoint：不能假设未来插入事件、
  未来任务表、总插入次数或最终命令流。

## 当前边界

- 这是 FUTS 训练/评估版本，不是生产设备控制器。
- `dispatch_until` 目前只作为候选接口和状态管理要求参与命令流；真实设备下发、
  ACK、失败恢复和数据库写回还需要单独的 runtime layer。
- 插入任务场景由当前数据集确定性生成，后续可以扩展为多插入、多优先级、
  设备故障、已下发任务锁定等 benchmark。
