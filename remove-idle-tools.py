#!/usr/bin/env python3
"""删除 7 个闲置工具：知识库 4 + 学习计划 2 + 副实例控制 1。

边界策略：从工具自身起点切到「下一个工具的起点」为止（上次用远端标记误删过 16 个工具）。
删完做两道校验：工具总数、关键工具是否还在。
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

REMOVE = ['kb_overview', 'kb_questions', 'kb_textbook', 'kb_progress',
          'study_plan', 'study_log', 'teacher_control']
BEFORE = sorted(set(re.findall(r"name: '([a-z_]+)'", s)))
print('删除前工具数:', len(BEFORE))


def remove_tool(name):
    global s
    start = f"    {{\n      name: '{name}',"
    i = s.find(start)
    if i < 0:
        # 有些工具块缩进可能不同，退化匹配
        m = re.search(r"\n    \{\n      name: '" + name + r"',", s)
        if not m:
            print(f'  ! 找不到 {name}')
            return False
        i = m.start() + 1
    nxt = s.find("\n    {\n      name: '", i + len(start))
    if nxt < 0:
        print(f'  ! {name} 后面找不到下一个工具')
        return False
    removed = nxt - i
    s = s[:i] + s[nxt:]
    print(f'  ✓ 删除 {name}（{removed} 字符）')
    return True


for name in REMOVE:
    remove_tool(name)

open(P, 'w', encoding='utf-8').write(s)

AFTER = sorted(set(re.findall(r"name: '([a-z_]+)'", s)))
print('\n删除后工具数:', len(AFTER))
print('实际删除:', [t for t in BEFORE if t not in AFTER])
print('意外丢失:', [t for t in AFTER if t not in BEFORE] or '无')

MUST = ['send_message', 'send_sticker', 'send_voice', 'send_image', 'send_file', 'send_poke',
        'receive_file', 'list_stickers', 'get_sticker_image', 'sticker_note', 'collect_sticker',
        'get_message_images', 'get_message_video', 'get_recent_messages', 'get_active_members',
        'get_message_detail', 'bili_video', 'web_search', 'web_fetch', 'memory_append',
        'memory_query', 'memory_remove', 'dsh_task', 'write_handover', 'finish', 'report_feedback']
missing = [t for t in MUST if t not in AFTER]
print('关键工具缺失:', missing or '无 ✓')
print('剩余:', ' '.join(AFTER))
