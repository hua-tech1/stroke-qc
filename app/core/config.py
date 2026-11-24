# -*- coding: utf-8 -*-
"""配置集中处：所有判定参数只在这里改，避免散落在代码与文档之间。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "demo"
STATIC = ROOT / "app" / "static"

# ---- 判定参数（与 00-总方案 附录 C 一致）----
CONF = 0.5
K_IN = 3                  # 连续 3 帧确认进入
M_OUT = 5                 # 连续 5 帧确认离开
FPS = 15.0
FRAME_MS = 1000.0 / FPS   # 66.7ms
TIMEOUT_MS = 30_000       # 滞留超时阈值（演示序列）
WARN_DEDUP_TTL = 60       # 告警防抖（秒）

DEVICE = "guidewire"
EV_VISIBLE_START = "device_visible_start"
EV_VISIBLE_END = "device_visible_end"

# ---- 演示序列（复用旧项目资产）----
SEQUENCES = {
    "A": {"seq": "10_ST0_SE9", "case_no": "CZ-DEMO-001",
          "label": "病例 001 · 器械进出",
          "hint": "器械入画后离画，事件闭合，不超时"},
    "B": {"seq": "10", "case_no": "CZ-DEMO-002",
          "label": "病例 002 · 全程在场",
          "hint": "器械全程在场未闭合，将触发滞留超时"},
}

# ---- 数据库 ----
PG_DSN = os.getenv(
    "PG_DSN",
    "host=127.0.0.1 port=5432 dbname=strokeqc user=stroke password=stroke_local_pwd")
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "redis_local_pwd")

# ---- 演示时钟（决策 U6）----
TODAY = "2026-10-31"          # 系统"今天"，随访判定与报表期间都以此为准
CURRENT_PERIOD = "2026-10"

# ---- 身份 ----
# 会话密钥统一由 app/core/auth.py 读 SESSION_SECRET；
# 这里不再另设 SECRET_KEY，避免"设了 A 变量却读 B"的部署事故。
