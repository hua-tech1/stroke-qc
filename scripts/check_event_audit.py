# -*- coding: utf-8 -*-
"""事件级自检 · 自检脚本（第①层验收）

运行：python scripts/check_event_audit.py
断言 event_audit 模块的三命题闭式解与 experiments/efo 的实测结论一致。
全部通过则 exit 0，任何一条不通过 exit 1。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config as C
from app.qc import event_audit as ea


@dataclass
class Ev:
    code: str
    frame: int


def check(cond: bool, label: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        sys.exit(1)


def main() -> None:
    frame_ms = C.FRAME_MS

    # ---- P1 盲区：k=3 → 2 帧 = 133.33 ms ----
    check(abs(ea.blind_zone_ms(3, frame_ms) - 133.333) < 0.01, "P1 盲区 = 133.33 ms")
    check(abs(ea.blind_zone_ms(1, frame_ms)) < 1e-9, "P1 盲区 k=1 → 0")

    # ---- P2 检出上界：0.95^3 = 0.857375 ----
    check(abs(ea.detection_upper_bound(0.95, 3) - 0.857375) < 1e-6, "P2 上界 = 0.8574")
    check(abs(ea.detection_upper_bound(0.95, 5) - 0.95 ** 5) < 1e-9, "P2 上界 k=5 = 0.95^5")

    # ---- P3 偏置（区间 + 中心口径）----
    check(abs(ea.dwell_bias_interval_ms(3, 5, frame_ms) - 133.333) < 0.01, "P3 区间口径 = +133.33")
    check(abs(ea.dwell_bias_center_ms(3, 5, frame_ms) - 200.0) < 0.01, "P3 中心口径 = +200.00")
    check(abs(ea.corrected_dwell_ms(300.0, 3, 5, frame_ms) - 100.0) < 0.01, "P3 校正 300→100")

    # ---- 事件匹配：完全命中 → F1=1；漏一个 → recall=0.5 ----
    ref = [Ev("device_visible_start", 4), Ev("device_visible_end", 113)]
    full = [Ev("device_visible_start", 5), Ev("device_visible_end", 114)]
    miss = [Ev("device_visible_start", 5)]
    check(ea.match_events(ref, full, tol_frames=2).f1 == 1.0, "匹配·完全命中 F1=1.0")
    check(abs(ea.match_events(ref, miss, tol_frames=2).recall - 0.5) < 1e-9, "匹配·漏一个 recall=0.5")

    # ---- 系统级汇总：三个数字与 experiments/efo 一致 ----
    audit = ea.event_audit(p=0.95)
    check(audit["blind_zone_ms"] == 133.33, f"汇总·盲区 {audit['blind_zone_ms']}")
    check(audit["dwell_bias_center_ms"] == 200.0, f"汇总·中心偏置 {audit['dwell_bias_center_ms']}")
    check(audit["detection_upper_bound"] == 0.8574, f"汇总·检出上界 {audit['detection_upper_bound']}")

    print("\n自检通过：event_audit 三命题闭式解与实测一致。")


if __name__ == "__main__":
    main()
