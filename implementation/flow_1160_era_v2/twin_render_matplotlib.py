#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""matplotlib 3D 静态可视化（不依赖 isaac sim 渲染，可靠产 PNG）。

设备按类型 bar3d 着色 + 板散点（按 material_code）+ 设备类型标签。
作为 isaac sim（headless 截图受限）的可靠可视化替代，便于远程查看。

用法:
  python3 twin_render_matplotlib.py /tmp/events1160.json /tmp/twin_matplotlib.png [time_frac]
  time_frac: 0.0~1.0，渲染该时刻的快照（默认 1.0=末态）
"""
import sys, json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
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


TYPE_COLOR = {
  "移液工作站": "#e54b4b", "培养箱": "#4b7de0", "酶标仪": "#4bcc66",
  "挑单克隆仪": "#b34bd6", "堆栈": "#8c8c92", "温控模块": "#f2cc33", "其它": "#999999",
}
TYPE_ORDER = ["温控模块", "移液工作站", "培养箱", "挑单克隆仪", "酶标仪", "堆栈", "其它"]
PLATE_COLOR = ["#e63939", "#39e673", "#e6d739", "#3955e6", "#e673c9", "#39c9e6"]


def main():
  events = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/events1160.json"))
  out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/twin_matplotlib.png"
  time_frac = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0

  devices = events["devices"]
  moves = sorted(events["plate_moves"], key=lambda m: m["ready_time"])
  makespan = events["timeline_meta"]["makespan_seconds"]
  sim_t = makespan * max(0.0, min(1.0, time_frac))

  # 设备按类型聚簇布局（同 isaac_twin）
  by_type = defaultdict(list)
  for d in devices:
    by_type[device_type(d["code"])].append(d)
  dev_pos = {}
  col_x = -14
  for t in TYPE_ORDER:
    lst = by_type.get(t, [])
    if not lst:
      continue
    for i, d in enumerate(lst):
      x = col_x + (i % 2) * 1.6
      y = -6 + (i // 2) * 1.6
      dev_pos[d["code"]] = (x, y, t)
    col_x += 4.0

  # 板按 material_code 转移序列；求 sim_t 时刻位置（插值）
  moves_by_code = defaultdict(list)
  for m in moves:
    moves_by_code[m["material_code"]].append(m)
  for c in moves_by_code:
    moves_by_code[c].sort(key=lambda m: m["ready_time"])
  mat_codes = sorted(moves_by_code.keys())
  plate_pos = {}
  for k, code in enumerate(mat_codes):
    seq = moves_by_code[code]
    prev = list(dev_pos.get(seq[0]["from_device"], (0, 0, "")))[:2] if seq else [0, 0]
    for m in seq:
      fr = dev_pos.get(m["from_device"], (0, 0, ""))[:2]
      to = dev_pos.get(m["to_device"], (0, 0, ""))[:2]
      ready, need = m["ready_time"], m["need_by"]
      if sim_t < ready:
        break
      span = max(1.0, float(need - ready))
      if sim_t <= need:
        p = (sim_t - ready) / span
        prev = [fr[0] * (1 - p) + to[0] * p, fr[1] * (1 - p) + to[1] * p]
        break
      prev = list(to)
    plate_pos[code] = prev

  # 当前执行中的设备
  active = {a["device"] for a in events["device_actions"] if a["start"] <= sim_t < a["end"]}

  # 画
  fig = plt.figure(figsize=(16, 9))
  ax = fig.add_subplot(111, projection="3d")
  for code, (x, y, t) in dev_pos.items():
    color = TYPE_COLOR[t]
    h = 1.3 if t in ("移液工作站", "堆栈") else (0.9 if t == "培养箱" else (0.5 if t == "酶标仪" else 0.6))
    z0 = 0.3 if code in active else 0.0  # 执行中上浮
    ax.bar3d(x - 0.5, y - 0.5, z0, 1.0, 1.0, h, color=color, alpha=0.85, edgecolor="black", linewidth=0.5)
    ax.text(x, y, z0 + h + 0.25, t, fontsize=7, ha="center", color="black")
  for k, code in enumerate(mat_codes):
    px, py = plate_pos[code]
    ax.scatter(px, py, 1.6, c=PLATE_COLOR[k % len(PLATE_COLOR)], s=120,
               edgecolors="black", linewidths=0.8, depthshade=True)
    ax.text(px, py, 1.9, code, fontsize=6, ha="center", color="#222")

  # 图例
  handles = [plt.Rectangle((0, 0), 1, 1, color=TYPE_COLOR[t]) for t in TYPE_ORDER if by_type.get(t)]
  labels = ["%s(%d)" % (t, len(by_type[t])) for t in TYPE_ORDER if by_type.get(t)]
  ax.legend(handles, labels, loc="upper left", fontsize=8, title="设备类型")

  ax.set_title("flow_1160 v2 排程孪生快照  t=%.1fh / %.1fh  (执行设备=%d, 板类=%d)" % (
    sim_t / 3600, makespan / 3600, len(active), len(mat_codes)), fontsize=12)
  ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
  ax.set_zlim(0, 3)
  plt.savefig(out, dpi=120, bbox_inches="tight")
  print("[render] saved %s  (t=%.1fh, %d设备/%d板)" % (out, sim_t / 3600, len(dev_pos), len(mat_codes)))


if __name__ == "__main__":
  main()
