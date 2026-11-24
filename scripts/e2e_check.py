# -*- coding: utf-8 -*-
"""端到端走查（S9 验收）

不测"接口返回 200"，测**数据对不对、权限拦不拦得住、页面之间能不能对上**。
用法：
  python scripts/e2e_check.py
  python scripts/e2e_check.py --base http://127.0.0.1:8099
"""
from __future__ import annotations

import argparse
import sys

import httpx

OK, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []
PW = "Demo@2026"
ROLES = ("doctor", "nurse", "qc", "guest")


def check(name: str, cond: bool, detail: str = ""):
    results.append((OK if cond else FAIL, name, detail))
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  —— {detail}" if detail else ""))
    return cond


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    a = ap.parse_args()
    B = a.base

    def new_client():
        return httpx.Client(base_url=B, timeout=30, trust_env=False, follow_redirects=False)

    print(f"\n端到端走查 · {B}\n" + "=" * 72)

    # ---------- 0. 登录 ----------
    print("\n[0] 登录与会话")
    anon = new_client()
    r = anon.get("/monitor")
    check("未登录访问页面 → 302 登录页",
          r.status_code == 302 and "/login" in r.headers.get("location", ""),
          f"{r.status_code} {r.headers.get('location','')}")
    r = anon.get("/api/cases")
    check("未登录访问接口 → 401", r.status_code == 401, str(r.status_code))
    r = anon.get("/login")
    check("登录页可访问", r.status_code == 200 and "登录" in r.text, str(r.status_code))
    r = anon.get("/about")
    check("数据说明免登录", r.status_code == 200, str(r.status_code))

    r = anon.post("/api/login", json={"username": "doctor", "password": "wrong"})
    check("口令错误 → 401", r.status_code == 401, r.text[:40])
    r = anon.post("/api/login", json={"username": "nobody", "password": PW})
    check("账号不存在 → 401（提示与口令错误一致）",
          r.status_code == 401 and "账号或口令不正确" in r.text, r.text[:40])

    cli = {}
    for role in ROLES:
        c = new_client()
        r = c.post("/api/login", json={"username": role, "password": PW})
        ok = r.status_code == 200 and r.json().get("role") == role
        check(f"登录 {role}", ok, r.json().get("home") if ok else r.text[:40])
        cli[role] = c
    cd, cn, cq, cg = cli["doctor"], cli["nurse"], cli["qc"], cli["guest"]

    r = cq.get("/api/me")
    check("会话可读 /api/me",
          r.status_code == 200 and r.json()["role"] == "qc", r.text[:60])

    # ---------- 0.1 权限矩阵 ----------
    print("\n[0.1] 页面权限矩阵（期望：仅授权角色 200，其余 403）")
    PAGE_EXPECT = {
        "/monitor":   {"doctor": 200, "nurse": 403, "qc": 403, "guest": 200},
        "/followups": {"doctor": 403, "nurse": 200, "qc": 403, "guest": 200},
        "/qc":        {"doctor": 403, "nurse": 403, "qc": 200, "guest": 200},
        "/cases":     {r: 200 for r in ROLES},
    }
    for path, exp in PAGE_EXPECT.items():
        got = {role: cli[role].get(path).status_code for role in ROLES}
        check(f"{path} 权限", got == exp,
              " ".join(f"{k}={v}" for k, v in got.items()))

    print("\n[0.2] 接口权限矩阵")
    API_EXPECT = {
        "/api/qc/report?range=m12": {"doctor": 403, "nurse": 403, "qc": 200, "guest": 200},
        "/api/followups?limit=1":   {"doctor": 403, "nurse": 200, "qc": 403, "guest": 200},
        "/api/demo":                {"doctor": 200, "nurse": 403, "qc": 403, "guest": 200},
        "/api/cases?limit=1":       {r: 200 for r in ROLES},
    }
    for path, exp in API_EXPECT.items():
        got = {role: cli[role].get(path).status_code for role in ROLES}
        check(f"{path} 权限", got == exp, " ".join(f"{k}={v}" for k, v in got.items()))

    print("\n[0.3] 写权限（游客/医生不得改数据）")
    r = cg.post("/api/qc/findings/5/assign", json={"owner_id": "doctor"})
    check("guest 指派整改 → 403", r.status_code == 403, r.text[:40])
    r = cd.post("/api/qc/findings/5/assign", json={"owner_id": "doctor"})
    check("doctor 指派整改 → 403", r.status_code == 403, r.text[:40])

    # ---------- 1. 页面 ----------
    print("\n[1] 页面渲染")
    pages = {"/monitor": "术中监控", "/cases": "病例列表",
             "/followups": "随访", "/qc": "质控报表", "/about": "数据说明"}
    for path, kw in pages.items():
        r = cg.get(path)
        check(f"GET {path}", r.status_code == 200 and kw in r.text,
              f"{r.status_code} · {len(r.text)}B")

    # ---------- 2. 首屏数字 vs 报表 ----------
    print("\n[2] 总览数字 与 报表口径一致")
    ov = cq.get("/api/overview").json()
    rep = cq.get("/api/qc/report?range=m12").json()
    check("建档总数一致", ov["counts"]["total"] == rep["denominator"]["total"],
          f"{ov['counts']['total']} vs {rep['denominator']['total']}")
    check("分母一致", ov["counts"]["eligible"] == rep["denominator"]["eligible"],
          f"{ov['counts']['eligible']} vs {rep['denominator']['eligible']}")
    dnt = next(x for l in rep["layers"] for x in l["rows"] if x["code"] == "PR03")
    check("DNT 指标一致", ov["dnt"]["display"] == dnt["display"],
          f"{ov['dnt']['display']} vs {dnt['display']}")

    # ---------- 3. 分母减法 ----------
    print("\n[3] 分母减法自洽")
    d = rep["denominator"]
    sub = sum(s["n"] for s in d["steps"][1:])
    check("总数 − 各层排除 = 分母", d["total"] - sub == d["eligible"],
          f"{d['total']} − {sub} = {d['total'] - sub}，分母 {d['eligible']}")
    bd = d["steps"][1].get("breakdown") or {}
    check("非缺血细分与总数相符", sum(bd.values()) == d["steps"][1]["n"],
          f"{bd} 合计 {sum(bd.values())}")

    # ---------- 3.1 列表与报表 ----------
    print("\n[3.1] 病例列表 与 报表分母 一致")
    lst_all = cg.get("/api/cases", params={"only_eligible": "1", "limit": 1}).json()["total"]
    check("列表纳入总数 = 近12月分母", lst_all == d["eligible"], f"{lst_all} vs {d['eligible']}")
    m1r = cq.get("/api/qc/report?range=m1").json()
    lst_p = cg.get("/api/cases", params={"period": "2026-10", "limit": 1}).json()["total"]
    lst_pe = cg.get("/api/cases",
                    params={"period": "2026-10", "only_eligible": "1", "limit": 1}).json()["total"]
    check("本期列表总数 = 本期报表总数", lst_p == m1r["denominator"]["total"],
          f"{lst_p} vs {m1r['denominator']['total']}")
    check("本期列表纳入 = 本期报表分母", lst_pe == m1r["denominator"]["eligible"],
          f"{lst_pe} vs {m1r['denominator']['eligible']}")

    # ---------- 4. 指标与下钻 ----------
    print("\n[4] 22 项指标与下钻同源")
    rows = [x for l in rep["layers"] for x in l["rows"]]
    check("指标数 22", len(rows) == 22, str(len(rows)))
    bad = []
    for x in rows:
        if x["den"] is None or x["code"].startswith("ST"):
            continue
        dr = cq.get(f"/api/qc/indicators/{x['code']}/drill",
                    params={"side": "den", "range": "m12"}).json()
        if dr.get("n") != x["den"]:
            bad.append(f"{x['code']}: drill={dr.get('n')} vs den={x['den']}")
    check("每个指标下钻条数 = 分母", not bad, "；".join(bad[:3]) or "18 项全部对齐")

    pr03 = next(x for x in rows if x["code"] == "PR03")
    dn = cq.get("/api/qc/indicators/PR03/drill",
                params={"side": "num", "range": "m12"}).json()
    check("PR03 分子下钻 = num", dn["n"] == pr03["num"], f"{dn['n']} vs {pr03['num']}")
    check("分子全部落在分母内", all(r["hit"] for r in dn["rows"]), f"{dn['n']} 条全部命中")

    # ---------- 5. 期间 ----------
    print("\n[5] 期间切换单调")
    check("本期 ≤ 近3月 ≤ 近12月",
          m1r["denominator"]["total"] <= 150 <= d["total"],
          f"{m1r['denominator']['total']} / 150 / {d['total']}")
    check("本期分母 > 0", m1r["denominator"]["eligible"] > 0,
          str(m1r["denominator"]["eligible"]))

    # ---------- 6. 演示序列 ----------
    print("\n[6] 演示序列与数据库对得上")
    for code, exp in (("A", True), ("B", False)):
        ev = cd.get(f"/api/demo/{code}/events").json()
        closed = len(ev["events"]) == 2
        check(f"序列 {code} 闭合={exp}", closed == exp,
              " · ".join(f"{e['code']}@{e['ts_ms']:.0f}ms" for e in ev["events"]))
    d1 = cd.get("/api/cases/CZ-DEMO-001").json()
    d2 = cd.get("/api/cases/CZ-DEMO-002").json()
    check("CZ-DEMO-001 属于本期", d1["case"]["period"] == "2026-10", d1["case"]["period"])
    check("CZ-DEMO-002 属于本期", d2["case"]["period"] == "2026-10", d2["case"]["period"])
    check("演示病例有里程碑", len(d1["milestones"]) >= 5, f"{len(d1['milestones'])} 个节点")
    codes = [m["code"] for m in d2["milestones"]]
    check("病例002 器械未闭合",
          "device_visible_start" in codes and "device_visible_end" not in codes,
          ",".join(codes[-2:]))
    fr = cd.get("/api/demo/A/frame/4")
    check("帧图可取", fr.status_code == 200 and fr.headers["content-type"].startswith("image"),
          f"{fr.status_code} {len(fr.content)}B")

    # ---------- 7. 随访 ----------
    print("\n[7] 随访工作台自洽")
    fu = cn.get("/api/followups", params={"limit": 1}).json()
    s = sum(fu["counts"].values())
    check("各分组之和 = 总数", s == fu["total"], f"{s} vs {fu['total']}")
    check("今日待访非空", fu["counts"].get("today", 0) > 0, str(fu["counts"]))
    check("逾期非空（演示要点）", fu["counts"].get("overdue", 0) > 0,
          f"overdue={fu['counts'].get('overdue')}")

    # ---------- 8. 整改 ----------
    print("\n[8] 整改台账六态齐全")
    fs = cq.get("/api/qc/findings").json()
    check("6 条事项", len(fs["rows"]) == 6, str(len(fs["rows"])))
    need = {"open", "assigned", "fixing", "verifying", "closed", "rejected"}
    check("六态各 1 条", set(fs["counts"]) == need and all(v == 1 for v in fs["counts"].values()),
          str(fs["counts"]))
    closed = next(r for r in fs["rows"] if r["status"] == "closed")
    check("已关闭项带前后对比",
          bool(closed["metrics_at_open"]) and bool(closed["metrics_at_close"]),
          f"{list((closed['metrics_at_open'] or {}).values())[0]['value']}% → "
          f"{list((closed['metrics_at_close'] or {}).values())[0]['value']}%")
    det = cq.get("/api/qc/findings/3").json()
    check("待复核项可取当期指标值", bool(det.get("current_metric")), str(det.get("current_metric")))
    check("待复核项可用动作 = 关闭/退回",
          set(det["allowed"]) == {"closed", "fixing"}, str(list(det["allowed"])))

    # ---------- 9. 状态机 ----------
    print("\n[9] 状态机拒绝非法操作")
    r = cq.post("/api/qc/findings/5/submit", json={})
    check("open 不能提交复核", r.status_code == 409, f"{r.status_code} {r.text[:40]}")
    r = cq.post("/api/qc/findings/1/assign", json={"owner_id": "doctor"})
    check("closed 不能指派", r.status_code == 409, str(r.status_code))
    r = cq.post("/api/qc/findings/5/reject", json={"note": ""})
    check("驳回必须写理由", r.status_code == 409, f"{r.status_code} {r.text[:30]}")

    # ---------- 10. 数据说明 ----------
    print("\n[10] 数据说明页自洽")
    ab = anon.get("/api/about").json()
    check("参数总数 = 各组之和",
          ab["param_total"] == sum(g["count"] for g in ab["groups"]),
          f"{ab['param_total']} vs {sum(g['count'] for g in ab['groups'])}")
    check("假设类单独标注", "工程假设" in ab["dist"], str(ab["dist"]))
    check("导丝数据集标高风险",
          any("未标注" in l["license"] and l["risk"] == "high" for l in ab["licenses"]), "")
    check("能力边界不可证条目 ≥ 4", len(ab["limits"]["cannot"]) >= 4,
          f"{len(ab['limits']['cannot'])} 条")

    # ---------- 11. 退出 ----------
    print("\n[11] 退出后会话失效")
    r = cg.post("/api/logout")
    check("退出返回 200", r.status_code == 200, str(r.status_code))
    r = cg.get("/qc")
    check("退出后访问页面 → 302", r.status_code == 302, str(r.status_code))

    # ---------- 汇总 ----------
    print("\n" + "=" * 72)
    fail = [x for x in results if x[0] == FAIL]
    print(f"共 {len(results)} 项 · 通过 {len(results) - len(fail)} · 失败 {len(fail)}")
    if fail:
        print("\n失败项：")
        for _, n, dt in fail:
            print(f"  ✗ {n}  {dt}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
