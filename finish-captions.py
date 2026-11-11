#!/usr/bin/env python3
"""收尾：把最后几张「下载/解码失败」的表情补齐标注。

策略：
  1. 候选地址：原 url → 同 id 的 media/*.png|jpg|webp → 各地址的 ghfast 镜像
  2. 下载后校验文件头（RIFF/PNG/JPEG/GIF），不是图片就换下一个
  3. ffmpeg 解码失败时换更保守的参数（format=rgb24 / 单帧）
"""
import base64
import json
import os
import re
import subprocess
import time
import urllib.request

STICKERS = '/opt/qq-agent/data/stickers.json'
CFG = '/opt/qq-agent/data/config.json'
api = json.load(open(CFG, encoding='utf-8'))['api']
KEY, BASE, MODEL = api['apiKey'], api['baseUrl'].rstrip('/'), api['model']
BLIND = re.compile(r'^鲸鱼娘表情 \d+$')
PROMPT = ('这是一张 QQ 聊天用的表情包（卡通鲸鱼娘）。用不超过 12 个字描述它的情绪或动作，'
          '只输出描述本身，不要编号、不要标点、不要解释。')

GH = 'https://ghfast.top/https://raw.githubusercontent.com/EDMOK/blue-fish-archive/main/'
CDN = 'https://cdn.jsdelivr.net/gh/EDMOK/blue-fish-archive@main/'


def candidates(entry):
    url = entry['url']
    stem = os.path.splitext(url)[1]
    name = url.rsplit('/', 1)[-1]
    base = os.path.splitext(name)[0]
    raw = []
    for dirname in ('large', 'media'):
        for ext in (stem, '.png', '.jpg', '.jpeg', '.webp'):
            for prefix in (CDN, GH):
                raw.append(f'{prefix}{dirname}/{base}{ext}')
    seen = set()
    out = []
    for u in raw:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_image(buf):
    return (buf[:4] == b'RIFF' or buf[:4] == b'\x89PNG' or buf[:3] == b'\xff\xd8\xff'
            or buf[:4] == b'GIF8' or buf[:4] == b'<svg' or buf[:5] == b'<?xml')


def try_download(entry):
    for url in candidates(entry):
        try:
            buf = urllib.request.urlopen(url, timeout=40).read()
            if len(buf) > 800 and is_image(buf):
                p = '/tmp/fin_in.bin'
                open(p, 'wb').write(buf)
                return p, url
        except Exception:
            continue
    return None, None


def convert(src):
    for vf in ("scale='min(480,iw)':-2,format=rgb24", "format=rgb24", "scale=320:-2"):
        try:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', src,
                            '-vf', vf, '-frames:v', '1', '-q:v', '6', '/tmp/fin_out.jpg'],
                           check=True, timeout=60)
            return '/tmp/fin_out.jpg'
        except Exception:
            continue
    return None


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
    text = (d['choices'][0]['message'].get('content') or '').strip()
    return re.sub(r'[\s"“”「」（）()。，,、；;：:！!？?]', '', text)[:16]


def main():
    data = json.load(open(STICKERS, encoding='utf-8'))
    left = [e for e in data if BLIND.match(str(e.get('desc') or ''))]
    print(f'剩余 {len(left)} 张', flush=True)
    ok = fail = 0
    for e in left:
        src, used = try_download(e)
        if not src:
            print(f'  下载全失败 {e["id"][:16]}', flush=True); fail += 1; continue
        jpg = convert(src)
        if not jpg:
            print(f'  解码失败 {e["id"][:16]} ({used.split("/")[-1]})', flush=True); fail += 1; continue
        try:
            cap = caption(jpg)
        except Exception as ex:
            print(f'  标注失败 {e["id"][:16]}: {ex}', flush=True); fail += 1; continue
        if not cap:
            print(f'  空描述 {e["id"][:16]}', flush=True); fail += 1; continue
        e['desc'] = cap
        tags = list(e.get('tags') or [])
        if '自动标注' not in tags:
            tags.append('自动标注')
        e['tags'] = tags
        print(f'  ✓ {cap}  ({e["id"][:14]})', flush=True)
        ok += 1
        time.sleep(0.5)
    json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    remain = len([x for x in data if BLIND.match(str(x.get('desc') or ''))])
    print(f'完成：本补齐 {ok}，失败 {fail}，仍未标注 {remain}', flush=True)


if __name__ == '__main__':
    main()
