# -*- coding: utf-8 -*-
"""帧乱序对「连续 k 帧确认」的破坏 + 保序策略 —— EFO 的硬件扩展。

背景：状态机假设帧严格按序输入；多路异步解码/回传可能乱序。
临界长度的命中段（恰为 k_in 帧）对乱序最敏感：边界一次交换即可能击穿。

本模块提供：
  reorder_adjacent  相邻帧乱序注入
  reorder_buffer    按序列号重排的保序缓冲
  detection_rate    临界长度事件的检出率（无保序 vs 有保序）

诚实边界：乱序模型（相邻交换）是仿真假设，非 DVPP 实测。
"""
from __future__ import annotations

import random
from typing import Sequence

from .events import generate_events


def reorder_adjacent(frames: Sequence, p: float, seed: int) -> list[dict]:
    """相邻帧以概率 p 交换（模拟多路异步回传的乱序）。"""
    rng = random.Random(seed)
    out = [dict(f) for f in frames]
    for i in range(len(out) - 1):
        if rng.random() < p:
            out[i], out[i + 1] = out[i + 1], out[i]
    return out


def reorder_buffer(frames: Sequence, frame_key: str = "frame") -> list[dict]:
    """按序列号重排的保序缓冲（最简单的保序策略）。"""
    return sorted(frames, key=lambda f: f[frame_key])


def detection_rate(
    frames: Sequence,
    p: float,
    k_in: int = 3,
    m_out: int = 5,
    conf: float = 0.5,
    trials: int = 500,
    seed: int = 0,
    with_buffer: bool = False,
) -> float:
    """「入画」事件的检出率：乱序 vs 乱序+保序。

    每个试次独立乱序（种子由主 rng 派生），统计至少产生一次入画事件的试次占比。
    """
    rng = random.Random(seed)
    hit = 0
    for _ in range(trials):
        r = reorder_adjacent(frames, p, rng.randrange(1 << 30))
        if with_buffer:
            r = reorder_buffer(r)
        ev = generate_events(r, conf=conf, k_in=k_in, m_out=m_out)
        if any(e.code == "device_visible_start" for e in ev):
            hit += 1
    return round(hit / trials, 4)
