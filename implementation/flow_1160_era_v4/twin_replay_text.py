#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯 Python 文本回放 v3 事件流（不依赖 isaac sim，秒级验证事件流逻辑）。

打印时间轴：设备执行 + 板分布。作为 isaac sim 三维孪生的快速 fallback 与调试工具，
确认数据桥产出的事件流在时间轴上自洽（板流转、设备占用合理）。

用法: python3 twin_replay_text.py /tmp/events1160.json [--ticks 12]
"""
import sys, json, argparse
from collections import Counter


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("events", nargs="?", default="/tmp/events1160.json")
  ap.add_argument("--ticks", type=int, default=12)
  a = ap.parse_args()
  e = json.load(open(a.events))
  moves = sorted(e["plate_moves"], key=lambda m: m["ready_time"])
  actions = sorted(e["device_actions"], key=lambda x: x["start"])
  makespan = e["timeline_meta"]["makespan_seconds"]
  n = a.ticks

  print("=== flow_1160 v3 排程文本回放 (makespan=%ds=%.1fh, %d设备动作, %d板流转) ===" % (
    makespan, makespan / 3600, len(actions), len(moves)))

  plate_pos = {}        # material_code -> device
  move_idx = 0
  for tick in range(n + 1):
    t = makespan * tick // n
    while move_idx < len(moves) and moves[move_idx]["ready_time"] <= t:
      m = moves[move_idx]
      plate_pos[m["material_code"]] = m["to_device"]
      move_idx += 1
    active = [ac for ac in actions if ac["start"] <= t < ac["end"]]
    names = [ac["name"] + "(" + ac["device"] + ")" for ac in active]
    print("[%5.1fh] 设备执行(%d): %s%s" % (
      t / 3600, len(active),
      ", ".join(names[:4]),
      "..." if len(names) > 4 else ""))
    dev_plates = Counter(plate_pos.values())
    print("          板分布(设备:种类数) Top3:", dev_plates.most_common(3))

  print("\n回放完成: %d/%d 板流转已应用" % (move_idx, len(moves)))
  # 末态板分布
  print("末态板所在设备:", Counter(plate_pos.values()).most_common())


if __name__ == "__main__":
  main()
