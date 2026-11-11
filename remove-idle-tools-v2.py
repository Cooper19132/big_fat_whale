#!/usr/bin/env python3
"""删除 A/B/C 三组闲置工具。

发现：kb_* 与 study_* 都在 KB_TOOLS 数组里，而 orchestrator 只在身份模式 = 'tutor'
时才挂载它们 —— 你平时不是 tutor，所以这 6 个工具一直是死的。
teacher_control 是主数组最后一个元素。
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TOOLS = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
ORCH = r'D:\dshworks\qqbot\qq-agent\src\orchestrator.js'


def rd(p):
    return open(p, encoding='utf-8').read()


def wr(p, s):
    open(p, 'w', encoding='utf-8').write(s)


s = rd(TOOLS)
before = sorted(set(re.findall(r"name: '([a-z_]+)'", s)))
print('删除前工具数:', len(before))

# ① buildToolDefs 里去掉 ...KB_TOOLS 展开
old_spread = "  return [...KB_TOOLS,\n"
assert s.count(old_spread) == 1, f'spread 匹配 {s.count(old_spread)} 次'
s = s.replace(old_spread, "  return [\n")

# ② 整块删掉 KB_TOOLS 数组（含 kb_* 与 study_* 共 6 个工具）
i = s.find('const KB_TOOLS = [')
assert i > 0, '找不到 KB_TOOLS'
j = s.find('\n];\n', i)
assert j > i, '找不到 KB_TOOLS 结尾'
removed_chars = j + 4 - i
s = s[:i] + s[j + 4:]
print(f'  ✓ 删除 KB_TOOLS 数组（{removed_chars} 字符，含 6 个工具）')

# ③ 删掉 KB_TOOL_NAMES 导出
old_names = "export const KB_TOOL_NAMES = new Set(KB_TOOLS.map((t) => t.name));\n"
if old_names in s:
    s = s.replace(old_names, '')
    print('  ✓ 删除 KB_TOOL_NAMES 导出')

# ④ 删掉 teacher_control（主数组最后一个元素）
start = "    {\n      name: 'teacher_control',"
i2 = s.find(start)
assert i2 > 0, '找不到 teacher_control'
j2 = s.find('  ];\n', i2)
assert j2 > i2, '找不到主数组结尾'
s = s[:i2] + s[j2:]
print(f'  ✓ 删除 teacher_control（{j2 - i2} 字符）')

# ⑤ knowledge 模块 import 已无引用
old_imp = "import * as KB from './knowledge.js';\n"
if old_imp in s and 'KB.' not in s:
    s = s.replace(old_imp, '')
    print('  ✓ 删除 knowledge.js 的 import（已无引用）')

wr(TOOLS, s)

# ⑥ orchestrator：去掉按身份过滤 KB 工具的逻辑
o = rd(ORCH)
o2 = o.replace("import { buildToolDefs, toOpenAiTools, executeTool, KB_TOOL_NAMES } from './tools.js';",
               "import { buildToolDefs, toOpenAiTools, executeTool } from './tools.js';")
if o2 != o:
    print('  ✓ orchestrator import 已更新')
o = o2
gate = "      if (KB_TOOL_NAMES.has(d.name) && ident.mode !== 'tutor') return false;\n"
if gate in o:
    o = o.replace(gate, '')
    print('  ✓ orchestrator 里的 tutor 模式过滤已删除')
wr(ORCH, o)

after = sorted(set(re.findall(r"name: '([a-z_]+)'", o if False else rd(TOOLS))))
print('\n删除后工具数:', len(after))
print('实际删除:', [t for t in before if t not in after])
print('意外丢失:', [t for t in after if t not in before] or '无')

MUST = ['send_message', 'send_sticker', 'send_voice', 'send_image', 'send_file', 'send_poke',
        'receive_file', 'list_stickers', 'get_sticker_image', 'sticker_note', 'collect_sticker',
        'get_message_images', 'get_message_video', 'get_recent_messages', 'get_active_members',
        'get_message_detail', 'bili_video', 'web_search', 'web_fetch', 'memory_append',
        'memory_query', 'memory_remove', 'dsh_task', 'write_handover', 'finish', 'report_feedback',
        'schedule_task']
missing = [t for t in MUST if t not in after]
print('关键工具缺失:', missing or '无 ✓')
