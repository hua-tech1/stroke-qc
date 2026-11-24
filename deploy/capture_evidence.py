# -*- coding: utf-8 -*-
"""在 ECS 上采集「部署证据」——把"我们说上云了"变成"可核验的留痕"。

只读、无第三方依赖、不改任何数据。运行后：
  1) 终端打印一份可截图的清单
  2) 生成 evidence.json（含时间戳，可附在材料里）

用法（在 ECS 上、仓库根目录）：
  python3 deploy/capture_evidence.py
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence.json")


def run(cmd: list[str], timeout: int = 8) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return f"<未取到: {type(e).__name__}>"


def http(url: str, timeout: int = 5) -> str:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return f"HTTP {r.status} / {len(r.read())} bytes"
    except Exception as e:  # noqa: BLE001
        return f"<失败 {type(e).__name__}: {e}>"


def main() -> None:
    ev = {
        "captured_at": datetime.now(CST).isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
        "public_ip": run(["bash", "-lc", "curl -s --max-time 5 ifconfig.me || true"]),
        "os": platform.platform(),
        "kernel": platform.release(),
        "cpu_cores": os.cpu_count(),
        "mem_total": run(["bash", "-lc", "free -h | awk '/Mem:/{print $2}'"]),
        "disk": run(["bash", "-lc", "df -h / | tail -1 | awk '{print $2\" total, \"$4\" avail\"}'"]),
        "docker": run(["docker", "--version"]),
        "compose": run(["bash", "-lc", "docker compose version || docker-compose --version"]),
        "containers": run(["bash", "-lc",
                           "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'"]),
        "health": http("http://127.0.0.1:8080/health"),
        "login_page": http("http://127.0.0.1:8080/login"),
        "pg_version": run(["bash", "-lc",
                           "docker exec stroke_app python -c \"import os,psycopg2;"
                           "d=os.getenv('PG_DSN');c=psycopg2.connect(d);cur=c.cursor();"
                           "cur.execute('select version()');print(cur.fetchone()[0][:60])\" 2>/dev/null"]),
        "redis_ping": run(["bash", "-lc",
                           "docker exec stroke_app python -c \"import os,redis;"
                           "r=redis.Redis(host=os.getenv('REDIS_HOST'),port=int(os.getenv('REDIS_PORT')),"
                           "password=os.getenv('REDIS_PASSWORD'));print(r.ping())\" 2>/dev/null"]),
    }

    # 数据库行数（证明数据真的在云上，不是本地）
    ev["row_counts"] = run(["bash", "-lc",
                            "docker exec stroke_app python -c \""
                            "import os,psycopg2;c=psycopg2.connect(os.getenv('PG_DSN'));cur=c.cursor();"
                            "cur.execute(\\\"select 'cases',count(*) from cases union all "
                            "select 'milestones',count(*) from milestones union all "
                            "select 'followup_plans',count(*) from followup_plans union all "
                            "select 'audit_logs',count(*) from audit_logs\\\");"
                            "[print(a,b) for a,b in cur.fetchall()]\" 2>/dev/null"])

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)

    print("=" * 66)
    print("部署证据清单（逐项截图，覆盖 5 张 + 终端 1 张）")
    print("=" * 66)
    for k, v in ev.items():
        print(f"{k:14s}: {v}")
    print("=" * 66)
    print(f"已写出 {OUT}")
    print("\n还需要你手动补的 3 张截图（本脚本取不到）：")
    print("  1. 华为云控制台 ECS 详情页（含实例 ID / 地域 / 创建时间）")
    print("  2. 华为云控制台 RDS 与 DCS 实例列表（同上）")
    print("  3. 浏览器地址栏 + 质控报表页（证明公网可访问）")
    print("  4. 计费中心 / 费用账单（金额可打码，保留日期与资源名）")


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        print("请在 ECS(Ubuntu) 上运行；Windows 下 docker exec 的引号行为不同。")
    main()
