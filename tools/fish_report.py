#!/usr/bin/env python3
"""批量体检：把小鲸鱼最近 N 天的发言逐条过 fishtalk_lite，统计命中分布。

用法（服务器）：python3 fish_report.py [天数]
只读本地消息 JSON，不联网、不调模型。
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

from fishtalk_lite import analyze, SKELETON  # noqa: E402

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7
CUT = time.time() - DAYS * 86400
MSG_DIR = '/opt/qq-agent/data/messages'


def main():
    mine = []
    for f in glob.glob(os.path.join(MSG_DIR, '*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        msgs = d if isinstance(d, list) else d.get('messages', [])
        for m in msgs:
            if not m.get('self'):
                continue
            if (m.get('ts') or 0) / 1000 < CUT:
                continue
            t = str(m.get('text') or '').strip()
            if not t or t.startswith('[图片]'):
                continue
            mine.append(t)

    print(f'样本：她最近 {DAYS} 天 {len(mine)} 条发言\n')
    if not mine:
        return

    verdicts = Counter()
    fam_counter = Counter()
    bad = []
    for t in mine:
        v, fams, pos, hits = analyze(t)
        verdicts[v] += 1
        for f in fams:
            fam_counter[f] += 1
        if v.startswith('✗') or v.startswith('△'):
            bad.append((v, fams, pos, t, hits))

    n = len(mine)
    print('判定分布：')
    for v, c in verdicts.most_common():
        print(f'  {v:12s} {c:4d}  ({c / n * 100:.1f}%)')

    print('\n命中的骨架家族（按次数）：')
    for f, c in fam_counter.most_common():
        print(f'  {f:10s} {c:4d}  ({c / n * 100:.1f}% 的发言命中)')

    print(f'\n需要改的样本（{len(bad)} 条，抽前 8 条）：')
    for v, fams, pos, t, hits in bad[:8]:
        print(f'  {v} [{"+".join(fams)}] {"".join(sorted(pos)) or "-"}')
        print(f'    {t[:60]}')


if __name__ == '__main__':
    main()
