#!/usr/bin/env python3
"""排查：某条视频的字幕到底取到谁的。"""
import io
import json
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

CFG = '/opt/qq-agent/data/config.json'
cfg = json.load(open(CFG, encoding='utf-8'))
bili = cfg.get('bili') or {}
cookie = bili.get('cookie') or ''
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'


def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA,
                                               'Referer': 'https://www.bilibili.com/',
                                               'Cookie': cookie})
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode())


def main():
    for bv in sys.argv[1:] or ['BV1gLng6vE6j']:
        d = get('https://api.bilibili.com/x/web-interface/view?bvid=' + bv)
        if d.get('code') != 0:
            print(bv, 'view 失败:', d.get('message'))
            continue
        v = d['data']
        cid = v['cid']
        print('=' * 60)
        print(bv, '|', v['title'][:50])
        print('  aid', v['aid'], '| cid', cid, '| 时长', v['duration'], '秒')
        for label, url in (
            ('player/v2(wbi)', 'https://api.bilibili.com/x/player/wbi/v2?bvid=%s&cid=%s' % (bv, cid)),
            ('player/v2', 'https://api.bilibili.com/x/player/v2?bvid=%s&cid=%s' % (bv, cid)),
        ):
            try:
                p = get(url)
                subs = ((p.get('data') or {}).get('subtitle') or {})
                items = subs.get('subtitles') or []
                print('  [%s] code=%s 字幕 %d 条' % (label, p.get('code'), len(items)))
                for s in items[:5]:
                    print('     lan=%s url=%s' % (s.get('lan'), (s.get('subtitle_url') or '')[:90]))
            except Exception as e:
                print('  [%s] 异常: %s' % (label, e))


if __name__ == '__main__':
    main()
