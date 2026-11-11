#!/usr/bin/env python3
"""把本地人设卡推到 QQ Agent（UTF-8 文件方式，避免 Windows shell 转码）。"""
import json
import urllib.request

SRC = "/tmp/persona-new.md"
CFG = "/opt/qq-agent/data/config.json"

text = open(SRC, encoding="utf-8").read()
print("新人设长度:", len(text), "字符")

body = json.dumps({"persona": {"roleText": text}}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:3210/api/config",
    data=body, headers={"content-type": "application/json"}, method="POST")
print("写入:", urllib.request.urlopen(req, timeout=20).status)

c = json.load(open(CFG, encoding="utf-8"))
t = c["persona"]["roleText"]
print("落盘长度:", len(t))
checks = [
    ("认领大肥鱼", "已经认了这个外号" in t),
    ("白饭=token", "白饭就是 token" in t or "白饭就是token" in t),
    ("语音不推辞", "被要求发语音时就直接发" in t),
    ("主人绑定", "246695065" in t),
]
for name, okv in checks:
    print(("  ✓ " if okv else "  ✗ ") + name)
