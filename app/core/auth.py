# -*- coding: utf-8 -*-
"""会话与口令（R7，S9 补做）

只用标准库，不引 bcrypt / passlib / itsdangerous：
  · 口令哈希用 hashlib.scrypt（内存硬，比 PBKDF2 更抗 GPU 爆破）
  · 会话用 HMAC-SHA256 签名的 Cookie（无服务端会话表，适合单实例演示）

存库格式：
  scrypt$16384$8$1$<salt_hex>$<hash_hex>

Cookie 格式：
  base64url(payload_json) + "." + base64url(hmac_sha256(secret, payload_b64))
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

COOKIE = "qc_sess"
TTL = 8 * 3600                     # 8 小时
_N, _R, _P = 16384, 8, 1

# 演示用默认密钥；正式部署必须用环境变量覆盖
SECRET = os.getenv("SESSION_SECRET", "stroke-qc-demo-secret-change-me").encode()

# 角色 -> 登录后落地页
HOME = {"doctor": "/monitor", "nurse": "/followups", "qc": "/qc", "guest": "/qc"}

# 页面 / 接口读权限
READ_PAGES = {
    "/monitor":   {"doctor", "guest"},
    "/cases":     {"doctor", "nurse", "qc", "guest"},
    "/followups": {"nurse", "guest"},
    "/qc":        {"qc", "guest"},
}
# 写权限（按动作归类）
WRITE_PERM = {
    "followup": {"nurse"},             # 随访录入 / 联系 / 标记，由护士执行
    "qc":       {"qc"},                # 整改流转，由质控科执行
}


# ---------------- 口令 ----------------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, n, r, p, salt_hex, hash_hex = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(hash_hex)))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------- 会话 ----------------
def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: str, name: str, role: str) -> str:
    payload = {"u": user_id, "n": name, "r": role, "exp": int(time.time()) + TTL}
    body = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def parse_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    want = _b64e(hmac.new(SECRET, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, want):
        return None
    try:
        p = json.loads(_b64d(body))
    except Exception:
        return None
    if p.get("exp", 0) < time.time():
        return None
    return p


# ---------------- 权限 ----------------
def can_page(role: str, path: str) -> bool:
    """按前缀匹配页面权限；未列入的路径默认放行（如 /about /static）。"""
    for prefix, roles in READ_PAGES.items():
        if path == prefix or path.startswith(prefix + "/"):
            return role in roles
    return True


def can_write(role: str, kind: str) -> bool:
    return role in WRITE_PERM.get(kind, set())
