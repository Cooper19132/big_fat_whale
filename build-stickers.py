#!/usr/bin/env python3
"""把 blue-fish-archive 的 270 张大肥鱼表情转成 qq-agent 的 stickers.json。"""
import json
import io
import sys
from datetime import datetime, timezone
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = 'bfa-manifest.json'
OUT = 'stickers-import.json'
CDN = 'https://cdn.jsdelivr.net/gh/EDMOK/blue-fish-archive@main/'

manifest = json.load(open(SRC, encoding='utf-8'))
now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

entries = []
for i, item in enumerate(manifest, 1):
    large = item.get('large') or item.get('original') or ''
    if not large:
        continue
    stem = large.split('/')[-1].rsplit('.', 1)[0]
    entries.append({
        'id': stem,
        'resId': stem,
        'url': CDN + quote(large),
        'desc': f'鲸鱼娘表情 {i:03d}',
        'localNote': '',
        'tags': ['大肥鱼', '鲸鱼娘', '表情'],
        'usage': '',
        'source': 'manual',
        'useCount': 0,
        'lastUsedAt': 0,
        'lastContext': '',
        'createdAt': now,
        'updatedAt': now,
    })

json.dump(entries, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(f"生成 {len(entries)} 条 → {OUT}")
print("首条:", json.dumps(entries[0], ensure_ascii=False))
print("末条:", json.dumps(entries[-1], ensure_ascii=False))
sizes = {}
for e in entries:
    sizes[e['url'].split('.')[-1]] = sizes.get(e['url'].split('.')[-1], 0) + 1
print("格式分布:", sizes)
