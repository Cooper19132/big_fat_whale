#!/usr/bin/env python3
"""验证 NapCat 能不能把 mp3 当 QQ 语音发出去（发到主人私聊）。"""
import base64
import json
import urllib.request

MP3 = "/tmp/tts-test.mp3"
TARGET = 246695065
API = "http://127.0.0.1:3000/send_private_msg"

raw = open(MP3, "rb").read()
b64 = base64.b64encode(raw).decode()
print(f"音频 {len(raw)} 字节 → base64 {len(b64)} 字符")

payload = {
    "user_id": TARGET,
    "message": [{"type": "record", "data": {"file": "base64://" + b64}}],
}
req = urllib.request.Request(
    API,
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode("utf-8", "ignore")
    print("HTTP", r.status)
    print("返回:", body[:500])
except Exception as e:
    print("请求失败:", e)
    try:
        print("错误体:", e.read().decode("utf-8", "ignore")[:500])
    except Exception:
        pass
