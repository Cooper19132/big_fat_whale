#!/usr/bin/env python3
"""量化：pastStateLimit 取不同值时，每轮要重发多少字/多少 token。"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CHAT = '/opt/qq-agent/data/messages/group_1035218437.json'
MAX_CHARS = 6000          # pastStateMaxChars 默认值
RATIO = 1.73              # 实测：12367 字符 → 21430 token

d = json.load(open(CHAT, encoding='utf-8'))
msgs = d if isinstance(d, list) else d.get('messages', [])
print(f"群聊存档共 {len(msgs)} 条")

def line_of(m):
    who = '我' if m.get('self') else (m.get('senderName') or '?')
    text = str(m.get('text') or '')
    return f"[{who}] {text}"

print(f"\n{'pastStateLimit':>15}{'实际条数':>9}{'字符数':>9}{'≈token':>9}{'vs 80条':>9}")
base = None
for limit in (80, 60, 40, 30, 20):
    picked = msgs[-limit:]
    lines = [line_of(m) for m in picked]
    # 模拟 buildPastState 的字符预算：超了从头部丢
    while len(lines) > 1 and sum(len(x) + 1 for x in lines) > MAX_CHARS:
        lines.pop(0)
    chars = sum(len(x) + 1 for x in lines)
    tok = int(chars * RATIO)
    if base is None:
        base = tok
    print(f"{limit:>15}{len(lines):>9}{chars:>9}{tok:>9}{tok / base * 100:>8.0f}%")

print(f"\n说明：过去状态 = 每轮**重新发送**的最近聊天记录，是每轮 token 的主要构成。")
print(f"截断判定：条数到 limit 或字符超 {MAX_CHARS} 都会让 truncated=true（触发交接提示）。")
