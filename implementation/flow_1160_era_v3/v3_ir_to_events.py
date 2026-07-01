#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flow_1160_era_v3 IR → 数字孪生事件流 JSON。

load v3 IR + 跑 reference CP-SAT solver 产出 assignments，再合成 isaac sim 可消费的
时间轴事件流：device_actions（设备执行）/ plate_moves（板流转）/ buffer_events
（堆栈缓冲）/ logistics_events（转运）/ timeline_meta。

v3 相比 v1 的优势：material_edges（板级流转拓扑）+ logistics_events/buffers（物流）
已结构化，isaac sim 直接消费做孪生，不用从抽象 assignment 反推。

用法:
  python3 v3_ir_to_events.py 1160 > events.json
  python3 v3_ir_to_events.py 1160 --summary   # 只打印摘要到 stderr
"""
import sys, json, importlib.util

sys.path.insert(0, "/home/era")
from implementation.flow_1160_era_v3.isaac_motion import MotionTiming, build_isaac_motion_events
from implementation.flow_1160_era_v3.problem import load_problem

# reference solver（已验证 makespan≈40.3h）
_REF = "/home/era/implementation/flow_1160_era_v3/reference_v3_cpsat_candidate.py"
_spec = importlib.util.spec_from_file_location("v3_ref", _REF)
_ref = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ref)


def build_events(project_id="1160", *, timing=None):
  timing = timing or MotionTiming()
  prob = load_problem(str(project_id))
  ds = prob.dataset
  f = ds["fjspb"]

  # 跑 reference solver 产出排程
  sched = _ref.solve(ds)
  assignments = sched.get("assignments", [])
  task_by_id = {int(t["task_id"]): t for j in f["jobs"] for t in j["tasks"]}
  asgn_by_tid = {int(a["task_id"]): a for a in assignments}

  # 1) device_actions：设备在 [start,end] 执行 task
  device_actions = []
  for a in assignments:
    tid = int(a["task_id"])
    t = task_by_id.get(tid, {})
    device_actions.append({
      "task_id": tid, "name": t.get("name"), "device": a.get("machine"),
      "start": int(a.get("start")), "end": int(a.get("end")),
      "duration": int(t.get("duration", 0)),
      "required_capacity": int(t.get("required_capacity", 1)),
    })
  device_actions.sort(key=lambda x: x["start"])

  # 2) plate_moves：material_edges 的板级流转（src_task 完成后板送到 dst_task）
  plate_moves = []
  for e in f.get("material_edges", []):
    st, dt = e.get("src_task_id"), e.get("dst_task_id")
    if st is None or dt is None:
      continue
    sa, da = asgn_by_tid.get(int(st)), asgn_by_tid.get(int(dt))
    if not sa or not da:
      continue
    plate_moves.append({
      "edge_id": e.get("edge_id"),
      "plate": e.get("barcode_name") or e.get("material_name") or "plate",
      "material_code": e.get("material_code"),
      "quantity": e.get("quantity"),
      "from_device": sa.get("machine"), "to_device": da.get("machine"),
      "ready_time": int(sa.get("end")),   # src 完成即可转运
      "need_by": int(da.get("start")),    # dst 开始前须到达
    })
  plate_moves.sort(key=lambda x: x["ready_time"])

  # 3) logistics_events：堆栈/进退板/扫码/转运（直接透传 + 关联 task 时间）
  logistics = []
  for ev in f.get("logistics_events", []):
    # 用 successor task 的开始作为该物流事件的发生时间近似
    succ = ev.get("successor_task_ids") or []
    t0 = None
    for sid in succ:
      sa = asgn_by_tid.get(int(sid))
      if sa:
        t0 = int(sa.get("start")); break
    logistics.append({
      "id": ev.get("id"), "node_name": ev.get("node_name"), "kind": ev.get("kind"),
      "resources": ev.get("resources"), "buffer_ids": ev.get("buffer_ids"),
      "duration": int(ev.get("duration") or 0), "time": t0,
      "successor_task_ids": succ,
    })

  # 4) buffers：堆栈/缓冲区元数据
  buffers = [{"id": b.get("id"), "device": b.get("device_name"),
              "capacity": b.get("capacity"), "type": b.get("type")}
             for b in f.get("buffers", [])]

  makespan = max((a["end"] for a in device_actions), default=0)
  devices = [{"code": m, "capacity": c} for m, c in f.get("machines", {}).items()]
  motion = build_isaac_motion_events(ds, sched, timing=timing)

  return {
    "project_id": str(project_id),
    "timeline_meta": {
      "makespan_seconds": int(makespan),
      "makespan_hours": round(makespan / 3600, 2),
      "device_count": len(devices), "buffer_count": len(buffers),
      "action_count": len(device_actions), "plate_move_count": len(plate_moves),
      "logistics_event_count": len(logistics),
      "robot_action_count": len(motion["robot_actions"]),
      "motion_ok": motion["motion_monitor"]["ok"],
      "motion_conflict_count": motion["motion_monitor"]["conflict_count"],
      "motion_deadlock_count": motion["motion_monitor"]["deadlock_count"],
    },
    "devices": devices,
    "buffers": buffers,
    "device_actions": device_actions,
    "plate_moves": plate_moves,
    "logistics_events": logistics,
    "robot_actions": motion["robot_actions"],
    "plate_transfers": motion["plate_transfers"],
    "motion_timing": motion["timing"],
    "motion_monitor": motion["motion_monitor"],
  }


def main():
  pid = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "1160"
  summary_only = "--summary" in sys.argv
  timing = MotionTiming(
      pick_seconds=_flag_int("--pick-seconds", 30),
      move_seconds=_flag_int("--move-seconds", 300),
      place_seconds=_flag_int("--place-seconds", 30),
      drop_seconds=_flag_int("--drop-seconds", 10),
      safety_gap_seconds=_flag_int("--safety-gap-seconds", 10),
  )
  events = build_events(pid, timing=timing)
  if summary_only:
    m = events["timeline_meta"]
    sys.stderr.write(
      "v3→事件流 项目%s: makespan=%.1fh, %d设备/%d缓冲, %d设备动作/%d板流转/%d物流事件/%d机械臂动作, motion_ok=%s, conflicts=%d, deadlocks=%d\n" % (
        pid, m["makespan_hours"], m["device_count"], m["buffer_count"],
        m["action_count"], m["plate_move_count"], m["logistics_event_count"],
        m["robot_action_count"], m["motion_ok"], m["motion_conflict_count"],
        m["motion_deadlock_count"]))
  else:
    print(json.dumps(events, ensure_ascii=False, indent=2))


def _flag_int(name, default):
  if name not in sys.argv:
    return default
  idx = sys.argv.index(name)
  if idx + 1 >= len(sys.argv):
    return default
  return int(sys.argv[idx + 1])


if __name__ == "__main__":
  main()
