#!/usr/bin/env python3
"""统计：潜水（noreply）vs 发言（done）各消耗多少 token。"""
import glob
import json
import io
import os
import sys
from collections import defaultdict
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

files = glob.glob('/opt/qq-agent/data/sessions/*.json')
print(f"会话文件总数: {len(files)}")

buckets = defaultdict(lambda: {'n': 0, 'p': 0, 'c': 0})
by_day = defaultdict(lambda: defaultdict(lambda: {'n': 0, 'p': 0, 'c': 0}))
zero_run = 0

for f in files:
    try:
        d = json.load(open(f, encoding='utf-8'))
    except Exception:
        continue
    u = d.get('usage') or {}
    p = int(u.get('promptTokens') or 0)
    c = int(u.get('completionTokens') or 0)
    st = d.get('status') or 'unknown'
    calls = int(u.get('calls') or 0)
    if calls == 0 and p == 0:
        zero_run += 1
    b = buckets[st]
    b['n'] += 1; b['p'] += p; b['c'] += c
    day = datetime.fromtimestamp((d.get('startedAt') or 0) / 1000).strftime('%m-%d')
    db = by_day[day][st]
    db['n'] += 1; db['p'] += p; db['c'] += c

PRICE_IN, PRICE_OUT = 2.0, 8.0   # 元/百万 token（配置里的高峰价）


def avg(x, k):
    return x[k] / x['n'] if x['n'] else 0


print("\n=== 按状态汇总 ===")
print(f"{'状态':<10}{'轮数':>6}{'输入tok':>12}{'输出tok':>10}{'均输入':>10}{'均输出':>9}{'费用(元)':>10}")
for st, b in sorted(buckets.items(), key=lambda kv: -kv[1]['n']):
    cost = b['p'] * PRICE_IN / 1e6 + b['c'] * PRICE_OUT / 1e6
    print(f"{st:<10}{b['n']:>6}{b['p']:>12}{b['c']:>10}{avg(b,'p'):>10.0f}{avg(b,'c'):>9.0f}{cost:>10.4f}")

print("\n=== 最近 3 天 ===")
for day in sorted(by_day)[-3:]:
    tot_n = sum(v['n'] for v in by_day[day].values())
    tot_p = sum(v['p'] for v in by_day[day].values())
    tot_c = sum(v['c'] for v in by_day[day].values())
    cost = tot_p * PRICE_IN / 1e6 + tot_c * PRICE_OUT / 1e6
    parts = "  ".join(f"{k}:{v['n']}轮/{v['p']}tok" for k, v in sorted(by_day[day].items()))
    print(f"{day}  合计 {tot_n} 轮 / {tot_p} 入 + {tot_c} 出 = {cost:.4f} 元")
    print(f"      {parts}")

print(f"\n零调用会话（没跑模型就结束的）: {zero_run}")
