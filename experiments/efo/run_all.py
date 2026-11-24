# -*- coding: utf-8 -*-
"""EFO 实验总入口

用法（在仓库根目录执行）：

    python -m experiments.efo.run_all

产出：
    experiments/efo/out/exp1_blind_zone.{json,md}
    experiments/efo/out/exp2_amplification.{json,md}
    experiments/efo/out/exp3_dwell_bias.{json,md}
    experiments/efo/out/SUMMARY.md
"""
from __future__ import annotations

from datetime import datetime

from . import core, exp1_blind_zone, exp2_amplification, exp3_dwell_bias


def _fmt(x, nd=2):
    return "n/a" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def main() -> None:
    print("[1/3] 结构性盲区 ...")
    p1 = exp1_blind_zone.run()

    print("[2/3] 指数放大 ...")
    p2 = exp2_amplification.run()

    print("[3/3] 滞留偏置 ...")
    p3 = exp3_dwell_bias.run()

    frame_ms = p1["frame_ms"]
    k_default = core.C.K_IN
    blind = p1["measured_blind_frames"]

    # 2a：k=3, p=0.95 处
    a95 = [x for x in p2["exp2a"] if x["k_in"] == 3 and abs(x["p"] - 0.95) < 1e-9]
    a95 = a95[0] if a95 else None

    # 3：主配置偏差
    rows35 = p3["combos"]["3,5"]
    det35 = [r for r in rows35 if r["detected"]]
    bias_i = core.mean([r["bias_interval_ms"] for r in det35]) if det35 else None
    bias_c = core.mean([r["bias_center_ms"] for r in det35]) if det35 else None

    lines = [
        "# EFO 实验汇总（事件保真优化）",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"配置：fps={core.C.FPS}，Δt={frame_ms}ms，CONF={core.C.CONF}",
        "",
        "## 三条命题的实测结论",
        "",
        "| 命题 | 预测 | 实测 | 判定 |",
        "|---|---|---|---|",
        f"| P1 结构性盲区 | 盲区 = k_in-1 = {k_default - 1} 帧 | "
        f"{blind[str(k_default)]} 帧 | {'成立' if blind[str(k_default)] == k_default - 1 else '不成立'} |",
        f"| P2 指数放大（k=3, p=0.95） | p^k = {_fmt(a95['predicted_p_pow_k'], 4) if a95 else 'n/a'} | "
        f"{_fmt(a95['measured_rate'], 4) if a95 else 'n/a'} | "
        f"{'成立' if a95 and a95['abs_error'] < 0.02 else '待核'} |",
        f"| P3 滞留偏置（区间口径） | (m_out-k_in)Δt = {_fmt((core.C.M_OUT - core.C.K_IN) * frame_ms, 1)} ms | "
        f"{_fmt(bias_i, 1)} ms | {'成立' if bias_i is not None and abs(bias_i - (core.C.M_OUT - core.C.K_IN) * frame_ms) < 0.5 else '待核'} |",
        "",
        "## 可直接引用的数字",
        "",
        f"- 器械可见时长不足 **{k_default - 1} 帧（{(k_default - 1) * frame_ms:.0f} ms）** 时，"
        f"系统在当前判据下**必然漏检**（检出率 0，与模型精度无关）。",
        f"- 单帧命中率 0.95 时，事件级检出率降至 **{_fmt(a95['measured_rate'], 4) if a95 else 'n/a'}**；"
        f"相对单帧损失 **{_fmt((0.95 ** 3 - 1) * 100, 1)}%**。",
        f"- 滞留时长在理想检测下仍被系统性高估 **{_fmt(bias_i, 1)} ms**（区间口径）"
        f"／**{_fmt(bias_c, 1)} ms**（中心口径）。",
        "- 追加发现：现有 `dwell_ms()` 返回 `int(...)`，把滞留时长截断到整毫秒，"
        "在闭式解之上再引入约 0.33 ms 的截断损失（见 exp3）。",
        "",
        "## 说明与边界",
        "",
        "- 全部实验以项目内 `app/modules/events/state_machine.py` 的 `generate_events` 为唯一实现，"
        "实验与系统同源。",
        "- 实验一、三为全枚举确定性实验，无随机；实验二固定随机种子，报告内已写回。",
        "- 本批数据来自 `data/demo/json` 的两段离线序列；"
        "**1527 帧验证集尚未接入**，接入后只需替换 `list_sequences()` 的数据源即可复算。",
        "- 命题 P2 的工程结论（真实序列上的事件 F1 衰减）依赖注入噪声模型，"
        "不等同于真实量化误差，材料中应注明。",
    ]

    out = core.OUT_DIR / "SUMMARY.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print()
    print("\n".join(lines))
    print(f"\n已写入：{out}")


if __name__ == "__main__":
    main()
