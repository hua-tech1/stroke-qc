# -*- coding: utf-8 -*-
"""质控报表（S7）

设计要点：
  1. **不重写指标逻辑**。报表直接复用 app.qc.indicators.compute()，
     只是把数据源从 seed.json 换成数据库。一份实现，一个口径。
  2. **分母必须能展开**。总例数 → 排除 → 分母，每一层可点开看是哪些病例。
     不能展开的分母，等于不可信。
  3. **页脚三要素**：口径版本 / 数据截止 / 生成时间。缺一样就是不规范报表。
"""
from __future__ import annotations

from datetime import datetime

from app.core import config as C
from app.core import db
from app.qc.indicators import META, compute, evaluate, fmt

LAYER_CN = {"structure": "结构指标", "process": "过程指标", "outcome": "结果指标"}

# 期间范围：默认近 12 个月（单月样本太小，多数指标会落进"样本不足"）
RANGES = {
    "m1":  ("本期", 1),
    "m3":  ("近 3 个月", 3),
    "m12": ("近 12 个月", 12),
    "all": ("全部", None),
}


def _periods_back(months: int) -> list[str]:
    """从 CURRENT_PERIOD 往前数 N 个月，返回 period 字符串列表。"""
    y, m = (int(x) for x in C.CURRENT_PERIOD.split("-"))
    out = []
    for _ in range(months):
        out.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def _load(rng: str, dept: str | None):
    """一次性把三张表读进内存。600 例规模下比逐指标查库快得多。"""
    if rng == "all":
        where, args = "c.tenant='demo'", []
    else:
        n = RANGES[rng][1]
        periods = _periods_back(n)
        where, args = "c.tenant='demo' AND c.period = ANY(%s)", [periods]
    if dept:
        where += " AND c.dept_id = %s"
        args.append(dept)

    cases = db.query(f"SELECT * FROM cases c WHERE {where} ORDER BY c.id", args or None)
    if not cases:
        return [], [], []

    ids = [c["id"] for c in cases]
    plans = db.query(
        "SELECT id, case_id, node, due_date, window_start, window_end, status "
        "FROM followup_plans WHERE case_id = ANY(%s)", (ids,))
    ms = db.query(
        "SELECT case_id, code, occurred_at, seq_ts_ms, source, ts_source, voided "
        "FROM milestones WHERE case_id = ANY(%s) AND NOT voided", (ids,))

    # sICH 存在 complications 表（带判定标准），不在 cases 上
    sich = {r["case_id"] for r in db.query(
        "SELECT case_id FROM complications WHERE type='sich' AND case_id = ANY(%s)", (ids,))}
    for c in cases:
        c["sich"] = c["id"] in sich
        c["is_ihs"] = bool(c["is_ihs"])
        c["af"] = bool(c["af"])
        for k in ("dysphagia_24h", "antiplatelet_48h", "anticoag_discharge"):
            pass  # 已是 bool/None，原样使用

    # engine 期望 ISO 字符串或 None
    for c in cases:
        for k in ("arrival_at", "ct_at", "needle_at", "puncture_at",
                  "reperfusion_at", "discharge_at"):
            v = c.get(k)
            c[k] = v.isoformat() if isinstance(v, datetime) else v
    for p in plans:
        for k in ("due_date", "window_start", "window_end"):
            v = p.get(k)
            p[k] = v.isoformat() if hasattr(v, "isoformat") else v
    for m in ms:
        v = m.get("occurred_at")
        m["occurred_at"] = v.isoformat() if hasattr(v, "isoformat") else v

    return cases, plans, ms


def denominator(rng: str = "m12", dept: str | None = None) -> dict:
    """分母减法：总量 → 三类排除 → 可评价。

    「分母是多少、为什么排除」是质控报表第一个会被问的问题，
    所以这一层必须能被点开核对，不能只给最终数字。
    """
    cases, _, _ = _load(rng, dept)
    total = len(cases)
    non_ais = [c for c in cases if c["case_type"] != "ais"]
    ihs = [c for c in cases if c["case_type"] == "ais" and c["is_ihs"]]
    data_excl = [c for c in cases if c["case_type"] == "ais"
                 and not c["is_ihs"] and c["exclude_reason"]]
    eligible = [c for c in cases if c["case_type"] == "ais"
                and not c["is_ihs"] and not c["exclude_reason"]]

    def by_type(rows):
        agg = {}
        for c in rows:
            agg[c["case_type"]] = agg.get(c["case_type"], 0) + 1
        return agg

    return {
        "total": total,
        "steps": [
            {"key": "total", "label": "期间建档总数", "n": total, "op": "",
             "note": "本期全部卒中相关病例"},
            {"key": "non_ais", "label": "非缺血性卒中", "n": len(non_ais), "op": "−",
             "note": "出血性 / 蛛网膜下腔 / 静脉窦血栓，不进入缺血性质控分母",
             "breakdown": by_type(non_ais)},
            {"key": "ihs", "label": "院内卒中（IHS）", "n": len(ihs), "op": "−",
             "note": "住院期间新发，流程起点不同，单列统计"},
            {"key": "data_excl", "label": "关键节点缺失", "n": len(data_excl), "op": "−",
             "note": "到院时间无法确认，时间类指标无法计算"},
        ],
        "eligible": len(eligible),
        "eligible_by_dept": _by_dept(eligible),
    }


def _by_dept(rows):
    agg = {}
    for c in rows:
        agg[c["dept_id"]] = agg.get(c["dept_id"], 0) + 1
    return agg


def build(rng: str = "m12", dept: str | None = None) -> dict:
    cases, plans, ms = _load(rng, dept)
    if not cases:
        return {"empty": True, "range": rng, "range_cn": RANGES[rng][0],
                "denominator": {"total": 0, "steps": [], "eligible": 0}}

    ctx = {"today": C.TODAY, "dsa_available": 1, "dsa_total": 1,
           "evt_doctors": 1, "intervention_doctors": 1}
    raw = compute(cases, plans, ms, ctx)

    # 下钻用的 ID 集合单独存，不塞进表格数据里
    ids = {v["code"]: {"num": v["_num_ids"], "den": v["_den_ids"],
                       "kind": v["_id_kind"]} for v in raw}

    inds = []
    for v in raw:
        inds.append({
            "code": v["code"], "name": v["name"], "layer": v["layer"],
            "num": v["num"], "den": v["den"], "value": v["value"],
            "target": v["target"], "direction": v["direction"],
            "unit": v["unit"], "kind": v["kind"],
            "computable": v["computable"], "na_reason": v["na_reason"],
            "status": v["status"], "display": fmt(v), "status_cn": evaluate(v),
        })

    layers = []
    for key in ("structure", "process", "outcome"):
        rows = [i for i in inds if i["layer"] == key]
        layers.append({
            "key": key, "label": LAYER_CN[key], "rows": rows,
            "pass": sum(1 for r in rows if r["status"] == "pass"),
            "fail": sum(1 for r in rows if r["status"] == "fail"),
            "na": sum(1 for r in rows if r["status"] in ("na", "insufficient")),
        })

    # 口径版本：本期指标定义的最高版本号
    ver = db.query_one("SELECT max(version) AS v FROM indicator_defs") or {"v": 1}

    return {
        "empty": False,
        "range": rng, "range_cn": RANGES[rng][0],
        "range_periods": (_periods_back(RANGES[rng][1]) if rng != "all" else ["全部"]),
        "dept": dept,
        "denominator": denominator(rng, dept),
        "layers": layers,
        "ids": ids,
        "summary": {
            "pass": sum(l["pass"] for l in layers),
            "fail": sum(l["fail"] for l in layers),
            "na": sum(l["na"] for l in layers),
            "total": len(inds),
        },
        "footer": {
            "version": f"v{ver['v']}",
            "data_until": C.TODAY,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "scope": "缺血性卒中（AIS）· 排除院内卒中与关键节点缺失",
        },
    }


def metric_value(code: str, rng: str = "m12", dept: str | None = None) -> dict:
    """现场计算某指标当前值，供整改关闭时写入 metrics_at_close。

    刻意不接受前端传值——关闭整改时的"当期值"必须由系统算，
    否则台账会变成"自己打个分说自己改好了"。
    """
    cases, plans, ms = _load(rng, dept)
    if not cases:
        return {}
    raw = {v["code"]: v for v in compute(cases, plans, ms, {"today": C.TODAY})}
    v = raw.get(code)
    if not v or not v["computable"]:
        return {}
    return {code: {"value": v["value"], "n": v["den"],
                   "window": RANGES[rng][0], "period_until": C.TODAY}}


def drill(code: str, side: str = "den", rng: str = "m12", dept: str | None = None) -> dict:
    """下钻：某一指标的分子/分母是哪几例。"""
    if code not in META:
        return {"code": code, "rows": [], "error": "指标不存在"}

    cases, plans, ms = _load(rng, dept)
    ctx = {"today": C.TODAY}
    raw = {v["code"]: v for v in compute(cases, plans, ms, ctx)}
    v = raw.get(code)
    if not v:
        return {"code": code, "rows": [], "error": "指标未计算"}

    if v["_id_kind"] == "config":
        return {"code": code, "name": v["name"], "kind": "config",
                "rows": [], "note": "结构指标来自设备/人员台账，无病例明细"}

    selected = v["_num_ids"] if side == "num" else v["_den_ids"]
    in_num = set(v["_num_ids"])

    if v["_id_kind"] == "plan":
        rows = db.query("""
            SELECT p.id, p.node, p.status, p.due_date, p.window_end,
                   c.case_no, c.patient_name, c.dept_id
            FROM followup_plans p JOIN cases c ON c.id = p.case_id
            WHERE p.id = ANY(%s) ORDER BY p.window_end DESC""", (selected,))
        for r in rows:
            r["hit"] = r["id"] in in_num
            r["due_date"] = r["due_date"].isoformat() if r["due_date"] else None
            r["window_end"] = r["window_end"].isoformat() if r["window_end"] else None
        return {"code": code, "name": v["name"], "kind": "plan", "side": side,
                "n": len(rows), "rows": rows}

    rows = db.query("""
        SELECT id, case_no, patient_name, dept_id, case_type, is_ihs,
               arrival_at, discharge_type, mtici, mrs_90
        FROM cases WHERE id = ANY(%s) ORDER BY case_no""", (selected,))
    for r in rows:
        r["hit"] = r["id"] in in_num
        r["arrival_at"] = r["arrival_at"].isoformat() if r["arrival_at"] else None
    return {"code": code, "name": v["name"], "kind": "case", "side": side,
            "n": len(rows), "rows": rows}
