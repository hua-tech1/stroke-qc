# -*- coding: utf-8 -*-
"""整改闭环状态机（S8）

六态：open → assigned → fixing → verifying → closed，另有 rejected 终止态。

三条硬规则（不是提示，是拒绝执行）：
  1. **关闭必须带当期指标值**，且该值由系统现场计算，不接受手工填写。
     否则整改台账就变成"自己打个分说自己改好了"。
  2. **提交复核必须先有措施记录**。没有措施就进 verifying，等于空转。
  3. **退回必须写原因**，且 return_count 累加，退回次数本身就是质量信号。
"""
from __future__ import annotations

from datetime import date, timedelta

from app.core import db

STATUS_CN = {
    "open": "待处理", "assigned": "已指派", "fixing": "整改中",
    "verifying": "待复核", "closed": "已关闭", "rejected": "已驳回",
}

# 允许的迁移：from -> {to: 动作名}
ALLOWED = {
    "open":      {"assigned": "assign", "rejected": "reject"},
    "assigned":  {"fixing": "start", "verifying": "submit", "rejected": "reject"},
    "fixing":    {"verifying": "submit", "rejected": "reject"},
    "verifying": {"closed": "verify", "fixing": "return"},
    "closed":    {},
    "rejected":  {},
}

# 期限：个案 7 天，系统性 30 天
DUE_DAYS = {"case": 7, "systemic": 30}


class TransitionError(Exception):
    """状态迁移被拒。带上原因，前端直接展示。"""


def _get(fid: int) -> dict:
    f = db.query_one("""
        SELECT f.*, u.name AS owner_name FROM qc_findings f
        LEFT JOIN users u ON u.id = f.owner_id WHERE f.id = %s""", (fid,))
    if not f:
        raise TransitionError(f"整改事项不存在：{fid}")
    return f


def _check(f: dict, to: str):
    cur = f["status"]
    nxt = ALLOWED.get(cur, {})
    if to not in nxt:
        raise TransitionError(
            f"当前状态「{STATUS_CN.get(cur, cur)}」不能直接转为「{STATUS_CN.get(to, to)}」")


def _action_count(fid: int) -> int:
    return db.query_one("SELECT count(*) AS n FROM qc_actions WHERE finding_id=%s",
                        (fid,))["n"]


def assign(fid: int, owner_id: str, due_date: str | None = None, actor: str | None = None) -> dict:
    f = _get(fid)
    _check(f, "assigned")

    u = db.query_one("SELECT id, name, role FROM users WHERE id=%s AND active", (owner_id,))
    if not u:
        raise TransitionError(f"责任人不存在或已停用：{owner_id}")
    if not due_date:
        due_date = (date.today() + timedelta(days=DUE_DAYS.get(f["level"], 30))).isoformat()

    db.execute("UPDATE qc_findings SET status='assigned', owner_id=%s, due_date=%s WHERE id=%s",
               (owner_id, due_date, fid))
    db.audit("qc_finding", fid, "assign", actor,
             {"to": owner_id, "due_date": due_date,
              "from_status": f["status"], "to_status": "assigned"})
    return {"ok": True, "status": "assigned", "owner_id": owner_id,
            "owner_name": u["name"], "due_date": due_date}


def start(fid: int, actor: str | None = None) -> dict:
    """已指派 → 整改中。"""
    f = _get(fid)
    _check(f, "fixing")
    db.execute("UPDATE qc_findings SET status='fixing' WHERE id=%s", (fid,))
    db.audit("qc_finding", fid, "start", actor, {"from_status": f["status"]})
    return {"ok": True, "status": "fixing"}


def add_action(fid: int, action: str, owner_id: str | None = None,
               due_date: str | None = None, result: str | None = None,
               actor: str | None = None) -> dict:
    """登记一条整改措施。closed / rejected 之后不允许再加。"""
    f = _get(fid)
    if f["status"] in ("closed", "rejected"):
        raise TransitionError("事项已结束，不能再追加措施")
    if not action or not action.strip():
        raise TransitionError("措施内容不能为空")

    aid = db.insert_returning("""
        INSERT INTO qc_actions (finding_id, action, owner_id, due_date, result)
        VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (fid, action.strip(), owner_id, due_date, result))
    db.audit("qc_finding", fid, "action", actor,
             {"action_id": aid, "text": action.strip()[:80]})
    return {"ok": True, "action_id": aid, "actions": _action_count(fid)}


def submit(fid: int, note: str | None = None, actor: str | None = None,
           current_metric: dict | None = None) -> dict:
    """提交复核。无措施不许提交——空转的整改不算整改。"""
    f = _get(fid)
    _check(f, "verifying")
    n = _action_count(fid)
    if n == 0:
        raise TransitionError("尚未登记任何整改措施，不能提交复核")

    db.execute("UPDATE qc_findings SET status='verifying', verify_note=%s WHERE id=%s",
               (note, fid))
    db.audit("qc_finding", fid, "submit", actor,
             {"actions": n, "note": note, "current_metric": current_metric,
              "from_status": f["status"]})
    return {"ok": True, "status": "verifying", "actions": n}


def verify(fid: int, passed: bool, note: str | None = None,
           metrics: dict | None = None, actor: str | None = None) -> dict:
    """复核。通过则关闭（必须带当期指标值），不通过则退回整改中。

    metrics 由调用方从指标引擎现场计算后传入，**不接受前端手填**。
    数据库还有 CHECK 兜底：status='closed' 时 metrics_at_close 不能为空。
    """
    f = _get(fid)
    if not passed:
        _check(f, "fixing")
        if not note or not note.strip():
            raise TransitionError("退回必须写明原因")
        db.execute("""UPDATE qc_findings
                      SET status='fixing', return_count=return_count+1, verify_note=%s
                      WHERE id=%s""", (note.strip(), fid))
        db.audit("qc_finding", fid, "return", actor,
                 {"note": note.strip(), "return_count": f["return_count"] + 1})
        return {"ok": True, "status": "fixing", "return_count": f["return_count"] + 1}

    _check(f, "closed")
    if not metrics:
        raise TransitionError("关闭必须带当期指标值（由系统计算，不接受手工填写）")

    db.execute("""UPDATE qc_findings
                  SET status='closed', metrics_at_close=%s, verify_note=%s, closed_at=now()
                  WHERE id=%s""",
               (db_json(metrics), note, fid))
    db.audit("qc_finding", fid, "close", actor,
             {"metrics_at_close": metrics, "note": note})
    return {"ok": True, "status": "closed", "metrics_at_close": metrics}


def reject(fid: int, note: str | None = None, actor: str | None = None) -> dict:
    """驳回：确认不是质量问题，或口径有误。必须写理由。"""
    f = _get(fid)
    _check(f, "rejected")
    if not note or not note.strip():
        raise TransitionError("驳回必须写明理由")
    db.execute("UPDATE qc_findings SET status='rejected', verify_note=%s WHERE id=%s",
               (note.strip(), fid))
    db.audit("qc_finding", fid, "reject", actor,
             {"note": note.strip(), "from_status": f["status"]})
    return {"ok": True, "status": "rejected"}


def db_json(v: dict) -> str:
    import json
    return json.dumps(v, ensure_ascii=False)


def detail(fid: int) -> dict:
    f = _get(fid)
    acts = db.query("""
        SELECT a.id, a.action, a.owner_id, u.name AS owner_name, a.due_date,
               a.result, a.created_at
        FROM qc_actions a LEFT JOIN users u ON u.id = a.owner_id
        WHERE a.finding_id=%s ORDER BY a.id""", (fid,))
    logs = db.query("""
        SELECT action, actor, detail, created_at FROM audit_logs
        WHERE entity='qc_finding' AND entity_id=%s ORDER BY id""", (str(fid),))
    for r in acts:
        if r["due_date"]:
            r["due_date"] = r["due_date"].isoformat()
        if r["created_at"]:
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d")
    for r in logs:
        if r["created_at"]:
            r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M")
    f["status_cn"] = STATUS_CN.get(f["status"], f["status"])
    for k in ("due_date", "closed_at", "created_at"):
        if f.get(k) is not None:
            f[k] = f[k].strftime("%Y-%m-%d")

    # allowed 要反映"实际能做的"，不是状态机理论上允许的
    allowed = dict(ALLOWED.get(f["status"], {}))
    if "verifying" in allowed and len(acts) == 0:
        allowed.pop("verifying")      # 没措施不许提交，与 submit() 的校验保持一致

    return {"finding": f, "actions": acts, "logs": logs,
            "allowed": {k: STATUS_CN.get(k, k) for k in allowed}}
