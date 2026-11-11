#!/usr/bin/env python3
"""给表情库里的「无文案」表情批量打语义标签（可中断续跑）。

- 只处理 desc 形如「鲸鱼娘表情 NNN」的条目
- 用视觉模型看缩略图，输出 ≤12 字的中文描述（情绪/动作）
- 每 10 条落盘一次；重复运行会跳过已标注的
"""
import base64
import json
import os
import subprocess
import re
import sys
import time
import urllib.request

STICKERS = '/opt/qq-agent/data/stickers.json'
CFG = '/opt/qq-agent/data/config.json'
LOG = '/opt/qq-agent/data/sticker-caption.log'

cfg = json.load(open(CFG, encoding='utf-8'))
api = cfg['api']
KEY, BASE, MODEL = api['apiKey'], api['baseUrl'].rstrip('/'), api['model']

PROMPT = (
    '这是一张 QQ 聊天用的表情包（卡通鲸鱼娘）。'
    '请用不超过 12 个字描述它的情绪或动作，只输出描述本身，不要编号、不要标点、不要解释。'
    '例如：鼓脸生气 / 躺平摸鱼 / 举手欢呼 / 害羞捂脸 / 无语沉默'
)

BLIND = re.compile(r'^鲸鱼娘表情 \d+$')

CACHE = '/opt/qq-agent/data/stickers'
MIRRORS = [
    lambda u: u.replace('https://cdn.jsdelivr.net/gh/EMDOK/blue-fish-archive@main/',
                        'https://ghfast.top/https://raw.githubusercontent.com/EMDOK/blue-fish-archive/main/'),
    lambda u: u,                                                        # 原地址（jsDelivr）兜底
]


def ensure_local(entry):
    """把表情图下到本地缓存（双源 + 重试），返回本地路径；失败返回 None。"""
    os.makedirs(CACHE, exist_ok=True)
    ext = os.path.splitext(entry['url'])[1] or '.webp'
    local = os.path.join(CACHE, entry['id'] + ext)
    if os.path.exists(local) and os.path.getsize(local) > 1024:
        return local
    for attempt in range(3):
        for mk in MIRRORS:
            url = mk(entry['url'])
            try:
                data = urllib.request.urlopen(url, timeout=45).read()
                if len(data) > 1024:
                    open(local, 'wb').write(data)
                    return local
            except Exception:
                continue
        time.sleep(2.0 + 2.0 * attempt)
    return None


def log(msg):
    line = f'{time.strftime("%H:%M:%S")} {msg}'
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def caption(local_path):
    # 本地文件 → jpg → base64 data URL（API 不接受远程 URL）
    tmp_out = '/tmp/cap_out.jpg'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', local_path,
                    '-vf', "scale='min(480,iw)':-2", '-q:v', '6', tmp_out],
                   check=True, timeout=60)
    b64 = base64.b64encode(open(tmp_out, 'rb').read()).decode()
    data_url = 'data:image/jpeg;base64,' + b64
    body = json.dumps({
        'model': MODEL,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': PROMPT},
            {'type': 'image_url', 'image_url': {'url': data_url}},
        ]}],
        'max_tokens': 64,
        'temperature': 0,
        'thinking': {'type': 'disabled'},   # 关键：不关思考，token 全被 reasoning 吃掉，正文为空
    }).encode()
    req = urllib.request.Request(
        BASE + '/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + KEY, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read().decode())
    text = (d['choices'][0]['message'].get('content') or '').strip()
    text = re.sub(r'[\s"“”「」（）()。，,、；;：:！!？?]', '', text)
    return text[:16]


def main():
    data = json.load(open(STICKERS, encoding='utf-8'))
    todo = [i for i, e in enumerate(data) if BLIND.match(str(e.get('desc') or ''))]
    log(f'待标注 {len(todo)} 条 / 共 {len(data)} 条')
    done = 0
    cost_tokens = 0
    for idx in todo:
        entry = data[idx]
        try:
            local = ensure_local(entry)
            if not local:
                log(f'下载失败，跳过 {entry["id"]}')
                continue
            cap = caption(local)
            if not cap:
                log(f'空描述，跳过 {entry["id"]}')
                continue
            entry['desc'] = cap
            tags = list(entry.get('tags') or [])
            if '自动标注' not in tags:
                tags.append('自动标注')
            entry['tags'] = tags
            done += 1
            if done % 10 == 0:
                json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                log(f'进度 {done}/{len(todo)}（已落盘）  例：{entry["desc"]}')
        except Exception as e:
            log(f'失败 {entry["id"]}: {e}')
            time.sleep(2)
        time.sleep(1.0)
    json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'完成：本轮标注 {done} 条')


if __name__ == '__main__':
    main()
