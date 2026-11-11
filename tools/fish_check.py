#!/usr/bin/env python3
"""每周八股体检（服务器侧，cron 每周日 22:00）。

做什么：
  ① 用 fishtalk_lite 的骨架检测器扫她最近 7 天的发言
     - 口径一：按单条消息
     - 口径二：按「一次运行」（把同轮连发的几条拼起来，能抓到三件套组合）
  ② 只有出现 ✗（先别发）或 △（砍一处）才私聊主人，附上原文片段
  ③ 一切正常就不打扰，只写日志

用法：
  python3 fish_check.py            # 正常体检
  python3 fish_check.py --test     # 发一条测试通知，验证投递链路
  python3 fish_check.py --days 14  # 换统计窗口
"""
import glob
import io
import json
import os
import sys
import time
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from fishtalk_lite import analyze  # noqa: E402

MSG_DIR = '/opt/qq-agent/data/messages'
SESS_DIR = '/opt/qq-agent/data/sessions'
CONFIG = '/opt/qq-agent/data/config.json'
ONEBOT = 'http://127.0.0.1:3000'
LOG = '/var/log/qqbot-fishtalk.log'


def log(msg):
    line = f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def master_id():
    try:
        c = json.load(open(CONFIG, encoding='utf-8'))
        return str((c.get('persona') or {}).get('masterQQ') or '').strip()
    except Exception:
        return ''


def send_private(text):
    uid = master_id()
    if not uid:
        log('没有 masterQQ，通知发不出去')
        return False
    body = json.dumps({'user_id': int(uid), 'message': text, 'auto_escape': False}).encode()
    req = urllib.request.Request(f'{ONEBOT}/send_private_msg', data=body,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            ok = json.loads(r.read().decode('utf-8')).get('status') == 'ok'
        log(f'通知已发送（{uid}）: {ok}')
        return ok
    except Exception as e:
        log(f'通知发送失败: {e}')
        return False


def collect_messages(days):
    cut = time.time() - days * 86400
    out = []
    for f in glob.glob(os.path.join(MSG_DIR, '*.json')):
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        msgs = d if isinstance(d, list) else d.get('messages', [])
        for m in msgs:
            if not m.get('self') or (m.get('ts') or 0) / 1000 < cut:
                continue
            t = str(m.get('text') or '').strip()
            if t and not t.startswith('[图片]'):
                out.append(t)
    return out


def collect_runs(days):
    cut = time.time() - days * 86400
    runs = []
    for f in glob.glob(os.path.join(SESS_DIR, '*.json')):
        if os.path.getmtime(f) < cut:
            continue
        try:
            d = json.load(open(f, encoding='utf-8'))
        except Exception:
            continue
        texts = []
        for m in d.get('messages') or []:
            for tc in (m.get('tool_calls') or []):
                fn = tc.get('function') or {}
                if fn.get('name') != 'send_message':
                    continue
                try:
                    a = json.loads(fn.get('arguments') or '{}')
                except Exception:
                    continue
                v = a.get('messages') or a.get('text')
                if isinstance(v, list):
                    texts.extend(str(x) for x in v)
                elif v:
                    texts.append(str(v))
        if texts:
            runs.append((os.path.getmtime(f), d.get('chatKey'), texts))
    return runs


def main():
    test = '--test' in sys.argv
    days = 7
    if '--days' in sys.argv:
        try:
            days = max(1, min(60, int(sys.argv[sys.argv.index('--days') + 1])))
        except Exception:
            pass

    if test:
        send_private('【八股体检·测试】这条是测试通知，收到说明链路通了。以后每周日 22:00 我会自动扫一遍她的发言，'
                     '只有出现「✗ 先别发 / △ 砍一处」才打扰你。')
        return

    msgs = collect_messages(days)
    runs = collect_runs(days)
    log(f'开始体检：{days} 天，单条 {len(msgs)} 条 / 运行 {len(runs)} 次')

    # 口径一：单条
    v1 = Counter()
    fam1 = Counter()
    bad1 = []
    for t in msgs:
        v, fams, pos, hits = analyze(t)
        v1[v] += 1
        for x in fams:
            fam1[x] += 1
        if v.startswith('✗') or v.startswith('△'):
            bad1.append((v, fams, t))

    # 口径二：按运行
    v2 = Counter()
    fam2 = Counter()
    bad2 = []
    for ts, chat, texts in runs:
        v, fams, pos, hits = analyze('\n'.join(texts))
        v2[v] += 1
        for x in fams:
            fam2[x] += 1
        if v.startswith('✗') or v.startswith('△'):
            bad2.append((ts, chat, v, fams, texts))

    def pct(c, n):
        return f'{c / n * 100:.1f}%' if n else '0%'

    summary = (f'单条 {len(msgs)} 条：✗{v1.get("✗ 先别发", 0)} / △{v1.get("△ 可以用，但砍掉一处", 0)}；'
               f'运行 {len(runs)} 次：✗{v2.get("✗ 先别发", 0)} / △{v2.get("△ 可以用，但砍掉一处", 0)}')
    log('结果：' + summary)
    log('单条命中家族：' + '，'.join(f'{k} {c}（{pct(c, len(msgs))}）' for k, c in fam1.most_common()) or '无')

    if not bad1 and not bad2:
        log('全部通过，不通知主人。')
        return

    lines = [f'【八股体检】最近 {days} 天', summary, '']
    if bad2:
        lines.append('按运行（连发几条拼起来）有问题：')
        for ts, chat, v, fams, texts in bad2[:3]:
            lines.append(f'· {time.strftime("%m-%d %H:%M", time.localtime(ts))} {chat} → {v}［{"+".join(fams)}］')
            lines.append('   ' + texts[0][:50])
    if bad1:
        lines.append('')
        lines.append('按单条有问题：')
        for v, fams, t in bad1[:3]:
            lines.append(f'· {v}［{"+".join(fams)}］{t[:50]}')
    lines.append('')
    lines.append('要不要我按这几条改人设？回一句就行。')
    send_private('\n'.join(lines))


if __name__ == '__main__':
    main()
