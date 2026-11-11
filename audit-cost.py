#!/usr/bin/env python3
"""量化：34 个工具各占多少字符/token，人设各节各占多少。"""
import io
import json
import re
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ── 工具 ──
d = json.loads(urllib.request.urlopen('http://127.0.0.1:3210/api/capabilities', timeout=10).read().decode())
tools = d.get('tools', [])
print(f'工具数 {len(tools)}\n')
print(f"{'工具名':<20}{'描述字数':>8}{'参数数':>7}")
print('-' * 38)
for t in sorted(tools, key=lambda x: -len(str(x.get('description') or ''))):
    print(f"{t['name']:<20}{len(str(t.get('description') or '')):>8}{len(t.get('params') or []):>7}")

# ── 人设各节 ──
cfg = json.load(open('/opt/qq-agent/data/config.json', encoding='utf-8'))
persona = cfg['persona']['roleText']
print(f'\n\n人设 {len(persona)} 字符，各节占比：')
print(f"{'节':<34}{'字符':>7}{'占比':>7}")
print('-' * 48)
parts = re.split(r'(?m)^(?=#{2,3} )', persona)
for p in parts:
    if not p.strip():
        continue
    title = p.strip().split('\n', 1)[0].lstrip('# ').strip()[:30]
    print(f'{title:<34}{len(p):>7}{len(p)/len(persona)*100:>6.1f}%')
