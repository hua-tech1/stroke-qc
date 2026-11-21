# -*- coding: utf-8 -*-
"""校准：把三命题从「测量」升级成「解法」。

  corrected_dwell_ms       P3 解法：偏置校正，输出校正后的滞留时长
  suggest_k                P1 解法：盲区感知的参数建议，反推 k 上界
  recalibrate_after_quant  P2 解法：量化感知重标定，量化后自动重选阈值救回事件召回

诚实边界：阈值重标定是旧方法；这里的价值不在算法本身，而在把它做成
「量化后的事件级恢复能力」——部署/量化验收流程中通常缺失的一环。
"""
from __future__ import annotations

from typing import Sequence

from .events import generate_events
from .laws import dwell_bias_center_ms
from .metrics import match_events


def corrected_dwell_ms(raw_ms: float, k_in: int, m_out: int, frame_ms: float) -> float:
    """P3 解法：校正滞留时长（中心口径）。

    校正后 = 原始 - (m_out - k_in + 1) * Δt。
    """
    return raw_ms - dwell_bias_center_ms(k_in, m_out, frame_ms)


def suggest_k(min_action_ms: float, frame_ms: float) -> int:
    """P1 解法：盲区感知的参数建议。

    返回不遗漏「可见时长 >= min_action_ms」动作的最大 k_in。
    推导：可见 L 帧的动作可被检出当且仅当 L >= k_in，故 k_in <= min_action_ms / Δt。
    """
    fps = 1000.0 / frame_ms
    k = int(min_action_ms * fps / 1000.0 + 1e-9)
    return max(1, k)


def recalibrate_after_quant(
    fp32_frames: Sequence,
    int8_frames: Sequence,
    *,
    conf_ref: float = 0.5,
    k_in: int = 3,
    m_out: int = 5,
    conf_grid: Sequence[float] | None = None,
    tol_frames: int = 2,
) -> dict:
    """P2 解法：量化感知重标定。

    量化会整体漂移逐帧置信度分布，原阈值 conf_ref 不再是事件级最优。
    以 FP32 输出的事件为参照，在 INT8 输出上网格搜索 conf，取事件级 F1 最大者。

    返回
    ----
    {
      "ref_conf": conf_ref,
      "baseline_f1": 原阈值下的事件级 F1,
      "best_conf": 事件级 F1 最大的阈值,
      "best_f1": 该阈值下的 F1,
      "gain": best_f1 - baseline_f1,
    }
    """
    conf_grid = list(conf_grid) if conf_grid is not None \
        else [round(0.30 + 0.02 * i, 2) for i in range(21)]  # 0.30 .. 0.70

    ref_events = generate_events(fp32_frames, conf=conf_ref, k_in=k_in, m_out=m_out)
    baseline = match_events(
        ref_events,
        generate_events(int8_frames, conf=conf_ref, k_in=k_in, m_out=m_out),
        tol_frames,
    )

    best_conf, best_f1 = conf_ref, baseline.f1
    for c in conf_grid:
        if abs(c - conf_ref) < 1e-9:
            continue
        ev = generate_events(int8_frames, conf=c, k_in=k_in, m_out=m_out)
        m = match_events(ref_events, ev, tol_frames)
        if m.f1 > best_f1:
            best_conf, best_f1 = c, m.f1

    return {
        "ref_conf": conf_ref,
        "baseline_f1": round(baseline.f1, 4),
        "baseline": baseline.to_dict(),
        "best_conf": best_conf,
        "best_f1": round(best_f1, 4),
        "gain": round(best_f1 - baseline.f1, 4),
    }
