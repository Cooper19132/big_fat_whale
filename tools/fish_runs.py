#!/usr/bin/env python3
"""按「一次运行」体检：把她在同一轮里发出的多条消息拼成一段，再过多骨架检测。

为什么需要这个：她的单条消息很短（中位 24 字），八股骨架很难塞进一条；
但一轮里连发 3~4 条时，「开场认账 + 中途不是X是Y + 结尾自贬」这种组合就会出现。

用法（服务器）：python3 fish_runs.py [天数]
"""
import glob
import io
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from fishtalk_lite import analyze  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
CUT = time.time() - DAYS * 86400
SESS_DIR = '/opt/qq-agent/data/sessions'


def texts_of(session):
    """取出这一轮她实际发出的文本（send_message 的参数）。"""
    out = []
    for m in session.get('messages') or []:
        for tc in (m.get('tool_calls') or []):
            fn = tc.get('function') or {}
            if fn.get('name') != 'send_message':
                continue
            try:
                a = json.loads(fn.get('arguments') or '{}')
            except Exception:
                continue
            v = a.get('messages') or a.get('text')
            if isinstance(v, list):
                out.extend(str(x) for x in v)
            elif v:
                out.append(str(v))
    return out


def main():
    runs = []
    for f in glob.glob(os.path.join(SESS_DIR, '*.json')):
        if os.path.getmtime(f) < CUT:
            continue
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        t = texts_of(d)
        if t:
            runs.append((os.path.getmtime(f), d.get('chatKey'), t))

    print(f'样本：最近 {DAYS} 天她发过言的运行 {len(runs)} 次\n')
    if not runs:
        return

    verdicts = Counter()
    fam_counter = Counter()
    bad = []
    for ts, chat, texts in runs:
        joined = '\n'.join(texts)
        v, fams, pos, hits = analyze(joined)
        verdicts[v] += 1
        for x in fams:
            fam_counter[x] += 1
        if v.startswith('✗') or v.startswith('△'):
            bad.append((ts, chat, v, fams, pos, texts, hits))

    n = len(runs)
    print('判定分布（按一次运行算）：')
    for v, c in verdicts.most_common():
        print(f'  {v:22s} {c:3d}  ({c / n * 100:.1f}%)')

    print('\n命中家族：')
    for x, c in fam_counter.most_common():
        print(f'  {x:12s} {c:3d}  ({c / n * 100:.1f}%)')

    print(f'\n需要改的运行（{len(bad)} 次），抽前 5 次：')
    for ts, chat, v, fams, pos, texts, hits in bad[:5]:
        print(f'\n  {time.strftime("%m-%d %H:%M", time.localtime(ts))} {chat} → {v} [{"+".join(fams)}] {"".join(sorted(pos)) or "-"}')
        for i, t in enumerate(texts[:4], 1):
            print(f'    {i}. {t[:60]}')


if __name__ == '__main__':
    main()
