#!/usr/bin/env python3
"""测试：把 blue-fish-archive 的 webp 表情发到主人私聊，验证 QQ 能否正常显示。"""
import json
import urllib.request

TARGET = 246695065
URL = "https://cdn.jsdelivr.net/gh/EDMOK/blue-fish-archive@main/large/00dc341c60ffdff4d04e515fe9644a02.webp"

payload = {
    "user_id": TARGET,
    "message": [
        {"type": "text", "data": {"text": "【测试】这是一张 webp 格式的大肥鱼表情，看看能不能正常显示："}},
        {"type": "image", "data": {"file": URL}},
    ],
}
req = urllib.request.Request(
    "http://127.0.0.1:3000/send_private_msg",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=90) as r:
    d = json.loads(r.read().decode())
print("webp 表情发送 →", "retcode:", d.get("retcode"), "| message_id:", (d.get("data") or {}).get("message_id"))
