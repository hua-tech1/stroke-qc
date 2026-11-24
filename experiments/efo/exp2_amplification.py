# -*- coding: utf-8 -*-
"""实验二：帧级误差的事件级指数放大（P2）

命题
----
在"连续 k 帧确认"下，单帧命中概率 p 会退化为 p^k：

    P(入画事件被检出) = p^k        （当可见段长度恰为 k 帧时取等号）

因此帧级精度 5% 的下降，在 k=3 时会放大成约 14% 的事件级检出损失。
推论：任何按帧级 mAP 验收的部署流程（包括量化后验收）都可能系统性高估
事件级可靠性。

实验设计
--------
2a 合成对照（可解析验证）
    可见段长度 L = k（恰好一个确认窗口），每帧独立以概率 p 命中，
    N=2000 次重复，测检出率，与 p^k 解析值对比。
    若实测≈解析，则"p^k 定律"成立。

2b 真实序列注入（工程可证）
    在真实检测序列上按概率 q 注入漏检/误检（帧级错误率≈q），
    以干净运行的事件为参照，测事件级 F1 随 q 的衰减。
    用来回答："帧级只错 5%，事件级会错多少？"

随机性全部固定种子，报告写回种子值。
"""
from __future__ import annotations

from . import core

SEED_A = 20261120
SEED_B = 20261120
CANVAS = 60
OFFSET = 10
TRIALS_A = 2000
REPS_B = 60
TOL_FRAMES = 2


def _p_sweep() -> list[float]:
    return [round(0.80 + 0.01 * i, 2) for i in range(21)]


def exp2a() -> list[dict]:
    """可见段恰为 k 帧：实测检出率 vs p^k。"""
    frame_ms = 1000.0 / core.C.FPS
    r = core.rng(SEED_A)
    out = []
    for k in [2, 3, 4, 5]:
        for p in _p_sweep():
            hits_found = 0
            for _ in range(TRIALS_A):
                hits = [False] * CANVAS
                for i in range(OFFSET, OFFSET + k):
                    hits[i] = r.random() < p
                frames = core.build_frames(hits, frame_ms)
                evs = core.run_sm(frames, conf=core.C.CONF, k_in=k, m_out=core.C.M_OUT)
                if core.events_of(evs, core.START):
                    hits_found += 1
            lo, hi = core.wilson_ci(hits_found, TRIALS_A)
            out.append({
                "k_in": k, "p": p,
                "predicted_p_pow_k": round(p ** k, 4),
                "measured_rate": round(hits_found / TRIALS_A, 4),
                "ci95": [round(lo, 4), round(hi, 4)],
                "abs_error": round(abs(hits_found / TRIALS_A - p ** k), 4),
            })
    return out


def _pick_sequence() -> str:
    """优先选同时含入画与离画事件的序列 —— 事件数越多，F1 越有区分度。"""
    best = None
    for seq in core.list_sequences():
        det = core.load_detection(seq)
        evs = core.run_sm(core.build_frames_from_detection(det, core.hit_flags(det)))
        n_start = len(core.events_of(evs, core.START))
        n_end = len(core.events_of(evs, core.END))
        if n_start and n_end:
            return seq
        if n_start and best is None:
            best = seq
    if best is not None:
        return best
    raise RuntimeError("没有可用的演示序列")


def exp2b(seq: str | None = None) -> dict:
    """真实序列注入噪声，测事件级 F1 随帧级错误的衰减。"""
    seq = seq or _pick_sequence()
    det = core.load_detection(seq)
    clean_hits = core.hit_flags(det)
    ref_events = core.run_sm(core.build_frames_from_detection(det, clean_hits))
    r = core.rng(SEED_B)

    rows = []
    for q in [round(0.01 * i, 3) for i in range(0, 21)]:
        f1s, accs, dts, precs, recs = [], [], [], [], []
        for _ in range(REPS_B):
            hits = [h if r.random() >= q else (not h) for h in clean_hits]
            frames = core.build_frames_from_detection(det, hits)
            evs = core.run_sm(frames)
            m = core.match_events(ref_events, evs, tol_frames=TOL_FRAMES)
            f1s.append(m.f1)
            precs.append(m.precision)
            recs.append(m.recall)
            accs.append(sum(1 for a, b in zip(hits, clean_hits) if a == b) / len(hits))
            # 匹配对上入画事件的时刻偏移（帧差 -> 毫秒）
            pairs, _, _ = core.match_pairs(ref_events, evs, tol_frames=TOL_FRAMES)
            for ref_e, tst_e in pairs:
                if tst_e.code == core.START:
                    dts.append(abs(tst_e.frame - ref_e.frame) * 1000.0 / core.C.FPS)
        rows.append({
            "q_frame_error": q,
            "frame_accuracy": round(core.mean(accs), 4),
            "event_precision": round(core.mean(precs), 4),
            "event_recall": round(core.mean(recs), 4),
            "event_f1_mean": round(core.mean(f1s), 4),
            "event_f1_p05": round(core.pct(f1s, 0.05), 4),
            "event_f1_p95": round(core.pct(f1s, 0.95), 4),
            "dt_p50_ms": round(core.pct(dts, 0.50), 1) if dts else None,
        })
    return {
        "sequence": seq,
        "frames": len(clean_hits),
        "clean_event_count": len(ref_events),
        "tolerance_frames": TOL_FRAMES,
        "seed": SEED_B,
        "rows": rows,
    }


def run() -> dict:
    a = exp2a()
    b = exp2b()

    # 2a 表：每个 k 一行，列出 p=0.95 处的对照
    rows_a = []
    for k in [2, 3, 4, 5]:
        sub = [x for x in a if x["k_in"] == k]
        hit = next((x for x in sub if abs(x["p"] - 0.95) < 1e-9), None)
        rows_a.append([k,
                       f"{hit['predicted_p_pow_k']:.4f}" if hit else "-",
                       f"{hit['measured_rate']:.4f}" if hit else "-",
                       f"{hit['ci95'][0]:.4f}~{hit['ci95'][1]:.4f}" if hit else "-",
                       f"{hit['abs_error']:.4f}" if hit else "-",
                       f"{(0.95 ** k - 1) * 100:+.1f}%"])
    t_a = ("## 2a 解析对照（p = 0.95 处）\n\n"
           + core.md_table(["k_in", "预测 p^k", "实测检出率", "95% CI", "绝对误差", "相对单帧的损失"],
                           rows_a))

    rows_b = [[r["q_frame_error"], r["frame_accuracy"], r["event_precision"],
               r["event_recall"], r["event_f1_mean"],
               f'{r["event_f1_p05"]}~{r["event_f1_p95"]}', r["dt_p50_ms"]]
              for r in b["rows"]]
    t_b = (f'## 2b 真实序列注入（{b["sequence"]}，{b["frames"]} 帧，'
           f'{b["clean_event_count"]} 个参照事件）\n\n'
           + core.md_table(["帧级错误率 q", "帧级准确率", "事件 P", "事件 R",
                            "事件 F1 均值", "F1 5%~95%", "Δt P50 (ms)"], rows_b))

    payload = {"experiment": "P2-exponential-amplification",
               "seed_a": SEED_A, "trials_a": TRIALS_A, "exp2a": a, "exp2b": b}
    core.write_outputs("exp2_amplification", payload, [t_a, t_b])
    return payload


if __name__ == "__main__":
    d = run()
    print("2a n =", len(d["exp2a"]), "| 2b seq =", d["exp2b"]["sequence"])
