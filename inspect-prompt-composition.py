#!/usr/bin/env python3
"""看最近会话的提示词构成：系统提示 / 用户提示 各占多少。"""
import glob
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

files = sorted(glob.glob('/opt/qq-agent/data/sessions/*.json'), key=os.path.getmtime)[-4:]
for f in files:
    d = json.load(open(f, encoding='utf-8'))
    u = d.get('usage') or {}
    sp = str(d.get('systemPrompt') or '')
    up = str(d.get('userPrompt') or d.get('prompt') or '')
    print('---', os.path.basename(f)[:24], '| status=', d.get('status'),
          '| calls=', u.get('calls'), '| promptTokens=', u.get('promptTokens'))
    print('    字段:', list(d.keys())[:16])
    print('    systemPrompt 字符:', len(sp), '| userPrompt 字符:', len(up),
          '| promptChars(记录值):', d.get('promptChars'))
    if up:
        # 粗略拆：找出各段标题的位置
        for tag in ('【角色设定】', '【过去状态】', '【本次唤醒】', '【记忆】', '【可用表情包】', '【引导说明】', '【参与度参考】'):
            i = up.find(tag)
            print(f'      {tag}: {"有" if i >= 0 else "无"} @ {i}')
    print()
