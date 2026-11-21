# -*- coding: utf-8 -*-
"""检测事件落库 · 真库实测（第 4 步验收，需 PostgreSQL + Redis 已起）

直接调用端点函数（不依赖 TestClient），走真实 DB + Redis：
应用 006 迁移 → persist 两次 → 校验落库 + exactly-once。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import db
from app.main import persist_demo_events
from app.modules.events import sink


def cleanup_sequence_events() -> None:
    """删除演示病例的历史 sequence_index 事件，保证脚本可重复运行。"""
    for case_no in ("CZ-DEMO-001", "CZ-DEMO-002"):
        cid = sink.case_id_for_case_no(case_no)
        if cid:
            db.execute(
                "DELETE FROM milestones WHERE case_id = %s "
                "AND source = 'detector' AND ts_source = 'sequence_index'", (cid,))


def ensure_migration() -> None:
    rows = db.query("SELECT indexname FROM pg_indexes WHERE indexname = 'uq_ms_detector_frame'")
    if rows:
        print("索引 uq_ms_detector_frame 已存在，跳过")
        return
    db.execute(
        "CREATE UNIQUE INDEX uq_ms_detector_frame "
        "ON milestones (case_id, code, (evidence->>'frame')) "
        "WHERE source = 'detector' AND voided = false")
    print("已创建索引 uq_ms_detector_frame")


def check(cond: bool, label: str) -> None:
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        sys.exit(1)


def main() -> None:
    ensure_migration()
    cleanup_sequence_events()

    j1 = persist_demo_events("A")
    event_count = j1["event_count"]
    case_id = j1["case_id"]
    print("  首次落库：", {k: j1[k] for k in ("case_id", "event_count", "inserted", "deduped", "unique_blocked")})
    check(j1["inserted"] == event_count, f"首次 inserted == 事件数（{j1['inserted']} == {event_count}）")

    j2 = persist_demo_events("A")
    print("  二次落库：", {k: j2[k] for k in ("inserted", "deduped", "unique_blocked")})
    check(j2["inserted"] == 0, f"二次 inserted == 0（实际 {j2['inserted']}）")
    check(j2["deduped"] + j2["unique_blocked"] == event_count,
          f"二次全部被拦截（{j2['deduped'] + j2['unique_blocked']} == {event_count}）")

    rows = db.query(
        "SELECT id, code, seq_ts_ms, source, ts_source, evidence "
        "FROM milestones WHERE case_id = %s AND source = 'detector' AND ts_source = 'sequence_index' "
        "ORDER BY id", (case_id,))
    check(len(rows) == event_count, f"milestones sequence_index 事件数 == {event_count}（实际 {len(rows)}）")
    for row in rows:
        ev = row["evidence"]
        check(row["source"] == "detector" and row["ts_source"] == "sequence_index",
              f"source/ts_source 正确（{row['source']}/{row['ts_source']}）")
        check(isinstance(ev, dict) and {"frame", "rule", "model_ver"} <= set(ev),
              f"evidence 含 frame/rule/model_ver")
        print(f"    落库：{row['code']} @ {row['seq_ts_ms']}ms | frame={ev.get('frame')} conf={ev.get('conf')} rule={ev.get('rule')}")

    print("\n真库实测通过：检测事件已幂等写入 milestones，exactly-once 生效。")


if __name__ == "__main__":
    main()
