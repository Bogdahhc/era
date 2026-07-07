#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""isaac sim 数字孪生：消费 v3 事件流 JSON，三维回放 flow_1160 排程。

设备用「组合几何体」拼出每种仪器的特征形状（移液站/培养箱/酶标仪/挑克隆仪/堆栈/温控），
设备静止不跳动，板（长方体）在设备上方平滑运送。默认 GUI 循环回放。

用法:
  python3 isaac_twin.py /tmp/events1160.json                 # GUI 循环回放
  python3 isaac_twin.py /tmp/events1160.json --speed 80       # 慢放看清运送
  python3 isaac_twin.py /tmp/events1160.json --headless       # 无显示器（截图）
"""
import sys, json, argparse, os
from collections import defaultdict


def device_type(code):
  c = str(code).lower()
  if c in ("d-0007", "d-0038", "d-0039", "d-0040"): return "移液工作站"
  if c in ("d-0011", "d-0012", "d-0069"): return "培养箱"
  if c == "d-0015": return "挑单克隆仪"
  if c in ("d-0017", "d-0018"): return "酶标仪"
  if c == "d-0013": return "堆栈"
  if c in ("d-0001", "d-0002", "d-0003", "d-0004", "d-0005", "d-0006", "d-0036"): return "温控模块"
  return "其它"


# 设备占地尺寸（布局用）+ 主体高度（标签/板高度用）
TYPE_FOOTPRINT = {
  "移液工作站": (1.6, 1.6, 1.2), "培养箱": (2.0, 2.0, 0.9), "酶标仪": (1.8, 1.4, 0.45),
  "挑单克隆仪": (1.4, 1.4, 1.0), "堆栈": (1.6, 1.6, 1.8), "温控模块": (1.0, 1.0, 0.45),
  "其它": (1.2, 1.2, 0.6),
}
TYPE_ORDER = ["温控模块", "移液工作站", "培养箱", "挑单克隆仪", "酶标仪", "堆栈", "其它"]
PLATE_COLOR = ["#e63939", "#39e673", "#e6d739", "#3955e6", "#e673c9", "#39c9e6"]


def parse_args():
  ap = argparse.ArgumentParser()
  ap.add_argument("events", nargs="?", default="/tmp/events1160.json")
  ap.add_argument("--shots", type=int, default=6)
  ap.add_argument("--speed", type=int, default=120, help="每 sim 步推进的排程秒数（小=慢看清）")
  ap.add_argument("--headless", action="store_true", help="无显示器用（默认 GUI 循环回放）")
  ap.add_argument("--hold", type=int, default=0, help="GUI 保持秒（仅单次模式；默认循环）")
  ap.add_argument("--screenshot", default="/tmp/twin_end.png", help="headless 截图输出路径")
  ap.add_argument("--report-json", help="headless 运行报告 JSON 输出路径")
  return ap.parse_args()


def main():
  import numpy as np
  args = parse_args()
  from isaacsim import SimulationApp
  app = SimulationApp({"headless": args.headless})
  from isaacsim.core.api import World
  from isaacsim.core.api.objects import FixedCuboid

  draw = None
  for _mod in ("isaacsim.util.debug_draw", "omni.isaac.debug_draw"):
    try:
      _dbg = __import__(_mod, fromlist=["_debug_draw"])
      draw = _dbg._debug_draw.acquire_debug_draw_interface()
      break
    except Exception:
      continue

  events = json.load(open(args.events))
  devices = events["devices"]
  buffers = events["buffers"]
  moves = sorted(events["plate_moves"], key=lambda m: m["ready_time"])
  actions = sorted(events["device_actions"], key=lambda x: x["start"])
  makespan = events["timeline_meta"]["makespan_seconds"]

  world = World(stage_units_in_meters=1.0)
  try:
    from pxr import UsdLux, Sdf
    stage = world.stage
    dome = UsdLux.DomeLight.Define(stage, Sdf.Path("/World/DomeLight"))
    dome.CreateIntensityAttr(450.0)
    sun = UsdLux.DistantLight.Define(stage, Sdf.Path("/World/DistantLight"))
    sun.CreateIntensityAttr(1200.0)
    sun.CreateAngleAttr(0.45)
  except Exception:
    pass
  FixedCuboid(prim_path="/ground", name="ground", position=[0, 0, -0.05],
              scale=[48, 24, 0.1], color=np.array([0.16, 0.16, 0.18]))

  def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])

  # ---- 每种仪器组合几何体（特征形状）----
  def build_device(code, t, x, y):
    base = "/dev_" + code.replace("-", "_")

    def cub(name, pos, scale, color):
      FixedCuboid(prim_path=base + "_" + name, name=name, position=pos,
                  scale=scale, color=np.array(color))

    if t == "移液工作站":  # 箱体 + 移液臂横梁 + tip 架
      cub("body", [x, y, 0.6], [1.2, 1.2, 1.2], [0.80, 0.28, 0.28])
      cub("arm", [x, y + 0.5, 1.15], [0.9, 0.12, 0.12], [0.30, 0.30, 0.34])
      cub("gantry", [x, y + 0.5, 1.35], [0.08, 0.08, 0.4], [0.25, 0.25, 0.28])
      cub("tiprack", [x + 0.85, y, 0.15], [0.35, 0.35, 0.3], [0.18, 0.18, 0.20])
    elif t == "培养箱":  # 箱体 + 门 + 内层架
      cub("body", [x, y, 0.5], [1.6, 1.6, 1.0], [0.28, 0.48, 0.88])
      cub("door", [x, y - 0.78, 0.5], [1.5, 0.06, 0.9], [0.18, 0.28, 0.48])
      cub("handle", [x, y - 0.82, 0.5], [0.2, 0.04, 0.08], [0.7, 0.7, 0.72])
      for i in range(3):
        cub("shelf%d" % i, [x, y, 0.25 + i * 0.3], [1.4, 1.4, 0.04], [0.45, 0.55, 0.65])
    elif t == "酶标仪":  # 扁箱 + 读数头 + 屏
      cub("body", [x, y, 0.25], [1.5, 1.0, 0.5], [0.28, 0.78, 0.40])
      cub("reader", [x, y, 0.58], [0.5, 0.5, 0.18], [0.18, 0.22, 0.18])
      cub("screen", [x, y + 0.48, 0.35], [0.4, 0.03, 0.2], [0.10, 0.12, 0.14])
      cub("keypad", [x + 0.5, y + 0.45, 0.28], [0.2, 0.03, 0.12], [0.3, 0.3, 0.32])
    elif t == "挑单克隆仪":  # 箱 + 挑针臂
      cub("body", [x, y, 0.55], [1.0, 1.0, 1.1], [0.68, 0.28, 0.83])
      cub("arm", [x, y + 0.45, 1.05], [0.7, 0.1, 0.1], [0.32, 0.32, 0.38])
      cub("pin", [x, y + 0.45, 0.85], [0.04, 0.04, 0.3], [0.6, 0.6, 0.62])
      cub("dish", [x, y - 0.3, 0.06], [0.4, 0.4, 0.1], [0.2, 0.2, 0.22])
    elif t == "堆栈":  # 多层架 + 立柱
      for i in range(5):
        cub("lay%d" % i, [x, y, 0.1 + i * 0.36], [1.2, 1.2, 0.06], [0.52, 0.52, 0.58])
      for dx, dy in [(-0.55, -0.55), (0.55, -0.55), (-0.55, 0.55), (0.55, 0.55)]:
        cub("post_%.0f_%.0f" % (dx, dy), [x + dx, y + dy, 0.95], [0.08, 0.08, 1.9], [0.38, 0.38, 0.42])
    elif t == "温控模块":  # 小箱 + 散热片
      cub("body", [x, y, 0.25], [0.7, 0.7, 0.5], [0.92, 0.78, 0.22])
      for i in range(4):
        cub("fin%d" % i, [x - 0.21 + i * 0.14, y, 0.52], [0.06, 0.5, 0.1], [0.65, 0.55, 0.14])
    else:
      cub("body", [x, y, 0.3], [0.9, 0.9, 0.6], [0.6, 0.6, 0.6])

  # 设备按类型聚簇布局
  by_type = defaultdict(list)
  for d in devices:
    by_type[device_type(d["code"])].append(d)
  dev_pos, dev_top_z = {}, {}
  col_x = -18
  for t in TYPE_ORDER:
    lst = by_type.get(t, [])
    if not lst:
      continue
    fw, fd, fh = TYPE_FOOTPRINT[t]
    for i, d in enumerate(lst):
      x = col_x + (i % 2) * (fw + 0.5)
      y = -7 + (i // 2) * (fd + 0.5)
      dev_pos[d["code"]] = (x, y)
      dev_top_z[d["code"]] = fh
      build_device(d["code"], t, x, y)
    col_x += fw * 2 + 1.8

  for j, b in enumerate(buffers[:12]):
    FixedCuboid(prim_path="/buf_%d" % j, name="buf_" + b["id"],
                position=[16 + (j % 3) * 1.2, -7 + (j // 3) * 1.6, 0.2],
                scale=[0.5, 0.5, 0.4], color=np.array([0.35, 0.35, 0.40]))

  # 板：长方体（像 96 孔板），按 material_code 配色
  mat_codes = sorted({m["material_code"] for m in moves if m.get("material_code")})
  plates = {}
  for k, code in enumerate(mat_codes):
    first = next((m for m in moves if m["material_code"] == code), None)
    sd = first["from_device"] if first and first["from_device"] in dev_pos else devices[0]["code"]
    sx, sy = dev_pos.get(sd, (0, 0))
    plates[code] = FixedCuboid(
      prim_path="/plate_" + code, name="plate_" + code, position=[sx, sy, 2.0],
      scale=[0.8, 0.5, 0.12], color=_hex(PLATE_COLOR[k % len(PLATE_COLOR)]))

  # 板插值
  moves_by_code = defaultdict(list)
  for m in moves:
    moves_by_code[m["material_code"]].append(m)
  for c in moves_by_code:
    moves_by_code[c].sort(key=lambda m: m["ready_time"])

  def plate_xy_at(code, sim_t):
    seq = moves_by_code.get(code, [])
    if not seq:
      return list(dev_pos.get(devices[0]["code"], (0, 0)))
    prev = list(dev_pos.get(seq[0]["from_device"], (0, 0)))[:2]
    for m in seq:
      fr = dev_pos.get(m["from_device"], tuple(prev))[:2]
      to = dev_pos.get(m["to_device"], tuple(prev))[:2]
      ready, need = m["ready_time"], m["need_by"]
      if sim_t < ready:
        return prev
      span = max(1.0, float(need - ready))
      if sim_t <= need:
        p = (sim_t - ready) / span
        return [fr[0] * (1 - p) + to[0] * p, fr[1] * (1 - p) + to[1] * p]
      prev = list(to)
    return prev

  def draw_labels():
    if draw is None:
      return
    for code, (x, y) in dev_pos.items():
      z = dev_top_z[code] + 0.6
      name = device_type(code)
      try:
        draw.draw_text([x, y, z], name, [1.0, 1.0, 1.0, 1.0], 0.4)
      except TypeError:
        try:
          draw.draw_text(name, [x, y, z], [1.0, 1.0, 1.0, 1.0], 0.4)
        except Exception:
          pass
      except Exception:
        pass

  legend = " / ".join(t for t in TYPE_ORDER if by_type.get(t))
  print("[twin] 场景建好: %d 设备(%d 类型: %s), %d 缓冲, %d 板类, makespan=%.1fh" % (
    len(devices), sum(1 for t in TYPE_ORDER if by_type.get(t)), legend,
    len(buffers), len(mat_codes), makespan / 3600), flush=True)
  draw_labels()

  xs = [p[0] for p in dev_pos.values()] or [0.0]
  ys = [p[1] for p in dev_pos.values()] or [0.0]
  camera_target = [float((min(xs) + max(xs)) / 2.0), float((min(ys) + max(ys)) / 2.0), 0.8]
  camera_eye = [camera_target[0], float(min(ys) - 20.0), 18.0]

  cam = None
  for _cmod in ("isaacsim.core.api.sensors", "isaacsim.sensors.camera"):
    try:
      _CM = __import__(_cmod, fromlist=["Camera"])
      cam = _CM.Camera(prim_path="/view_cam", resolution=[1920, 1080])
      world.scene.add(cam)
      break
    except Exception:
      cam = None

  world.reset()
  if cam is not None:
    try:
      cam.initialize()
      try:
        from pxr import Gf, UsdGeom
        xform = UsdGeom.Xformable(world.stage.GetPrimAtPath("/view_cam"))
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(Gf.Vec3d(*camera_eye))
        quat = Gf.Matrix4d().SetLookAt(
          Gf.Vec3d(*camera_eye), Gf.Vec3d(*camera_target), Gf.Vec3d(0.0, 0.0, 1.0)
        ).GetInverse().ExtractRotation().GetQuat()
        xform.AddOrientOp().Set(Gf.Quatf(quat))
      except Exception:
        from isaacsim.core.utils.rotations import euler_angles_to_quat
        cam.set_world_pose(position=[0, -26, 22], orientation=euler_angles_to_quat(np.array([60, 0, 0]), degrees=True))
    except Exception:
      cam = None

  def shot(path):
    def _save_rgb(rgb):
      from PIL import Image
      if rgb.dtype != np.uint8:
        rgb = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
      Image.fromarray(rgb[:, :, :3]).save(path)
      rgb3 = rgb[:, :, :3]
      mean_rgb = float(rgb3.mean())
      max_rgb = float(rgb3.max())
      std_rgb = float(rgb3.std())
      nonblack_fraction = float((rgb3.max(axis=2) > 8).mean())
      print("[twin] 截图 -> %s" % path, flush=True)
      return {
        "written": True,
        "mean_rgb": mean_rgb,
        "max_rgb": max_rgb,
        "std_rgb": std_rgb,
        "nonblack_fraction": nonblack_fraction,
      }

    if cam is None:
      return {"written": False, "mean_rgb": 0.0, "max_rgb": 0.0, "std_rgb": 0.0, "nonblack_fraction": 0.0}
    try:
      from PIL import Image
      for _ in range(15):
        world.step()
      arr = np.asarray(cam.get_rgba())
      if arr.ndim == 3 and arr.max() > 0:
        return _save_rgb(arr[:, :, :3])
    except Exception as e:
      print("[twin] 截图失败: %s" % e, flush=True)
    return {"written": False, "mean_rgb": 0.0, "max_rgb": 0.0, "std_rgb": 0.0, "nonblack_fraction": 0.0}

  total_steps = max(1, makespan // args.speed)

  def play_once():
    """板在设备上方平滑运送（设备静止）。"""
    for step in range(total_steps + 1):
      sim_t = step * args.speed
      for code, cub in plates.items():
        xy = plate_xy_at(code, sim_t)
        cub.set_world_pose(position=[xy[0], xy[1], 2.0])
      world.step()

  if args.headless:
    play_once()
    print("[twin] 回放完成（headless 单次）", flush=True)
    screenshot = shot(args.screenshot)
    _write_report(
      args.report_json,
      events,
      {
        "mode": "headless",
        "completed": True,
        "event_file": args.events,
        "speed": args.speed,
        "total_steps": int(total_steps),
        "screenshot": args.screenshot,
        "screenshot_written": bool(screenshot.get("written") and os.path.exists(args.screenshot)),
        "screenshot_mean_rgb": screenshot.get("mean_rgb", 0.0),
        "screenshot_max_rgb": screenshot.get("max_rgb", 0.0),
        "screenshot_std_rgb": screenshot.get("std_rgb", 0.0),
        "screenshot_nonblack_fraction": screenshot.get("nonblack_fraction", 0.0),
        "screenshot_scene_visible": bool(screenshot.get("std_rgb", 0.0) > 1.0),
      },
    )
    app.close()
    return

  print("[twin] GUI 循环回放——设备静止(拼特征仪器)，板在上方运送。关 isaac sim 窗口或 Ctrl+C 退出", flush=True)
  print("[twin] 视角: Alt+左键旋转 / Alt+中键平移 / 滚轮缩放 / 选中设备按F聚焦", flush=True)
  lap = 0
  try:
    while True:
      lap += 1
      print("[twin] === 第 %d 轮回放 (每轮 %d 步 ≈ %.1f 排程小时) ===" % (
        lap, total_steps, makespan / 3600), flush=True)
      play_once()
  except (KeyboardInterrupt, Exception):
    pass
  app.close()


def _write_report(path, events, isaac_result):
  if not path:
    return
  meta = events.get("timeline_meta") or {}
  motion = events.get("motion_monitor") or {}
  conflict_count = int(motion.get("conflict_count", 0) or 0)
  deadlock_count = int(motion.get("deadlock_count", 0) or 0)
  report = {
    "ok": bool(isaac_result.get("completed")) and conflict_count == 0 and deadlock_count == 0,
    "isaac": isaac_result,
    "timeline_meta": meta,
    "motion_monitor": {
      "ok": motion.get("ok"),
      "conflict_count": conflict_count,
      "deadlock_count": deadlock_count,
      "warning_count": motion.get("warning_count", 0),
      "first_conflict": (motion.get("conflicts") or [None])[0],
      "first_deadlock": (motion.get("deadlocks") or [None])[0],
    },
    "counts": {
      "devices": len(events.get("devices") or []),
      "buffers": len(events.get("buffers") or []),
      "device_actions": len(events.get("device_actions") or []),
      "plate_moves": len(events.get("plate_moves") or []),
      "robot_actions": len(events.get("robot_actions") or []),
      "plate_transfers": len(events.get("plate_transfers") or []),
    },
  }
  with open(path, "w", encoding="utf-8") as fh:
    json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
    fh.write("\n")
  print("[twin] report -> %s" % path, flush=True)


if __name__ == "__main__":
  main()
