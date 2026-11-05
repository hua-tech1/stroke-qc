# -*- coding: utf-8 -*-
"""卒中绿色通道质控台 · 后端入口

S4：术中监控（采集抽象 + 事件状态机 + 播放接口）
S5：病例列表与详情（读数据库 600 例）

启动：
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

from pydantic import BaseModel

from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core import auth
from app.core import config as C
from app.core import data_notes
from app.core import db
from app.modules.events.source import FileSequenceSource
from app.modules.events.state_machine import dwell_ms, generate_events, is_open
from app.modules.followup import engine as fu
from app.qc import findings as qc_findings_mod
from app.qc import report as qc_report

app = FastAPI(title="卒中绿色通道质控台", version="0.5.0")

JSON_DIR = C.DATA / "json"
FRAME_DIR = C.DATA / "frames"


# ============================================================
# 演示序列（术中监控）
# ============================================================
@lru_cache(maxsize=8)
def load_detection(seq: str) -> dict:
    p = JSON_DIR / f"{seq}.json"
    if not p.exists():
        raise HTTPException(500, f"预生成检测结果缺失：{p}")
    return json.loads(p.read_text(encoding="utf-8"))


def demo_meta(code: str) -> dict:
    code = code.upper()
    if code not in C.SEQUENCES:
        raise HTTPException(404, f"未知演示序列：{code}")
    return C.SEQUENCES[code]


@app.get("/api/demo")
def list_demo():
    out = []
    for code, meta in C.SEQUENCES.items():
        try:
            d = load_detection(meta["seq"])
            n, hit = d["total_frames"], d["hit_frames"]
        except HTTPException:
            n, hit = 0, 0
        out.append({"code": code, "seq": meta["seq"], "label": meta["label"],
                    "hint": meta["hint"], "case_no": meta["case_no"],
                    "total_frames": n, "hit_frames": hit,
                    "data_source": "离线序列（预生成检测）"})
    return {"sequences": out, "source_name": FileSequenceSource.name}


@app.get("/api/demo/{code}/frames")
def demo_frames(code: str):
    meta = demo_meta(code)
    d = load_detection(meta["seq"])
    src = FileSequenceSource(meta["seq"], FRAME_DIR, C.FPS)
    return {"case": code, "seq": meta["seq"], "case_no": meta["case_no"],
            "fps": d["fps"], "frame_ms": d["frame_ms"],
            "total_frames": d["total_frames"], "conf": d["conf"],
            "frames": d["frames"], "meta": src.meta()}


@app.get("/api/demo/{code}/events")
def demo_events(code: str):
    """事件一律由状态机现算，不读写死的 JSON。"""
    meta = demo_meta(code)
    d = load_detection(meta["seq"])
    events = generate_events(d["frames"])
    return {"case": code, "seq": meta["seq"], "case_no": meta["case_no"],
            "events": [e.dict() for e in events], "event_count": len(events),
            "open": is_open(events), "dwell_ms": dwell_ms(d["frames"], events),
            "params": {"conf": C.CONF, "k_in": C.K_IN, "m_out": C.M_OUT}}


@app.get("/api/demo/{code}/frame/{idx}")
def demo_frame(code: str, idx: int):
    meta = demo_meta(code)
    p = FRAME_DIR / meta["seq"] / f"{idx:04d}.jpg"
    if not p.exists():
        raise HTTPException(404, f"帧不存在：{idx}")
    return FileResponse(str(p), media_type="image/jpeg")


# ============================================================
# 病例列表与详情（数据库）
# ============================================================
LIST_SQL = """
SELECT c.id, c.case_no, c.period, c.dept_id, d.name AS dept_name,
       c.age, c.sex, c.case_type, c.is_ihs, c.is_transfer,
       c.exclude_reason, c.exclude_kind, c.is_featured, c.discharge_type,
       c.arrival_at, c.mtici,
       ROUND(EXTRACT(EPOCH FROM (n.occurred_at - a.occurred_at))/60.0, 1) AS dnt,
       ROUND(EXTRACT(EPOCH FROM (p.occurred_at - a.occurred_at))/60.0, 1) AS dpt
FROM cases c
LEFT JOIN depts d ON d.id = c.dept_id
LEFT JOIN milestones a ON a.case_id = c.id AND a.code = 'arrival'  AND NOT a.voided
LEFT JOIN milestones n ON n.case_id = c.id AND n.code = 'needle'   AND NOT n.voided
LEFT JOIN milestones p ON p.case_id = c.id AND p.code = 'puncture' AND NOT p.voided
WHERE c.tenant = 'demo'
  AND (%(period)s IS NULL OR c.period = %(period)s)
  AND (%(dept)s   IS NULL OR c.dept_id = %(dept)s)
  AND (%(type)s   IS NULL OR c.case_type = %(type)s)
  AND (%(only_eligible)s = false
       OR (c.case_type = 'ais' AND c.is_ihs = false AND c.exclude_reason IS NULL))
ORDER BY c.arrival_at DESC
LIMIT %(limit)s OFFSET %(offset)s
"""


@app.get("/api/cases")
def list_cases(period: str | None = None, dept: str | None = None,
               type: str | None = None, only_eligible: bool = False,
               limit: int = Query(50, le=500), offset: int = 0):
    if not db.online():
        raise HTTPException(503, "数据库不可用，病例列表暂不可用（演示降级）")
    args = dict(period=period or None, dept=dept or None, type=type or None,
                only_eligible=only_eligible, limit=limit, offset=offset)
    rows = db.query(LIST_SQL, args)
    # 计数必须用与列表完全相同的条件，否则分页会显示"共 48 例"但只有 40 行
    total = db.query_one("""
        SELECT count(*) AS n FROM cases c
        WHERE c.tenant='demo'
          AND (%(period)s IS NULL OR c.period = %(period)s)
          AND (%(dept)s IS NULL OR c.dept_id = %(dept)s)
          AND (%(type)s IS NULL OR c.case_type = %(type)s)
          AND (%(only_eligible)s = false
               OR (c.case_type = 'ais' AND c.is_ihs = false AND c.exclude_reason IS NULL))
    """, dict(period=period or None, dept=dept or None, type=type or None,
             only_eligible=only_eligible))
    return {"total": total["n"] if total else 0, "limit": limit, "offset": offset,
            "rows": rows}


@app.get("/api/cases/{case_no}")
def case_detail(case_no: str):
    if not db.online():
        raise HTTPException(503, "数据库不可用")
    c = db.query_one("""
        SELECT c.*, d.name AS dept_name
        FROM cases c LEFT JOIN depts d ON d.id = c.dept_id
        WHERE c.tenant='demo' AND c.case_no = %s
    """, (case_no,))
    if not c:
        raise HTTPException(404, f"病例不存在：{case_no}")

    ms = db.query("""
        SELECT m.code, md.name, m.source, m.ts_source, m.occurred_at, m.seq_ts_ms,
               m.voided, m.void_reason, m.evidence
        FROM milestones m JOIN milestone_defs md ON md.code = m.code
        WHERE m.case_id = %s ORDER BY m.occurred_at NULLS LAST, m.seq_ts_ms
    """, (c["id"],))

    comps = db.query("""
        SELECT type, occurred_at, severity, criterion, description
        FROM complications WHERE case_id = %s ORDER BY occurred_at
    """, (c["id"],))

    plans = db.query("""
        SELECT id, node, due_date, window_start, window_end, status
        FROM followup_plans WHERE case_id = %s ORDER BY due_date
    """, (c["id"],))

    issues = db.query("""
        SELECT rule_code, rule_type, severity, field, detail, status
        FROM quality_issues WHERE case_id = %s ORDER BY severity, id
    """, (c["id"],))

    src_stat = {}
    for m in ms:
        src_stat[m["source"]] = src_stat.get(m["source"], 0) + 1

    return {"case": c, "milestones": ms, "complications": comps,
            "followup_plans": plans, "quality_issues": issues,
            "source_stat": src_stat}


@app.get("/api/meta")
def meta():
    if not db.online():
        return {"online": False}
    return {
        "online": True,
        "periods": [r["period"] for r in
                    db.query("SELECT DISTINCT period FROM cases ORDER BY 1 DESC")],
        "depts": db.query("SELECT id, name FROM depts ORDER BY id"),
        "types": [r["case_type"] for r in
                  db.query("SELECT DISTINCT case_type FROM cases ORDER BY 1")],
        "counts": db.query_one("""
            SELECT (SELECT count(*) FROM cases) AS cases,
                   (SELECT count(*) FROM v_qc_eligible) AS eligible,
                   (SELECT count(*) FROM milestones) AS milestones,
                   (SELECT count(*) FROM followup_plans) AS plans
        """),
    }



# ============================================================
# 随访工作台（S6）
# ============================================================
FOLLOWUP_SQL = """
SELECT p.id, p.node, p.due_date, p.window_start, p.window_end, p.status,
       c.case_no, c.patient_name, c.dept_id, d.name AS dept_name,
       c.age, c.sex, c.discharge_at,
       (SELECT count(*) FROM followup_attempts a WHERE a.plan_id = p.id) AS attempts,
       (SELECT r.mrs FROM followup_records r WHERE r.plan_id = p.id
          ORDER BY r.id DESC LIMIT 1) AS last_mrs
FROM followup_plans p
JOIN cases c ON c.id = p.case_id
LEFT JOIN depts d ON d.id = c.dept_id
WHERE c.tenant = 'demo'
  AND (%(dept)s IS NULL OR c.dept_id = %(dept)s)
"""

ORDER = {"today": 0, "overdue": 1, "lost": 2, "refused": 3, "upcoming": 4,
         "completed": 5, "deceased": 6}


@app.get("/api/followups")
def list_followups(bucket: str | None = None, dept: str | None = None,
                   limit: int = Query(50, le=500), offset: int = 0):
    if not db.online():
        raise HTTPException(503, "数据库不可用")
    today = date.fromisoformat(C.TODAY)
    raw = db.query(FOLLOWUP_SQL, {"dept": dept or None})

    rows = []
    for p in raw:
        p["bucket"] = fu.classify(p, p["attempts"], today)
        p["overdue_days"] = fu.overdue_days(p, today)
        p["can_lost"], p["lost_reason"] = fu.can_mark_lost(p, p["attempts"], today)
        rows.append(p)

    counts = fu.summary(rows)
    rows.sort(key=lambda r: (ORDER.get(r["bucket"], 9), str(r["window_end"])))
    if bucket:
        rows = [r for r in rows if r["bucket"] == bucket]

    return {"today": C.TODAY, "counts": counts, "total": len(rows),
            "rows": rows[offset:offset + limit], "bucket_cn": fu.BUCKET_CN}


def _plan_or_404(plan_id: int) -> dict:
    p = db.query_one("""
        SELECT p.*, c.case_no, c.patient_name FROM followup_plans p
        JOIN cases c ON c.id = p.case_id WHERE p.id = %s""", (plan_id,))
    if not p:
        raise HTTPException(404, f"随访节点不存在：{plan_id}")
    return p


class RecordBody(BaseModel):
    mrs: int
    nihss: int | None = None
    barthel: int | None = None
    source: str = "family"
    note: str | None = None
    actor: str | None = "nurse"


class AttemptBody(BaseModel):
    channel: str = "phone"
    result: str = "no_answer"
    note: str | None = None
    actor: str | None = "nurse"


class NoteBody(BaseModel):
    note: str | None = None
    actor: str | None = "qc"


@app.post("/api/followups/{plan_id}/record")
def submit_record(plan_id: int, body: RecordBody):
    """录入随访结果：completed 必须挂记录，这里强制写入。"""
    p = _plan_or_404(plan_id)
    ok, why = fu.can_complete(p)
    if not ok:
        raise HTTPException(409, why)
    if not (0 <= body.mrs <= 6):
        raise HTTPException(400, "mRS 必须在 0–6 之间")

    rid = db.insert_returning("""
        INSERT INTO followup_records (plan_id, mrs, nihss, barthel, source, note, recorded_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (plan_id, body.mrs, body.nihss, body.barthel, body.source, body.note, body.actor))
    db.execute("UPDATE followup_plans SET status='completed', completed_at=now() WHERE id=%s",
               (plan_id,))
    db.audit("followup", plan_id, "record", body.actor,
             {"mrs": body.mrs, "source": body.source, "record_id": rid,
              "case_no": p["case_no"]})
    return {"ok": True, "record_id": rid, "status": "completed"}


@app.post("/api/followups/{plan_id}/attempt")
def add_attempt(plan_id: int, body: AttemptBody):
    """记一次联系。这是标失访的前置条件。"""
    _plan_or_404(plan_id)
    aid = db.insert_returning("""
        INSERT INTO followup_attempts (plan_id, channel, result, note, by_user)
        VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (plan_id, body.channel, body.result, body.note, body.actor))
    n = db.query_one("SELECT count(*) AS n FROM followup_attempts WHERE plan_id=%s",
                     (plan_id,))["n"]
    db.audit("followup", plan_id, "attempt", body.actor,
             {"channel": body.channel, "result": body.result, "attempt_no": n})
    return {"ok": True, "attempt_id": aid, "attempts": n}


@app.post("/api/followups/{plan_id}/lost")
def mark_lost(plan_id: int, body: NoteBody = NoteBody()):
    """标失访：必须已联系 ≥3 次且逾期 ≥30 天，否则拒绝。"""
    p = _plan_or_404(plan_id)
    n = db.query_one("SELECT count(*) AS n FROM followup_attempts WHERE plan_id=%s",
                     (plan_id,))["n"]
    today = date.fromisoformat(C.TODAY)
    ok, why = fu.can_mark_lost(p, n, today)
    if not ok:
        raise HTTPException(409, why)
    db.execute("UPDATE followup_plans SET status='lost' WHERE id=%s", (plan_id,))
    db.audit("followup", plan_id, "lost", body.actor,
             {"attempts": n, "overdue_days": fu.overdue_days(p, today),
              "note": body.note, "case_no": p["case_no"]})
    return {"ok": True, "status": "lost"}


@app.post("/api/followups/{plan_id}/refuse")
def mark_refuse(plan_id: int, body: NoteBody = NoteBody()):
    p = _plan_or_404(plan_id)
    if p["status"] in ("completed", "lost", "deceased"):
        raise HTTPException(409, "该节点已结束，不能标拒绝")
    db.execute("UPDATE followup_plans SET status='refused' WHERE id=%s", (plan_id,))
    db.audit("followup", plan_id, "refused", body.actor,
             {"note": body.note, "case_no": p["case_no"]})
    return {"ok": True, "status": "refused"}


@app.get("/api/followups/{plan_id}/attempts")
def list_attempts(plan_id: int):
    _plan_or_404(plan_id)
    rows = db.query("""
        SELECT id, attempted_at, channel, result, note, by_user
        FROM followup_attempts WHERE plan_id=%s ORDER BY attempted_at DESC""", (plan_id,))
    return {"rows": rows, "count": len(rows)}


@app.get("/followups")
def followups_page():
    return _page("followups.html")


# ============================================================
# 质控报表与整改台账（S7）
# ============================================================
FINDING_STATUS_CN = {
    "open": "待处理", "assigned": "已指派", "fixing": "整改中",
    "verifying": "待复核", "closed": "已关闭", "rejected": "已驳回",
}
SEVERITY_CN = {"high": "高", "medium": "中", "low": "低"}


@app.get("/api/qc/report")
def qc_report_api(range: str = "m12", dept: str | None = None):
    if range not in qc_report.RANGES:
        raise HTTPException(400, f"未知期间范围：{range}")
    if not db.online():
        raise HTTPException(503, "数据库不可用，报表无法生成")
    r = qc_report.build(range, dept or None)
    r["ranges"] = [{"key": k, "label": v[0]} for k, v in qc_report.RANGES.items()]
    r["depts"] = db.query("SELECT id, name FROM depts ORDER BY id")
    return r


@app.get("/api/qc/indicators/{code}/drill")
def qc_drill(code: str, side: str = "den", range: str = "m12", dept: str | None = None):
    """下钻：这个指标的分子/分母是哪几例。"""
    if side not in ("num", "den"):
        raise HTTPException(400, "side 只能是 num 或 den")
    if not db.online():
        raise HTTPException(503, "数据库不可用")
    return qc_report.drill(code, side, range, dept or None)


@app.get("/api/qc/findings")
def qc_findings(status: str | None = None, level: str | None = None):
    if not db.online():
        raise HTTPException(503, "数据库不可用")
    where, args = ["1=1"], []
    if status:
        where.append("f.status = %s")
        args.append(status)
    if level:
        where.append("f.level = %s")
        args.append(level)
    rows = db.query(f"""
        SELECT f.id, f.period, f.indicator_code, f.level, f.source, f.severity,
               f.title, f.description, f.owner_id, u.name AS owner_name,
               f.due_date, f.status, f.return_count,
               f.metrics_at_open, f.metrics_at_close, f.verify_note,
               f.closed_at, f.created_at,
               c.case_no,
               (SELECT count(*) FROM qc_actions a WHERE a.finding_id = f.id) AS actions
        FROM qc_findings f
        LEFT JOIN users u ON u.id = f.owner_id
        LEFT JOIN cases c ON c.id = f.case_id
        WHERE {' AND '.join(where)}
        ORDER BY CASE f.status WHEN 'open' THEN 1 WHEN 'assigned' THEN 2
                 WHEN 'fixing' THEN 3 WHEN 'verifying' THEN 4
                 WHEN 'closed' THEN 5 ELSE 6 END, f.id DESC
    """, args or None)
    for r in rows:
        r["status_cn"] = FINDING_STATUS_CN.get(r["status"], r["status"])
        r["severity_cn"] = SEVERITY_CN.get(r["severity"], r["severity"])
        r["level_cn"] = "系统性" if r["level"] == "systemic" else "个案"
        for k in ("due_date", "closed_at", "created_at"):
            if r[k] is not None:
                r[k] = r[k].strftime("%Y-%m-%d")
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"rows": rows, "counts": counts, "status_cn": FINDING_STATUS_CN}


@app.get("/api/qc/findings/{fid}")
def qc_finding_detail(fid: int):
    """详情：含措施记录、审计时间轴、当前可用动作。"""
    if not db.online():
        raise HTTPException(503, "数据库不可用")
    try:
        d = qc_findings_mod.detail(fid)
    except qc_findings_mod.TransitionError as e:
        raise HTTPException(404, str(e))
    code = d["finding"].get("indicator_code")
    if code:
        d["current_metric"] = qc_report.metric_value(code)
    return d


class AssignBody(BaseModel):
    owner_id: str
    due_date: str | None = None
    actor: str | None = "qc"


class ActionBody(BaseModel):
    action: str
    owner_id: str | None = None
    due_date: str | None = None
    result: str | None = None
    actor: str | None = "qc"


class SubmitBody(BaseModel):
    note: str | None = None
    actor: str | None = "qc"


class VerifyBody(BaseModel):
    passed: bool
    note: str | None = None
    actor: str | None = "qc"


class RejectBody(BaseModel):
    note: str
    actor: str | None = "qc"


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except qc_findings_mod.TransitionError as e:
        # 409：状态机拒绝，不是参数错也不是服务器错
        raise HTTPException(409, str(e))


@app.post("/api/qc/findings/{fid}/assign")
def qc_finding_assign(fid: int, body: AssignBody):
    return _guard(qc_findings_mod.assign, fid, body.owner_id, body.due_date, body.actor)


@app.post("/api/qc/findings/{fid}/start")
def qc_finding_start(fid: int, body: SubmitBody = SubmitBody()):
    return _guard(qc_findings_mod.start, fid, body.actor)


@app.post("/api/qc/findings/{fid}/action")
def qc_finding_action(fid: int, body: ActionBody):
    return _guard(qc_findings_mod.add_action, fid, body.action,
                  body.owner_id, body.due_date, body.result, body.actor)


@app.post("/api/qc/findings/{fid}/submit")
def qc_finding_submit(fid: int, body: SubmitBody):
    # 提交时把当期指标值一并留档，便于复核人判断"改没改"
    f = qc_findings_mod._get(fid)
    cur = qc_report.metric_value(f["indicator_code"]) if f.get("indicator_code") else None
    return _guard(qc_findings_mod.submit, fid, body.note, body.actor, cur)


@app.post("/api/qc/findings/{fid}/verify")
def qc_finding_verify(fid: int, body: VerifyBody):
    f = qc_findings_mod._get(fid)
    metrics = None
    if body.passed and f.get("indicator_code"):
        metrics = qc_report.metric_value(f["indicator_code"])
    return _guard(qc_findings_mod.verify, fid, body.passed, body.note, metrics, body.actor)


@app.post("/api/qc/findings/{fid}/reject")
def qc_finding_reject(fid: int, body: RejectBody):
    return _guard(qc_findings_mod.reject, fid, body.note, body.actor)


@app.get("/qc")
def qc_page():
    return _page("qc.html")



# ============================================================
# 身份与会话（R7）
# ============================================================
# 无需登录即可访问：登录页、健康检查、数据说明、登录接口本身
PUBLIC = {"/login", "/api/login", "/health", "/about", "/api/about", "/favicon.ico"}

# API 读权限（页面权限在 READ_PAGES 里）
READ_APIS = [
    ("/api/overview",  {"qc", "guest"}),
    ("/api/demo",      {"doctor", "guest"}),
    ("/api/followups", {"nurse", "guest"}),
    ("/api/qc",        {"qc", "guest"}),
]
# 写权限
WRITE_APIS = [
    ("/api/followups", "followup"),
    ("/api/qc/findings", "qc"),
]


def _forbidden(msg: str, role: str):
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>无权访问</title><style>
body{{margin:0;font:13px/1.7 "Microsoft YaHei",sans-serif;background:#F0F2F5;color:#1F2937;
display:flex;align-items:center;justify-content:center;height:100vh}}
.box{{background:#fff;border:1px solid #D9DEE6;padding:28px 32px;max-width:460px}}
h1{{margin:0 0 8px;font-size:16px;color:#A32D2D}}
p{{margin:6px 0;color:#4B5563}} code{{background:#F3F4F6;padding:1px 5px;border-radius:2px}}
a{{color:#1A5FB4}}
</style></head><body><div class="box">
<h1>403 · 当前角色无权访问</h1>
<p>{msg}</p>
<p>当前身份：<b>{role}</b></p>
<p><a href="/">回到我的首页</a>　·　<a href="/about">数据说明</a></p>
</div></body></html>"""
    return HTMLResponse(html, status_code=403)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path in PUBLIC:
        return await call_next(request)

    # 登录页自身之外，一律先验会话
    user = auth.parse_token(request.cookies.get(auth.COOKIE))
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "未登录或会话已过期"}, status_code=401)
        nxt = quote(request.url.path + (("?" + request.url.query) if request.url.query else ""))
        return RedirectResponse(f"/login?next={nxt}", status_code=302)

    request.state.user = user
    role = user["r"]

    # 读权限
    if path.startswith("/api/"):
        for prefix, roles in READ_APIS:
            if path.startswith(prefix) and role not in roles:
                return JSONResponse(
                    {"detail": f"当前角色（{role}）无权访问该接口"}, status_code=403)
    else:
        for prefix, roles in auth.READ_PAGES.items():
            if (path == prefix or path.startswith(prefix + "/")) and role not in roles:
                return _forbidden(f"该模块仅对 {('、'.join(sorted(roles)))} 开放。", role)

    # 写权限
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        for prefix, kind in WRITE_APIS:
            if path.startswith(prefix) and not auth.can_write(role, kind):
                return JSONResponse(
                    {"detail": f"当前角色（{role}）无写权限，操作已拒绝"}, status_code=403)

    return await call_next(request)


class LoginBody(BaseModel):
    username: str
    password: str


@app.get("/login")
def login_page(request: Request):
    """已是登录态就直接回首页，避免反复登录。"""
    if auth.parse_token(request.cookies.get(auth.COOKIE)):
        return RedirectResponse("/", status_code=302)
    return _page("login.html")


@app.post("/api/login")
def api_login(body: LoginBody):
    if not db.online():
        raise HTTPException(503, "数据库不可用，无法登录")
    u = db.query_one(
        "SELECT id, name, role, password_hash, active FROM users WHERE id = %s",
        (body.username.strip(),))
    # 账号不存在与口令错误返回同一句话，不泄露账号是否存在
    if not u or not u["active"] or not auth.verify_password(body.password, u["password_hash"]):
        db.audit("auth", body.username.strip(), "login_failed", None, {"ip_hint": "local"})
        raise HTTPException(401, "账号或口令不正确")

    db.audit("auth", u["id"], "login", u["id"], {"role": u["role"]})
    token = auth.make_token(u["id"], u["name"], u["role"])
    resp = JSONResponse({"ok": True, "role": u["role"], "name": u["name"],
                         "home": auth.HOME.get(u["role"], "/")})
    resp.set_cookie(auth.COOKIE, token, max_age=auth.TTL, httponly=True,
                    samesite="lax", path="/")
    return resp


@app.post("/api/logout")
def api_logout(request: Request):
    u = getattr(request.state, "user", None)
    if u:
        db.audit("auth", u["u"], "logout", u["u"], {})
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


@app.get("/api/me")
def api_me(request: Request):
    u = request.state.user
    return {"id": u["u"], "name": u["n"], "role": u["r"],
            "home": auth.HOME.get(u["r"], "/"),
            "exp": u["exp"]}


# ============================================================
# 健康检查与页面
# ============================================================
@app.get("/health")
def health():
    redis_ok = False
    try:
        import redis
        r = redis.Redis(host=C.REDIS_HOST, port=C.REDIS_PORT,
                        password=C.REDIS_PASSWORD, socket_connect_timeout=2)
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"ok": True, "postgres": db.online(), "redis": redis_ok,
            "auth": "required",
            "params": {"conf": C.CONF, "k_in": C.K_IN, "m_out": C.M_OUT,
                       "fps": C.FPS, "timeout_ms": C.TIMEOUT_MS}}


def _page(name: str):
    p = C.STATIC / name
    if not p.exists():
        return JSONResponse({"error": f"{name} 尚未创建"}, status_code=200)
    return FileResponse(str(p))


@app.get("/")
def index(request: Request):
    """已登录按角色进各自首页；未登录由中间件跳 /login。"""
    u = getattr(request.state, "user", None)
    return RedirectResponse(auth.HOME.get((u or {}).get("r", ""), "/login"))


@app.get("/monitor")
def monitor_page():
    return _page("index.html")


@app.get("/about")
def about_page():
    return _page("about.html")


@app.get("/api/about")
def about_api():
    """数据说明：参数来源、许可、能做/不能做的边界。"""
    return data_notes.build()


@app.get("/api/overview")
def overview_api():
    """首屏四个关键数。取不到就返回空，不阻塞页面渲染。"""
    out = {"counts": None, "report": None, "findings": None}
    try:
        out["counts"] = qc_report.denominator("m12")
    except Exception:
        pass
    try:
        r = qc_report.build("m12")
        out["report"] = {"pass": r["summary"]["pass"], "fail": r["summary"]["fail"],
                         "na": r["summary"]["na"], "total": r["summary"]["total"],
                         "range_cn": r["range_cn"]}
        dnt = next((x for l in r["layers"] for x in l["rows"] if x["code"] == "PR03"), None)
        out["dnt"] = dnt
    except Exception:
        pass
    try:
        rows = db.query("SELECT status, count(*) AS n FROM qc_findings GROUP BY status")
        out["findings"] = {r["status"]: r["n"] for r in rows}
    except Exception:
        pass
    return out


@app.get("/cases")
def cases_page():
    return _page("cases.html")


if C.STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(C.STATIC)), name="static")
