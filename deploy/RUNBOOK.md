# 华为云部署 Runbook（网评取证专用）

> 目标不是「长期在线」，而是**用最低成本留下可核验的部署痕迹**。
> 按需计费 → 跑通 → 截图 → 释放。**总耗时半天，总费用量级：数十元（以官网价格页为准）。**

---

## 0. 产出物（这才是本次的真正交付）

跑完后你手上应该有这 **8 项**，缺任何一项都不要在材料里写「已部署」：

| # | 证据 | 形态 | 对应门槛 |
|---|---|---|---|
| 1 | ECS 实例详情（含实例 ID / 地域 / 创建时间） | 控制台截图 | 云端部署 |
| 2 | RDS for PostgreSQL 实例详情 | 控制台截图 | RDS |
| 3 | DCS for Redis 实例详情 | 控制台截图 | Redis |
| 4 | 公网地址 + 登录页 | 浏览器截图（地址栏可见） | 现场可访问 |
| 5 | 质控报表页（22 项指标） | 浏览器截图 | 真系统 |
| 6 | `capture_evidence.py` 输出（含 PG 版本、Redis ping、四张表行数） | 终端截图 + `evidence.json` | 数据真在云上 |
| 7 | 费用账单 / 计费明细（金额可打码，保留资源名与日期） | 截图 | 真实开通 |
| 8 | 30 秒录屏：打开公网地址 → 登录 → 进报表 → 看到指标 | mp4 | 演示 |

---

## 1. 开通顺序（同一 VPC，私网互通）

在**华北-北京四**（或你账号默认地域）按此顺序：

### 1.1 网络
- VPC：用默认 VPC 即可（记下网段，如 192.168.0.0/16）
- 安全组 `sg-stroke`：
  - 入方向：TCP 22（你的公网 IP/32）、TCP 80（0.0.0.0/0）
  - 出方向：默认全放通

### 1.2 数据库 RDS for PostgreSQL 16
- 规格：单机 · 2 核 4GB · 存储 40GB（最小可用即可）
- 网络：与 ECS 同 VPC、同子网
- 数据库名 `strokeqc`，用户 `stroke`，密码自定义（记下来）
- 安全组：放行 **5432**，源 = `sg-stroke`（只允许 ECS 访问）

### 1.3 缓存 DCS for Redis 6.0 / 7.0
- 规格：单机 · 1GB
- 同 VPC；**设置访问密码**（记下来）
- 安全组放行 **6379**，源 = `sg-stroke`

### 1.4 计算 ECS
- 规格：`s6.large.2`（2 核 4GB）· Ubuntu 22.04 · 系统盘 40GB
- 弹性公网 IP：按带宽 5 Mbit/s，或按流量
- 安全组：`sg-stroke`

---

## 2. 在 ECS 上把系统跑起来

```bash
# 2.1 基础环境
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER && newgrp docker

# 2.2 取代码（三选一）
git clone <你的仓库地址> stroke-qc && cd stroke-qc
# 或在本地打包上传：
#   tar czf stroke-qc.tar.gz --exclude=.git --exclude=node_modules .
#   scp stroke-qc.tar.gz ubuntu@<EIP>:/home/ubuntu/

# 2.3 填环境变量
cp deploy/.env.cloud.example deploy/.env.cloud
vim deploy/.env.cloud     # 填 RDS/DCS 私网地址与密码 + SESSION_SECRET
# 生成密钥：python3 -c "import secrets;print(secrets.token_urlsafe(48))"

# 2.4 初始化数据库（顺序不能换）
pip3 install --quiet psycopg2-binary
export $(grep -v '^#' deploy/.env.cloud | xargs)
for f in 001_init 002_defs 003_seed_demo 004_findings 005_auth 006_detector_sink; do
  echo "== $f =="
  psql "$PG_DSN" -v ON_ERROR_STOP=1 -f "migrations/$f.sql" >/dev/null && echo ok
done
# psql 没装的话：sudo apt install -y postgresql-client

# 2.5 起服务
docker compose -f deploy/docker-compose.cloud.yml --env-file deploy/.env.cloud up -d --build
docker compose -f deploy/docker-compose.cloud.yml ps
curl -s http://127.0.0.1:8080/health
```

浏览器打开 `http://<EIP>/login` → `qc / Demo@2026` → 质控报表。

---

## 3. 取证

```bash
python3 deploy/capture_evidence.py     # 打印清单 + 写 evidence.json
```

然后手动补 4 张控制台截图（见 §0 的 1/2/3/7）。
录屏 30 秒：刷新公网地址 → 登录 → 报表 → 点开一个指标下钻。

> 截图注意：**不要露出密码、AK/SK、完整私网地址**；账单金额可涂掉，但保留资源名与日期。

---

## 4. 常见坑（大概率会遇到一个）

| 现象 | 原因 | 处理 |
|---|---|---|
| `psql: could not connect` | 安全组没放行 / 不在同 VPC | 检查 RDS 安全组源是否为 `sg-stroke` |
| `Redis 连接超时` | DCS 未设密码或密码错 | 用 `redis-cli -h <ip> -a <pwd> ping` 验证 |
| `502 / 页面打不开` | 容器没起或端口未映射 | `docker logs stroke_app --tail 50` |
| `003_seed_demo.sql` 报错 | 前面迁移没跑完 | 严格按 001→006 顺序，`ON_ERROR_STOP=1` 会中断 |
| 登录后 302 循环 | `SESSION_SECRET` 为空 | 必须设置且长度足够 |

---

## 5. 跑完立刻释放

```bash
docker compose -f deploy/docker-compose.cloud.yml down -v
```
然后在控制台**退订/删除** ECS、RDS、DCS、EIP，保留账单截图。

---

## 6. 材料里该怎么写（照抄改数字即可）

> **已实现**：本地 Docker 全链路跑通（PostgreSQL 16 + Redis 7 + FastAPI）；
> **已按需上云验证**：华为云 ECS（s6.large.2）+ RDS for PostgreSQL + DCS for Redis，
> 同一 VPC 私网互通，公网仅开放 80，验证后释放（截图与计费记录见附录 B）。
> **暂未实现**：持续在线部署、昇腾 Atlas 上机。

这样写的好处：每一句都能被核，且不承诺你做不到的事。**评委最反感的是「已部署」三个字后面查不到东西。**
