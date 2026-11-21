# -*- coding: utf-8 -*-
"""通用事件化：把逐帧检测收敛成离散事件（连续 k 帧确认）。

这是整个体系的地基。输入是一段逐帧检测结果，输出是少数几个可入库、
可追责的离散事件；规则为「连续 k_in 帧命中判入画、连续 m_out 帧未命中判离画」。

与具体业务解耦：帧字典的键名、事件码均可通过关键字参数覆盖，默认值
与 stroke-qc 项目的数据契约一致（frame / ts_ms / boxes[].conf）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class Event:
    """一个离散事件：code（事件码）、frame（触发帧号）、ts_ms（触发时刻）、
    confidence（触发时的置信度）、rule（为什么这一帧算触发）。"""

    code: str
    frame: int
    ts_ms: float
    confidence: float
    rule: str

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "frame": self.frame,
            "ts_ms": self.ts_ms,
            "confidence": self.confidence,
            "rule": self.rule,
        }


def _hit(boxes: Iterable[Any], conf: float, conf_key: str) -> tuple[bool, float]:
    """单帧命中判定：是否存在 conf 达到阈值的框；返回 (是否命中, 最高置信度)。"""
    best = 0.0
    for b in boxes:
        c = b.get(conf_key, 0.0) if isinstance(b, dict) else float(b)
        if c >= conf:
            best = max(best, c)
    return best > 0.0, round(best, 4)


def generate_events(
    frames: Sequence[Any],
    *,
    conf: float = 0.5,
    k_in: int = 3,
    m_out: int = 5,
    conf_key: str = "conf",
    frame_key: str = "frame",
    ts_key: str = "ts_ms",
    boxes_key: str = "boxes",
    enter_code: str = "device_visible_start",
    exit_code: str = "device_visible_end",
) -> list[Event]:
    """按帧序生成事件。

    参数
    ----
    frames   逐帧检测结果的可迭代对象，每项需可按下标/键取到 frame / ts / boxes。
    conf     置信度阈值。
    k_in     连续多少帧命中判「入画」。
    m_out    连续多少帧未命中判「离画」。
    其余为字段键名与事件码，可覆盖以适配不同数据契约。

    返回
    ----
    list[Event]，按触发顺序排列。
    """
    state = "absent"
    streak = 0
    events: list[Event] = []

    for fr in frames:
        boxes = fr.get(boxes_key, []) if isinstance(fr, dict) else getattr(fr, boxes_key, [])
        hit, best = _hit(boxes or [], conf, conf_key)
        fno = fr[frame_key] if isinstance(fr, dict) else getattr(fr, frame_key)
        tms = fr[ts_key] if isinstance(fr, dict) else getattr(fr, ts_key)

        if state == "absent":
            streak = streak + 1 if hit else 0
            if streak >= k_in:
                state, streak = "present", 0
                events.append(Event(
                    code=enter_code, frame=fno, ts_ms=tms, confidence=best,
                    rule=f"连续 {k_in} 帧 conf≥{conf} 判入画"))
        else:
            streak = streak + 1 if not hit else 0
            if streak >= m_out:
                state, streak = "absent", 0
                events.append(Event(
                    code=exit_code, frame=fno, ts_ms=tms, confidence=best,
                    rule=f"连续 {m_out} 帧无命中 判离画"))

    return events
