# -*- coding: utf-8 -*-
"""数据说明页（R12 / S9）

这一页存在的唯一目的：**让评委不用问，就知道数据是哪来的、哪部分是仿真的、哪部分不能信。**

三条原则：
  1. 仿真必须在第一屏说清楚，不能藏在第 8 页
  2. 每个参数都要有出处（dataset / literature / guideline / assumption），
     assumption 也照实标 assumption，不冒充文献
  3. 明确写出"能证明什么 / 不能证明什么"——这一节比参数表更值钱
"""
from __future__ import annotations

import json
from statistics import median

from app.core import config as C

SRC_CN = {
    "dataset": "公开数据集实测",
    "literature": "临床文献区间",
    "guideline": "指南／规范",
    "assumption": "工程假设",
}
SRC_ORDER = ["dataset", "guideline", "literature", "assumption"]

# 参数中文名（对照 seed.py 的 key）
PARAM_CN = {
    "months": "时间跨度（月）",
    "cases_per_month": "月均病例数",
    "type_mix": "卒中类型构成",
    "ihs_share": "院内卒中占比",
    "transfer_share": "外院转入占比",
    "missing_key_share": "关键节点缺失比例",
    "age_median": "年龄中位数",
    "age_ge60_share": "≥60 岁占比（卒中患者）",
    "female_share": "女性占比",
    "htn_share": "高血压患病率",
    "af_share": "房颤患病率",
    "ct_median_min": "到院至 CT 完成（中位，min）",
    "dnt_median_min": "DNT 中位数（min）",
    "dnt_p90_min": "DNT P90（min）",
    "dpt_median_min": "DPT 中位数（min）",
    "dpt_p90_min": "DPT P90（min）",
    "thrombolysis_rate": "静脉溶栓率",
    "evt_rate": "血管内治疗率",
    "mtici_mix": "再通分级构成",
    "sich_rate": "症状性颅内出血率",
    "death_rate": "院内死亡率",
    "mrs_good_rate": "90 天 mRS 0–2 比例",
    "lost_rate": "失访率",
    "refused_rate": "拒绝随访比例",
    "overdue_share": "逾期未随访比例",
    "sich_criterion": "sICH 判定标准",
}

LICENSES = [
    {"name": "X-ray Fluoroscopy Guidewire（导丝透视数据集）",
     "license": "未标注（HuggingFace license 字段为 null）",
     "usage": "仅本机演示，不随作品分发、不进公开仓库",
     "risk": "high",
     "note": "许可缺失即默认保留所有权利。材料中只能以截图引用并注明来源与许可状态。"},
    {"name": "Stroke Prediction Dataset（Nnaodeh 镜像）",
     "license": "CC0-1.0（公有领域）",
     "usage": "用于校准年龄与性别构成，不读原始影像",
     "risk": "low",
     "note": "无使用限制。但为社区筛查队列，合并症谱不可用于卒中住院队列。"},
    {"name": "ISLES24（缺血性卒中影像）",
     "license": "CC-BY-NC-SA 4.0",
     "usage": "本期未使用",
     "risk": "medium",
     "note": "非商用许可，与竞赛用途存在解释空间，本期未纳入。"},
    {"name": "Ultralytics YOLOv8",
     "license": "AGPL-3.0",
     "usage": "检测模型与训练框架",
     "risk": "medium",
     "note": "分发衍生作品需同许可开源。仓库已按 AGPL-3.0 声明。"},
]

LIMITS = {
    "can": [
        "证明「逐帧检测 → 离散事件 → 时间戳」这条链在真实影像序列上跑得通",
        "证明事件级时间戳的精度（误差量级 ≤ 数百毫秒）",
        "证明纳排规则、分母口径、指标计算与整改闭环能被审计",
        "证明系统在缺少某类数据时会如实报告「算不出来」，而不是编一个数",
    ],
    "cannot": [
        "**不能**证明临床有效性——没有前瞻对照，没有真实科室使用",
        "**不能**证明泛化性——只有单一中心、单一设备的两段序列",
        "**不能**证明统计显著性——n 小，且数据为仿真",
        "**不能**替代 HIS 对接——采集接口只做了抽象层，未接真实设备",
        "**不能**用于真实诊疗决策——本系统只产质控数据，不做诊断",
    ],
}


def _load():
    base = C.ROOT / "data" / "seed"
    sp = json.loads((base / "seed_params.json").read_text(encoding="utf-8"))
    sd = json.loads((base / "seed.json").read_text(encoding="utf-8"))
    return sp, sd


def _sim_profile(sd: dict) -> dict:
    cases = sd["cases"]
    ais = [c for c in cases if c["case_type"] == "ais"]
    ages = [c["age"] for c in ais]
    return {
        "n": len(ais),
        "age_median": median(ages) if ages else None,
        "age_ge60": round(100 * sum(1 for a in ages if a >= 60) / len(ages), 1) if ages else None,
        "female": round(100 * sum(1 for c in ais if c["sex"] == "F") / len(ais), 1) if ais else None,
    }


def build() -> dict:
    sp, sd = _load()
    params = sp["params"]
    sim = _sim_profile(sd)

    groups = []
    for src in SRC_ORDER:
        rows = []
        for k, v in params.items():
            if v["src"] != src:
                continue
            val = v["value"]
            if isinstance(val, dict):
                val = " · ".join(f"{kk} {vv}" for kk, vv in val.items())
            elif isinstance(val, float) and val <= 1:
                val = f"{val * 100:.0f}%"
            rows.append({"key": k, "name": PARAM_CN.get(k, k),
                         "value": val, "ref": v["ref"]})
        if rows:
            groups.append({"src": src, "label": SRC_CN[src],
                           "count": len(rows), "rows": rows})

    # 仿真队列 vs 公开数据集：证明"仿真是有依据的"，同时也是诚实的证据
    # 只列口径可比的项。年龄中位数不列——公开数据集是全样本社区筛查队列（中位 45 岁），
    # 与"住院卒中队列"不是一个口径，放进来只会误导。
    compare = [
        {"label": "卒中患者中 ≥60 岁占比", "sim": sim["age_ge60"], "pub": 72.7, "unit": "%",
         "pub_src": "CC0 数据集卒中子集"},
        {"label": "女性占比", "sim": sim["female"], "pub": 58.6, "unit": "%",
         "pub_src": "CC0 数据集全样本"},
    ]
    compare_note = ("年龄中位数未列入对比：公开数据集为社区筛查队列（全样本中位 45 岁），"
                    "与住院卒中队列口径不同，直接比较会误导。"
                    "本队列 AIS 年龄中位数为 "
                    f"{sim['age_median']:.0f} 岁，与国内卒中住院人群的常见区间一致。")

    dist = {}
    for v in params.values():
        dist[v["src"]] = dist.get(v["src"], 0) + 1

    return {
        "seed": sp["seed"],
        "generated_at": sp["generated_at"],
        "today": sp["today"],
        "counts": sp["counts"],
        "param_total": len(params),
        "dist": {SRC_CN[k]: dist.get(k, 0) for k in SRC_ORDER if dist.get(k)},
        "groups": groups,
        "compare": compare,
        "compare_note": compare_note,
        "sim_profile": sim,
        "licenses": LICENSES,
        "limits": LIMITS,
        "reproduce": {
            "seed": sp["seed"],
            "cmd": ["python scripts/seed.py --seed 42",
                    "python scripts/emit_sql.py",
                    "psql -f migrations/003_seed_demo.sql"],
        },
    }
