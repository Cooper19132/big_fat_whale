#!/usr/bin/env python3
"""对比：当前工具的名单 vs 备份（原始）工具的名单，看课表补丁误删了什么。"""
import io
import json
import re
import subprocess
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 当前运行中的工具
with urllib.request.urlopen('http://127.0.0.1:3210/api/capabilities', timeout=10) as r:
    cur = sorted(t['name'] for t in json.loads(r.read().decode()).get('tools', []))

# 备份里的原始工具
bak_dir = subprocess.run(['bash', '-lc', 'ls -d /opt/qq-agent/src.bak-noschedule-* 2>/dev/null | tail -1'],
                         capture_output=True, text=True).stdout.strip()
print('备份目录:', bak_dir or '(没有备份)')
orig = []
if bak_dir:
    txt = open(f'{bak_dir}/tools.js', encoding='utf-8').read()
    orig = sorted(set(re.findall(r"name: '([a-z_]+)'", txt)))

print(f'\n当前 {len(cur)} 个:')
print('  ' + ' '.join(cur))
print(f'\n原始 {len(orig)} 个:')
print('  ' + ' '.join(orig))

lost = [t for t in orig if t not in cur]
print(f'\n❌ 被误删的 {len(lost)} 个:')
for t in lost:
    print('  -', t)
