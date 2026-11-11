#!/usr/bin/env python3
"""量化：27 个工具的 schema 到底占多少 token（用真实 API 计数，对照组为空 schema）。"""
import io
import json
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

JS = r'''
import { buildToolDefs, toOpenAiTools } from "/opt/qq-agent/src/tools.js";
const defs = buildToolDefs();
console.log(JSON.stringify({ count: defs.length, tools: toOpenAiTools(defs) }));
'''
open('/tmp/dump-tools.mjs', 'w').write(JS)
out = subprocess.run(['node', '/tmp/dump-tools.mjs'], capture_output=True, text=True, timeout=60)
if out.returncode != 0:
    raise SystemExit('导出工具失败: ' + out.stderr[:300])
payload = json.loads(out.stdout)
tools = payload['tools']
print('工具数:', payload['count'])

cfg = json.load(open('/opt/qq-agent/data/config.json', encoding='utf-8'))['api']
import urllib.request


def count(with_tools):
    body = {'model': cfg['model'], 'messages': [{'role': 'user', 'content': '你好'}],
            'max_tokens': 1, 'thinking': {'type': 'disabled'}}
    if with_tools:
        body['tools'] = tools
    req = urllib.request.Request(cfg['baseUrl'].rstrip('/') + '/chat/completions',
                                 data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + cfg['apiKey'],
                                          'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=60).read().decode())['usage']['prompt_tokens']


base = count(False)
full = count(True)
print(f'空请求（仅"你好"）: {base} token')
print(f'带 27 个工具:      {full} token')
print(f'→ 工具 schema 占:  {full - base} token')
print()
print(f'删除前（34 个工具）: 3265 token')
print(f'现在（27 个工具）:   {full - base} token')
print(f'省下:                {3265 - (full - base)} token/轮')
