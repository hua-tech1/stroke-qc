# 卒中绿色通道 · 介入流程质控台

> 把手术台上**没被记录的那一段**，变成可审计的时间。

现有卒中中心系统的时间节点止步于「穿刺」。穿刺之后——导丝何时到位、何时撤出、中间有没有无效操作——靠护士回忆补录。
本系统用视觉检测把这几十秒的器械动作转成**离散事件与时间戳**，再驱动超时预警、随访任务与质控整改闭环。

**当前状态**：本地可完整运行。数据为仿真队列（600 例 / 12 个月 / 3 病区），非真实患者数据。

---

## 它解决什么

| 失控点 | 现状 | 本系统 |
| :--- | :--- | :--- |
| 术中器械时刻 | 靠口述、事后回忆补录 | 逐帧检测 → 滞回状态机 → 可追溯时间戳 |
| 术后随访 | 人工台账，凭记忆打电话 | 计划驱动 + 到期提醒 + 失访需三次联系 |
| 质控上报 | 月末收表手工汇总 | 过程留痕 + 22 项指标自动计算 + 整改闭环 |

**边界**：只产质控数据，**不做诊断**；采集接口只做抽象层，**未对接真实 DSA**。

---

## 快速开始

```bash
# 1. 起数据库与缓存
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d

# 2. 建表 → 字典 → 仿真队列 → 整改台账 → 账号口令（顺序不能换）
for f in 001_init 002_defs 003_seed_demo 004_findings 005_auth; do
  docker exec -i stroke_pg psql -U stroke -d strokeqc -v ON_ERROR_STOP=1 < "migrations/$f.sql"
done

# 3. 启动
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8080
```

打开 <http://127.0.0.1:8080/login>。

> 演示影像（`data/demo/frames/`）**不在仓库内**——见下方「数据与许可」。
> 缺失时影像区为空，其余页面（病例、随访、报表、整改）不受影响。
>
> 重新生成队列：`python scripts/seed.py --seed 42 && python scripts/emit_sql.py`，
> 再执行 `003_seed_demo.sql`。同种子输出完全一致。

### 演示账号

| 账号 | 角色 | 落地页 |
| :--- | :--- | :--- |
| `doctor` | 医生 | 术中监控 · 病例列表 |
| `nurse` | 护士 | 随访工作台 · 病例列表 |
| `qc` | 质控科 | 质控报表 · 整改台账 |
| `guest` | 访客 | 全部只读 |

统一口令 `Demo@2026`（登录页可展开「演示账号」查看）。

**这两个值只用于演示环境。** 数据全部虚构；正式部署请删除登录页的提示面板，并设置 `SESSION_SECRET`。

---

## 页面

| 路径 | 内容 | 权限 |
| :--- | :--- | :--- |
| `/login` | 账号密码登录 | 公开 |
| `/monitor` | DSA 播放 + 检测框 + 事件流 + 滞留计时 | doctor / guest |
| `/cases` | 病例密集表格 + 详情抽屉 | 全部角色 |
| `/followups` | 随访四段分组 + 录入 + 联系记录 | nurse / guest |
| `/qc` | 22 项指标三层 + 分母减法 + 下钻 + 整改台账 | qc / guest |
| `/about` | 参数来源、许可、能力边界 | 公开 |

越权返回 403 页面，未登录 302 到登录页。权限在后端中间件强制，不只是隐藏菜单。

---

## 三个关键设计

**1. 事件口径是「入画 / 离画」，不称「到位」**

「到位」是位置概念（头端到靶血管），「入画」是存在概念。混用会被一句"导丝一进画面就算到位？"问倒。
事件名、界面文案、数据库字典三处统一。

**2. 关闭整改必须带当期指标值，且由系统计算**

整改台账最容易变成"自己打个分说自己改好了"。关闭时后端现场跑指标引擎取当期值写入 `metrics_at_close`，数据库还有 `CHECK` 兜底。

**3. 分母必须能展开**

`600 − 非缺血 150 − 院内卒中 25 − 关键节点缺失 16 = 409`。
每一层可点开看口径，任一指标可下钻到具体病例——下钻用的 ID 集合与算出该数字的那一套同源，不是另写一条查询"大概对上"。

---

## 结构

```
app/
├── core/          config · db · auth（scrypt 口令 + HMAC 签名会话）· data_notes
├── modules/
│   ├── events/    FrameSource 抽象（File 实现 / DICOM 与 LiveStream 桩）· 滞回状态机
│   └── followup/  随访状态判定（逾期 / 失访 / 可完成）
├── qc/            indicators（22 项）· report（分层 + 分母减法 + 下钻）· findings（整改六态）
└── static/        原生 HTML/CSS/JS，无前端构建、无 CDN 依赖（断网可演示）
migrations/        001 建表 · 002 字典 · 003 队列 · 004 整改 · 005 账号
scripts/           seed（参数化生成）· emit_sql · check_metrics · e2e_check
```

技术栈：FastAPI + PostgreSQL 16 + Redis 7，无 ORM、无前端框架。

---

## 数据与许可

- **队列是仿真的**。600 例由 `scripts/seed.py` 按参数化模型生成，种子固定可复现；每个参数标注来源（公开数据集 / 指南 / 文献 / 工程假设），见 `/about`。
- **演示影像不在仓库内**。两段 DSA 序列来自公开数据集 `pikopico/X-ray_fluoroscopy_guidewire`，其 HuggingFace `license` 字段为 **null**（即未授予任何许可）。因此只提交逐帧检测坐标（`data/demo/json/`），不提交影像本身。
- 合成队列的人群参数参考 `Nnaodeh/Stroke_Prediction_Dataset`（CC0-1.0）。

## 已知限制

- 未对接真实 DSA：`DicomSeriesSource` / `LiveStreamSource` 是桩，调用即抛 `NotImplemented`。
- 未做前瞻验证：无真实科室使用数据，不能证明临床有效性。
- 单一中心、两段序列：不能证明泛化性。
- 检测框显示做了指数平滑（可在界面关闭），**事件时间戳始终用原始检测**。

## 许可

代码 MIT。若引入 Ultralytics YOLOv8 权重/训练代码，须同时遵守其 AGPL-3.0。
