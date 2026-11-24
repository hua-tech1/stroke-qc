# -*- coding: utf-8 -*-
"""滞回状态机：把逐帧检测收敛成离散事件

这是整个项目的技术核心，不是模型本身。
113 帧的噪声输出 → 2 个可入库、可追责的临床事件。

规则（参数来自 config）：
  连续 K_IN 帧命中  → 判"入画"
  连续 M_OUT 帧未命中 → 判"离画"
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

from app.core import config as C


@dataclass
class Event:
    code: str
    frame: int
    ts_ms: float
    confidence: float
    rule: str            # 触发该事件的规则描述，用于解释与留痕

    def dict(self):
        return asdict(self)


def _hit(boxes: Iterable[dict], conf: float) -> tuple[bool, float]:
    best = 0.0
    for b in boxes:
        if b.get("conf", 0.0) >= conf:
            best = max(best, b["conf"])
    return best > 0, round(best, 4)


def generate_events(frames: list[dict], conf: float = C.CONF,
                    k_in: int = C.K_IN, m_out: int = C.M_OUT) -> list[Event]:
    """按帧序生成事件。frames 元素需含 frame / ts_ms / boxes。"""
    state = "absent"
    streak = 0
    events: list[Event] = []

    for fr in frames:
        hit, best = _hit(fr.get("boxes", []), conf)

        if state == "absent":
            streak = streak + 1 if hit else 0
            if streak >= k_in:
                state, streak = "present", 0
                events.append(Event(
                    code=C.EV_VISIBLE_START, frame=fr["frame"], ts_ms=fr["ts_ms"],
                    confidence=best,
                    rule=f"连续 {k_in} 帧 conf≥{conf} 判入画"))
        else:
            streak = streak + 1 if not hit else 0
            if streak >= m_out:
                state, streak = "absent", 0
                events.append(Event(
                    code=C.EV_VISIBLE_END, frame=fr["frame"], ts_ms=fr["ts_ms"],
                    confidence=best,
                    rule=f"连续 {m_out} 帧无命中 判离画"))

    return events


def dwell_ms(frames: list[dict], events: list[Event]) -> int | None:
    """最早入画到最晚离画之间的滞留时长；未闭合返回 None。"""
    ins = [e for e in events if e.code == C.EV_VISIBLE_START]
    outs = [e for e in events if e.code == C.EV_VISIBLE_END]
    if not ins:
        return None
    if not outs:
        return None
    return int(max(e.ts_ms for e in outs) - min(e.ts_ms for e in ins))


def is_open(events: list[Event]) -> bool:
    """有进入但无离开 → 未闭合（术中滞留超时的判定依据）。"""
    has_in = any(e.code == C.EV_VISIBLE_START for e in events)
    has_out = any(e.code == C.EV_VISIBLE_END for e in events)
    return has_in and not has_out
