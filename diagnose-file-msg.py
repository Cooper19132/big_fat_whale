#!/usr/bin/env python3
"""诊断：QQ 文件消息在存档里长什么样、文件到底在不在服务器上。"""
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

f = '/opt/qq-agent/data/messages/private_246695065.json'
d = json.load(open(f, encoding='utf-8'))
msgs = d if isinstance(d, list) else d.get('messages', [])

found = 0
for m in msgs:
    media = m.get('media') or []
    if not media:
        continue
    print(f"\n[{m.get('ts')}] {m.get('senderName')}: {str(m.get('text'))[:80]}")
    for md in media:
        print("   media:", json.dumps(md, ensure_ascii=False)[:300])
        for key in ('file', 'path', 'localPath'):
            p = md.get(key)
            if isinstance(p, str) and p:
                print(f"      {key}={p} → 存在: {os.path.exists(p)}")
    found += 1
    if found >= 6:
        break

print("\n=== 服务器上找 .ics 文件 ===")
for root in ('/root/Napcat', '/opt/qq-agent', '/tmp', '/root/.config/QQ'):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [x for x in dirnames if x not in ('node_modules', '.git', 'python', 'repo')]
        for fn in filenames:
            if fn.lower().endswith('.ics') or '课程表' in fn:
                p = os.path.join(dirpath, fn)
                print("  找到:", p, os.path.getsize(p), "字节")
