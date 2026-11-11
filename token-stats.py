#!/usr/bin/env python3
"""按天统计小鲸鱼的 token 消耗与费用。"""
import glob
import io
import json
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PIN, POUT = 2.0, 8.0   # 元/百万 token（配置里的高峰价）

days = defaultdict(lambda: {'runs': 0, 'p': 0, 'c': 0, 'noreply': 0, 'done': 0})
tot = {'runs': 0, 'p': 0, 'c': 0}

for f in glob.glob('/opt/qq-agent/data/sessions/*.json'):
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    u = d.get('usage') or {}
    p = int(u.get('promptTokens') or 0)
    c = int(u.get('completionTokens') or 0)
    ts = d.get('startedAt') or 0
    if not ts:
        continue
    day = datetime.fromtimestamp(ts / 1000).strftime('%m-%d')
    rec = days[day]
    rec['runs'] += 1
    rec['p'] += p
    rec['c'] += c
    if (d.get('status') or '') == 'noreply':
        rec['noreply'] += 1
    else:
        rec['done'] += 1
    tot['runs'] += 1
    tot['p'] += p
    tot['c'] += c

print(f"{'日期':<8}{'轮数':>6}{'输入tok':>12}{'输出tok':>10}{'合计tok':>12}{'费用(元)':>10}{'均token':>10}")
for day in sorted(days):
    r = days[day]
    total = r['p'] + r['c']
    cost = r['p'] * PIN / 1e6 + r['c'] * POUT / 1e6
    print(f"{day:<8}{r['runs']:>6}{r['p']:>12}{r['c']:>10}{total:>12}{cost:>10.2f}{total // max(1, r['runs']):>10}")

total_all = tot['p'] + tot['c']
cost_all = tot['p'] * PIN / 1e6 + tot['c'] * POUT / 1e6
print('-' * 70)
print(f"{'累计':<8}{tot['runs']:>6}{tot['p']:>12}{tot['c']:>10}{total_all:>12}{cost_all:>10.2f}")
print()
print(f"累计 token: {total_all:,}  |  累计费用(按高峰价上限): {cost_all:.2f} 元")
if tot['runs']:
    print(f"平均每轮: {total_all // tot['runs']:,} token")
if len(days) > 1:
    print(f"有数据 {len(days)} 天，日均: {total_all // len(days):,} token / {cost_all / len(days):.2f} 元")
