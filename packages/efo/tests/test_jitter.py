# -*- coding: utf-8 -*-
import math

from efo.jitter import blind_zone_p99, dwell_error_p99, dwell_error_stats

DT = 1000.0 / 15.0


def _frames():
    return [{"frame": i, "ts_ms": round(i * 66.67, 2),
             "boxes": [{"conf": 0.9}] if 10 <= i < 40 else []} for i in range(50)]


def test_blind_zone_p99_sigma_zero():
    assert abs(blind_zone_p99(3, DT, 0.0) - 2 * DT) < 1e-6


def test_blind_zone_p99_grows_with_sigma():
    assert blind_zone_p99(3, DT, 10.0) > blind_zone_p99(3, DT, 0.0)
    assert blind_zone_p99(3, DT, 20.0) > blind_zone_p99(3, DT, 10.0)


def test_dwell_error_p99_formula():
    assert abs(dwell_error_p99(10.0) - 2.3263 * math.sqrt(2.0) * 10.0) < 1e-6


def test_dwell_error_stats_increases_with_sigma():
    a = dwell_error_stats(_frames(), 0.0, trials=200, seed=0)
    b = dwell_error_stats(_frames(), 20.0, trials=200, seed=0)
    assert a is not None and b is not None
    assert a["p99"] == 0.0          # σ=0 → 无误差
    assert b["p99"] > a["p99"]      # σ>0 → 误差出现
