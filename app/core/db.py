# -*- coding: utf-8 -*-
"""数据库访问：薄封装，连不上就明确报降级，不静默失败。"""
from __future__ import annotations

from contextlib import contextmanager

from app.core import config as C


def connect():
    import psycopg2
    conn = psycopg2.connect(C.PG_DSN, connect_timeout=3)
    conn.autocommit = True
    return conn


def online() -> bool:
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cases LIMIT 1")
        return True
    except Exception:
        return False


@contextmanager
def cursor():
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def query(sql: str, args=None) -> list[dict]:
    with cursor() as cur:
        cur.execute(sql, args or ())
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def query_one(sql: str, args=None):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args=None) -> int:
    """写操作，返回受影响行数。"""
    with cursor() as cur:
        cur.execute(sql, args or ())
        return cur.rowcount


def insert_returning(sql: str, args=None):
    with cursor() as cur:
        cur.execute(sql, args or ())
        row = cur.fetchone()
        return row[0] if row else None


def audit(entity: str, entity_id, action: str, actor: str | None, detail: dict | None = None):
    """写审计。任何写操作都应调用，这是可追溯的底线。"""
    import json
    execute("INSERT INTO audit_logs (entity, entity_id, action, actor, detail) "
            "VALUES (%s,%s,%s,%s,%s)",
            (entity, str(entity_id) if entity_id is not None else None,
             action, actor, json.dumps(detail or {}, ensure_ascii=False)))
