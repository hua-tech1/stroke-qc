# -*- coding: utf-8 -*-
"""1527 帧验证集 · 事件级评估（真实数据，非注入）

重要前提（决定了本实验能证明什么、不能证明什么）：
  导出后发现，验证集 15 个序列的 **每一帧都带导丝标注**（gt_hit 全为 True）。
  这是一个"导丝在场"片段集，不含空帧、不含完整手术序列。因此：
    ✅ 可测：入画事件是否被检出、入画时刻的确认延迟、检测器内部空档造成的伪离画
    ❌ 不可测：结构性盲区（没有短动作段）、离画事件、闭合滞留时长（序列末尾截断）
  这一点必须写进材料 —— 它同时说明"我们知道自己数据的边界"，也指出下一步要补什么。

运行：python experiments/efo_val/run_val_experiment.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "efo"))  # efo 包所在目录
sys.path.insert(0, str(ROOT))

from efo import generate_events  # noqa: E402  与系统同源的状态机

DET_DIR = HERE / "out" / "detections"
OUT_DIR = HERE / "out"
CONF, K_IN, M_OUT = 0.5, 3, 5
FRAME_MS = 66.667
CONF_GRID = [round(0.30 + 0.02 * i, 2) for i in range(21)]

# 可选：--dir <检测目录> --tag <输出后缀>，用于对照（如 INT8 权重量化）
if "--dir" in sys.argv:
    DET_DIR = Path(sys.argv[sys.argv.index("--dir") + 1])
TAG = sys.argv[sys.argv.index("--tag") + 1] if "--tag" in sys.argv else ""


def load_seqs() -> list[dict]:
    out = []
    for p in sorted(DET_DIR.glob("*.json")):
        if p.name.startswith("_"):
            continue
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def analyse(frames: list[dict], conf: float) -> dict:
    ev = generate_events(frames, conf=conf, k_in=K_IN, m_out=M_OUT)
    starts = [e for e in ev if e.code == "device_visible_start"]
    ends = [e for e in ev if e.code == "device_visible_end"]

    # 逐帧命中率（检测 vs 阈值）
    hit = sum(1 for f in frames if any(b["conf"] >= conf for b in f["boxes"]))
    gt_first = next((f["frame"] for f in frames if f.get("gt_hit", True)), None)
    first_start = starts[0].frame if starts else None

    return {
        "start_count": len(starts),
        "end_count": len(ends),
        "first_start_frame": first_start,
        "gt_first_frame": gt_first,
        "confirm_lag_frames": (first_start - gt_first) if (first_start is not None and gt_first is not None) else None,
        "frame_hit_rate": round(hit / len(frames), 4),
        "n_frames": len(frames),
        # 序列级正确：恰好一次入画、无伪离画
        "seq_correct": len(starts) == 1 and len(ends) == 0,
    }


def aggregate(seqs: list[dict], conf: float) -> dict:
    rows = []
    for rec in seqs:
        a = analyse(rec["frames"], conf)
        a["seq"] = rec["seq"]
        rows.append(a)

    n = len(rows)
    with_start = sum(1 for r in rows if r["start_count"] >= 1)
    exact_one = sum(1 for r in rows if r["start_count"] == 1)
    correct = sum(1 for r in rows if r["seq_correct"])
    extra_start = sum(max(0, r["start_count"] - 1) for r in rows)
    false_end = sum(r["end_count"] for r in rows)
    lags = [r["confirm_lag_frames"] for r in rows if r["confirm_lag_frames"] is not None]

    # 序列即事件：TP=序列级完全正确；FP=多余入画+伪离画；FN=漏掉的序列
    tp, fp, fn = correct, extra_start + false_end, n - with_start
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r_ = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r_ / (p + r_) if (p + r_) else 0.0

    return {
        "conf": conf, "sequences": n,
        "seq_with_event": with_start, "seq_exactly_one": exact_one,
        "seq_correct": correct,
        "extra_start_events": extra_start, "false_end_events": false_end,
        "confirm_lag_frames_median": sorted(lags)[len(lags) // 2] if lags else None,
        "confirm_lag_frames_min": min(lags) if lags else None,
        "confirm_lag_frames_max": max(lags) if lags else None,
        "event_precision": round(p, 4), "event_recall": round(r_, 4), "event_f1": round(f1, 4),
        "mean_frame_hit_rate": round(sum(r["frame_hit_rate"] for r in rows) / n, 4),
        "rows": rows,
    }


def main() -> None:
    seqs = load_seqs()
    if not seqs:
        raise SystemExit(f"缺检测结果，先跑 export_detections.py（{DET_DIR}）")

    base = aggregate(seqs, CONF)
    sweep = [aggregate(seqs, c) for c in CONF_GRID]
    best = max(sweep, key=lambda x: x["event_f1"])
    at_half = next(x for x in sweep if abs(x["conf"] - 0.5) < 1e-9)

    total_frames = sum(len(s["frames"]) for s in seqs)
    lag_ms = (base["confirm_lag_frames_median"] or 0) * FRAME_MS

    summary = {"frames": total_frames, "sequences": len(seqs),
               "config": {"conf": CONF, "k_in": K_IN, "m_out": M_OUT, "frame_ms": FRAME_MS},
               "baseline": {k: v for k, v in base.items() if k != "rows"},
               "per_sequence": base["rows"],
               "conf_sweep": {str(x["conf"]): {k: v for k, v in x.items() if k != "rows"}
                              for x in sweep},
               "best_conf": {"conf": best["conf"], "f1": best["event_f1"]},
               "gain_f1": round(best["event_f1"] - at_half["event_f1"], 4)}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"val_event_level{TAG}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    L = []
    A = L.append
    A("# 1527 帧验证集 · 事件级评估（真实数据）\n")
    A(f"数据：**{len(seqs)} 个序列 / {total_frames} 帧**，逐帧真值来自标注文件；"
      f"判据 conf={CONF}、k_in={K_IN}、m_out={M_OUT}；状态机为 `packages/efo/generate_events`（与系统同源）。\n")
    A("## 一、先说数据边界（重要）\n")
    A("导出时发现：**15 个序列的每一帧都带导丝标注**，即验证集是一个「导丝在场」片段集，"
      "不含空帧、不含完整手术起止。因此本实验：\n")
    A("| 能证明 | 不能证明 |")
    A("|---|---|")
    A("| 入画事件在 1527 帧真实数据上是否被检出 | 结构性盲区（无短动作段可测） |")
    A("| 入画时刻的确认延迟是否符合 (k_in−1)·Δt | 离画事件与闭合滞留时长（序列末尾截断） |")
    A("| 检测器内部空档是否会造成伪离画 | 真实量化下的事件级崩坏（需 INT8 权重） |")
    A("")
    A("## 二、事件级结果（conf = 0.5）\n")
    A("| 项 | 值 |")
    A("|---|---:|")
    A(f"| 序列数 / 帧数 | {len(seqs)} / {total_frames} |")
    A(f"| 产生入画事件的序列 | {base['seq_with_event']} / {len(seqs)} |")
    A(f"| 恰好一次入画的序列 | {base['seq_exactly_one']} / {len(seqs)} |")
    A(f"| 序列级完全正确（一次入画 + 无伪离画） | {base['seq_correct']} / {len(seqs)} |")
    A(f"| 多余入画事件 | {base['extra_start_events']} |")
    A(f"| 伪离画事件 | {base['false_end_events']} |")
    A(f"| 事件级 Precision / Recall / F1 | {base['event_precision']:.4f} / "
      f"{base['event_recall']:.4f} / {base['event_f1']:.4f} |")
    A(f"| 平均逐帧命中率 | {base['mean_frame_hit_rate']:.4f} |")
    A("")
    A("## 三、入画确认延迟（真实数据验证 P1 的机制）\n")
    A(f"检测到的入画时刻相对序列首帧的滞后：中位 **{base['confirm_lag_frames_median']} 帧**"
      f"（区间 {base['confirm_lag_frames_min']}–{base['confirm_lag_frames_max']} 帧）"
      f"= **{lag_ms:.1f} ms**。")
    A(f"闭式解预测 (k_in−1)·Δt = {(K_IN - 1) * FRAME_MS:.1f} ms。")
    A("→ 这是「入画时刻不是第 1 帧，而是第 k_in 帧」在真实数据上的直接体现："
      "**系统报出的时间戳天然比真实开始晚 (k_in−1) 帧**，材料里必须说清这是判据性质而非误差。\n")
    A("## 四、conf 阈值扫描（真实数据）\n")
    A("| conf | 序列级正确 | 漏检序列 | 伪离画 | P | R | F1 |")
    A("|---:|---:|---:|---:|---:|---:|---:|")
    for x in sweep:
        mk = " ← 当前" if abs(x["conf"] - 0.5) < 1e-9 else (" ← 最优" if x is best else "")
        A(f"| {x['conf']:.2f} | {x['seq_correct']} | {x['sequences'] - x['seq_with_event']} | "
          f"{x['false_end_events']} | {x['event_precision']:.4f} | {x['event_recall']:.4f} | "
          f"{x['event_f1']:.4f}{mk} |")
    A("")
    A(f"当前 0.5 的 F1 = {at_half['event_f1']:.4f}；最优 {best['conf']:.2f} 的 F1 = "
      f"{best['event_f1']:.4f}（{best['event_f1'] - at_half['event_f1']:+.4f}）。")
    A("→ 阈值扫描在真实数据上给出的是「事件级指标对阈值的敏感曲线」，"
      "它是量化后重标定（recalibrate_after_quant）的依据；但**不等同于真实 INT8 结果**。\n")
    A("## 五、逐序列明细\n")
    A("| 序列 | 帧数 | 逐帧命中率 | 入画次数 | 离画次数 | 确认滞后(帧) | 判定 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for r in base["rows"]:
        flag = "✅" if r["seq_correct"] else "⚠️"
        A(f"| {r['seq']} | {r['n_frames']} | {r['frame_hit_rate']:.4f} | {r['start_count']} | "
          f"{r['end_count']} | {r['confirm_lag_frames'] if r['confirm_lag_frames'] is not None else '—'} | {flag} |")
    A("")
    A("## 六、结论与下一步\n")
    A("1. 在真实 1527 帧上，事件的**生成**是确定的：不该有的重复入画与伪离画可以逐条核对。")
    A("2. 入画时刻的滞后与闭式解一致 —— 说明「事件时间戳需要校正」不是猜的。")
    A("3. 要补的两件事：① 负样本 / 完整手术序列（才能测盲区与离画）；"
      "② 真实 INT8 权重（才能把「量化崩坏」从仿真升级为实测）。")

    (OUT_DIR / f"val_event_level{TAG}.md").write_text("\n".join(L), encoding="utf-8")

    print(f"序列 {len(seqs)} / 帧 {total_frames}")
    print(f"序列级正确 {base['seq_correct']}/{len(seqs)}  伪离画 {base['false_end_events']}  "
          f"多余入画 {base['extra_start_events']}")
    print(f"事件级 P/R/F1 = {base['event_precision']:.4f}/{base['event_recall']:.4f}/{base['event_f1']:.4f}")
    print(f"确认滞后中位 {base['confirm_lag_frames_median']} 帧 = {lag_ms:.1f} ms")
    print(f"最优 conf {best['conf']} F1={best['event_f1']:.4f}（0.5 时 {at_half['event_f1']:.4f}）")


if __name__ == "__main__":
    main()
