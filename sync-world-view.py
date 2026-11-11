#!/usr/bin/env python3
"""把 DSH 的 B站人格札记接给小鲸鱼。

链路：
  ~/.dsh/bili-humanism/human-world.md   （DSH 侧，插件写入）
        ↓ 本脚本取最近若干条「日期 + 反思」，压成 ≤380 字
  服务器 /opt/qq-agent/data/world-view.md
        ↓ prompt.js 每次运行时读入【世界观察】
  小鲸鱼在 QQ 里的说话方式（只是背景，不是每句都念）
"""
import io
import os
import re
import subprocess
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SRC = os.path.expanduser('~/.dsh/bili-humanism/human-world.md')
SSH_KEY = r'D:\dshworks\qqbot\ssh\id_ed25519'
KNOWN = r'D:/dshworks/qqbot/ssh/known_hosts'
HOST = 'admin@116.62.149.191'
REMOTE = '/opt/qq-agent/data/world-view.md'
MAX_CHARS = 380
KEEP = 6


def parse_entries(text):
    """只取「日期 + 引用反思」：## YYYY-MM-DD 下面以 > 开头的句子。"""
    entries = []
    cur_date = ''
    for line in text.splitlines():
        line = line.rstrip()
        m = re.match(r'^##\s*(\d{4}-\d{2}-\d{2})', line)
        if m:
            cur_date = m.group(1)
            continue
        if line.startswith('>'):
            body = line.lstrip('> ').strip()
            if body:
                entries.append((cur_date, body))
    return entries


def build_digest(entries, keep=KEEP, max_chars=MAX_CHARS):
    picked = entries[-keep:]
    lines = []
    for date, body in picked:
        one = re.sub(r'\s+', ' ', body).strip()
        lines.append('· ' + ((date + '：') if date else '') + one)
    text = '\n'.join(lines)
    while len(text) > max_chars and len(lines) > 1:
        lines.pop(0)
        text = '\n'.join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + '…'
    return text.strip()


def main():
    if not os.path.exists(SRC):
        raise SystemExit('找不到人格札记：' + SRC)
    entries = parse_entries(open(SRC, encoding='utf-8').read())
    print('读到 %d 条人格札记' % len(entries))
    if not entries:
        raise SystemExit('札记里还没有条目（先在 DSH 里 select 一句）')
    digest = build_digest(entries)
    print('压缩后（%d 字）：\n%s' % (len(digest), digest))

    tmp = os.path.join(os.environ.get('TEMP', '.'), 'world-view.md')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(digest + '\n')

    scp = subprocess.run(
        ['scp', '-i', SSH_KEY, '-o', 'StrictHostKeyChecking=accept-new',
         '-o', 'UserKnownHostsFile=' + KNOWN, tmp, HOST + ':/tmp/world-view.md'],
        capture_output=True, text=True)
    if scp.returncode != 0:
        raise SystemExit('scp 失败: ' + scp.stderr[:200])

    mv = subprocess.run(
        ['ssh', '-i', SSH_KEY, '-o', 'StrictHostKeyChecking=accept-new',
         '-o', 'UserKnownHostsFile=' + KNOWN, HOST,
         'sudo cp /tmp/world-view.md ' + REMOTE + ' && sudo chmod 644 ' + REMOTE + ' && wc -c < ' + REMOTE],
        capture_output=True, text=True)
    print('服务器写入：', (mv.stdout or mv.stderr).strip())
    if mv.returncode != 0:
        raise SystemExit('远端写入失败')


if __name__ == '__main__':
    main()
