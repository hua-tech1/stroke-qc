# -*- coding: utf-8 -*-
"""FP32 vs INT8 权重量化：逐帧置信度漂移对照，产出 summary.json

前端「量化感知重标定」面板要显示真实数字，而不是写死在 HTML 里。
本脚本把两组逐帧检测结果（FP32 / INT8 权重）对齐比较，输出：

  mean_drift / p99_drift / max_drift   逐帧最大置信度的漂移
  frames_crossing                      跨过判定阈值 0.5 的帧数
  event_identical                      事件序列是否完全相同

运行（需先跑过 export_detections.py 与 weight_int8.py）：
  python experiments/int8/compare.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "efo"))

from efo import generate_events  # noqa: E402

FP32_DIR = ROOT / "experiments" / "efo_val" / "out" / "detections"
INT8_DIR = HERE / "out" / "detections_int8w"
OUT = HERE / "out" / "summary.json"
CONF, FRAME_MS = 0.5, 66.667


def max_conf(frame: dict) -> float:
    return max([b["conf"] for b in frame.get("boxes", [])], default=0.0)


def main() -> None:
    if not FP32_DIR.exists() or not INT8_DIR.exists():
        raise SystemExit(f"缺检测结果：{FP32_DIR} / {INT8_DIR}")

    drifts, cross, frames = [], 0, 0
    same_events, seqs = 0, 0

    for p in sorted(FP32_DIR.glob("*.json")):
        q = INT8_DIR / p.name
        if not q.exists():
            continue
        a = json.loads(p.read_text(encoding="utf-8"))["frames"]
        b = json.loads(q.read_text(encoding="utf-8"))["frames"]
        seqs += 1

        for fa, fb in zip(a, b):
            ca, cb = max_conf(fa), max_conf(fb)
            drifts.append(abs(ca - cb))
            frames += 1
            if (ca >= CONF) != (cb >= CONF):
                cross += 1

        ea = generate_events(a, conf=CONF, k_in=3, m_out=5)
        eb = generate_events(b, conf=CONF, k_in=3, m_out=5)
        if [(e.code, e.frame) for e in ea] == [(e.code, e.frame) for e in eb]:
            same_events += 1

    s = sorted(drifts)
    summary = {
        "sequences": seqs,
        "frames": frames,
        "mean_drift": round(statistics.mean(drifts), 6),
        "p99_drift": round(s[int(0.99 * (len(s) - 1))], 6),
        "max_drift": round(s[-1], 6),
        "threshold": CONF,
        "frames_crossing": cross,
        "event_identical_sequences": same_events,
        "method": "per-channel symmetric INT8 weights (fake-quant), activations FP32",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{frames} 帧 / {seqs} 序列")
    print(f"  mean |Δconf| = {summary['mean_drift']}")
    print(f"  p99  |Δconf| = {summary['p99_drift']}")
    print(f"  max  |Δconf| = {summary['max_drift']}")
    print(f"  跨阈值 {CONF} 帧数 = {cross}")
    print(f"  事件完全一致的序列 = {same_events}/{seqs}")
    print(f"输出：{OUT}")


if __name__ == "__main__":
    main()
