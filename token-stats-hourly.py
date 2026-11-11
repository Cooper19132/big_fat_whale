#!/usr/bin/env python3
"""按「活跃小时」统计 token 消耗：只算真正有运行的钟点。"""
import glob
import io
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

PIN, POUT = 2.0, 8.0

hours = defaultdict(lambda: {'runs': 0, 'p': 0, 'c': 0})
for f in glob.glob('/opt/qq-agent/data/sessions/*.json'):
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    u = d.get('usage') or {}
    ts = d.get('startedAt') or 0
    if not ts:
        continue
    dt = datetime.fromtimestamp(ts / 1000)
    key = dt.strftime('%m-%d %H时')
    h = hours[key]
    h['runs'] += 1
    h['p'] += int(u.get('promptTokens') or 0)
    h['c'] += int(u.get('completionTokens') or 0)

rows = []
for k, h in hours.items():
    total = h['p'] + h['c']
    cost = h['p'] * PIN / 1e6 + h['c'] * POUT / 1e6
    rows.append((k, h['runs'], h['p'], h['c'], total, cost))

rows.sort()
print(f"{'活跃小时':<12}{'轮数':>5}{'输入tok':>11}{'输出tok':>9}{'合计tok':>11}{'费用(元)':>9}")
print('-' * 60)
for k, runs, p, c, total, cost in rows:
    print(f"{k:<12}{runs:>5}{p:>11}{c:>9}{total:>11}{cost:>9.2f}")

n = len(rows)
sum_runs = sum(r[1] for r in rows)
sum_tok = sum(r[4] for r in rows)
sum_cost = sum(r[5] for r in rows)
toks = [r[4] for r in rows]
costs = [r[5] for r in rows]
print('-' * 60)
print(f"活跃小时数: {n}  （总轮数 {sum_runs}，累计 {sum_tok:,} token，{sum_cost:.2f} 元）")
print()
print(f"每小时均值:  {sum_tok / n:,.0f} token / {sum_cost / n:.2f} 元 / {sum_runs / n:.1f} 轮")
print(f"每小时中位数: {statistics.median(toks):,.0f} token / {statistics.median(costs):.2f} 元")
print(f"最忙一小时:  {max(rows, key=lambda r: r[4])[0]}  {max(toks):,} token")
print(f"最高费用小时: {max(rows, key=lambda r: r[5])[0]}  {max(costs):.2f} 元")
