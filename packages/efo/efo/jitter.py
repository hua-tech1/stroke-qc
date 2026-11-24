# -*- coding: utf-8 -*-
"""帧时序抖动（jitter）对事件级指标的影响 —— EFO 的硬件扩展。

背景：EFO 三定律假设「帧间隔恒等于 Δt」。真实边缘硬件（如昇腾 DVPP 多路硬解）
的帧到达时刻是抖动的，把三定律里的「常数」变成「随机变量」。

本模块提供：
  解析推广 —— blind_zone_p99 / dwell_error_p99（闭式解）
  实证函数 —— dwell_error_stats（对 ts_ms 注入 iid 抖动，重跑事件测误差分布）

诚实边界：抖动模型 δ~N(0,σ²) 是仿真假设，非 DVPP 实测；真分布需昇腾硬件。
"""
from __future__ import annotations

import math
import random
from typing import Sequence

from .events import generate_events

Z99 = 2.3263  # 单侧 99% 分位（标准正态）


def blind_zone_p99(k_in: int, frame_ms: float, sigma: float) -> float:
    """盲区（最短可检出动作时长）在抖动下的 P99。

    盲区 = (k_in-1) 个帧间隔的时间跨度。每帧间隔独立抖动 δ~N(0,σ²)，
    故跨度均值 (k_in-1)·Δt、标准差 √(k_in-1)·σ，P99 = 均值 + Z99·std。
    """
    return (k_in - 1) * frame_ms + Z99 * math.sqrt(k_in - 1) * sigma


def dwell_error_p99(sigma: float) -> float:
    """滞留时长测量误差的 P99（两端点抖动合成，与序列长度无关）。"""
    return Z99 * math.sqrt(2.0) * sigma


def dwell_error_stats(
    frames: Sequence,
    sigma: float,
    k_in: int = 3,
    m_out: int = 5,
    conf: float = 0.5,
    trials: int = 500,
    seed: int = 0,
) -> dict | None:
    """实证：给 ts_ms 加 iid 抖动 δ~N(0,σ²)，重跑事件，测滞留时长的误差分布。

    返回 {"p50", "p99", "trials"}（绝对误差，单位 ms）；无闭合事件时返回 None。
    """
    rng = random.Random(seed)
    base = generate_events(frames, conf=conf, k_in=k_in, m_out=m_out)
    ins = [e for e in base if e.code == "device_visible_start"]
    outs = [e for e in base if e.code == "device_visible_end"]
    if not ins or not outs:
        return None
    nominal = outs[-1].ts_ms - ins[0].ts_ms

    errs: list[float] = []
    for _ in range(trials):
        jit = [{**f, "ts_ms": f["ts_ms"] + rng.gauss(0.0, sigma)} for f in frames]
        ev = generate_events(jit, conf=conf, k_in=k_in, m_out=m_out)
        ji = [e for e in ev if e.code == "device_visible_start"]
        jo = [e for e in ev if e.code == "device_visible_end"]
        if ji and jo:
            errs.append(abs((jo[-1].ts_ms - ji[0].ts_ms) - nominal))

    errs.sort()

    def pct(q: float) -> float:
        if not errs:
            return 0.0
        return errs[min(len(errs) - 1, int(q * (len(errs) - 1)))]

    return {"p50": round(pct(0.50), 2), "p99": round(pct(0.99), 2), "trials": len(errs)}
