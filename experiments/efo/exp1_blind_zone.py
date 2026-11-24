# -*- coding: utf-8 -*-
"""实验一：帧确认的结构性盲区（P1）

命题
----
若事件判定采用"连续 k_in 帧命中才算入画"，则任何可见时长
L < k_in 帧的器械事件，在理想检测器（逐帧 100% 命中）下也必然漏检。

这不是模型精度问题，是判据本身的结构性质，因此与置信度阈值、
与检测器好坏都无关。推论：盲区宽度 = (k_in - 1) 帧 = (k_in - 1) * Δt 毫秒。

实验设计（全枚举，无随机）
--------------------------
画布 60 帧，在其中放置一段长度 L 的可见段，起点遍历所有合法位置。
对每个 (k_in, L) 组合，统计"至少产生一个入画事件"的比例。
若命题成立，则 L < k_in 时该比例必须严格为 0。

对照组
------
- k_in = 1（无确认）：盲区应为 0，用来证明"盲区由 k 引入"
- k_in = 2..5：盲区宽度应随 k 线性增长
"""
from __future__ import annotations

from . import core

CANVAS = 60
K_RANGE = [1, 2, 3, 4, 5]
L_RANGE = list(range(1, 13))


def run() -> dict:
    frame_ms = 1000.0 / core.C.FPS
    table = {}
    detail = []

    for k in K_RANGE:
        row = {}
        for L in L_RANGE:
            hits_found = 0
            trials = 0
            for off in range(0, CANVAS - L + 1):
                hits = [False] * CANVAS
                for i in range(off, off + L):
                    hits[i] = True
                frames = core.build_frames(hits, frame_ms)
                evs = core.run_sm(frames, conf=core.C.CONF, k_in=k, m_out=core.C.M_OUT)
                trials += 1
                if core.events_of(evs, core.START):
                    hits_found += 1
            rate = hits_found / trials
            row[L] = rate
            detail.append({
                "k_in": k, "visible_frames": L,
                "trials": trials, "detected": hits_found,
                "detection_rate": round(rate, 4),
                "blind_zone_ms": round((k - 1) * frame_ms, 2),
            })
        table[k] = row

    # 盲区实测宽度：检出率为 0 的最大 L
    measured_blind = {}
    for k in K_RANGE:
        w = 0
        for L in L_RANGE:
            if table[k][L] == 0.0:
                w = L
            else:
                break
        measured_blind[k] = w

    payload = {
        "experiment": "P1-structural-blind-zone",
        "frame_ms": round(frame_ms, 3),
        "fps": core.C.FPS,
        "m_out": core.C.M_OUT,
        "canvas_frames": CANVAS,
        "table": {str(k): {str(L): v for L, v in row.items()} for k, row in table.items()},
        "measured_blind_frames": {str(k): v for k, v in measured_blind.items()},
        "predicted_blind_frames": {str(k): k - 1 for k in K_RANGE},
        "detail": detail,
    }

    header = ["k_in", "盲区(实测,帧)", "盲区(预测,帧)", "盲区(ms)"] + [f"L={L}" for L in L_RANGE]
    rows = []
    for k in K_RANGE:
        rows.append([k, measured_blind[k], k - 1, round((k - 1) * frame_ms, 1)]
                    + [f"{table[k][L]:.2f}" for L in L_RANGE])
    t1 = ("## 检出率表（每格 = 该可见时长下的入画事件检出率）\n\n"
          + core.md_table(header, rows))
    t2 = ("## 命题检验\n\n"
          "预测盲区 = k_in - 1 帧；实测与预测逐行相等即命题成立。")
    core.write_outputs("exp1_blind_zone", payload, [t1, t2])
    return payload


if __name__ == "__main__":
    import json
    print(json.dumps(run()["measured_blind_frames"], ensure_ascii=False, indent=2))
