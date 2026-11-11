#!/usr/bin/env python3
"""把「性格层 + 语言层」拼成一份人设推到 QQ Agent。

为什么要拼：qq-agent 的配置只有一个 persona.roleText 字段（外部要改代码才能加第二字段），
所以源文件分两层维护，推送时按「性格层 → 语言层」顺序合并。
合并规则：先知道我是谁，再知道怎么开口。
"""
import json
import urllib.request

CHAR = "/tmp/persona-char.md"
LANG = "/tmp/persona-lang.md"
CFG = "/opt/qq-agent/data/config.json"

char = open(CHAR, encoding="utf-8").read().strip()
lang = open(LANG, encoding="utf-8").read().strip()
text = char + "\n\n---\n\n" + lang + "\n"

print(f"  性格层 {len(char):,} 字符 + 语言层 {len(lang):,} 字符 = {len(text):,} 字符")

body = json.dumps({"persona": {"roleText": text}}).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:3210/api/config",
    data=body, headers={"content-type": "application/json"}, method="POST")
print("  写入 HTTP:", urllib.request.urlopen(req, timeout=20).status)

c = json.load(open(CFG, encoding="utf-8"))
t = c["persona"]["roleText"]
print("  落盘:", len(t), "字符")
checks = [
    ("性格层在", "性格层：小鲸鱼是谁" in t),
    ("语言层在", "语言层：小鲸鱼怎么说话" in t),
    ("语气词配比", "句尾语气词配比" in t),
    ("五组别犯", "五组别犯" in t),
    ("空洞夸赞", "不许空洞夸赞" in t),
    ("主人绑定", "246695065" in t),
    ("成人尺度", "放得开的那种" in t),
]
for name, ok in checks:
    print(("  ✓ " if ok else "  ✗ ") + name)
