# -*- coding: utf-8 -*-
"""检测事件落库（sink）：把「检测 → 事件 → 时间戳 → 落库」这条断链补上。

设计要点
--------
1. exactly-once：Redis SETNX 做软去重（2s 窗口），数据库唯一索引
   uq_ms_detector_frame 做硬保证，重复摄入不会产生重复里程碑。
2. 降级明确：Redis 不可用时软去重退化为「交数据库兜底」，不静默吞错；
   数据库不可用时抛出异常，由调用方决定（与 db.online() 的降级哲学一致）。
3. 证据完整：每条事件写入 evidence（frame / conf / k_in / m_out / rule / model_ver），
   使「为什么这一帧算入画」可追溯——这正是事件级自检的落地形态。
"""
from __future__ import annotations

import json

from app.core import config as C
from app.core import db

DEDUP_TTL_MS = 2000            # 与前端「去重窗口 2000ms」一致
DETECTOR = "detector"
TS_SOURCE = "sequence_index"


def _redis():
    import redis
    return redis.Redis(
        host=C.REDIS_HOST, port=C.REDIS_PORT,
        password=C.REDIS_PASSWORD or None,
        socket_connect_timeout=1, socket_timeout=1,
    )


def redis_setnx(key: str, ttl_ms: int = DEDUP_TTL_MS) -> bool:
    """Redis 软去重：SET NX PX。Redis 不可用时返回 True（交 DB 硬保证兜底）。"""
    try:
        return bool(_redis().set(key, "1", nx=True, px=ttl_ms))
    except Exception:
        return True


def case_id_for_case_no(case_no: str) -> int | None:
    row = db.query_one(
        "SELECT id FROM cases WHERE tenant = 'demo' AND case_no = %s", (case_no,))
    return row["id"] if row else None


def evidence_payload(event, k_in: int, m_out: int, model_ver: str) -> dict:
    """构造 evidence jsonb：记录事件的全部判定依据。"""
    return {
        "frame": event.frame,
        "conf": event.confidence,
        "k_in": k_in,
        "m_out": m_out,
        "rule": event.rule,
        "model_ver": model_ver,
    }


def persist_events(case_id: int, events, *, k_in: int, m_out: int,
                   model_ver: str, actor: str | None = None) -> dict:
    """把一批事件幂等地写入 milestones。

    events 为 state_machine.Event 序列（含 code / frame / ts_ms / confidence / rule）。
    返回 {inserted, deduped, unique_blocked} 供调用方与自检观察。
    """
    inserted = deduped = unique_blocked = 0
    for e in events:
        key = f"det:dedup:{case_id}:{e.code}:{e.frame}"
        if not redis_setnx(key):
            deduped += 1
            continue
        try:
            evidence = json.dumps(
                evidence_payload(e, k_in, m_out, model_ver), ensure_ascii=False)
            db.execute(
                "INSERT INTO milestones "
                "(case_id, code, seq_ts_ms, source, ts_source, entered_by, evidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (case_id, e.code, int(round(e.ts_ms)), DETECTOR, TS_SOURCE,
                 actor, evidence))
            inserted += 1
        except Exception as exc:
            # psycopg2.errors.UniqueViolation：唯一索引兜底，视为「已存在」
            if exc.__class__.__name__ == "UniqueViolation":
                unique_blocked += 1
                continue
            raise
    return {"inserted": inserted, "deduped": deduped, "unique_blocked": unique_blocked}
