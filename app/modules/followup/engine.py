# -*- coding: utf-8 -*-
"""随访状态判定（M4）

规则来自 00-总方案 §5.5 与临床规范：
  1. 分母只算"窗口已过"或"窗口内"的节点，未到窗口的不进待办
  2. 逾期 = 窗口结束仍未完成
  3. 标失访必须：已联系 ≥3 次 **且** 逾期 ≥30 天
  4. completed 必须挂一条记录（由 API 层强制）
  5. 死亡病例其余节点自动关闭（deceased）
"""
from __future__ import annotations

from datetime import date

MIN_ATTEMPTS_FOR_LOST = 3
MIN_OVERDUE_DAYS = 30

BUCKET_CN = {
    "today": "今日待访",
    "overdue": "逾期",
    "lost": "失访",
    "completed": "已完成",
    "upcoming": "未到窗口",
    "refused": "拒绝",
    "deceased": "已故关闭",
}


def classify(plan: dict, attempts: int, today: date) -> str:
    """返回该随访节点当前所处分组。"""
    st = plan["status"]
    if st in ("completed", "refused", "deceased", "lost"):
        return st

    ws = date.fromisoformat(str(plan["window_start"]))
    we = date.fromisoformat(str(plan["window_end"]))

    if today > we:
        return "overdue"
    if ws <= today <= we:
        return "today"
    return "upcoming"


def overdue_days(plan: dict, today: date) -> int:
    we = date.fromisoformat(str(plan["window_end"]))
    return max(0, (today - we).days)


def can_mark_lost(plan: dict, attempts: int, today: date) -> tuple[bool, str]:
    """失访不是随手点一下：必须联系够次数且逾期够久。"""
    if plan["status"] in ("completed", "deceased"):
        return False, "该节点已完成或患者已故，不能标失访"
    if attempts < MIN_ATTEMPTS_FOR_LOST:
        return False, f"已联系 {attempts} 次，不足 {MIN_ATTEMPTS_FOR_LOST} 次"
    days = overdue_days(plan, today)
    if days < MIN_OVERDUE_DAYS:
        return False, f"逾期 {days} 天，不足 {MIN_OVERDUE_DAYS} 天"
    return True, "满足失访条件"


def can_complete(plan: dict) -> tuple[bool, str]:
    if plan["status"] == "deceased":
        return False, "患者已故，节点已关闭"
    if plan["status"] in ("completed", "lost"):
        return False, "该节点已结束"
    return True, ""


def summary(rows: list[dict]) -> dict:
    """四段计数，供工作台顶部显示。"""
    out = {"today": 0, "overdue": 0, "lost": 0, "completed": 0,
           "upcoming": 0, "refused": 0, "deceased": 0}
    for r in rows:
        out[r["bucket"]] = out.get(r["bucket"], 0) + 1
    return out
