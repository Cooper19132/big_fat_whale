#!/usr/bin/env python3
"""在 GitHub 上搜「让 AI 说话更像人」相关的仓库 / 提示词 / skill。"""
import json
import sys
import time
import urllib.parse
import urllib.request

QUERIES = [
    '去AI味',
    'AI味 提示词',
    '真人语感',
    'humanize AI text prompt',
    'anti-ai-slop writing',
    'dsh skill',
    '大肥鱼 提示词',
    '群聊 人设 提示词',
]

UA = {'Accept': 'application/vnd.github+json', 'User-Agent': 'dsh-research'}


def search(q, per_page=5):
    url = ('https://api.github.com/search/repositories?q='
           + urllib.parse.quote(q) + f'&sort=stars&order=desc&per_page={per_page}')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


for q in QUERIES:
    print(f'=== {q} ===')
    try:
        d = search(q)
    except Exception as e:
        print('  查询失败:', e)
        continue
    items = d.get('items') or []
    if not items:
        print('  (无结果)')
    for r in items:
        desc = (r.get('description') or '').replace('\n', ' ')[:90]
        line = f"  {r['full_name']}  stars={r['stargazers_count']}  {desc}"
        sys.stdout.write(line.encode('utf-8', 'replace').decode('utf-8', 'replace') + '\n')
    time.sleep(2)
