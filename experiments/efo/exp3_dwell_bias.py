# -*- coding: utf-8 -*-
"""实验三：滞回判定引入的滞留时长偏置（P3）

命题
----
在无噪声、逐帧理想检测的条件下，状态机输出的滞留时长仍系统性偏离真值：

    区间口径（覆盖时长）: 偏差 = (m_out - k_in)     * Δt
    中心口径（首末帧中心）: 偏差 = (m_out - k_in + 1) * Δt

k_in=3, m_out=5, Δt=66.67ms 时，区间口径高估 +133.3 ms，中心口径高估 +200.0 ms。

偏差来源不是模型，而是判据的"确认延迟不对称"：
入画要等 k 帧（相对首帧延迟 k-1 帧），离画要等 m 帧（相对末帧延迟 m 帧）。

实验设计
--------
合成可见段，长度 L 从 1 扫到 80 帧，全部理想命中，无随机。
对多种 (k_in, m_out) 组合重复，检验闭式解是否逐行成立。
L < k_in 时不应产生任何事件（与实验一一致）。
"""
from __future__ import annotations

from . import core

CANVAS = 200
OFFSET = 20
L_RANGE = list(range(1, 81))
COMBOS = [(3, 5), (2, 5), (3, 3), (5, 2), (1, 1)]


def _one(L: int, k_in: int, m_out: int, frame_ms: float) -> dict:
    hits = [False] * CANVAS
    for i in range(OFFSET, OFFSET + L):
        hits[i] = True
    frames = core.build_frames(hits, frame_ms)
    evs = core.run_sm(frames, conf=core.C.CONF, k_in=k_in, m_out=m_out)

    starts = core.events_of(evs, core.START)
    ends = core.events_of(evs, core.END)
    measured = core.dwell_ms(frames, evs)          # 系统实现：int 截断
    if starts and ends:
        measured_float = round(max(e.ts_ms for e in ends) - min(e.ts_ms for e in starts), 2)
    else:
        measured_float = None

    true_interval = L * frame_ms
    true_center = (L - 1) * frame_ms
    return {
        "L": L,
        "detected": bool(starts),
        "closed": bool(ends),
        "measured_ms": measured,                   # 系统口径（整数毫秒）
        "measured_float_ms": measured_float,       # 精确口径
        "truncation_ms": None if (measured is None or measured_float is None)
        else round(measured_float - measured, 2),
        "true_interval_ms": round(true_interval, 2),
        "true_center_ms": round(true_center, 2),
        "bias_interval_ms": None if measured_float is None
        else round(measured_float - true_interval, 2),
        "bias_center_ms": None if measured_float is None
        else round(measured_float - true_center, 2),
        "start_frame": starts[0].frame if starts else None,
        "end_frame": ends[0].frame if ends else None,
    }


def run() -> dict:
    frame_ms = 1000.0 / core.C.FPS
    results = {}
    check_rows = []

    for k_in, m_out in COMBOS:
        rows = [_one(L, k_in, m_out, frame_ms) for L in L_RANGE]
        results[f"{k_in},{m_out}"] = rows

        detected = [r for r in rows if r["detected"]]
        # ts_ms 保留两位小数，偏差会有 ±0.01ms 的舍入抖动，因此用容差判定
        TOL = 0.05
        bi = [r["bias_interval_ms"] for r in detected]
        bc = [r["bias_center_ms"] for r in detected]
        tc = [r["truncation_ms"] for r in detected if r["truncation_ms"] is not None]

        pred_i = round((m_out - k_in) * frame_ms, 2)
        pred_c = round((m_out - k_in + 1) * frame_ms, 2)
        ok_i = bool(bi) and (max(bi) - min(bi) <= TOL) and abs(core.mean(bi) - pred_i) <= TOL
        ok_c = bool(bc) and (max(bc) - min(bc) <= TOL) and abs(core.mean(bc) - pred_c) <= TOL
        check_rows.append([
            f"{k_in},{m_out}",
            len(detected),
            f"{core.mean(bi):.2f} [{min(bi):.2f}~{max(bi):.2f}]" if bi else "n/a",
            pred_i,
            f"{core.mean(bc):.2f} [{min(bc):.2f}~{max(bc):.2f}]" if bc else "n/a",
            pred_c,
            f"{core.mean(tc):.2f}" if tc else "n/a",
            "✓" if (ok_i and ok_c) else "✗",
        ])

    t1 = ("## 闭式解检验（逐 L 检验偏差是否恒等于预测值）\n\n"
          + core.md_table(
              ["(k_in,m_out)", "检出段数", "实测 Δ区间", "预测 Δ区间",
               "实测 Δ中心", "预测 Δ中心", "系统截断(ms)", "成立"], check_rows))
    t1 += ("\n\n> 说明：`dwell_ms()` 返回 `int(...)`，滞留时长被截断到整毫秒，"
           "在闭式解之上再引入 0~1 ms 的负向偏差。上表“系统截断”列即该部分。")

    main = results["3,5"]
    sample = [[r["L"], r["true_interval_ms"], r["measured_float_ms"], r["measured_ms"],
               r["bias_interval_ms"], r["bias_center_ms"]]
              for r in main if r["L"] in (1, 2, 3, 4, 5, 10, 20, 40, 80)]
    t2 = ("## 主配置 (k_in=3, m_out=5) 抽样\n\n"
          + core.md_table(["L 帧", "真值区间(ms)", "实测·精确(ms)", "实测·系统(ms)",
                           "偏差·区间口径(ms)", "偏差·中心口径(ms)"], sample))

    payload = {
        "experiment": "P3-dwell-bias",
        "frame_ms": round(frame_ms, 3),
        "fps": core.C.FPS,
        "offsets": {"canvas": CANVAS, "start_offset": OFFSET},
        "combos": {k: v for k, v in results.items()},
    }
    core.write_outputs("exp3_dwell_bias", payload, [t1, t2])
    return payload


if __name__ == "__main__":
    import json
    d = run()
    print(json.dumps({k: len(v) for k, v in d["combos"].items()}, ensure_ascii=False))
