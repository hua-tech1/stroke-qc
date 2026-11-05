# -*- coding: utf-8 -*-
"""把 seed.json 转成可执行的 SQL（migrations/003_seed_demo.sql）

不用数据库驱动，靠 psql -f 执行，避免额外依赖。
用法：
  python scripts/emit_sql.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "data" / "seed" / "seed.json"
OUT = ROOT / "migrations" / "003_seed_demo.sql"

SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
BATCH = 300


def esc(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def rows_to_sql(table, cols, rows):
    out = []
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        vals = ",\n".join("(" + ",".join(esc(v) for v in r) + ")" for r in chunk)
        out.append(f"INSERT INTO {table} ({','.join(cols)}) VALUES\n{vals};")
    return "\n".join(out)


def main():
    d = json.loads(SEED.read_text(encoding="utf-8"))
    cases, plans, records = d["cases"], d["plans"], d["records"]
    attempts, ms, meta = d["attempts"], d["milestones"], d["meta"]

    case_rows = []
    for c in cases:
        name = f"{SURNAMES[c['id'] % len(SURNAMES)]}**"
        case_rows.append([
            c["id"], c["case_no"], "demo", c["period"], c["dept_id"], name,
            c["sex"], c["age"], f"MZ{c['id']:08d}",
            c["case_type"], c["is_ihs"], c["is_transfer"], c["transfer_from"],
            c["exclude_reason"], c["exclude_kind"],
            c["arrival_at"], c["ct_at"], c["needle_at"], c["puncture_at"],
            c["reperfusion_at"], c["discharge_at"],
            c["nihss"], c["aspects"], c["lvo_site"], c["toast"], c["ocsp"],
            c["mtici"], c["discharge_type"], c["mrs_90"],
            c["dysphagia_24h"], c["antiplatelet_48h"], c["af"],
            c["anticoag_discharge"], c["is_featured"],
        ])

    plan_rows = [[p["id"], p["case_id"], p["node"], p["due_date"],
                  p["window_start"], p["window_end"], p["status"]] for p in plans]
    rec_rows = [[r["plan_id"], r["mrs"], "family"] for r in records]
    att_rows = [[a["plan_id"], a["attempted_at"], a["channel"], a["result"]]
                for a in attempts]
    ms_rows = [[m["case_id"], m["code"], m.get("occurred_at"), m.get("seq_ts_ms"),
                m["source"], m["ts_source"]] for m in ms]

    # sICH 必须落在 complications 表（带判定标准），不能只存在生成器里
    # 否则报表读库时 OU02 无法计算——这是入库时才发现的缺口
    comp_rows = [[c["id"], "sich", "sits_most", "severe" if c["mrs_90"] is None else "moderate",
                  "24–36h 复查影像示颅内出血，NIHSS 较基线加重 ≥4 分"]
                 for c in cases if c.get("sich")]

    sql = [
        "-- 仿真队列种子（自动生成，勿手改）",
        f"-- seed={meta['seed']}  generated_at={meta['generated_at']}",
        f"-- cases={len(cases)} plans={len(plans)} records={len(records)} "
        f"attempts={len(attempts)} milestones={len(ms)}",
        "BEGIN;",
        "TRUNCATE audit_logs, qc_actions, qc_findings, quality_issues, indicator_values,"
        " followup_attempts, followup_records, followup_plans, milestones,"
        " case_devices, complications, cases RESTART IDENTITY CASCADE;",
        rows_to_sql("cases", ["id", "case_no", "tenant", "period", "dept_id",
                              "patient_name", "sex", "age", "mrn", "case_type",
                              "is_ihs", "is_transfer", "transfer_from",
                              "exclude_reason", "exclude_kind", "arrival_at",
                              "ct_at", "needle_at", "puncture_at", "reperfusion_at",
                              "discharge_at", "nihss", "aspects", "lvo_site",
                              "toast", "ocsp", "mtici", "discharge_type", "mrs_90",
                              "dysphagia_24h", "antiplatelet_48h", "af",
                              "anticoag_discharge", "is_featured"], case_rows),
        rows_to_sql("followup_plans", ["id", "case_id", "node", "due_date",
                                       "window_start", "window_end", "status"], plan_rows),
        rows_to_sql("followup_records", ["plan_id", "mrs", "source"], rec_rows),
        rows_to_sql("followup_attempts", ["plan_id", "attempted_at", "channel", "result"],
                    att_rows),
        rows_to_sql("milestones", ["case_id", "code", "occurred_at", "seq_ts_ms",
                                   "source", "ts_source"], ms_rows),
        rows_to_sql("complications", ["case_id", "type", "criterion", "severity",
                                      "description"], comp_rows) if comp_rows else "",
        f"SELECT setval('cases_id_seq', {max(c['id'] for c in cases)});",
        f"SELECT setval('followup_plans_id_seq', {max(p['id'] for p in plans)});",
        "COMMIT;",
    ]

    OUT.write_text("\n\n".join(sql) + "\n", encoding="utf-8")
    size = OUT.stat().st_size / 1024
    print(f"[ok] {OUT}  {size:.0f} KB")
    for k, v in [("cases", len(cases)), ("plans", len(plans)),
                 ("records", len(records)), ("attempts", len(attempts)),
                 ("milestones", len(ms))]:
        print(f"     {k:11s} {v}")


if __name__ == "__main__":
    main()
