# -*- coding: utf-8 -*-
"""事件级保真自检（EFO）—— 对开源包 efo 的薄封装（吃自己的狗粮）。

核心逻辑全部来自 efo 开源包；本模块只做两件事：
  1. 重新导出 efo 的公共接口，保证 app 内既有 import 不破坏；
  2. 提供 event_audit() 这个「读取本系统配置」的便捷汇总函数。

这样系统与通用库共用同一份实现，避免「系统里写的」与「实验里测的」两套逻辑漂移。
"""
from __future__ import annotations

from efo import (
    MatchResult,
    blind_zone_ms,
    corrected_dwell_ms,
    detection_upper_bound,
    dwell_bias_center_ms,
    dwell_bias_interval_ms,
    match_events,
)

from app.core import config as C

__all__ = [
    "MatchResult",
    "blind_zone_ms",
    "dwell_bias_interval_ms",
    "dwell_bias_center_ms",
    "detection_upper_bound",
    "corrected_dwell_ms",
    "match_events",
    "event_audit",
]


def event_audit(p: float = 0.95) -> dict:
    """返回当前判据配置下的三命题自检结果（供 /api/demo/event-audit）。"""
    frame_ms = C.FRAME_MS
    k_in, m_out = C.K_IN, C.M_OUT
    return {
        "k_in": k_in,
        "m_out": m_out,
        "fps": C.FPS,
        "frame_ms": round(frame_ms, 3),
        "blind_zone_ms": round(blind_zone_ms(k_in, frame_ms), 2),           # P1
        "detection_upper_bound": round(detection_upper_bound(p, k_in), 4),   # P2
        "p_assumed": p,
        "dwell_bias_interval_ms": round(dwell_bias_interval_ms(k_in, m_out, frame_ms), 2),
        "dwell_bias_center_ms": round(dwell_bias_center_ms(k_in, m_out, frame_ms), 2),  # P3
    }
