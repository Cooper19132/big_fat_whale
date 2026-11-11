#!/usr/bin/env python3
"""对照实验：往群里发一条**不带引用**的语音，验证「引用+语音」是不是打不开的原因。"""
import base64
import json
import os
import subprocess
import urllib.request

GROUP = 1035218437
API = "http://127.0.0.1:3000/send_group_msg"
MP3 = "/tmp/voicesel/zh-CN-XiaoyiNeural.mp3"

subprocess.run(
    ["python3", "-m", "edge_tts", "--voice", "zh-CN-XiaoyiNeural",
     "--text", "这条是测试语音，没有带引用，能听到就说明问题出在引用上。",
     "--write-media", MP3],
    check=True, capture_output=True, timeout=120,
)

b64 = base64.b64encode(open(MP3, "rb").read()).decode()
payload = {"group_id": GROUP, "message": [{"type": "record", "data": {"file": "base64://" + b64}}]}
req = urllib.request.Request(API, data=json.dumps(payload).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=60) as r:
    d = json.loads(r.read().decode())
print("不带引用的群语音 →", "retcode:", d.get("retcode"), "| message_id:", (d.get("data") or {}).get("message_id"))

# 再发一条带引用的做对照（引用它自己刚发的那条消息）
mid = (d.get("data") or {}).get("message_id")
if mid:
    payload2 = {"group_id": GROUP, "message": [
        {"type": "reply", "data": {"id": str(mid)}},
        {"type": "record", "data": {"file": "base64://" + b64}},
    ]}
    req2 = urllib.request.Request(API, data=json.dumps(payload2).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req2, timeout=60) as r2:
        d2 = json.loads(r2.read().decode())
    print("带引用的群语音 →", "retcode:", d2.get("retcode"), "| message_id:", (d2.get("data") or {}).get("message_id"))
