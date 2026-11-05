-- 卒中绿色通道质控系统 · 初始化建表
-- 目标库：PostgreSQL 15+
-- 约定：
--   1. 只作废不删除（milestones / quality_issues）
--   2. 事件与流程节点同表（milestones），靠 source 区分来源
--   3. 指标只从原始表算；派生缓存统一前缀 agg_（本文件不含）
--   4. 演示数据统一 tenant = 'demo'

BEGIN;

-- ============================================================
-- 一、组织与人员
-- ============================================================

CREATE TABLE depts (
    id          text PRIMARY KEY,                 -- 如 n1 / n2 / ir
    name        text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('emergency','neurology','intervention','icu','other')),
    ward        text,                             -- 病区名，用于按病区聚合
    active      boolean NOT NULL DEFAULT true
);

CREATE TABLE users (
    id              text PRIMARY KEY,             -- 登录名：doctor / nurse / qc
    name            text NOT NULL,
    role            text NOT NULL CHECK (role IN ('doctor','nurse','qc','admin','guest')),
    dept_id         text REFERENCES depts(id),
    qualification   text[],                       -- 如 {thrombectomy, thrombolysis}
    password_hash   text,                         -- bcrypt；DEMO_AUTH=off 时为空
    is_demo         boolean NOT NULL DEFAULT true,
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- 设备台账（DSA / CT / MRI）—— 与术中器械使用区分
CREATE TABLE devices (
    id                text PRIMARY KEY,
    kind              text NOT NULL CHECK (kind IN ('dsa','ct','mri')),
    model             text,
    status            text NOT NULL DEFAULT 'available'
                      CHECK (status IN ('available','maintenance','down')),
    last_available_at timestamptz,
    dept_id           text REFERENCES depts(id)
);

-- ============================================================
-- 二、节点字典（R8）
-- ============================================================

CREATE TABLE milestone_defs (
    code          text PRIMARY KEY,               -- arrival / ct_done / device_visible_start ...
    name          text NOT NULL,
    definition    text,
    capture       text NOT NULL CHECK (capture IN ('auto','interface','manual')),
    target_value  numeric,                        -- 目标值，如 60
    target_unit   text,                           -- min
    target_dir    text CHECK (target_dir IN ('le','ge')),
    owner_role    text CHECK (owner_role IN ('doctor','nurse','qc')),
    required      boolean NOT NULL DEFAULT false, -- 缺失即"数据不完整"
    sort_order    int NOT NULL DEFAULT 0
);

-- ============================================================
-- 三、病例与流程节点
-- ============================================================

CREATE TABLE cases (
    id                 bigserial PRIMARY KEY,
    case_no            text NOT NULL,
    tenant             text NOT NULL DEFAULT 'demo',
    period             text NOT NULL,             -- '2026-10'
    dept_id            text REFERENCES depts(id),

    patient_name       text,                      -- 演示数据为脱敏名，如 张**
    sex                text CHECK (sex IN ('M','F')),
    age                int CHECK (age BETWEEN 0 AND 120),
    mrn                text,

    case_type          text NOT NULL CHECK (case_type IN ('ais','ich','sah','cvt','ihs')),
    is_ihs             boolean NOT NULL DEFAULT false,
    is_transfer        boolean NOT NULL DEFAULT false,
    transfer_from      text,

    -- 纳排（R1）
    exclude_reason     text,
    exclude_kind       text CHECK (exclude_kind IN ('non_ais','missing_key','manual')),
    excluded_by        text REFERENCES users(id),
    excluded_at        timestamptz,
    exclude_note       text,

    -- 关键时间点（真实时间）
    arrival_at         timestamptz,
    ct_at              timestamptz,
    needle_at          timestamptz,
    puncture_at        timestamptz,
    reperfusion_at     timestamptz,
    discharge_at       timestamptz,

    -- 临床字段（R2）
    nihss              int CHECK (nihss BETWEEN 0 AND 42),
    aspects            int CHECK (aspects BETWEEN 0 AND 10),
    lvo_site           text,
    toast              text CHECK (toast IN ('LAA','CE','SVO','SOE','SUE')),
    ocsp               text CHECK (ocsp IN ('TACI','PACI','POCI','LACI')),
    mtici              text CHECK (mtici IN ('0','1','2a','2b','2c','3','NR')),
    discharge_type     text CHECK (discharge_type IN ('home','rehab','transfer','death','against_advice')),
    mrs_90             int CHECK (mrs_90 BETWEEN 0 AND 6),
    dysphagia_24h      boolean,
    antiplatelet_48h   boolean,
    af                 boolean,
    anticoag_discharge boolean,

    status             text NOT NULL DEFAULT 'active',
    is_featured        boolean NOT NULL DEFAULT false,   -- 演示重点病例（可点开细看/可回放影像）
    created_at         timestamptz NOT NULL DEFAULT now(),

    UNIQUE (tenant, case_no),
    -- 排除必须能说清是哪一类
    CONSTRAINT cases_exclude_needs_kind
        CHECK (exclude_reason IS NULL OR exclude_kind IS NOT NULL),
    CONSTRAINT cases_manual_exclude_needs_note
        CHECK (exclude_kind <> 'manual' OR exclude_note IS NOT NULL)
);

CREATE INDEX idx_cases_period ON cases (tenant, period, case_type);
CREATE INDEX idx_cases_dept   ON cases (tenant, dept_id, period);
CREATE INDEX idx_cases_mrn    ON cases (tenant, mrn);

-- 流程节点 + 检测事件（同表）
CREATE TABLE milestones (
    id            bigserial PRIMARY KEY,
    case_id       bigint NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    code          text NOT NULL REFERENCES milestone_defs(code),

    -- 两种时间，由 ts_source 决定哪个有效
    occurred_at   timestamptz,                    -- 真实时间（device_clock / wall_clock）
    seq_ts_ms     bigint,                         -- 序列内偏移（sequence_index）

    source        text NOT NULL CHECK (source IN ('detector','interface','manual')),
    ts_source     text NOT NULL CHECK (ts_source IN ('device_clock','wall_clock','sequence_index','simulated')),

    entered_by    text REFERENCES users(id),
    verified_by   text REFERENCES users(id),
    evidence      jsonb,                          -- {frame, conf, k_in, m_out, model_ver}

    voided        boolean NOT NULL DEFAULT false,
    void_reason   text,
    voided_by     text REFERENCES users(id),
    voided_at     timestamptz,

    created_at    timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT ms_time_required
        CHECK (occurred_at IS NOT NULL OR seq_ts_ms IS NOT NULL),
    CONSTRAINT ms_ts_source_match
        CHECK ((ts_source = 'sequence_index' AND seq_ts_ms IS NOT NULL)
            OR (ts_source IN ('device_clock','wall_clock') AND occurred_at IS NOT NULL)
            OR (ts_source = 'simulated')),
    CONSTRAINT ms_void_needs_reason
        CHECK (voided = false OR void_reason IS NOT NULL)
);

CREATE INDEX idx_ms_case   ON milestones (case_id, code) WHERE voided = false;
CREATE INDEX idx_ms_source ON milestones (source, ts_source);

-- 手工/接口节点：同病例同节点只能有一条有效记录
-- 检测事件可重复（器械多次进出），故排除 detector
CREATE UNIQUE INDEX uq_ms_active ON milestones (case_id, code)
    WHERE voided = false AND source <> 'detector';

-- 并发症（R2.4）
CREATE TABLE complications (
    id           bigserial PRIMARY KEY,
    case_id      bigint NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    type         text NOT NULL CHECK (type IN ('sich','recurrence','puncture','contrast_aki','dvt','other')),
    occurred_at  timestamptz,
    severity     text CHECK (severity IN ('mild','moderate','severe','fatal')),
    criterion    text,                            -- sICH 判定标准：sits_most / ecass3 / ninds
    description  text,
    evidence     text,
    reported_by  text REFERENCES users(id),
    reviewed_by  text REFERENCES users(id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    -- sICH 必须声明判定标准，否则同一数字无法比较
    CONSTRAINT comp_sich_needs_criterion
        CHECK (type <> 'sich' OR criterion IS NOT NULL)
);

CREATE INDEX idx_comp_case ON complications (case_id, type);

-- 术中器械使用记录
CREATE TABLE case_devices (
    id           bigserial PRIMARY KEY,
    case_id      bigint NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    device_type  text NOT NULL,                   -- guidewire / catheter / microcatheter / stent
    model        text,
    lot          text,
    used_at      timestamptz
);

-- ============================================================
-- 四、随访（R4 / M4）
-- ============================================================

CREATE TABLE followup_plans (
    id            bigserial PRIMARY KEY,
    case_id       bigint NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    node          text NOT NULL CHECK (node IN ('discharge','m1','m3','m6','m12')),
    due_date      date NOT NULL,
    window_start  date NOT NULL,
    window_end    date NOT NULL,
    status        text NOT NULL DEFAULT 'planned'
                  CHECK (status IN ('planned','scheduled','completed','lost','refused','deceased')),
    completed_at  timestamptz,
    UNIQUE (case_id, node),
    CONSTRAINT fp_window_valid
        CHECK (window_start <= due_date AND due_date <= window_end)
);

CREATE INDEX idx_fp_due ON followup_plans (status, due_date);

CREATE TABLE followup_records (
    id            bigserial PRIMARY KEY,
    plan_id       bigint NOT NULL REFERENCES followup_plans(id) ON DELETE CASCADE,
    mrs           int NOT NULL CHECK (mrs BETWEEN 0 AND 6),
    nihss         int,
    barthel       int CHECK (barthel BETWEEN 0 AND 100),
    recurrence    text CHECK (recurrence IN ('none','ischemic','hemorrhagic')),
    recurrence_at date,
    medication    jsonb,
    risk_factors  jsonb,
    source        text NOT NULL CHECK (source IN ('patient','family','outpatient','phone','other')),
    note          text,
    recorded_by   text REFERENCES users(id),
    recorded_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE followup_attempts (
    id            bigserial PRIMARY KEY,
    plan_id       bigint NOT NULL REFERENCES followup_plans(id) ON DELETE CASCADE,
    attempted_at  timestamptz NOT NULL DEFAULT now(),
    channel       text NOT NULL CHECK (channel IN ('phone','sms','wechat','outpatient','home')),
    result        text NOT NULL CHECK (result IN ('reached','no_answer','wrong_number','refused','callback')),
    note          text,
    by_user       text REFERENCES users(id)
);

CREATE INDEX idx_fa_plan ON followup_attempts (plan_id, attempted_at);

-- ============================================================
-- 五、质控指标（R4）
-- ============================================================

CREATE TABLE indicator_defs (
    code            text NOT NULL,
    version         int NOT NULL DEFAULT 1,
    name            text NOT NULL,
    layer           text NOT NULL CHECK (layer IN ('structure','process','outcome')),
    num_desc        text NOT NULL,
    den_desc        text NOT NULL,
    inclusion       text,
    exclusion       text,
    source_fields   text[],
    target_value    numeric,
    target_dir      text CHECK (target_dir IN ('le','ge')),
    period          text NOT NULL DEFAULT 'month',
    scope           text NOT NULL DEFAULT 'national' CHECK (scope IN ('national','local')),
    min_denominator int NOT NULL DEFAULT 10,      -- 分母低于此值只报例数不报率
    effective_from  date NOT NULL DEFAULT current_date,
    note            text,                          -- 口径补充说明（如 sICH 判定标准）
    PRIMARY KEY (code, version)
);

CREATE TABLE indicator_values (
    id           bigserial PRIMARY KEY,
    period       text NOT NULL,
    dept_id      text NOT NULL DEFAULT 'ALL',     -- ALL = 全院；避免 NULL 破坏唯一约束
    code         text NOT NULL,
    version      int NOT NULL,
    numerator    int,
    denominator  int,
    value        numeric,
    computable   boolean NOT NULL DEFAULT true,
    na_reason    text,
    frozen       boolean NOT NULL DEFAULT false,
    computed_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (period, dept_id, code, version),
    FOREIGN KEY (code, version) REFERENCES indicator_defs(code, version),
    CONSTRAINT iv_rate_needs_denominator
        CHECK (computable = false OR (denominator IS NOT NULL AND denominator > 0)),
    CONSTRAINT iv_na_needs_reason
        CHECK (computable = true OR na_reason IS NOT NULL)
);

CREATE INDEX idx_iv_lookup ON indicator_values (period, code);

-- ============================================================
-- 六、整改闭环（R5）
-- ============================================================

CREATE TABLE qc_findings (
    id              bigserial PRIMARY KEY,
    period          text NOT NULL,
    indicator_code  text,
    case_id         bigint REFERENCES cases(id) ON DELETE SET NULL,
    level           text NOT NULL CHECK (level IN ('case','systemic')),
    source          text NOT NULL CHECK (source IN ('indicator','case','manual')),
    severity        text NOT NULL DEFAULT 'medium' CHECK (severity IN ('high','medium','low')),
    title           text NOT NULL,
    description     text,
    owner_id        text REFERENCES users(id),
    due_date        date,
    status          text NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open','assigned','fixing','verifying','closed','rejected')),
    return_count    int NOT NULL DEFAULT 0,
    metrics_at_open jsonb,                        -- {code: {n, d, v}}
    metrics_at_close jsonb,
    verify_note     text,
    closed_at       timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),

    -- 落到具体人，不允许只填科室
    CONSTRAINT qf_owner_required
        CHECK (status = 'open' OR owner_id IS NOT NULL),
    -- 关闭必须带当期指标值，否则不算闭环
    CONSTRAINT qf_closed_needs_metrics
        CHECK (status <> 'closed' OR metrics_at_close IS NOT NULL)
);

CREATE INDEX idx_qf_status ON qc_findings (period, status);
CREATE INDEX idx_qf_owner  ON qc_findings (owner_id, status);

CREATE TABLE qc_actions (
    id           bigserial PRIMARY KEY,
    finding_id   bigint NOT NULL REFERENCES qc_findings(id) ON DELETE CASCADE,
    action       text NOT NULL,
    owner_id     text REFERENCES users(id),
    due_date     date,
    result       text,
    evidence_url text,
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- 七、数据质量（R3 / R9）
-- ============================================================

CREATE TABLE quality_issues (
    id           bigserial PRIMARY KEY,
    case_id      bigint NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    rule_code    text NOT NULL,
    rule_type    text NOT NULL CHECK (rule_type IN ('completeness','logic','outlier','consistency','timeliness')),
    severity     text NOT NULL CHECK (severity IN ('high','medium','low')),
    field        text,
    detail       text,
    status       text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open','verifying','confirmed','dismissed','unverifiable')),
    verified_by  text REFERENCES users(id),
    verified_at  timestamptz,
    verify_note  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT qi_verify_needs_user
        CHECK (status IN ('open','verifying') OR verified_by IS NOT NULL)
);

CREATE INDEX idx_qi_case ON quality_issues (case_id, status);
CREATE INDEX idx_qi_sev  ON quality_issues (severity, status);

-- ============================================================
-- 八、审计
-- ============================================================

CREATE TABLE audit_logs (
    id         bigserial PRIMARY KEY,
    entity     text NOT NULL,                     -- case / milestone / finding / auth / sim
    entity_id  text,
    action     text NOT NULL,
    actor      text,
    detail     jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_entity ON audit_logs (entity, entity_id);
CREATE INDEX idx_audit_time   ON audit_logs (created_at DESC);

-- ============================================================
-- 九、纳排视图（所有指标只认这个视图）
-- ============================================================

CREATE VIEW v_qc_eligible AS
SELECT *
FROM cases
WHERE tenant = 'demo'
  AND case_type = 'ais'
  AND is_ihs = false
  AND exclude_reason IS NULL;

COMMENT ON VIEW v_qc_eligible IS
'缺血性卒中质控分母。查询时按 period 过滤：WHERE period = $1。
 院内卒中(is_ihs)、非缺血(case_type<>ais)、已排除(exclude_reason) 均不进入。';

COMMIT;
