#!/usr/bin/env python3
"""导出最近的聊天记录，找小鲸鱼提出的需求。"""
import glob
import io
import json
import os
import sys
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

files = sorted(glob.glob('/opt/qq-agent/data/messages/*.json'), key=os.path.getmtime, reverse=True)
print('会话文件:', [os.path.basename(f) for f in files])

for f in files:
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception as e:
        print(f, '读取失败', e)
        continue
    msgs = d if isinstance(d, list) else d.get('messages', [])
    print(f'\n===== {os.path.basename(f)} （{len(msgs)} 条）最近 30 条 =====')
    for m in msgs[-30:]:
        ts = m.get('ts') or 0
        t = datetime.fromtimestamp(ts / 1000).strftime('%m-%d %H:%M')
        who = '她' if m.get('self') else (m.get('senderName') or '?')
        text = str(m.get('text') or '').replace('\n', ' ')
        print(f'[{t}] {who}: {text[:120]}')
