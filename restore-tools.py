#!/usr/bin/env python3
"""从备份恢复 tools.js，然后**精确**删除 schedule_query 与 import_schedule_ics 两个工具对象。

边界判定：每个工具对象结束后紧跟下一个工具（`\n    {\n      name: '`）。
之前用 write_handover 当end标记，结果把中间 16 个工具一起删了 —— 这次只切到下一个工具为止。
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

before = len(set(re.findall(r"name: '([a-z_]+)'", s)))
print('恢复后的工具数:', before)


def remove_tool(name):
    global s
    start_marker = f"    {{\n      name: '{name}',"
    i = s.find(start_marker)
    if i < 0:
        print(f'  ! 找不到工具 {name}')
        return False
    nxt = s.find("\n    {\n      name: '", i + len(start_marker))
    if nxt < 0:
        print(f'  ! 找不到 {name} 之后的下一个工具')
        return False
    removed = nxt - i
    s = s[:i] + s[nxt:]
    print(f'  ✓ 删除 {name}（{removed} 字符，到下一个工具为止）')
    return True


for t in ('schedule_query', 'import_schedule_ics'):
    remove_tool(t)

open(P, 'w', encoding='utf-8').write(s)
after = sorted(set(re.findall(r"name: '([a-z_]+)'", s)))
print('删除后工具数:', len(after))
missing = [t for t in ('receive_file', 'list_stickers', 'send_voice', 'send_sticker',
                       'get_message_images', 'get_message_video', 'bili_video',
                       'send_poke', 'collect_sticker', 'get_sticker_image')
           if t not in after]
print('关键工具是否都在:', '全在 ✓' if not missing else f'❌ 缺 {missing}')
print('课表相关是否清掉:', '是 ✓' if not any('schedule_query' in t or 'ics' in t for t in after) else '❌')
