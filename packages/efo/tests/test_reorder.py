# -*- coding: utf-8 -*-
from efo.reorder import detection_rate, reorder_buffer, reorder_adjacent


def _critical_frames():
    """5 帧无命中 + 恰 3 帧命中（临界长度）+ 5 帧无命中。"""
    confs = [0.0] * 5 + [0.9] * 3 + [0.0] * 5
    return [{"frame": i, "ts_ms": round(i * 66.67, 2),
             "boxes": [{"conf": c}] if c > 0 else []} for i, c in enumerate(confs)]


def test_no_reorder_detects_always():
    assert detection_rate(_critical_frames(), 0.0, trials=300, seed=0) == 1.0


def test_reorder_breaks_detection():
    d = detection_rate(_critical_frames(), 0.3, trials=500, seed=0)
    assert d < 1.0, f"乱序应击穿临界段，检出率 {d}"


def test_buffer_restores():
    d_no = detection_rate(_critical_frames(), 0.3, trials=500, seed=0, with_buffer=False)
    d_buf = detection_rate(_critical_frames(), 0.3, trials=500, seed=0, with_buffer=True)
    assert d_buf > d_no
    assert d_buf == 1.0          # 按序列号重排后完全恢复


def test_reorder_adjacent_is_reversible():
    import random
    frames = _critical_frames()
    r = reorder_adjacent(frames, 0.9, seed=42)
    assert reorder_buffer(r) == sorted(frames, key=lambda f: f["frame"])
