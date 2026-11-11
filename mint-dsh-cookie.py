#!/usr/bin/env python3
"""本地验证：按 qq-bridge 的算法铸造 DSH 会话 Cookie，打 DSH API 看是否放行。"""
import base64
import hashlib
import hmac
import json
import re
import sys
import time
import urllib.request

CRED = r"C:\Users\cooper\.dsh\.credentials.yaml"
BASE = "http://127.0.0.1:4598"
AUTHORITY = "127.0.0.1:4598"


def b64url(raw: bytes) -> str:
    return base64.b64encode(raw).decode().replace("+", "-").replace("/", "_").rstrip("=")


def read_secret() -> bytes:
    text = open(CRED, encoding="utf-8").read()
    m = re.search(r"client-connection/browser-session:.*?secret:\s*(\S+)", text, re.S)
    if not m:
        raise SystemExit("找不到 secret")
    s = m.group(1).strip()
    pad = "=" * (-len(s) % 4)
    raw = base64.urlsafe_b64decode(s + pad)
    print("secret 解码后字节数:", len(raw), "(需要 32)")
    if len(raw) != 32:
        raise SystemExit("密钥长度不对")
    return raw


def mint(secret: bytes, authority: str, lifetime_ms: int) -> str:
    issued = int(time.time() * 1000)
    body = b64url(json.dumps({
        "version": 1, "authority": authority,
        "issuedAt": issued, "expiresAt": issued + lifetime_ms,
    }, separators=(",", ":")).encode())
    sig = b64url(hmac.new(secret, body.encode(), hashlib.sha256).digest())
    name = "dsh-auth-" + b64url(hashlib.sha256(authority.encode()).digest())
    return f"{name}=v1.{body}.{sig}"


secret = read_secret()
cookie = mint(secret, AUTHORITY, 60 * 60 * 1000)
print("cookie 名:", cookie.split("=")[0])
print("cookie 长度:", len(cookie))

for path in ("/", "/api/status"):
    req = urllib.request.Request(BASE + path, headers={"Cookie": cookie})
    if path != "/":
        req = urllib.request.Request(
            BASE + path, method="POST", data=b'{"type":"client-request","rpcId":"p1","method":"status","payload":{}}',
            headers={"Cookie": cookie, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read(200).decode("utf-8", "ignore")
            print(f"{path} -> HTTP {r.status}  {body[:80]!r}")
    except Exception as e:
        code = getattr(getattr(e, "code", None), "__int__", lambda: None)()
        print(f"{path} -> 失败 {e}")
