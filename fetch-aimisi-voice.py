#!/usr/bin/env python3
"""从 B站下载爱弥斯干声素材，切一段适合做 IndexTTS 参考的音频。

输出：/tmp/aimisi/aimisi_ref.wav（10 秒左右、单声道、干净人声）
"""
import io
import json
import subprocess
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BVID = 'BV1xDFQzgE1J'
CFG = '/opt/qq-agent/data/config.json'
OUT = '/tmp/aimisi/aimisi_ref.wav'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'


def main():
    cfg = json.load(open(CFG, encoding='utf-8'))
    cookie = (cfg.get('bili') or {}).get('cookie') or ''
    h = {'User-Agent': UA, 'Referer': 'https://www.bilibili.com/', 'Cookie': cookie}

    def get(url):
        req = urllib.request.Request(url, headers=h)
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())

    v = get(f'https://api.bilibili.com/x/web-interface/view?bvid={BVID}')
    if v.get('code') != 0:
        raise SystemExit('view 失败: ' + str(v.get('message')))
    d = v['data']
    print('视频:', d['title'], '| 时长', d['duration'], '秒')

    p = get(f"https://api.bilibili.com/x/player/playurl?bvid={BVID}&cid={d['cid']}&fnval=16&fourk=1")
    if p.get('code') != 0:
        raise SystemExit('playurl 失败: ' + str(p.get('message')))
    dash = (p.get('data') or {}).get('dash') or {}
    audios = dash.get('audio') or []
    if not audios:
        # 兜底：durl
        durl = ((p.get('data') or {}).get('durl') or [{}])[0]
        url = durl.get('url')
    else:
        best = sorted(audios, key=lambda a: a.get('bandwidth') or 0)[-1]
        url = best.get('baseUrl') or best.get('base_url')
    if not url:
        raise SystemExit('拿不到音频地址')
    print('音频流:', url[:80], '…')

    import os
    os.makedirs('/tmp/aimisi', exist_ok=True)
    raw = '/tmp/aimisi/audio.m4s'
    # 带 Referer 下载（B站 CDN 必须）
    subprocess.run(['curl', '-sS', '-L', '-m', '300', '-A', UA,
                    '-e', 'https://www.bilibili.com/',
                    '-b', cookie,
                    '-o', raw, url], check=True)
    size = os.path.getsize(raw)
    print(f'下载完成 {size/1048576:.1f} MB')
    if size < 100000:
        raise SystemExit('下载内容太小，可能被拒')

    # 切 12 秒（从头 20 秒开始，避开开场空白/招呼）
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-ss', '20', '-t', '12',
                    '-i', raw, '-vn', '-ac', '1', '-ar', '24000', OUT], check=True)
    out_size = os.path.getsize(OUT)
    print(f'已切出参考音频: {OUT}（{out_size/1024:.0f} KB）')
    dur = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'csv=p=0', OUT], capture_output=True, text=True).stdout.strip()
    print('时长:', dur, '秒')


if __name__ == '__main__':
    main()
