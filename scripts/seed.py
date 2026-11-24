# -*- coding: utf-8 -*-
"""仿真队列生成器（R11）

原则：
  1. 参数化 + 固定种子，同参数必出同一结果
  2. 每个参数带 source（dataset / literature / guideline / assumption）
  3. 生成日志落盘 seed_params.json，可复现
  4. 数据必须"不完美"：超时、失访、sICH、死亡、排除都有

用法：
  python scripts/seed.py --seed 42
  python scripts/seed.py --seed 42 --out data/seed
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 31)          # 决策 U6：演示时刻固定
CURRENT_PERIOD = "2026-10"

# ---------------------------------------------------------------- 参数表
# source: dataset / literature / guideline / assumption
PARAMS = {
    "months":        {"value": 12,    "src": "assumption", "ref": "2025-11 ~ 2026-10"},
    "cases_per_month": {"value": 50,  "src": "assumption", "ref": "高级卒中中心月均体量"},
    "type_mix":      {"value": {"ais": 0.80, "ich": 0.12, "sah": 0.05, "cvt": 0.03},
                      "src": "literature", "ref": "缺血性占卒中约 80%"},
    "ihs_share":     {"value": 0.05,  "src": "literature", "ref": "院内卒中占 AIS 约 4-6%"},
    "transfer_share": {"value": 0.15, "src": "assumption", "ref": "外院转入比例"},
    "missing_key_share": {"value": 0.03, "src": "assumption", "ref": "关键节点缺失（演示排除用）"},
    "age_median":    {"value": 45,    "src": "dataset",    "ref": "HF Nnaodeh/Stroke_Prediction_Dataset (CC0, N=5110) 实测"},
    "age_ge60_share": {"value": 0.73, "src": "dataset",    "ref": "同上，卒中患者子集中 ≥60 岁占 72.7%"},
    "female_share":  {"value": 0.59,  "src": "dataset",    "ref": "同上，女性 58.6%"},
    "htn_share":     {"value": 0.65,  "src": "literature", "ref": "卒中住院队列高血压 60-70%"},
    "af_share":      {"value": 0.25,  "src": "literature", "ref": "房颤 20-30%"},
    "ct_median_min": {"value": 18,    "src": "guideline",  "ref": "到院至 CT 完成 ≤25min，中位约 18"},
    "dnt_median_min": {"value": 52,   "src": "assumption", "ref": "DNT 中位 52，P90 78（目标 ≤60）"},
    "dnt_p90_min":   {"value": 78,    "src": "assumption", "ref": "同上"},
    "dpt_median_min": {"value": 70,   "src": "assumption", "ref": "DPT 中位 70，P90 105（目标 ≤90）"},
    "dpt_p90_min":   {"value": 105,   "src": "assumption", "ref": "同上"},
    "thrombolysis_rate": {"value": 0.25, "src": "literature", "ref": "高级卒中中心静脉溶栓率 20-30%"},
    "evt_rate":      {"value": 0.08,  "src": "literature", "ref": "血管内治疗率 5-10%"},
    "mtici_mix":     {"value": {"2b": 0.40, "2c": 0.18, "3": 0.22, "2a": 0.12, "1": 0.05, "0": 0.03},
                      "src": "literature", "ref": "成功再通(2b-3)约 80%"},
    "sich_rate":     {"value": 0.05,  "src": "literature", "ref": "SITS-MOST 定义下 2-7%"},
    "death_rate":    {"value": 0.04,  "src": "literature", "ref": "院内死亡 3-5%"},
    "mrs_good_rate": {"value": 0.55,  "src": "literature", "ref": "90 天 mRS 0-2 约 50-60%"},
    "lost_rate":     {"value": 0.12,  "src": "literature", "ref": "失访率 10-20%"},
    "refused_rate":  {"value": 0.03,  "src": "assumption", "ref": "拒绝随访"},
    "overdue_share": {"value": 0.08,  "src": "assumption", "ref": "窗口已过但仍未随访（真实痛点，工作台必看）"},
    "sich_criterion": {"value": "sits_most", "src": "guideline", "ref": "决策 U1"},
}

TYPE_MIX = PARAMS["type_mix"]["value"]
MTICI_MIX = PARAMS["mtici_mix"]["value"]
# 再通分级用固定循环而非独立抽样：样本只有 30 例左右，
# 独立抽样会上下浮动 10 个百分点，指标就不可复现了。
MTICI_PATTERN = ["2b", "2b", "2b", "2b", "2c", "2c", "3", "3", "2a", "1"]


def _sigma(median: float, p90: float) -> float:
    """对数正态：由中位数与 P90 反推 sigma。"""
    return (math.log(p90) - math.log(median)) / 1.2816


def _lnorm(rng: random.Random, median: float, p90: float, floor: float) -> float:
    v = rng.lognormvariate(math.log(median), _sigma(median, p90))
    return max(floor, v)


def _weighted(rng: random.Random, mix: dict) -> str:
    r = rng.random()
    acc = 0.0
    for k, p in mix.items():
        acc += p
        if r <= acc:
            return k
    return list(mix)[-1]


NODE_SOURCE = {
    "arrival":              "interface",
    "triage":               "interface",
    "team_call":            "manual",
    "team_arrive":          "manual",
    "ct_start":             "interface",
    "ct_done":              "interface",
    "lab_result":           "interface",
    "consent":              "manual",
    "needle":               "manual",
    "puncture":             "interface",
    "device_visible_start": "detector",
    "device_visible_end":   "detector",
    "reperfusion":          "manual",
    "discharge":            "interface",
}


def _month_starts(n: int) -> list[date]:
    """2025-11 起 n 个月。"""
    out, y, m = [], 2025, 11
    for _ in range(n):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def generate(seed: int = 42) -> dict:
    # 两个独立随机流：病例侧与随访侧互不干扰。
    # 否则改动随访逻辑会重排病例的抽样结果，指标全部漂移（踩过一次）。
    rng = random.Random(seed)
    rng_plan = random.Random(seed * 7919 + 1)
    cases, plans, records, attempts, milestones = [], [], [], [], []
    cid = 0
    evt_seq = -1
    demo_quota = 2          # 本期强制 2 例取栓，供演示序列挂靠
    plan_id = 0

    months = _month_starts(PARAMS["months"]["value"])

    # 月分布固定（合计 600），避免病例数随机漂移导致分母不稳
    monthly = [48, 52, 46, 54, 49, 51, 47, 53, 50, 50, 52, 48]

    for mi, mstart in enumerate(months):
        period = f"{mstart.year}-{mstart.month:02d}"
        n = monthly[mi]

        for i in range(n):
            cid += 1
            ctype = _weighted(rng, TYPE_MIX)
            is_ihs = ctype == "ais" and rng.random() < PARAMS["ihs_share"]["value"]
            is_transfer = (not is_ihs) and rng.random() < PARAMS["transfer_share"]["value"]

            # 入院时间：当月 1-20 日，工作时段偏多
            day = rng.randint(1, 20)
            hour = rng.choice([7, 8, 9, 10, 11, 13, 14, 15, 16, 18, 20, 22, 2])
            arrival = datetime(mstart.year, mstart.month, day, hour, rng.randint(0, 59))

            # 到院至 CT
            ct_min = _lnorm(rng, PARAMS["ct_median_min"]["value"], 32, 5)
            ct = arrival + timedelta(minutes=ct_min)

            # 年龄 / 性别（卒中患者偏高龄）
            if rng.random() < PARAMS["age_ge60_share"]["value"]:
                age = rng.randint(60, 92)
            else:
                age = max(18, int(rng.gauss(52, 9)))
            sex = "F" if rng.random() < PARAMS["female_share"]["value"] else "M"

            c = {
                "id": cid,
                "case_no": f"CZ-{mstart.year}{mstart.month:02d}{i+1:03d}",
                "period": period,
                "dept_id": rng.choices(["n1", "n2", "ir"], weights=[45, 35, 20])[0],
                "sex": sex,
                "age": age,
                "case_type": ctype,
                "is_ihs": is_ihs,
                "is_transfer": is_transfer,
                "transfer_from": ("外院" if is_transfer else None),
                "exclude_reason": None,
                "exclude_kind": None,
                "arrival_at": arrival.isoformat(),
                "ct_at": ct.isoformat(),
                "needle_at": None,
                "puncture_at": None,
                "reperfusion_at": None,
                "discharge_at": None,
                "nihss": rng.choice([2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 22]),
                "aspects": rng.choice([6, 7, 8, 9, 10, 10, 10]),
                "lvo_site": None,
                "toast": rng.choices(["LAA", "CE", "SVO", "SOE", "SUE"], weights=[35, 25, 25, 5, 10])[0],
                "ocsp": rng.choices(["TACI", "PACI", "POCI", "LACI"], weights=[10, 55, 20, 15])[0],
                "mtici": None,
                "discharge_type": "home",
                "mrs_90": None,
                "dysphagia_24h": None,
                "antiplatelet_48h": None,
                "af": rng.random() < PARAMS["af_share"]["value"],
                "anticoag_discharge": None,
                "is_featured": False,
                "sich": False,
            }

            # 非缺血：直接出院，不进分母
            if ctype != "ais":
                los = rng.randint(7, 18)
                c["discharge_at"] = (arrival + timedelta(days=los)).isoformat()
                c["discharge_type"] = "home" if rng.random() > 0.10 else "death"
                c["exclude_kind"] = "non_ais"
                c["exclude_reason"] = "非缺血性卒中，不纳入缺血性质控分母"
                cases.append(c)
                for code, ts in (("arrival", c["arrival_at"]),
                                 ("ct_done", c["ct_at"]),
                                 ("discharge", c["discharge_at"])):
                    milestones.append({"case_id": cid, "code": code, "occurred_at": ts, "seq_ts_ms": None,
                                       "source": NODE_SOURCE[code],
                                       "ts_source": "simulated"})
                continue

            # 缺血性：治疗路径
            thrombolysis = rng.random() < PARAMS["thrombolysis_rate"]["value"]
            evt = rng.random() < PARAMS["evt_rate"]["value"]
            # 演示需要：本期（2026-10）保证有 2 例取栓病例，
            # 否则演示病例落在历史月份，按「本期」筛选时找不到
            if period == CURRENT_PERIOD and demo_quota > 0:
                evt = True
                demo_quota -= 1
            if evt:
                thrombolysis = thrombolysis or rng.random() < 0.35   # 桥接

            if thrombolysis:
                dnt = _lnorm(rng, PARAMS["dnt_median_min"]["value"],
                             PARAMS["dnt_p90_min"]["value"], 12)
                c["needle_at"] = (arrival + timedelta(minutes=dnt)).isoformat()

            if evt:
                c["dept_id"] = "ir"        # 取栓病例归介入病区
                evt_seq += 1
                dpt = _lnorm(rng, PARAMS["dpt_median_min"]["value"],
                             PARAMS["dpt_p90_min"]["value"], 25)
                # 桥接病例：溶栓必须在穿刺之前，否则临床上不成立
                if thrombolysis:
                    dnt_min = (datetime.fromisoformat(c["needle_at"])
                               - arrival).total_seconds() / 60.0
                    dpt = max(dpt, dnt_min + rng.uniform(8, 20))
                c["puncture_at"] = (arrival + timedelta(minutes=dpt)).isoformat()
                c["lvo_site"] = rng.choice(["ICA", "M1", "M2", "BA", "VA"])
                c["mtici"] = MTICI_PATTERN[evt_seq % len(MTICI_PATTERN)]
                rec_min = _lnorm(rng, 35, 65, 10)
                c["reperfusion_at"] = (
                    datetime.fromisoformat(c["puncture_at"]) + timedelta(minutes=rec_min)
                ).isoformat()

            # 结局
            reperfused = thrombolysis or evt
            if reperfused and rng.random() < PARAMS["sich_rate"]["value"]:
                c["sich"] = True

            died = c["sich"] and rng.random() < 0.35
            if rng.random() < PARAMS["death_rate"]["value"]:
                died = True
            c["discharge_type"] = "death" if died else (
                "rehab" if rng.random() < 0.35 else
                "transfer" if rng.random() < 0.10 else
                "against_advice" if rng.random() < 0.03 else "home"
            )

            los = rng.randint(5, 21)
            c["discharge_at"] = (arrival + timedelta(days=los)).isoformat()

            # 过程字段
            # 不适用的场景一律留 None，避免把"不适用"算成"没做"
            c["dysphagia_24h"] = None if died else (rng.random() < 0.88)
            c["antiplatelet_48h"] = None if (died or thrombolysis) else (rng.random() < 0.90)
            c["anticoag_discharge"] = (rng.random() < 0.65) if (c["af"] and not died) else None

            # 90 天 mRS（只有出院存活且时间已到的才有）
            if not died:
                d90 = datetime.fromisoformat(c["discharge_at"]).date() + timedelta(days=90)
                if d90 <= TODAY:
                    good = rng.random() < PARAMS["mrs_good_rate"]["value"]
                    if good:
                        c["mrs_90"] = rng.choice([0, 1, 1, 2, 2])
                    else:
                        c["mrs_90"] = rng.choice([3, 3, 4, 4, 5, 5])

            # 关键节点缺失（人为制造少量，用于演示纳排）
            if (not is_ihs) and rng.random() < PARAMS["missing_key_share"]["value"]:
                c["exclude_kind"] = "missing_key"
                c["exclude_reason"] = "关键节点缺失（到院时间无法确认），不进入时间类指标"

            cases.append(c)

            # 随访计划
            dis = datetime.fromisoformat(c["discharge_at"]).date()
            nodes = [("discharge", 0, 0), ("m1", 30, 14), ("m3", 90, 30),
                     ("m6", 180, 30), ("m12", 365, 30)]
            for node, offset, win in nodes:
                plan_id += 1
                due = dis + timedelta(days=offset)
                ws, we = due - timedelta(days=win), due + timedelta(days=win)
                p = {"id": plan_id, "case_id": cid, "node": node,
                     "due_date": due.isoformat(),
                     "window_start": ws.isoformat(), "window_end": we.isoformat()}

                if died:
                    p["status"] = "deceased"
                elif we > TODAY:
                    p["status"] = "planned"
                elif rng_plan.random() < PARAMS["overdue_share"]["value"]:
                    # 窗口已过但仍未访 → 逾期
                    p["status"] = "planned"
                    for k in range(rng_plan.choice([0, 1, 2])):
                        attempts.append({
                            "plan_id": plan_id,
                            "attempted_at": (we - timedelta(days=5 - k)).isoformat(),
                            "channel": "phone",
                            "result": "no_answer",
                        })
                else:
                    r = rng_plan.random()
                    if r < PARAMS["lost_rate"]["value"]:
                        p["status"] = "lost"
                        for k in range(3):
                            attempts.append({
                                "plan_id": plan_id,
                                "attempted_at": (we - timedelta(days=2 - k)).isoformat(),
                                "channel": "phone",
                                "result": "no_answer" if k < 2 else "wrong_number",
                            })
                    elif r < PARAMS["lost_rate"]["value"] + PARAMS["refused_rate"]["value"]:
                        p["status"] = "refused"
                    else:
                        p["status"] = "completed"
                        records.append({"plan_id": plan_id, "mrs": _followup_mrs(rng, c)})
                plans.append(p)

            # 并发症
            # （sICH 由下面的并发症记录产生，不在此处写里程碑）

            # 所有已发生节点写入里程碑（milestones 为权威，cases.* 为快照）
            for code, ts in (("arrival", c["arrival_at"]),
                             ("triage", c["arrival_at"]),
                             ("ct_done", c["ct_at"]),
                             ("needle", c["needle_at"]),
                             ("puncture", c["puncture_at"]),
                             ("reperfusion", c["reperfusion_at"]),
                             ("discharge", c["discharge_at"])):
                if ts:
                    milestones.append({"case_id": cid, "code": code, "occurred_at": ts, "seq_ts_ms": None,
                                       "source": NODE_SOURCE[code],
                                       "ts_source": "simulated"})

            # 检测事件：先只记录起点，循环结束后按配额统一生成（避免抽样互相干扰）
            if evt:
                c["_evt_start_ms"] = rng.randint(800, 5000)

    # 演示序列病例：先选定，再生成设备事件（保证病例 002 一定是"未闭合"那一例）
    cands = [c for c in cases
             if c["case_type"] == "ais" and not c["is_ihs"] and c["puncture_at"]]
    cur = [c for c in cands if c["period"] == CURRENT_PERIOD]
    demo = (cur or cands)[:2]
    for i, c in enumerate(demo):
        c["case_no"] = f"CZ-DEMO-{i + 1:03d}"
        c["is_featured"] = True
        c["demo_seq"] = "A" if i == 0 else "B"

    # 设备事件配额：恰好 10% 的取栓病例"未闭合"（对应术中滞留超时）
    rng_dev = random.Random(seed * 104729 + 7)
    evt_cases = [c for c in cases if "_evt_start_ms" in c]
    k_unclosed = max(1, round(len(evt_cases) * 0.10)) if evt_cases else 0
    unclosed_ids = ({c["id"] for c in rng_dev.sample(evt_cases, k_unclosed)}
                    if k_unclosed else set())
    # 病例 002 演的是"全程在场未闭合"，必须是未闭合那一例
    if len(demo) > 1 and demo[1]["id"] in {c["id"] for c in evt_cases}:
        unclosed_ids.add(demo[1]["id"])

    for c in evt_cases:
        start = c["_evt_start_ms"]
        milestones.append({"case_id": c["id"], "code": "device_visible_start",
                           "occurred_at": None, "seq_ts_ms": start,
                           "source": "detector", "ts_source": "simulated"})
        if c["id"] not in unclosed_ids:
            dwell = _lnorm(rng_dev, 220, 400, 60)          # 秒
            milestones.append({"case_id": c["id"], "code": "device_visible_end",
                               "occurred_at": None,
                               "seq_ts_ms": start + int(dwell * 1000),
                               "source": "detector", "ts_source": "simulated"})

    # 重点病例：给 10 个标记（决策 U3）
    for c in cases[:10]:
        c["is_featured"] = True

    meta = {
        "seed": seed,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": TODAY.isoformat(),
        "current_period": CURRENT_PERIOD,
        "params": PARAMS,
        "counts": {"cases": len(cases), "plans": len(plans),
                   "records": len(records), "attempts": len(attempts)},
    }
    return {"cases": cases, "plans": plans, "records": records,
            "attempts": attempts, "milestones": milestones, "meta": meta}


def _followup_mrs(rng: random.Random, case: dict) -> int:
    base = case.get("mrs_90")
    if base is None:
        return rng.choice([1, 2, 2, 3, 3, 4])
    return max(0, min(6, base + rng.choice([-1, 0, 0, 0, 1])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default=str(ROOT / "data" / "seed"))
    args = ap.parse_args()

    data = generate(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    (out / "seed.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "seed_params.json").write_text(
        json.dumps(data["meta"], ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] seed={args.seed} -> {out}")
    for k, v in data["meta"]["counts"].items():
        print(f"     {k:9s} {v}")


if __name__ == "__main__":
    main()
