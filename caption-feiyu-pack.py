#!/usr/bin/env python3
"""给新导入的「大肥鱼包」105 张表情做视觉打标（本地文件，不走图床）。

- 输入：data/stickers/<id>.<ext>（已落盘，gif 取首帧）
- 输出：desc 换成真实描述；原分类名（要饭/开心…）保留到 tags，场景搜索不受影响
- 断点续跑：desc 已是「分类·NN」格式的才处理
"""
import base64
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

STICKERS = '/opt/qq-agent/data/stickers.json'
SDIR = '/opt/qq-agent/data/stickers'
LOG = '/opt/qq-agent/data/fy-caption.log'
api = json.load(open('/opt/qq-agent/data/config.json', encoding='utf-8'))['api']
KEY, BASE, MODEL = api['apiKey'], api['baseUrl'].rstrip('/'), api['model']

PROMPT = ('这是一张 QQ 表情包（卡通鲸鱼娘/大肥鱼同人）。用不超过 12 个字描述画面里的动作和情绪，'
          '只输出描述本身，不要编号、不要标点、不要解释。例如：鼓脸生气 / 举碗讨饭 / 趴地睡觉')
LABEL = re.compile(r'^(.+?)·\d+$')


def log(m):
    line = f'{time.strftime("%H:%M:%S")} {m}'
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def find_local(sid):
    for ext in ('gif', 'jpg', 'jpeg', 'png', 'webp'):
        p = f'{SDIR}/{sid}.{ext}'
        if os.path.exists(p):
            return p
    return None


def to_jpg(path):
    if path.lower().endswith(('.jpg', '.jpeg')):
        return path
    out = '/tmp/fy_frame.jpg'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', path, '-frames:v', '1',
                    '-vf', "scale='min(480,iw)':-2,format=rgb24", '-q:v', '6', out],
                   check=True, timeout=60)
    return out


def caption(jpg):
    b64 = base64.b64encode(open(jpg, 'rb').read()).decode()
    body = json.dumps({
        'model': MODEL,
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': PROMPT},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
        ]}],
        'max_tokens': 64, 'temperature': 0, 'thinking': {'type': 'disabled'},
    }).encode()
    req = urllib.request.Request(BASE + '/chat/completions', data=body,
                                 headers={'Authorization': 'Bearer ' + KEY,
                                          'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=90) as r:
        d = json.loads(r.read().decode())
    t = (d['choices'][0]['message'].get('content') or '').strip()
    return re.sub(r'[\s"“”「」（）()。，,、；;：:！!？?·]', '', t)[:16]


def main():
    data = json.load(open(STICKERS, encoding='utf-8'))
    todo = [e for e in data if str(e.get('id', '')).startswith('fy-') and LABEL.match(str(e.get('desc') or ''))]
    log(f'待打标 {len(todo)} 张（大肥鱼包）')
    ok = fail = 0
    for i, e in enumerate(todo, 1):
        local = find_local(e['id'])
        if not local:
            log(f'  缺文件 {e["id"]}'); fail += 1; continue
        try:
            cap = caption(to_jpg(local))
        except Exception as ex:
            log(f'  失败 {e["id"]}: {str(ex)[:70]}'); fail += 1; continue
        if not cap:
            log(f'  空描述 {e["id"]}'); fail += 1; continue
        m = LABEL.match(str(e['desc']))
        label = m.group(1) if m else ''
        tags = list(e.get('tags') or [])
        if label and label not in tags:
            tags.append(label)
        e['tags'] = tags
        e['desc'] = cap
        ok += 1
        if i % 10 == 0:
            json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            log(f'进度 {i}/{len(todo)}  例：{cap}')
    json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'完成：成功 {ok}，失败 {fail}')


if __name__ == '__main__':
    main()
