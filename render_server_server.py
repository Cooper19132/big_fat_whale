#!/usr/bin/env python3
"""网页渲染服务（服务器侧，9903）：把需要 JS 的页面渲染成正文。

历史：
  最初跑在主人电脑上（复用 hyperframes 的 chrome-headless-shell），
  经 ssh 反向隧道给机器人用。2026-10-29 迁到服务器（装了 google-chrome），
  好处：主人关机也能读网页，少一条隧道端口。

接口：
  GET  /health                 → {"ok":true,"chrome":"/usr/bin/google-chrome"}
  POST /render {"url":"..."}   → {"ok":true,"title","text","chars","costSec"}
  GET  /render?url=...         同上（便于 curl 调试）

实现要点：
  · --dump-dom 拿渲染后 DOM，再用正则抽正文（不引第三方解析库）
  · 串行渲染（互斥锁）：单次约 300~400MB，服务器只有 1.6G，必须排队
  · 超时 60 秒；--virtual-time-budget 控制等待 JS 的时间
"""
import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 9903
CHROME = '/usr/bin/google-chrome'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')
MAX_CHARS = 20000
LOG = '/opt/qq-agent/data/render.log'
_lock = threading.Lock()


def log(msg):
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{time.strftime("%Y-%m-%d %H:%M:%S")}] {msg}\n')
    except Exception:
        pass


def extract(html):
    s = html
    s = re.sub(r'<!--[\s\S]*?-->', ' ', s)
    for tag in ('script', 'style', 'noscript', 'svg', 'iframe', 'template',
                'nav', 'header', 'footer', 'aside', 'form'):
        s = re.sub(rf'<{tag}[\s\S]*?</{tag}>', ' ', s, flags=re.I)
    m = re.search(r'<body[^>]*>([\s\S]*)</body>', s, re.I)
    if m:
        s = m.group(1)
    s = re.sub(r'<br\s*/?>', '\n', s, flags=re.I)
    s = re.sub(r'</(p|div|section|article|li|tr|h[1-6]|blockquote|pre|td|dd|dt)>', '\n', s, flags=re.I)
    s = re.sub(r'<li[^>]*>', '\n· ', s, flags=re.I)
    s = re.sub(r'<h[1-6][^>]*>', '\n\n', s, flags=re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    for a, b in (('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"'),
                 ('&#39;', "'"), ('&ldquo;', '“'), ('&rdquo;', '”'), ('&hellip;', '…'),
                 ('&mdash;', '—'), ('&middot;', '·')):
        s = s.replace(a, b)
    s = re.sub(r'&#x([0-9a-f]+);', lambda m: chr(int(m.group(1), 16)), s, flags=re.I)
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    lines = [re.sub(r'[ \t\u00a0]+', ' ', ln).strip() for ln in s.split('\n')]
    lines = [ln for ln in lines if ln]
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)).strip()


def title_of(html):
    m = re.search(r'<title[^>]*>([\s\S]*?)</title>', html, re.I)
    return re.sub(r'\s+', ' ', m.group(1)).strip() if m else ''


def render(url, budget_ms=15000):
    if not re.match(r'^https?://', url or ''):
        return {'ok': False, 'error': 'url 必须是 http(s)'}
    if not os.path.isfile(CHROME):
        return {'ok': False, 'error': f'找不到 chrome: {CHROME}'}
    with _lock:
        t0 = time.time()
        try:
            out = subprocess.run(
                [CHROME, '--headless=new', '--no-sandbox', '--disable-gpu',
                 '--disable-dev-shm-usage', '--hide-scrollbars', '--mute-audio',
                 f'--virtual-time-budget={budget_ms}', f'--user-agent={UA}',
                 '--dump-dom', url],
                capture_output=True, timeout=60
            )
            html = out.stdout.decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': '渲染超时（60 秒）'}
        except Exception as e:
            return {'ok': False, 'error': f'渲染失败: {e}'}
        cost = round(time.time() - t0, 1)
        if not html.strip():
            return {'ok': False, 'error': '渲染结果为空'}
        text = extract(html)[:MAX_CHARS]
        log(f'{url[:70]} → {len(text)} 字 / {cost}s')
        return {'ok': True, 'url': url, 'title': title_of(html), 'text': text,
                'chars': len(text), 'costSec': cost}


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == '/health':
            return self._json(200, {'ok': True, 'chrome': CHROME, 'exists': os.path.isfile(CHROME)})
        if u.path == '/render':
            q = urllib.parse.parse_qs(u.query)
            return self._json(200, render((q.get('url') or [''])[0]))
        return self._json(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != '/render':
            return self._json(404, {'ok': False, 'error': 'not found'})
        try:
            n = int(self.headers.get('Content-Length') or 0)
            payload = json.loads(self.rfile.read(n).decode('utf-8') or '{}') if n else {}
        except Exception:
            payload = {}
        return self._json(200, render(str(payload.get('url') or '')))


def main():
    log(f'渲染服务启动 :{PORT} chrome={CHROME}')
    print(f'[render] http://127.0.0.1:{PORT}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
