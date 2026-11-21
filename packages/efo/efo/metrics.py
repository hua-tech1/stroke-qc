# -*- coding: utf-8 -*-
"""事件级匹配与指标。

帧级指标（mAP）回答「这张图对不对」；本模块回答「这串帧合起来，事件对不对」。
match_events 对两串事件做一对一贪心最近匹配（按事件码 + 帧号容差），
据此计算事件级 P / R / F1，并可给出匹配对的帧差（时刻偏移）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class MatchResult:
    """事件级匹配结果：tp / fp / fn 及派生指标。"""

    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn,
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4),
                "f1": round(self.f1, 4)}


def match_pairs(ref, test, tol_frames: int = 2):
    """一对一贪心最近匹配。ref/test 的元素需含 .code 与 .frame 属性。

    返回 (pairs, fp, fn)：pairs 为 (ref_event, test_event) 列表，fp/fn 为误报/漏报数。
    """
    ref_pool = list(ref)
    used = [False] * len(ref_pool)
    pairs = []
    for t in test:
        best_i, best_d = -1, None
        for i, r in enumerate(ref_pool):
            if used[i] or r.code != t.code:
                continue
            d = abs(r.frame - t.frame)
            if d <= tol_frames and (best_d is None or d < best_d):
                best_i, best_d = i, d
        if best_i >= 0:
            used[best_i] = True
            pairs.append((ref_pool[best_i], t))
    return pairs, len(test) - len(pairs), sum(1 for u in used if not u)


def match_events(ref, test, tol_frames: int = 2) -> MatchResult:
    """事件级匹配结果（P/R/F1）。"""
    pairs, fp, fn = match_pairs(ref, test, tol_frames)
    return MatchResult(tp=len(pairs), fp=fp, fn=fn)


def event_deltas(ref, test, tol_frames: int = 2) -> list[int]:
    """匹配对的帧差（时刻偏移，单位：帧）。可用于 Δt 分布分析。"""
    pairs, _, _ = match_pairs(ref, test, tol_frames)
    return [abs(t.frame - r.frame) for r, t in pairs]
