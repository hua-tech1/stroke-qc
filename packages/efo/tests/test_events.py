# -*- coding: utf-8 -*-
from efo import generate_events


def _frames(confs):
    """confs: 每帧置信度，0 表示无框。"""
    return [{"frame": i, "ts_ms": round(i * 66.67, 2),
             "boxes": [{"conf": c}] if c > 0 else []} for i, c in enumerate(confs)]


def test_burst_produces_enter_and_exit():
    hits = [0.0] * 10 + [0.9] * 30 + [0.0] * 10
    ev = generate_events(_frames(hits), conf=0.5, k_in=3, m_out=5)
    codes = [e.code for e in ev]
    assert codes[0] == "device_visible_start"
    assert codes[-1] == "device_visible_end"
    # 入画触发于第 12 帧（10/11/12 连续三帧命中），离画触发于第 44 帧（40..44 连续五帧未命中）
    assert ev[0].frame == 12
    assert ev[-1].frame == 44


def test_short_burst_not_detected():
    # 只 2 帧命中，k_in=3 → 必漏
    hits = [0.0] * 10 + [0.9] * 2 + [0.0] * 10
    assert generate_events(_frames(hits), conf=0.5, k_in=3, m_out=5) == []


def test_blind_zone_grows_with_k():
    hits = [0.0] * 5 + [0.9] * 2 + [0.0] * 5
    assert generate_events(_frames(hits), conf=0.5, k_in=3, m_out=5) == []
    assert generate_events(_frames(hits), conf=0.5, k_in=2, m_out=5) != []
