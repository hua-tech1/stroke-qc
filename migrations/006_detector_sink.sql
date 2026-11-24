-- 006_detector_sink.sql
-- 检测事件 exactly-once：同一病例、同一事件码、同一帧，只允许一条有效记录。
-- 种子里的 simulated 检测事件 evidence 为 NULL（本索引对 NULL 不去重，Postgres 默认 NULLS DISTINCT），
-- 因此本索引只约束运行时写入的 sequence_index 事件，不影响既有仿真数据。

CREATE UNIQUE INDEX uq_ms_detector_frame
    ON milestones (case_id, code, (evidence->>'frame'))
    WHERE source = 'detector' AND voided = false;
