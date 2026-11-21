# -*- coding: utf-8 -*-
from efo import corrected_dwell_ms, recalibrate_after_quant, suggest_k

DT = 1000.0 / 15.0


def _frames(confs):
    return [{"frame": i, "ts_ms": round(i * 66.67, 2),
             "boxes": [{"conf": c}] if c > 0 else []} for i, c in enumerate(confs)]


def test_corrected_dwell():
    assert abs(corrected_dwell_ms(300.0, 3, 5, DT) - 100.0) < 0.01


def test_suggest_k():
    # 最短动作 200ms → 3 帧；最短动作 100ms → 1 帧
    assert suggest_k(200.0, DT) == 3
    assert suggest_k(100.0, DT) == 1


def test_recalibrate_recovers_events():
    # 背景噪声 conf=0.40（低于阈值但不是零）；真实段 0.60；量化后入画窗口 3 帧漂到 0.48
    fp32 = _frames([0.40] * 10 + [0.60] * 30 + [0.40] * 10)
    int8 = _frames([0.40] * 10 + [0.48] * 3 + [0.60] * 27 + [0.40] * 10)

    r = recalibrate_after_quant(fp32, int8, conf_ref=0.5, k_in=3, m_out=5, tol_frames=2)
    assert r["baseline_f1"] < 1.0, f"原阈值下事件受损，实际 {r['baseline_f1']}"
    assert r["best_f1"] > r["baseline_f1"], f"重标定应恢复，实际 {r}"
    assert r["gain"] > 0
    # 最优阈值应落在「救回 0.48 的帧、又不误收 0.40 的背景」区间内
    assert 0.40 < r["best_conf"] < 0.5, f"最优阈值不合理：{r['best_conf']}"
