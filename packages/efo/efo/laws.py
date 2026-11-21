# -*- coding: utf-8 -*-
"""三命题闭式解。

「连续 k 帧确认」这个判据自带三个系统性误差，均由定义直接推出、与模型精度无关：

  P1 结构性盲区   盲区 = (k_in - 1) * Δt          —— 可见时长短于此必然漏检
  P2 指数放大     事件检出上界 = p ** k_in         —— 帧级误差被 k 次幂放大
  P3 滞留偏置     偏置 = (m_out - k_in + 1) * Δt   —— 中心口径（首末帧中心）

诚实边界：P1/P3 是判据定义的直接后果；P2 是「各帧独立同分布」假设下的概率上界。
"""
from __future__ import annotations


def blind_zone_ms(k_in: int, frame_ms: float) -> float:
    """P1：结构性盲区（毫秒）。可见时长小于此值的事件必然漏检。

    推导：入画需连续 k_in 帧命中，因此最短可检出动作即 k_in 帧；
    短于 (k_in - 1) 帧的动作无论如何都凑不齐 k_in 帧。
    """
    return (k_in - 1) * frame_ms


def dwell_bias_interval_ms(k_in: int, m_out: int, frame_ms: float) -> float:
    """P3：滞留偏置（区间口径，即覆盖时长）。"""
    return (m_out - k_in) * frame_ms


def dwell_bias_center_ms(k_in: int, m_out: int, frame_ms: float) -> float:
    """P3：滞留偏置（中心口径，首末帧中心到中心）。

    推导：入画事件触发于第 (a + k_in - 1) 帧，离画事件触发于第 (b + m_out) 帧，
    滞留 = (b - a) + (m_out - k_in + 1) 帧，比真值 (b - a) 多出 (m_out - k_in + 1) 帧。
    """
    return (m_out - k_in + 1) * frame_ms


def detection_upper_bound(p: float, k_in: int) -> float:
    """P2：事件检出上界 p ** k_in（各帧独立同分布假设）。

    可见段恰为 k_in 帧时取等号；可见段更长时实际检出率高于该下界。
    """
    return p ** k_in
