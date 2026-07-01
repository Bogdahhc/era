"""Problem loading for smart-scheduling-system project flowData (project 1160).

派生自 multi_bot_era.problem：数据来源从 SQLite 改为调度系统 HTTP API。
把项目流程图 flowData(nodeList/lineList) + device/list + devicePosition
转换成 FJSPB IR（dataset["fjspb"]），供 FUTS 进化 CP-SAT 排程脚本。

已知简化（MVP）：
- flowData 无 duration → 优先用 projectAllNodeList；仅缺运行态字段时用 DEFAULT_DURATION_BY_WS 占位表。
- is_fixed 全 false、flags 全 false（1160 无化学标志位）。
- 单 job（实测 1160 是单连通分量 + 单根）。
- precedence 只用 flowData 显式边经非 task 节点传递后的 precedence_pairs。
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, defaultdict, deque
import copy
import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


DEFAULT_DATASET = "1160"  # 项目 id；也接受缓存文件路径

API_BASE = "http://172.16.223.65:8082/api"
TOKEN_FILE = "/tmp/les_token.txt"
CACHE_DIR = Path("/home/era/experiments/flow_1160_cache")

# 真 task 的 workstationTypeName 白名单。温控模块的 4度/42度 节点有真实设备、
# 时长和温度，且位于开始→转化的前置链路中，必须作为可排程 task。
TASK_WS_NAMES = {"移液工作站", "培养箱", "酶标仪", "挑单克隆仪", "温控模块"}
# duration 占位表（秒）—— flowData 无时长字段，占位仅为让 scorer 的 duration 检查通过
DEFAULT_DURATION_BY_WS = {
    "移液工作站": 1800,
    "培养箱": 7200,
    "酶标仪": 600,
    "挑单克隆仪": 1200,
}
FALLBACK_DURATION = 900

# 真实 duration 覆盖：调度系统未存储操作时长（flowData 无时长字段、结果CSV是检测读数、
# preBook 是设备动作日志无法映射到 task），故提供外部覆盖表让工艺工时可注入。
# 格式: {"<操作名 nodeName 或工位名 workstationTypeName>": 秒数}，优先按 name 精确匹配。
DURATION_OVERRIDE_PATH = Path("/home/era/implementation/flow_1160_era/duration_override.json")


def _load_duration_override() -> dict:
  try:
    return json.loads(DURATION_OVERRIDE_PATH.read_text(encoding="utf-8"))
  except Exception:
    return {}


DURATION_OVERRIDE = _load_duration_override()

# 振荡频率需求覆盖：flowData 无频率字段，按操作名注入（振荡培养等）。
# 默认对含"振荡/摇"的操作名推断 200rpm，可被此处覆盖。
FREQUENCY_OVERRIDE_PATH = Path("/home/era/implementation/flow_1160_era/frequency_override.json")


def _load_frequency_override() -> dict:
  try:
    return json.loads(FREQUENCY_OVERRIDE_PATH.read_text(encoding="utf-8"))
  except Exception:
    return {}


FREQUENCY_OVERRIDE = _load_frequency_override()

_TEMP_RE = re.compile(r"(\d+)\s*度")


def _node_temperature(node: dict) -> int | None:
  m = _TEMP_RE.search(str(node.get("nodeName", "")))
  return int(m.group(1)) if m else None


_EMPTY_FLAGS = {
    "odd": False, "put": False, "take": False, "start": False,
    "electronic_dripping": False, "electronic_test": False, "electronic_recycle": False,
    "xrd_dripping": False, "xrd_test": False, "xrd_recycle": False,
}


@dataclass(frozen=True)
class Flow1160Problem:
  instance_name: str
  description: str
  dataset: dict
  prompt_dataset: dict
  optimum: int | None = None


# ---------- HTTP（内网直连，禁代理）----------
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
urllib.request.install_opener(_opener)


def _token() -> str:
  try:
    return Path(TOKEN_FILE).read_text().strip()
  except FileNotFoundError:
    raise RuntimeError(
        "token 不存在 (%s)，先运行: "
        "LES_PWD=*** python3 /home/hehaochen/les_client.py autologin <user>"
        % TOKEN_FILE
    )


def _api_get(path: str) -> dict:
  req = urllib.request.Request(
      API_BASE + path, headers={"Authorization": "Bearer " + _token()}
  )
  with urllib.request.urlopen(req, timeout=25) as r:
    return json.loads(r.read().decode())


def _api_get_optional(path: str) -> dict:
  try:
    return _api_get(path)
  except urllib.error.HTTPError as exc:
    if exc.code == 404:
      return {"code": 404, "rows": [], "data": []}
    raise


def fetch_project(project_id: str) -> dict:
  """从调度系统拉 project 1160 planning + realism source data."""
  flow = _api_get("/material/tool/project/flowData?id=%s&language=cn" % project_id)
  devices = _api_get("/material/tool/device/list?pageNum=1&pageSize=500")
  positions = _api_get("/material/tool/devicePosition/list?pageNum=1&pageSize=1000")
  all_nodes_resp = _api_get(
      "/material/tool/projectRunning/projectAllNodeList?projectId=%s" % project_id
  )
  device_materials = _api_get_optional(
      "/design/proCenter/deviceMaterial/list?pageNum=1&pageSize=200&projectId=%s" % project_id
  )
  barcode_manage = _api_get_optional("/material/tool/barcodeManage/list?pageNum=1&pageSize=1000")
  barcode_settings = _api_get_optional("/material/tool/barcodesetting/list?pageNum=1&pageSize=500")
  material_settings = _api_get_optional("/material/tool/materialSetting/list?pageNum=1&pageSize=500")
  device_inner_settings = _api_get_optional("/material/tool/deviceInnerSetting/list?pageNum=1&pageSize=500")
  well_global = _api_get_optional("/material/tool/wellGlobal/list?pageNum=1&pageSize=500")
  device_running = _api_get_optional(
      "/design/proCenter/deviceRunning/list?pageNum=1&pageSize=200&projectId=%s" % project_id
  )
  dispatch_queue = _api_get_optional("/openApi/dispatch/nodeIdQueue/list?projectId=%s" % project_id)
  return {
      "project_id": str(project_id),
      "flow_data": flow.get("data", {}) or {},
      "devices": devices.get("rows", []),
      "positions": positions.get("rows", []),
      "all_nodes": all_nodes_resp.get("data", []) or [],
      "device_materials": device_materials.get("rows", []) or [],
      "barcode_manage": barcode_manage.get("rows", []) or [],
      "barcode_settings": barcode_settings.get("rows", []) or [],
      "material_settings": material_settings.get("rows", []) or [],
      "device_inner_settings": device_inner_settings.get("rows", []) or [],
      "well_global": well_global.get("rows", []) or [],
      "device_running": device_running.get("rows", []) or [],
      "dispatch_node_queue": dispatch_queue.get("data", []) or dispatch_queue.get("rows", []) or [],
  }


# ---------- adapter: flowData -> fjspb ----------

def _is_task_node(n: dict) -> bool:
  return str(n.get("nodeType")) == "0" and n.get("workstationTypeName") in TASK_WS_NAMES


def _task_successors(start_id: str, adj: dict, task_id_set: set) -> set:
  """从 task 节点沿非 task 节点 BFS，收集相邻 task 后继（传递闭包跳过条件/物料/判断节点）。"""
  succ = set()
  visited = set()
  queue = deque(adj.get(start_id, []))
  while queue:
    nid = queue.popleft()
    if nid in visited:
      continue
    visited.add(nid)
    if nid in task_id_set:
      succ.add(nid)  # 遇到 task 即作为直接后继，不再深入
    else:
      queue.extend(adj.get(nid, []))
  return succ


def _reachable_tasks_from(start_id: str, adj: dict, task_id_set: set) -> set:
  """Collect first task nodes reachable from an arbitrary flow node."""
  if start_id in task_id_set:
    return {start_id}
  succ = set()
  visited = set()
  queue = deque([start_id])
  while queue:
    nid = queue.popleft()
    if nid in visited:
      continue
    visited.add(nid)
    if nid in task_id_set:
      succ.add(nid)
    else:
      queue.extend(adj.get(nid, []))
  return succ


def _collect_branch_groups(
    nodes: list[dict],
    lines: list[dict],
    adj: dict,
    task_id_set: set,
    node_to_task_id: dict,
    runtime_node_ids: set,
) -> list[dict]:
  """Preserve flow graph branch structure for prompts/audits.

  project 1160 contains both explicit condition nodes and many multi-outgoing
  experimental branches. The current scorer still schedules every task-bearing
  branch because runtime data shows those branches executed, but the IR must
  retain the branch topology so future modeling can distinguish required
  parallel branches from mutually exclusive condition paths.
  """
  node_by_id = {n["id"]: n for n in nodes if "id" in n}
  lines_by_from = defaultdict(list)
  for line in lines:
    if line.get("from") and line.get("to"):
      lines_by_from[line["from"]].append(line)

  groups = []
  for node in nodes:
    node_id = node.get("id")
    outgoing = lines_by_from.get(node_id, [])
    is_condition_node = str(node.get("nodeType")) == "1"
    if len(outgoing) <= 1 and not is_condition_node:
      continue

    branches = []
    task_bearing = 0
    active_task_bearing = 0
    for line in sorted(
        outgoing,
        key=lambda item: (
            item.get("order") if item.get("order") is not None else 999999,
            item.get("label") if item.get("label") is not None else 999999,
            str(item.get("to")),
        ),
    ):
      to_id = line.get("to")
      task_successors = sorted(
          _reachable_tasks_from(to_id, adj, task_id_set),
          key=lambda tid: node_to_task_id.get(tid, 10**9),
      )
      successor_task_ids = [
          node_to_task_id[tid] for tid in task_successors if tid in node_to_task_id
      ]
      successor_step_ids = [
          node_by_id[tid].get("nodeId") for tid in task_successors if tid in node_by_id
      ]
      has_runtime = any(step_id in runtime_node_ids for step_id in successor_step_ids)
      if successor_task_ids:
        task_bearing += 1
        if has_runtime:
          active_task_bearing += 1
      target = node_by_id.get(to_id, {})
      branches.append({
          "to_node_id": target.get("nodeId"),
          "to_name": target.get("nodeName") or target.get("name"),
          "label": line.get("label"),
          "order": line.get("order"),
          "logic_direction": line.get("logicDirection"),
          "successor_task_ids": successor_task_ids,
          "successor_step_ids": successor_step_ids,
          "has_runtime_task_successor": has_runtime,
      })

    if is_condition_node:
      kind = "condition_node"
    elif task_bearing > 1 and active_task_bearing == task_bearing:
      kind = "required_experimental_branches"
    elif task_bearing > 1:
      kind = "possible_conditional_branches"
    else:
      kind = "side_effect_or_material_branch"

    groups.append({
        "from_node_id": node.get("nodeId"),
        "from_name": node.get("nodeName") or node.get("name"),
        "from_task_id": node_to_task_id.get(node_id),
        "node_type": node.get("nodeType"),
        "workstation_type_name": node.get("workstationTypeName"),
        "kind": kind,
        "branch_count": len(branches),
        "task_bearing_branch_count": task_bearing,
        "active_task_bearing_branch_count": active_task_bearing,
        "branches": branches,
    })
  return groups


def _branch_priority_pairs(branch_groups: list[dict]) -> list[dict]:
  """Build pairwise first-task start priority constraints from branch order.

  For project 1160, line order/label corresponds to the P1/P2/P3 priority shown
  in the UI. Runtime data confirms the first task on a lower-numbered branch
  starts no later than the first task on a lower-priority branch.
  """
  pairs = []
  for group in branch_groups:
    rows = []
    for branch in group.get("branches", []):
      successor_task_ids = branch.get("successor_task_ids") or []
      if not successor_task_ids:
        continue
      priority = branch.get("order")
      if priority is None:
        priority = branch.get("label")
      if priority is None:
        continue
      rows.append((int(priority), int(successor_task_ids[0]), branch))
    rows.sort(key=lambda item: (item[0], item[1]))
    for (hi_priority, hi_task_id, hi_branch), (lo_priority, lo_task_id, lo_branch) in zip(rows, rows[1:]):
      if hi_priority == lo_priority:
        continue
      pairs.append({
          "from_node_id": group.get("from_node_id"),
          "from_task_id": group.get("from_task_id"),
          "higher_priority": hi_priority,
          "lower_priority": lo_priority,
          "higher_task_id": hi_task_id,
          "lower_task_id": lo_task_id,
          "higher_to_node_id": hi_branch.get("to_node_id"),
          "lower_to_node_id": lo_branch.get("to_node_id"),
      })
  return pairs


def flow_data_to_fjspb(project: dict) -> dict:
  flow = project.get("flow_data", {})
  nodes = flow.get("nodeList", []) or []
  lines = flow.get("lineList", []) or []
  devices = project.get("devices", [])
  positions = project.get("positions", [])
  project_id = project.get("project_id", "unknown")

  node_by_id = {n["id"]: n for n in nodes if "id" in n}
  task_nodes = [n for n in nodes if _is_task_node(n)]
  task_id_set = {n["id"] for n in task_nodes}

  # 1) 候选机器：workstationTypeName -> 该 ws 的设备 deviceCode 列表
  ws_to_codes = defaultdict(list)
  for d in devices:
    ws = d.get("workstationTypeName")
    code = d.get("deviceCode")
    if ws and code:
      ws_to_codes[ws].append(code)
  for codes in ws_to_codes.values():
    codes.sort()

  # 2) capacity：见下方 dev_capacity_by_name（运行态真实并发）；devicePosition 料位数是存储位、不等于并发，已弃用。

  # 频率能力：devicePosition minFrequency/maxFrequency 按 deviceName 聚合 -> deviceCode
  name_to_freq: dict = {}
  for p in positions:
    pmin, pmax = p.get("minFrequency"), p.get("maxFrequency")
    if pmin is None and pmax is None:
      continue
    dn = p.get("deviceName")
    if not dn:
      continue
    lo, hi = name_to_freq.get(dn, [None, None])
    lo = pmin if lo is None else (min(lo, pmin) if pmin is not None else lo)
    hi = pmax if hi is None else (max(hi, pmax) if pmax is not None else hi)
    name_to_freq[dn] = [lo, hi]
  machine_frequencies = {}
  for d in devices:
    code, dn = d.get("deviceCode"), d.get("deviceName")
    if code and dn in name_to_freq:
      machine_frequencies[code] = name_to_freq[dn]

  # 3) 邻接表 + task 间传递闭包 precedence
  adj = defaultdict(list)
  adj_rev = defaultdict(list)
  for l in lines:
    f, t = l.get("from"), l.get("to")
    if f and t:
      adj[f].append(t)
      adj_rev[t].append(f)

  task_adj = {tid: [] for tid in task_id_set}
  indeg = {tid: 0 for tid in task_id_set}
  seen_edges = set()
  for tid in task_id_set:
    for s in _task_successors(tid, adj, task_id_set):
      if (tid, s) in seen_edges:
        continue
      seen_edges.add((tid, s))
      task_adj[tid].append(s)
      indeg[s] += 1

  # 4) Kahn 拓扑排序 -> task_id
  queue = deque(sorted([t for t in task_id_set if indeg[t] == 0]))
  order = []
  while queue:
    t = queue.popleft()
    order.append(t)
    for s in sorted(task_adj[t]):
      indeg[s] -= 1
      if indeg[s] == 0:
        queue.append(s)
  if len(order) != len(task_id_set):  # 有环或漏，兜底用原顺序
    remaining = [n["id"] for n in task_nodes if n["id"] not in order]
    order.extend(remaining)

  # 5) 温度继承：task 沿入边回溯找最近的温度条件节点（4度/42度 等）
  temp_memo = {}

  def _inherit_temp(tid):
    if tid in temp_memo:
      return temp_memo[tid]
    visited = {tid}
    stack = list(adj_rev.get(tid, []))
    while stack:
      cur = stack.pop()
      if cur in visited:
        continue
      visited.add(cur)
      if cur in task_id_set:
        stack.extend(adj_rev.get(cur, []))
        continue
      t = _node_temperature(node_by_id.get(cur, {}))
      if t is not None:
        temp_memo[tid] = t
        return t
      stack.extend(adj_rev.get(cur, []))
    temp_memo[tid] = None
    return None

  # 真实参数：projectAllNodeList 按 nodeId 取 duration/temperature/frequency（运行态真实值）
  all_nodes = project.get("all_nodes", [])

  def _parse_t(t):
    try:
      return datetime.fromisoformat(str(t).replace("Z", ""))
    except Exception:
      return None

  # ⭐ 真实设备并发容量：从 all_nodes 同设备同时运行的最大实例数（运行态实测值）。
  #    非 devicePosition 料位数（料位数是存储位，不等于可同时处理的并发数）。
  #    实测：Smart8A=8, CytomatA=6, QPixA=2, TecanA/温控=1
  dev_ivs = defaultdict(list)
  for an in all_nodes:
    s, e = _parse_t(an.get("startTime")), _parse_t(an.get("endTime"))
    if s and e and an.get("deviceName"):
      dev_ivs[an.get("deviceName")].append((s, e))
  dev_capacity_by_name = {}
  for dev, ivs in dev_ivs.items():
    events = []
    for s, e in ivs:
      events.append((s, 1))
      events.append((e, -1))
    events.sort()
    cur = mx = 0
    for _, delta in events:
      cur += delta
      mx = max(mx, cur)
    dev_capacity_by_name[dev] = max(1, mx)

  # ⭐ 节点实例数：同一 nodeId 在运行态有几块板/样本（多板并行）。task 占用设备容量数 = 实例数。
  node_instance = Counter(an.get("nodeId") for an in all_nodes if an.get("nodeId") is not None)

  # deviceCode → deviceName 桥接（capacity/frequency 按 deviceName 聚合，候选机器用 deviceCode）
  code_to_name = {d.get("deviceCode"): d.get("deviceName") for d in devices if d.get("deviceCode")}

  node_params = {}
  for an in all_nodes:
    nid = an.get("nodeId")
    if nid is None:
      continue
    p = node_params.setdefault(nid, {})
    for k in ("duration", "temperature", "frequency", "apsLoadingTime", "priority", "minWaitTime", "maxWaitTime"):
      v = an.get(k)
      # Keep explicit zero for temperature/frequency: in allNodeList it means
      # "no requirement", and must not trigger inheritance from upstream
      # condition nodes such as 4度.
      if k in ("temperature", "frequency"):
        if v not in (None, "") and k not in p:
          p[k] = v
      elif v not in (None, "", 0, 0.0) and k not in p:
        p[k] = v

  runtime_span_by_node = {}
  for an in all_nodes:
    nid = an.get("nodeId")
    if nid is None:
      continue
    s, e = _parse_t(an.get("startTime")), _parse_t(an.get("endTime"))
    if not (s and e):
      continue
    span = max(0, int(round((e - s).total_seconds())))
    if span > 0:
      runtime_span_by_node[nid] = max(runtime_span_by_node.get(nid, 0), span)

  # 6) 组装 tasks（单 job）
  tasks = []
  for idx, tid in enumerate(order, 1):
    n = node_by_id[tid]
    ws_name = n.get("workstationTypeName")
    inst = int(node_instance.get(n.get("nodeId"), 1))
    cand_all = list(ws_to_codes.get(ws_name, []))
    # 只保留能容纳该 task 实例数的候选机（required_capacity <= machine capacity）：
    # 实例数高的操作（如涂布8板）只能上高并发机（Smart8A cap8），cap1 机器会被过滤
    candidates = [c for c in cand_all if dev_capacity_by_name.get(code_to_name.get(c), 1) >= inst]
    candidates = candidates or cand_all or ["unknown_workstation"]
    name = n.get("nodeName") or n.get("name") or ""
    nparam = node_params.get(n.get("nodeId"), {})
    nd = nparam.get("duration")
    if nd not in (None, "", 0, 0.0):
      duration = int(float(nd)) * 60  # ⭐ allNodeList 真实值单位是「分钟」→ 秒（实测：4度dur20→1202秒）
    elif n.get("nodeId") in runtime_span_by_node:
      # Some runtime rows store duration=0 for short transfer/liquid-handling
      # actions even though start/end timestamps show a real operation span.
      duration = runtime_span_by_node[n.get("nodeId")]
    else:
      raw = (
          DURATION_OVERRIDE.get(name)
          or DURATION_OVERRIDE.get(ws_name)
          or DEFAULT_DURATION_BY_WS.get(ws_name, FALLBACK_DURATION)
      )
      duration = int(raw) if raw not in (None, "") else FALLBACK_DURATION  # override/占位表已是秒
    if "temperature" in nparam:
      raw_temp = nparam.get("temperature")
      temp = None if raw_temp in (None, "", 0, 0.0, "0") else raw_temp
    else:
      temp = _inherit_temp(tid)
    raw_freq = nparam.get("frequency") if "frequency" in nparam else None
    freq_need = None if raw_freq in (None, "", 0, 0.0, "0") else raw_freq
    freq_need = freq_need or FREQUENCY_OVERRIDE.get(name) or FREQUENCY_OVERRIDE.get(ws_name)
    if freq_need is None and ("振荡" in name or "摇" in name):
      freq_need = 200  # 振荡类默认 200rpm，可被 allNodeList/override 覆盖
    param: dict = {}
    if temp is not None:
      param["temperature"] = temp
    if freq_need is not None:
      param["frequency"] = int(freq_need)
    parameters = [{"param": param}] if param else []
    tasks.append({
        "task_id": idx,
        "step_id": n.get("nodeId"),
        "step_index": idx,
        "name": name,
        "machines": candidates,
        "nominal_machine": candidates[0],
        "scheduled_machine": None,
        "next_scheduled_machine": None,
        "duration": int(duration),
        "required_capacity": inst,  # 多板并行：占设备容量数=实例数
        "min_wait": int(float(nparam.get("minWaitTime") or 0) * 60),  # 最短静置(秒,硬约束)：后继须等待
        "max_wait": int(float(nparam.get("maxWaitTime") or 0) * 60),  # 时效窗口(秒,软约束/期望)：后继宜在此内开始
        "parameters": parameters,
        "detail": "",
        "fixed_start": None,
        "fixed_end": None,
        "is_fixed": False,
        "has_existing_schedule": False,
        "flags": dict(_EMPTY_FLAGS),
    })

  # machines：只保留 task 涉及候选机；capacity 用真实并发（运行态实测），非料位数
  machines = {}
  for t in tasks:
    for code in t["machines"]:
      if code not in machines:
        machines[code] = dev_capacity_by_name.get(code_to_name.get(code), 1)

  job = {
      "job_id": "proj_%s" % project_id,
      "expr_no": "proj_%s" % project_id,
      "expr_name": "flow_%s" % project_id,
      "tasks": tasks,
  }

  # task 间显式 precedence（来自 flowData 连线传递闭包），供 scorer 强校验并行兄弟
  node_to_task_id = {nid: idx for idx, nid in enumerate(order, 1)}
  precedence_pairs = sorted(
      [[node_to_task_id[a], node_to_task_id[b]] for (a, b) in seen_edges
       if a in node_to_task_id and b in node_to_task_id]
  )
  runtime_node_ids = {
      an.get("nodeId") for an in all_nodes if an.get("nodeId") is not None
  }
  branch_groups = _collect_branch_groups(
      nodes,
      lines,
      adj,
      task_id_set,
      node_to_task_id,
      runtime_node_ids,
  )
  branch_priority_pairs = _branch_priority_pairs(branch_groups)

  return {
      "source_sqlite_file": "smart_scheduling_project_%s" % project_id,
      "cur_ptr": 0,
      "machines": machines,
      "machine_frequencies": machine_frequencies,
      "precedence_pairs": precedence_pairs,
      "branch_groups": branch_groups,
      "branch_priority_pairs": branch_priority_pairs,
      "jobs": [job],
      "output_schema": {
          "assignments": [
              {"job_id": "string", "task_id": "integer 1..N",
               "machine": "one candidate machine code",
               "start": "integer >= 0", "end": "integer start + duration"}
          ]
      },
      "constraint_contract": [
          "Each (job_id, task_id) appears exactly once.",
          "Assigned machine must be in task.machines.",
          "Tasks connected by precedence_pairs [a,b] MUST satisfy assignment(a).end <= assignment(b).start (explicit edges from flow graph, overrides task_id ordering for parallel siblings).",
          "branch_groups preserves graph branch structure. For project 1160, task-bearing experimental branches are required unless branch metadata is explicitly extended with a mutually exclusive condition selector.",
          "branch_priority_pairs restores UI P1/P2/P3 route priority: the first task of a higher-priority branch must start no later than the first task of the next lower-priority branch.",
          "Non-fixed tasks start at or after cur_ptr.",
          "Machine capacity comes from machines[machine] (real per-device concurrency, not slot count).",
          "Cumulative capacity: at any instant, the sum of task.required_capacity of tasks running on the same machine must be <= machines[machine]. A multi-well task occupies instance_count slots (e.g. coating 8 plates -> required_capacity=8).",
          "(Chemistry / temperature / centrifuge constraints are listed for parity; this project's tasks carry no such flags in MVP.)",
      ],
  }


# ---------- 摘要（进 prompt，不泄露非 fixed incumbent；本分支无 incumbent）----------

def _summarize_fjspb(fjspb: dict) -> dict:
  jobs = fjspb["jobs"]
  task_count = sum(len(j["tasks"]) for j in jobs)
  route_counter = Counter(
      tuple(t["machines"]) for j in jobs for t in j["tasks"]
  )
  return {
      "problem_type": "flow_proj_fjspb",
      "job_count": len(jobs),
      "task_count": task_count,
      "machine_count": len(fjspb["machines"]),
      "cur_ptr": fjspb["cur_ptr"],
      "machine_route_patterns": [
          {"count": c, "machines": list(m)} for m, c in route_counter.most_common(12)
      ],
      "special_constraint_counts": {k: 0 for k in _EMPTY_FLAGS},
      "machine_capacity_sample": dict(list(fjspb["machines"].items())[:20]),
      "sample_jobs": [
          {**j, "tasks": j["tasks"][:12]} for j in jobs[:3]
      ],
  }


# ---------- load ----------

def load_problem(dataset_path: str = DEFAULT_DATASET) -> Flow1160Problem:
  path = Path(dataset_path)
  if path.exists():  # 直接给缓存文件路径
    project = json.loads(path.read_text(encoding="utf-8"))
    project_id = project.get("project_id", path.stem)
  else:  # 当作 project_id
    project_id = str(dataset_path)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / ("%s.json" % project_id)
    if cache_file.exists():
      project = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
      project = fetch_project(project_id)
      cache_file.write_text(
          json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8"
      )

  fjspb = flow_data_to_fjspb(project)
  dataset = {"fjspb": fjspb}
  summary = _summarize_fjspb(fjspb)
  num_tasks = summary["task_count"]
  num_machines = summary["machine_count"]
  description = (
      "Schedule smart-scheduling-system project %s flowData. " % project_id
      + "It has %d schedulable operations across a single job and %d candidate machines. " % (num_tasks, num_machines)
      + "Use dataset['fjspb'] as the primary IR: choose one candidate machine per task, "
      "enforce only the explicit precedence_pairs edges from the flow graph, "
      "machine capacities, cur_ptr, temperature compatibility on shared machines, and "
      "frequency-range match against machine_frequencies. "
      "Durations, temperatures and frequencies come from the project's runtime node "
      "parameters (projectAllNodeList); placeholder/override tables are only fallbacks. "
      "Return a feasible schedule that minimizes makespan."
  )
  return Flow1160Problem(
      instance_name="proj_%s" % project_id,
      description=description,
      dataset=dataset,
      prompt_dataset=copy.deepcopy(summary),
  )
