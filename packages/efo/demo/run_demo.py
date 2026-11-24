# -*- coding: utf-8 -*-
"""efo 最小示例：在任意检测输出上 10 行跑通「事件化 + 三命题 + 校准」。"""
import sys
from pathlib import Path

# 支持「直接运行」与「pip install 后运行」两种方式
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from efo import (
    blind_zone_ms,
    corrected_dwell_ms,
    dwell_bias_center_ms,
    generate_events,
    recalibrate_after_quant,
)

FRAME_MS = 1000.0 / 15.0


def demo():
    # 1) 模拟一段检测：前 10 帧无器械，中间 30 帧命中，后 10 帧无
    frames = [{"frame": i, "ts_ms": round(i * FRAME_MS, 2),
               "boxes": [{"conf": 0.9}] if 10 <= i < 40 else []} for i in range(50)]

    # 2) 事件化
    events = generate_events(frames, conf=0.5, k_in=3, m_out=5)
    print("事件：", [e.to_dict() for e in events])

    # 3) 三命题
    print("盲区：", round(blind_zone_ms(3, FRAME_MS), 1), "ms")
    print("滞留偏置（中心口径）：", round(dwell_bias_center_ms(3, 5, FRAME_MS), 1), "ms")

    # 4) 偏置校正（若有闭合事件）
    if len(events) >= 2:
        raw = events[-1].ts_ms - events[0].ts_ms
        print("原始滞留：", round(raw, 1), "ms → 校正后：",
              round(corrected_dwell_ms(raw, 3, 5, FRAME_MS), 1), "ms")

    # 5) 量化感知重标定（模拟量化漂移：入画窗口 3 帧 conf 掉到 0.48，背景噪声 0.40）
    def int8_frame(f):
        c = f["boxes"][0]["conf"] if f["boxes"] else 0.40
        if 10 <= f["frame"] < 13:
            c = 0.48          # 入画窗口漂移，低于 0.5
        elif 13 <= f["frame"] < 40:
            c = 0.90          # 真实命中
        else:
            c = 0.40          # 背景噪声（低于阈值，但不是零）
        return {"frame": f["frame"], "ts_ms": f["ts_ms"], "boxes": [{"conf": c}]}

    int8 = [int8_frame(f) for f in frames]
    r = recalibrate_after_quant(frames, int8, conf_ref=0.5, k_in=3, m_out=5)
    print("量化重标定：", {k: v for k, v in r.items() if k != "baseline"})


if __name__ == "__main__":
    demo()
