# -*- coding: utf-8 -*-
from efo import (
    blind_zone_ms,
    detection_upper_bound,
    dwell_bias_center_ms,
    dwell_bias_interval_ms,
)

DT = 1000.0 / 15.0  # 66.666...ms


def test_blind_zone():
    assert abs(blind_zone_ms(3, DT) - 133.333) < 0.01
    assert blind_zone_ms(1, DT) == 0.0
    assert blind_zone_ms(5, DT) > blind_zone_ms(3, DT)


def test_dwell_bias():
    assert abs(dwell_bias_interval_ms(3, 5, DT) - 133.333) < 0.01
    assert abs(dwell_bias_center_ms(3, 5, DT) - 200.0) < 0.01
    # k > m 时偏置为负（离画确认比入画还短）
    assert dwell_bias_center_ms(5, 2, DT) < 0


def test_detection_upper_bound():
    assert abs(detection_upper_bound(0.95, 3) - 0.857375) < 1e-6
    assert abs(detection_upper_bound(0.95, 5) - 0.95 ** 5) < 1e-9
