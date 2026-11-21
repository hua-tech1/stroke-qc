# -*- coding: utf-8 -*-
"""检测事件落库 · 自检脚本（第 4 步验收）

用 mock 验证 sink 的 exactly-once 逻辑与 evidence 载荷，不依赖真实 DB/Redis。
全部通过 exit 0，否则 exit 1。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.modules.events import sink


@dataclass
class Ev:
    code: str
    frame: int
    ts_ms: float
    confidence: float
    rule: str


class _UniqueViolation(Exception):
    pass


_UniqueViolation.__name__ = "UniqueViolation"


def check(cond: bool, label: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        sys.exit(1)


def main() -> None:
    e = Ev("device_visible_start", 4, 267.0, 0.97, "连续 3 帧 conf≥0.5 判入画")

    # ---- 1. evidence_payload 纯函数 ----
    p = sink.evidence_payload(e, 3, 5, "yolov8n-guidewire-v1")
    check(p == {"frame": 4, "conf": 0.97, "k_in": 3, "m_out": 5,
                "rule": e.rule, "model_ver": "yolov8n-guidewire-v1"},
          "evidence_payload 字段完整")

    # ---- 2. 正常插入路径 ----
    captured = {}
    sink.redis_setnx = lambda key, ttl=2000: True

    def fake_execute(sql, args):
        captured["sql"], captured["args"] = sql, args

    sink.db.execute = fake_execute
    res = sink.persist_events(554, [e], k_in=3, m_out=5, model_ver="yolov8n-guidewire-v1")
    check(res == {"inserted": 1, "deduped": 0, "unique_blocked": 0}, "正常插入 inserted=1")

    sql, args = captured["sql"], captured["args"]
    check("INSERT INTO milestones" in sql, "SQL 为 milestones 插入")
    check(args[3] == "detector" and args[4] == "sequence_index",
          f"source/ts_source 正确（{args[3]}/{args[4]}）")
    check(json.loads(args[6])["frame"] == 4, "evidence jsonb 载荷正确")

    # ---- 3. Redis 软去重路径 ----
    sink.redis_setnx = lambda key, ttl=2000: False
    res2 = sink.persist_events(554, [e], k_in=3, m_out=5, model_ver="v1")
    check(res2 == {"inserted": 0, "deduped": 1, "unique_blocked": 0}, "软去重 deduped=1")

    # ---- 4. DB 唯一索引兜底路径 ----
    def fake_execute_dup(sql, args):
        raise _UniqueViolation()

    sink.redis_setnx = lambda key, ttl=2000: True
    sink.db.execute = fake_execute_dup
    res3 = sink.persist_events(554, [e], k_in=3, m_out=5, model_ver="v1")
    check(res3 == {"inserted": 0, "deduped": 0, "unique_blocked": 1}, "DB 唯一索引兜底 unique_blocked=1")

    # ---- 5. case_id 缺失降级 ----
    sink.db.query_one = lambda sql, args: None
    check(sink.case_id_for_case_no("NOPE") is None, "病例缺失时返回 None")

    # ---- 6. 迁移文件存在且含索引名 ----
    mig = ROOT / "migrations" / "006_detector_sink.sql"
    check(mig.exists(), "迁移文件 006_detector_sink.sql 存在")
    check("uq_ms_detector_frame" in mig.read_text(encoding="utf-8"),
          "索引名 uq_ms_detector_frame 正确")

    print("\n自检通过：sink exactly-once 逻辑、evidence 载荷、迁移文件均正确。")


if __name__ == "__main__":
    main()
