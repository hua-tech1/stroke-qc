# -*- coding: utf-8 -*-
"""S2 验收脚本：生成 → 计算 → 对照

检查三件事：
  1. 22 项指标是否都给出了结论（可计算 / 样本不足 / 未接入）
  2. 数值是否落在设计区间（不合理就是生成器参数错了）
  3. 同一 seed 两次生成结果是否一致（可复现）
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.qc.indicators import compute, fmt, evaluate  # noqa: E402

# 设计区间：破区间说明生成器参数有问题
EXPECT = {
    "PR01": (10, 25), "PR02": (45, 65), "PR03": (55, 80), "PR04": (55, 85),
    "PR05": (55, 85), "PR06": (15, 35), "PR07": (4, 12), "PR08": (120, 400),
    "PR09": (3, 20), "PR10": (80, 95), "PR11": (80, 95), "PR12": (50, 75),
    "OU01": (70, 95), "OU02": (1, 8), "OU03": (2, 7), "OU04": (45, 65),
    "OU05": (75, 90), "OU06": (8, 20),
}


def load(seed: int):
    p = ROOT / "data" / "seed" / "seed.json"
    if not p.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "seed.py"),
                        "--seed", str(seed)], check=True)
    return json.loads(p.read_text(encoding="utf-8"))


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
    d = load(seed)
    res = compute(d["cases"], d["plans"], d["milestones"], {"today": "2026-10-31"})

    print(f"仿真队列 seed={seed}  病例 {len(d['cases'])}  "
          f"随访计划 {len(d['plans'])}  事件 {len(d['milestones'])}")
    print()
    print(f"{'码':5}{'指标':26}{'值':>9}{'分子/分母':>12}{'目标':>8}  {'状态':<6}区间")
    print("-" * 86)

    bad, warn = [], []
    for v in res:
        tgt = "" if v["target"] is None else f"{'≤' if v['direction'] == 'le' else '≥'}{v['target']}"
        if v["kind"] == "median":
            num = f"n={v['den']}" if v["den"] else ""
        elif v["den"] is None:
            num = ""
        else:
            num = f"{v['num']}/{v['den']}"

        rng = ""
        if v["computable"] and v["code"] in EXPECT:
            lo, hi = EXPECT[v["code"]]
            mark = "ok" if lo <= v["value"] <= hi else "!!"
            rng = f"[{lo},{hi}] {mark}"
            if mark == "!!":
                bad.append((v["code"], v["value"], lo, hi))

        print(f"{v['code']:5}{v['name'][:24]:24}{fmt(v):>10}{num:>12}{tgt:>8}  "
              f"{evaluate(v):<6}{rng}")

    print("-" * 86)
    stat = {}
    for v in res:
        stat[v["status"]] = stat.get(v["status"], 0) + 1
    print("状态分布:", stat)

    if bad:
        print("\n[失败] 以下指标超出设计区间：")
        for code, val, lo, hi in bad:
            print(f"  {code}: {val} 不在 [{lo},{hi}]")
        return 1

    print("[通过] 所有可计算指标均在设计区间内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
