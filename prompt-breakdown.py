#!/usr/bin/env python3
"""精算一次运行的提示词构成：各段占多少字符/token。"""
import glob
import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

f = sorted(glob.glob('/opt/qq-agent/data/sessions/*.json'), key=os.path.getmtime)[-1]
d = json.load(open(f, encoding='utf-8'))
sp = str(d.get('systemPrompt') or '')
up = str(d.get('userPrompt') or '')
tok = (d.get('usage') or {}).get('promptTokens') or 0
total_chars = len(sp) + len(up)
ratio = tok / total_chars if total_chars else 0

print('会话:', os.path.basename(f))
print(f'字符合计 {total_chars} → promptTokens {tok}（约 {ratio:.2f} token/字符）')
print()

marks = ['【角色设定】', '【过去状态】', '【本次唤醒】', '【参与者参考】', '【参与度参考】',
         '【记忆】', '【可用表情包】', '【引导说明】', '【交接摘要】']
pos = []
for m in marks:
    i = up.find(m)
    if i >= 0:
        pos.append((i, m))
pos.sort()

print(f"{'片段':<16}{'字符':>8}{'≈token':>9}")
print('-' * 34)
print(f"{'系统提示':<16}{len(sp):>8}{int(len(sp) * ratio):>9}")
for idx, (start, name) in enumerate(pos):
    end = pos[idx + 1][0] if idx + 1 < len(pos) else len(up)
    seg = end - start
    print(f"{name:<16}{seg:>8}{int(seg * ratio):>9}")
if pos and pos[0][0] > 0:
    print(f"{'(前导)':<16}{pos[0][0]:>8}{int(pos[0][0] * ratio):>9}")
print('-' * 34)
print(f"每轮合计 ≈ {tok} token")

# 估算 pastStateLimit 从 80 降到 40 的收益
past = dict((n, e - s) for (s, n), (e, _) in zip(pos, pos[1:] + [(len(up), '')]))
past_chars = past.get('【过去状态】', 0)
if past_chars:
    half = past_chars / 2
    print()
    print(f"过去状态当前 ≈ {past_chars} 字符（{int(past_chars * ratio)} token，占每轮 {past_chars / total_chars * 100:.0f}%）")
    print(f"80 条 → 40 条大约能省 {int(half * ratio)} token/轮 ≈ 每轮 {half / total_chars * 100:.0f}%")
