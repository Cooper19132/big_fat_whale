#!/usr/bin/env python3
"""抽出这些「闲置工具」的定义（描述+参数），用于写使用说明。"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = '/opt/qq-agent/src/tools.js'
txt = open(SRC, encoding='utf-8').read()

WANT = ['kb_overview', 'kb_questions', 'kb_textbook', 'kb_progress', 'study_plan',
        'study_log', 'teacher_control', 'report_feedback', 'collect_sticker',
        'sticker_note', 'get_message_detail', 'get_active_members', 'bili_video', 'send_poke']

# 按工具对象切块
blocks = re.split(r"\n    \{\n      name: '", txt)
for b in blocks[1:]:
    name = b.split("'", 1)[0]
    if name not in WANT:
        continue
    desc = re.search(r"description:\s*'((?:[^'\\]|\\.)*)'", b)
    props = re.findall(r"(\w+):\s*\{\s*type:\s*'?([\w\[\]']+)'", b[:3000])
    required = re.search(r"required:\s*\[([^\]]*)\]", b)
    print(f'### {name}')
    print('描述:', (desc.group(1) if desc else '')[:400])
    print('参数:', ', '.join(f'{k}:{t}' for k, t in props[:10]))
    print('必填:', (required.group(1).replace("'", '').strip() if required else ''))
    print()
