#!/usr/bin/env python3
"""生成 3 段不同音色的样音，逐个发到主人 QQ，供挑选。"""
import base64
import json
import os
import subprocess
import urllib.request

TARGET = 246695065
API_TEXT = "http://127.0.0.1:3000/send_private_msg"
TMP = "/tmp/voicesel"
os.makedirs(TMP, exist_ok=True)

TEXT = "主人主人，我是小鲸鱼呀。这个声音可爱吗？喜欢的话就用它吧。"

CANDIDATES = [
    ("zh-CN-XiaoyiNeural", "① 晓伊 —— 活泼可爱（卡通/小说风，最可爱的那一个）"),
    ("zh-CN-XiaoxiaoNeural", "② 晓晓 —— 温柔自然（最像真人、最稳）"),
    ("zh-TW-HsiaoYuNeural", "③ 曉雨 —— 台湾软糯（声音偏软偏甜）"),
]


def post(payload):
    req = urllib.request.Request(
        API_TEXT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def send_text(text):
    return post({"user_id": TARGET, "message": [{"type": "text", "data": {"text": text}}]})


def send_voice(path):
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    return post({"user_id": TARGET, "message": [{"type": "record", "data": {"file": "base64://" + b64}}]})


for voice, label in CANDIDATES:
    mp3 = os.path.join(TMP, voice + ".mp3")
    subprocess.run(
        ["python3", "-m", "edge_tts", "--voice", voice, "--text", TEXT, "--write-media", mp3],
        check=True, capture_output=True, timeout=120,
    )
    size = os.path.getsize(mp3)
    send_text(label)
    r = send_voice(mp3)
    print(f"{voice}: {size} 字节 → retcode={r.get('retcode')} id={r.get('data', {}).get('message_id')}")

send_text("三段发完了，回我编号（1/2/3）就行。想调语速也可以说「快一点/慢一点」。")
