-- 字典种子：14 个流程节点 + 22 项质控指标
-- 依据：R8 节点字典、R4 指标定义卡
-- 说明：national = 国家/行业口径（只读）；local = 本项目自建口径（可讨论）

BEGIN;

-- ============================================================
-- 一、流程节点字典（14 个）
-- ============================================================

INSERT INTO milestone_defs (code, name, definition, capture, target_value, target_unit, target_dir, owner_role, required, sort_order) VALUES
('arrival',              '到院',       '患者到达急诊分诊台并完成登记的时间',                 'interface', NULL, NULL, NULL, 'nurse',  true,  10),
('triage',               '分诊完成',   '完成卒中识别并启动绿色通道',                         'manual',    NULL, NULL, NULL, 'nurse',  false, 20),
('team_call',            '小组呼叫',   '发出卒中小组呼叫的时间',                             'manual',    NULL, NULL, NULL, 'nurse',  false, 30),
('team_arrive',          '团队到位',   '卒中小组关键成员到达急诊/导管室',                    'manual',    10,   'min','le', 'doctor', false, 40),
('ct_start',             'CT 开始',    '进入 CT 室开始扫描',                                 'interface', NULL, NULL, NULL, 'nurse',  false, 50),
('ct_done',              'CT 完成',    '头颅 CT 扫描结束、图像可判读',                       'interface', 25,   'min','le', 'doctor', true,  60),
('lab_result',           '化验回报',   '凝血、血常规等溶栓前必需化验回报',                   'interface', NULL, NULL, NULL, 'nurse',  false, 70),
('consent',              '知情同意',   '签署静脉溶栓/血管内治疗知情同意书',                  'manual',    NULL, NULL, NULL, 'doctor', false, 80),
('needle',               '溶栓给药',   '静脉溶栓药物开始推注（DNT 终点）',                   'manual',    60,   'min','le', 'nurse',  false, 90),
('puncture',             '穿刺开始',   '股动脉/桡动脉穿刺成功（DPT 终点）',                  'interface', 90,   'min','le', 'doctor', false, 100),
('device_visible_start', '器械入画',   '介入器械首次在 DSA 画面中稳定出现（自动检测）',      'auto',      NULL, NULL, NULL, 'doctor', false, 110),
('device_visible_end',   '器械离画',   '介入器械最后一次出现在画面后离开（自动检测）',      'auto',      NULL, NULL, NULL, 'doctor', false, 120),
('reperfusion',          '再通',       '造影确认血管再通（记录 mTICI 分级）',                'manual',    NULL, NULL, NULL, 'doctor', false, 130),
('discharge',            '出院',       '办理出院或转院',                                     'interface', NULL, NULL, NULL, 'nurse',  true,  140);

-- ============================================================
-- 二、质控指标定义卡（22 项）
-- ============================================================

-- 结构指标（4）
INSERT INTO indicator_defs (code, version, name, layer, num_desc, den_desc, inclusion, exclusion, source_fields, target_value, target_dir, period, scope, min_denominator) VALUES
('ST01',1,'DSA 设备可用率','structure','状态为 available 的 DSA 台数','DSA 总台数','全院在册 DSA','报废设备不计',ARRAY['devices.kind','devices.status'],100,'ge','month','local',1),
('ST02',1,'取栓资质医师占比','structure','具备取栓资质的医师数','介入医师总数','在职介入医师','进修/外聘不计',ARRAY['users.qualification','users.dept_id'],60,'ge','quarter','local',1),
('ST03',1,'卒中小组 7×24 覆盖率','structure','已排班小时数','应有小时数(168)','卒中小组值班表','—',ARRAY['duty_roster'],100,'ge','month','national',1),
('ST04',1,'溶栓药物常备率','structure','药品在库天数','统计天数','药房台账','—',ARRAY['pharmacy_ledger'],100,'ge','month','national',1);

-- 过程指标（12）
INSERT INTO indicator_defs (code, version, name, layer, num_desc, den_desc, inclusion, exclusion, source_fields, target_value, target_dir, period, scope, min_denominator) VALUES
('PR01',1,'到院至 CT 完成时间（中位数）','process','—（取中位数）','有 arrival 与 ct_done 的病例','缺血性卒中','关键节点缺失者剔除',ARRAY['cases.arrival_at','milestones.ct_done'],25,'le','month','national',10),
('PR02',1,'DNT 中位数','process','—（取中位数）','接受静脉溶栓的病例','ais 且 needle 非空','—',ARRAY['cases.arrival_at','milestones.needle'],45,'le','month','national',10),
('PR03',1,'DNT ≤60min 达标率','process','DNT ≤60 的例数','接受静脉溶栓的病例','ais 且 needle 非空','—',ARRAY['cases.arrival_at','milestones.needle'],70,'ge','month','national',10),
('PR04',1,'DPT 中位数','process','—（取中位数）','接受血管内治疗的病例','ais 且 puncture 非空','—',ARRAY['cases.arrival_at','milestones.puncture'],60,'le','month','national',10),
('PR05',1,'DPT ≤90min 达标率','process','DPT ≤90 的例数','接受血管内治疗的病例','ais 且 puncture 非空','—',ARRAY['cases.arrival_at','milestones.puncture'],70,'ge','month','national',10),
('PR06',1,'静脉溶栓率','process','接受溶栓的例数','缺血性卒中例数','v_qc_eligible','—',ARRAY['milestones.needle'],30,'ge','month','national',10),
('PR07',1,'血管内治疗率','process','接受取栓的例数','缺血性卒中例数','v_qc_eligible','—',ARRAY['milestones.puncture'],10,'ge','month','national',10),
('PR08',1,'器械可见时长（中位数）','process','—（入画至离画的中位时长）','有 device_visible_start 与 end 的病例','ais 且事件闭合','—',ARRAY['milestones.device_visible_start','milestones.device_visible_end'],NULL,NULL,'month','local',5),
('PR09',1,'术中滞留超时率','process','判定滞留超时的例数','有 device_visible_start 的病例','ais 且有检测事件','—',ARRAY['milestones.device_visible_start','milestones.device_visible_end'],15,'le','month','local',5),
('PR10',1,'24h 内吞咽功能评估率','process','dysphagia_24h = true 的例数','缺血性卒中例数','v_qc_eligible','24h 内死亡或转出者剔除',ARRAY['cases.dysphagia_24h'],90,'ge','month','national',10),
('PR11',1,'48h 内抗血小板治疗率','process','antiplatelet_48h = true 的例数','未溶栓的缺血性卒中例数','v_qc_eligible 且无 needle','溶栓病例不计入',ARRAY['cases.antiplatelet_48h'],85,'ge','month','national',10),
('PR12',1,'房颤患者出院抗凝率','process','anticoag_discharge = true 的例数','af = true 的出院病例','v_qc_eligible 且 af','死亡/转院剔除',ARRAY['cases.af','cases.anticoag_discharge'],60,'ge','month','national',10);

-- 结果指标（6）
INSERT INTO indicator_defs (code, version, name, layer, num_desc, den_desc, inclusion, exclusion, source_fields, target_value, target_dir, period, scope, min_denominator) VALUES
('OU01',1,'mTICI 2b–3 再通率','outcome','mTICI 2b/2c/3 的例数','完成血管内治疗的例数','有 mtici 且非 NR','未评估(NR)不计入分母',ARRAY['cases.mtici'],80,'ge','month','national',5),
('OU02',1,'症状性颅内出血率','outcome','sICH 例数','接受再灌注治疗的例数','溶栓或取栓','—',ARRAY['complications.type'],7,'le','month','national',5),
('OU03',1,'院内死亡率','outcome','discharge_type = death 的例数','缺血性卒中例数','v_qc_eligible','—',ARRAY['cases.discharge_type'],5,'le','month','national',10),
('OU04',1,'mRS 0–2 比例（90 天）','outcome','mrs_90 ≤2 的例数','有 90 天 mRS 且存活的例数','v_qc_eligible','死亡与失访剔除',ARRAY['cases.mrs_90'],50,'ge','month','national',10),
('OU05',1,'随访率','outcome','状态为 completed 的节点数','应随访节点数','存活出院病例的全部节点','死亡病例节点自动关闭',ARRAY['followup_plans.status'],80,'ge','month','national',10),
('OU06',1,'失访率','outcome','状态为 lost 的节点数','应随访节点数','存活出院病例的全部节点','—',ARRAY['followup_plans.status'],15,'le','month','national',10);

-- 结果指标口径补充（U1 决策）
UPDATE indicator_defs SET note = '按 SITS-MOST 定义：24–36h 复查影像见出血且 NIHSS 较基线加重 ≥4 分'
WHERE code = 'OU02' AND version = 1;

-- 自建指标标注（U10 决策）：不参与国家上报
UPDATE indicator_defs SET note = '本项目自建过程指标，仅用于验证术中采集能力，不参与国家上报'
WHERE code IN ('PR08','PR09') AND version = 1;

-- ============================================================
-- 三、组织与账号（演示用，口令由 seed.py 以 bcrypt 写入）
-- ============================================================

INSERT INTO depts (id, name, kind, ward) VALUES
('n1', '神经内科一区', 'neurology',    '神内一区'),
('n2', '神经内科二区', 'neurology',    '神内二区'),
('ir', '介入病区',     'intervention', '介入病区');

INSERT INTO users (id, name, role, dept_id, qualification, is_demo) VALUES
('doctor', '演示医生', 'doctor', 'ir', ARRAY['thrombolysis','thrombectomy'], true),
('nurse',  '演示护士', 'nurse',  'n1', ARRAY[]::text[],                     true),
('qc',     '演示质控', 'qc',     NULL, ARRAY[]::text[],                     true),
('guest',  '游客',     'guest',  NULL, ARRAY[]::text[],                     true);

INSERT INTO devices (id, kind, model, status, dept_id) VALUES
('dsa-01', 'dsa', '演示 DSA 机', 'available', 'ir'),
('ct-01',  'ct',  '演示 CT',     'available', 'n1');

COMMIT;
