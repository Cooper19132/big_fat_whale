#!/usr/bin/env python3
"""下载 B站视频（低清）并切出若干样本段，用于 video-watch-plus 分析。

用法：python grab_bili.py BV号 起始1-结束1 起始2-结束2 ...
      python grab_bili.py BV1BTJb6fE6y 0-180 600-780
"""
import io
import json
import os
import subprocess
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CFG = '/opt/qq-agent/data/config.json'
OUTDIR = '/tmp/vwclip'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def main():
    bvid = sys.argv[1]
    ranges = sys.argv[2:] or ['0-180']
    cfg = json.load(open(CFG, encoding='utf-8'))
    cookie = (cfg.get('bili') or {}).get('cookie') or ''
    h = {'User-Agent': UA, 'Referer': 'https://www.bilibili.com/', 'Cookie': cookie}

    def get(url):
        return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30).read().decode())

    v = get(f'https://api.bilibili.com/x/web-interface/view?bvid={bvid}')
    if v.get('code') != 0:
        raise SystemExit('view 失败: ' + str(v.get('message')))
    d = v['data']
    dur = d['duration']
    print(f"视频: {d['title']} | {dur//60}分{dur%60}秒")

    # qn=16 是 360p，体积小
    p = get(f"https://api.bilibili.com/x/player/playurl?bvid={bvid}&cid={d['cid']}&qn=16&fnval=0&fourk=0")
    if p.get('code') != 0:
        raise SystemExit('playurl 失败: ' + str(p.get('message')))
    durl = ((p.get('data') or {}).get('durl') or [{}])[0]
    url = durl.get('url')
    size_mb = round((durl.get('size') or 0) / 1048576)
    if not url:
        raise SystemExit('拿不到播放地址')
    print(f'360p 直链，约 {size_mb} MB')

    os.makedirs(OUTDIR, exist_ok=True)
    raw = os.path.join(OUTDIR, f'{bvid}_360p.mp4')
    if not (os.path.exists(raw) and os.path.getsize(raw) > 1048576):
        print('下载中…')
        subprocess.run(['curl', '-sS', '-L', '-m', '1800', '-A', UA,
                        '-e', 'https://www.bilibili.com/', '-b', cookie,
                        '-o', raw, url], check=True)
    print(f'已下载 {os.path.getsize(raw)/1048576:.1f} MB')

    for rng in ranges:
        a, b = rng.split('-')
        out = os.path.join(OUTDIR, f'{bvid}_{a}-{b}.mp4')
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', a, '-to', b,
                        '-i', raw, '-c', 'copy', out], check=True)
        print(f'切出 {out}（{os.path.getsize(out)/1048576:.1f} MB）')


if __name__ == '__main__':
    main()
