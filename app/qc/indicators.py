# -*- coding: utf-8 -*-
"""质控指标引擎（R4）

输入：cases / plans / milestones
输出：22 项指标，每项含分子、分母、值、可计算性、达标状态

四条硬规则：
  1. 分母 < min_denominator → 只报例数，不报率（决策 U2）
  2. 分母为 0 → 显示 "—"，不显示 0%
  3. 算不出来必须给 na_reason，不允许静默留空
  4. 分母只认纳排视图（ais + 非院内 + 未排除）
"""
from __future__ import annotations

from datetime import date, datetime
from statistics import median

# code -> (名称, 层级, 目标, 方向, 最小分母, 类型, 单位)
# 类型：rate=率 / median=中位数 / count=直接给出值
META = {
    "ST01": ("DSA 设备可用率",            "structure", 100,  "ge", 1,  "rate",   "%"),
    "ST02": ("取栓资质医师占比",            "structure", 60,   "ge", 1,  "rate",   "%"),
    "ST03": ("卒中小组 7×24 覆盖率",        "structure", 100,  "ge", 1,  "rate",   "%"),
    "ST04": ("溶栓药物常备率",              "structure", 100,  "ge", 1,  "rate",   "%"),
    "PR01": ("到院至 CT 完成时间（中位数）", "process",   25,   "le", 10, "median", "min"),
    "PR02": ("DNT 中位数",                 "process",   45,   "le", 10, "median", "min"),
    "PR03": ("DNT ≤60min 达标率",          "process",   70,   "ge", 10, "rate",   "%"),
    "PR04": ("DPT 中位数",                 "process",   60,   "le", 10, "median", "min"),
    "PR05": ("DPT ≤90min 达标率",          "process",   70,   "ge", 10, "rate",   "%"),
    "PR06": ("静脉溶栓率",                 "process",   30,   "ge", 10, "rate",   "%"),
    "PR07": ("血管内治疗率",               "process",   10,   "ge", 10, "rate",   "%"),
    "PR08": ("器械可见时长（中位数）",      "process",   None, None, 5,  "median", "s"),
    "PR09": ("术中滞留超时率",             "process",   15,   "le", 5,  "rate",   "%"),
    "PR10": ("24h 内吞咽功能评估率",        "process",   90,   "ge", 10, "rate",   "%"),
    "PR11": ("48h 内抗血小板治疗率",        "process",   85,   "ge", 10, "rate",   "%"),
    "PR12": ("房颤患者出院抗凝率",          "process",   60,   "ge", 10, "rate",   "%"),
    "OU01": ("mTICI 2b–3 再通率",          "outcome",   80,   "ge", 5,  "rate",   "%"),
    "OU02": ("症状性颅内出血率",            "outcome",   7,    "le", 5,  "rate",   "%"),
    "OU03": ("院内死亡率",                 "outcome",   5,    "le", 10, "rate",   "%"),
    "OU04": ("mRS 0–2 比例（90 天）",       "outcome",   50,   "ge", 10, "rate",   "%"),
    "OU05": ("随访率",                     "outcome",   80,   "ge", 10, "rate",   "%"),
    "OU06": ("失访率",                     "outcome",   15,   "le", 10, "rate",   "%"),
}


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def _mins(a, b):
    x, y = _dt(a), _dt(b)
    if not x or not y:
        return None
    return (y - x).total_seconds() / 60.0


def qc_pool(cases):
    """纳排：与视图 v_qc_eligible 同规则。"""
    return [c for c in cases
            if c["case_type"] == "ais"
            and not c.get("is_ihs")
            and not c.get("exclude_reason")]


def _r(code, num=None, den=None, value=None, na_reason=None,
       num_ids=None, den_ids=None, id_kind="case"):
    """num_ids / den_ids 用于下钻：点指标能列出"哪几例算进了分子/分母"。

    这两组 ID 必须和 num/den 同源计算，否则下钻看到的例数和上面的数字对不上。
    """
    name, layer, target, direction, min_den, kind, unit = META[code]
    base = dict(code=code, name=name, layer=layer, num=num, den=den, value=None,
                target=target, direction=direction, unit=unit, kind=kind,
                computable=False, na_reason=None, status="na",
                _num_ids=list(num_ids or []), _den_ids=list(den_ids or []),
                _id_kind=id_kind)

    if den is None or den == 0:
        base["na_reason"] = na_reason or "分母为 0，本期无可评价病例"
        return base

    if den < min_den:
        base["na_reason"] = na_reason or f"样本不足（n={den} < {min_den}），只报例数"
        base["status"] = "insufficient"
        return base

    if kind == "median":
        if value is None:
            base["na_reason"] = na_reason or "无有效数据"
            return base
        v = float(value)
    else:
        v = 100.0 * num / den if value is None else float(value)

    base.update(value=round(v, 1), computable=True, status="na")
    if target is not None:
        if direction == "ge":
            base["status"] = "pass" if v >= target else "fail"
        else:
            base["status"] = "pass" if v <= target else "fail"
    return base


def compute(cases, plans, milestones, ctx=None):
    ctx = ctx or {}
    pool = qc_pool(cases)
    pool_ids = {c["id"] for c in pool}
    out = []

    # ---------- 结构（配置型，分母是台数/人数，不套样本量规则） ----------
    # id_kind="config"：不提供病例下钻，明细来自设备/人员台账
    out.append(_r("ST01", ctx.get("dsa_available", 1), ctx.get("dsa_total", 1),
                  value=100.0 * ctx.get("dsa_available", 1) / ctx.get("dsa_total", 1),
                  id_kind="config"))
    out.append(_r("ST02", ctx.get("evt_doctors", 1), ctx.get("intervention_doctors", 1),
                  value=100.0 * ctx.get("evt_doctors", 1) / ctx.get("intervention_doctors", 1),
                  id_kind="config"))
    out.append(_r("ST03", na_reason="数据源未接入（值班表），本期不计算"))
    out.append(_r("ST04", na_reason="数据源未接入（药房台账），本期不计算"))

    # ---------- 过程 ----------
    # milestones 是权威；cases.* 只是快照，指标一律读里程碑
    ev = {}
    for m in milestones:
        if m["case_id"] in pool_ids:
            ev.setdefault(m["case_id"], {})[m["code"]] = m

    def t(cid, code):
        m = ev.get(cid, {}).get(code)
        return m.get("occurred_at") if m else None

    def dur(code_from, code_to):
        """返回 [(case_id, 分钟数)]，只在此两节点都存在的病例上计算。"""
        out_ = []
        for c in pool:
            d = _mins(t(c["id"], code_from), t(c["id"], code_to))
            if d is not None:
                out_.append((c["id"], d))
        return out_

    cts = dur("arrival", "ct_done")
    out.append(_r("PR01", len(cts), len(cts), median([d for _, d in cts]) if cts else None,
                  num_ids=[i for i, _ in cts], den_ids=[i for i, _ in cts]))

    dnt = dur("arrival", "needle")
    dnt_ids = [i for i, _ in dnt]
    out.append(_r("PR02", len(dnt), len(dnt), median([d for _, d in dnt]) if dnt else None,
                  num_ids=dnt_ids, den_ids=dnt_ids))
    out.append(_r("PR03", sum(1 for _, d in dnt if d <= 60), len(dnt),
                  num_ids=[i for i, d in dnt if d <= 60], den_ids=dnt_ids))

    dpt = dur("arrival", "puncture")
    dpt_ids = [i for i, _ in dpt]
    out.append(_r("PR04", len(dpt), len(dpt), median([d for _, d in dpt]) if dpt else None,
                  num_ids=dpt_ids, den_ids=dpt_ids))
    out.append(_r("PR05", sum(1 for _, d in dpt if d <= 90), len(dpt),
                  num_ids=[i for i, d in dpt if d <= 90], den_ids=dpt_ids))

    pool_list = [c["id"] for c in pool]
    out.append(_r("PR06", len(dnt), len(pool), num_ids=dnt_ids, den_ids=pool_list))
    out.append(_r("PR07", len(dpt), len(pool), num_ids=dpt_ids, den_ids=pool_list))

    dwell = [(cid, (e["seq_ts_ms"] - s["seq_ts_ms"]) / 1000.0)
             for cid, d in ev.items()
             if (s := d.get("device_visible_start")) and (e := d.get("device_visible_end"))
             and e["seq_ts_ms"] > s["seq_ts_ms"]]
    out.append(_r("PR08", len(dwell), len(dwell),
                  median([v for _, v in dwell]) if dwell else None,
                  num_ids=[i for i, _ in dwell], den_ids=[i for i, _ in dwell]))

    started = [cid for cid, d in ev.items() if "device_visible_start" in d]
    unclosed = [cid for cid in started if "device_visible_end" not in ev[cid]]
    out.append(_r("PR09", len(unclosed), len(started),
                  num_ids=unclosed, den_ids=started))

    dys = [c for c in pool if c.get("dysphagia_24h") is not None]
    out.append(_r("PR10", sum(1 for c in dys if c["dysphagia_24h"]), len(dys),
                  num_ids=[c["id"] for c in dys if c["dysphagia_24h"]],
                  den_ids=[c["id"] for c in dys]))

    ap = [c for c in pool if c.get("antiplatelet_48h") is not None]
    out.append(_r("PR11", sum(1 for c in ap if c["antiplatelet_48h"]), len(ap),
                  num_ids=[c["id"] for c in ap if c["antiplatelet_48h"]],
                  den_ids=[c["id"] for c in ap]))

    af = [c for c in pool if c.get("af") and c.get("anticoag_discharge") is not None]
    out.append(_r("PR12", sum(1 for c in af if c["anticoag_discharge"]), len(af),
                  num_ids=[c["id"] for c in af if c["anticoag_discharge"]],
                  den_ids=[c["id"] for c in af]))

    # ---------- 结果 ----------
    evt = [c for c in pool if c.get("mtici") and c["mtici"] != "NR"]
    out.append(_r("OU01", sum(1 for c in evt if c["mtici"] in ("2b", "2c", "3")), len(evt),
                  num_ids=[c["id"] for c in evt if c["mtici"] in ("2b", "2c", "3")],
                  den_ids=[c["id"] for c in evt]))

    reperf = [c for c in pool if "needle" in ev.get(c["id"], {}) or "puncture" in ev.get(c["id"], {})]
    out.append(_r("OU02", sum(1 for c in reperf if c.get("sich")), len(reperf),
                  num_ids=[c["id"] for c in reperf if c.get("sich")],
                  den_ids=[c["id"] for c in reperf]))

    out.append(_r("OU03", sum(1 for c in pool if c["discharge_type"] == "death"), len(pool),
                  num_ids=[c["id"] for c in pool if c["discharge_type"] == "death"],
                  den_ids=pool_list))

    mrs = [c for c in pool if c.get("mrs_90") is not None and c["discharge_type"] != "death"]
    out.append(_r("OU04", sum(1 for c in mrs if c["mrs_90"] <= 2), len(mrs),
                  num_ids=[c["id"] for c in mrs if c["mrs_90"] <= 2],
                  den_ids=[c["id"] for c in mrs]))

    today = date.fromisoformat(ctx.get("today", "2026-10-31"))
    alive = {c["id"] for c in cases if c["discharge_type"] != "death"}
    due = [p for p in plans
           if p["status"] != "deceased"
           and p["case_id"] in alive
           and date.fromisoformat(p["window_end"]) <= today]
    out.append(_r("OU05", sum(1 for p in due if p["status"] == "completed"), len(due),
                  num_ids=[p["id"] for p in due if p["status"] == "completed"],
                  den_ids=[p["id"] for p in due], id_kind="plan"))
    out.append(_r("OU06", sum(1 for p in due if p["status"] == "lost"), len(due),
                  num_ids=[p["id"] for p in due if p["status"] == "lost"],
                  den_ids=[p["id"] for p in due], id_kind="plan"))

    return out


def fmt(v):
    """报表展示规则：样本不足只报 n，分母 0 显示 —。"""
    if not v["computable"]:
        return f"n={v['den']}" if v["den"] else "—"
    if v["unit"] == "%":
        return f"{v['value']}%"
    return f"{v['value']}{v['unit']}"


def evaluate(v):
    return {"pass": "达标", "fail": "未达标",
            "insufficient": "样本不足", "na": "—"}[v["status"]]
