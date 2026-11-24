# -*- coding: utf-8 -*-
"""efo — 事件保真优化（Event Fidelity Optimization）。

面向「检测 → 连续 k 帧确认 → 业务事件」这类流水线：量化其帧级指标（mAP）
看不见的事件级误差，并给出校准解法。

四块能力：
  events     通用事件化状态机（连续 k 帧确认）
  metrics    事件级匹配与指标（P / R / F1 / Δt）
  laws       三命题闭式解（盲区 / 滞留偏置 / 检出上界）
  calibrate  三个解法（偏置校正 / 量化感知重标定 / 盲区感知参数建议）

零第三方依赖，纯标准库。任何检测流水线都可 `pip install efo` 直接使用。
"""
from __future__ import annotations

from .calibrate import corrected_dwell_ms, recalibrate_after_quant, suggest_k
from .events import Event, generate_events
from .laws import (
    blind_zone_ms,
    detection_upper_bound,
    dwell_bias_center_ms,
    dwell_bias_interval_ms,
)
from .metrics import MatchResult, event_deltas, match_events, match_pairs

__version__ = "0.1.0"

__all__ = [
    "Event",
    "generate_events",
    "MatchResult",
    "match_events",
    "match_pairs",
    "event_deltas",
    "blind_zone_ms",
    "dwell_bias_interval_ms",
    "dwell_bias_center_ms",
    "detection_upper_bound",
    "corrected_dwell_ms",
    "suggest_k",
    "recalibrate_after_quant",
    "__version__",
]
