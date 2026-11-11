#!/usr/bin/env python3
"""在人设卡里补一条「被要求语音就直接发」，避免害羞人设把语音推掉。"""
import json
import urllib.request

CFG = "/opt/qq-agent/data/config.json"
LINE = "- 被要求发语音时就直接发，不要因为害羞推掉——那就是你自己的声音，大大方方说就好。"

cfg = json.load(open(CFG, encoding="utf-8"))
role = cfg["persona"]["roleText"]
if LINE in role:
    print("已存在，跳过")
else:
    role = role.rstrip() + "\n" + LINE + "\n"
    body = json.dumps({"persona": {"roleText": role}}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:3210/api/config",
        data=body, headers={"content-type": "application/json"}, method="POST")
    print("写入:", urllib.request.urlopen(req, timeout=15).status)
    c2 = json.load(open(CFG, encoding="utf-8"))
    print("人设长度:", len(c2["persona"]["roleText"]))
    print("末行:", c2["persona"]["roleText"].strip().splitlines()[-1])
