#!/usr/bin/env python3
"""导入「大肥鱼表情包」到她的表情库：按 manifest 的分类自动打场景标签。

- 下载整包 tarball（ghfast 加速，失败回退 codeload）
- 只保留通用情绪分类，跳过股票/原神/鸣潮梗这类小众梗（会出现在不合时宜的场合）
- 文件落到 data/stickers/<id>.<ext>，stickers.json 追加条目（带场景 tags）
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

DATA = '/opt/qq-agent/data'
STICKERS = f'{DATA}/stickers.json'
STICKER_DIR = f'{DATA}/stickers'
WORK = '/tmp/feiyu-pack'
REPO = 'shirachino/astrbot-deepseek-meme-pack'
UA = 'Mozilla/5.0'
MIRRORS = [
    f'https://ghfast.top/https://github.com/{REPO}/archive/refs/heads/main.tar.gz',
    f'https://codeload.github.com/{REPO}/tar.gz/refs/heads/main',
    f'https://gh-proxy.com/https://github.com/{REPO}/archive/refs/heads/main.tar.gz',
]

# 分类 → (中文标签, 场景关键词, 是否保留)
CATS = {
    'angry':     ('生气', '抱怨、批评、被反驳', True),
    'baka':      ('吐槽', '轻微责备、可爱型抱怨', True),
    'color':     ('暧昧', '社交暧昧，低频', True),
    'confused':  ('困惑', '需要澄清、听不懂', True),
    'cpu':       ('卡壳', '复杂问题、加载中', True),
    'fool':      ('自嘲', '小失误、缓和气氛', True),
    'givemoney': ('要饭', '白饭、token、报酬', True),
    'happy':     ('开心', '成功、庆祝、积极反馈', True),
    'like':      ('喜欢', '赞同、推荐、喜欢', True),
    'meow':      ('卖萌', '宠物、撒娇、安抚', True),
    'morning':   ('早安', '早上打招呼', True),
    'reply':     ('等回复', '提问后、需要确认', True),
    'sad':       ('难过', '歉意、安慰、坏消息', True),
    'see':       ('偷瞄', '围观、盯进度', True),
    'shy':       ('害羞', '被夸、隐私、告白', True),
    'sigh':      ('无奈', '无语、重复问题', True),
    'sleep':     ('睡觉', '熬夜、疲劳、休息', True),
    'surprised': ('惊讶', '意外、转折、发现', True),
    'work':      ('干活', '任务、进度汇报', True),
    '_laugh':    ('大笑', '忍不住笑、嘲弄', True),
    # 以下小众梗不导入
    '_red':      ('股票涨', '股票基金', False),
    '_green':    ('股票跌', '股票基金', False),
    '_stock':    ('股票', '股票基金', False),
    '_genshin':  ('原神', '原神梗', False),
    '\u200c_kg': ('库狗', '鸣潮梗', False),
    '_\u200clkll': ('库洛拉了', '鸣潮梗', False),
    '\u200c_lksl': ('库洛神了', '鸣潮梗', False),
}


def log(m):
    print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)


def download():
    os.makedirs(WORK, exist_ok=True)
    tgz = f'{WORK}/pack.tar.gz'
    if os.path.exists(tgz) and os.path.getsize(tgz) > 5 * 1024 * 1024:
        log(f'已存在 tarball {os.path.getsize(tgz)/1048576:.1f} MB')
        return tgz
    for url in MIRRORS:
        try:
            log(f'下载 {url[:60]}…')
            subprocess.run(['curl', '-L', '--retry', '2', '-m', '420', '-A', UA, '-o', tgz, url],
                           check=True, timeout=450)
            size = os.path.getsize(tgz)
            if size > 5 * 1024 * 1024:
                log(f'下载完成 {size/1048576:.1f} MB')
                return tgz
            log(f'文件太小（{size} B），换镜像')
        except Exception as e:
            log(f'失败: {e}')
    raise SystemExit('所有镜像都下载失败')


def main():
    tgz = download()
    root = None
    with tarfile.open(tgz) as t:
        names = t.getnames()
        root = names[0].split('/')[0]
        t.extractall(WORK)
    log(f'解压完成，根目录 {root}')

    data = json.load(open(STICKERS, encoding='utf-8'))
    exist = {e['id'] for e in data}
    shutil.copyfile(STICKERS, STICKERS + '.bak-feiyu-' + time.strftime('%H%M%S'))
    os.makedirs(STICKER_DIR, exist_ok=True)

    memes_dir = os.path.join(WORK, root, 'memes')
    added = skipped = 0
    by_cat = {}
    for cat in sorted(os.listdir(memes_dir)):
        info = CATS.get(cat) or CATS.get(cat.strip())
        if not info:
            log(f'未知分类 {cat!r}，跳过')
            continue
        label, scene, keep = info
        if not keep:
            continue
        catdir = os.path.join(memes_dir, cat)
        if not os.path.isdir(catdir):
            continue
        files = sorted(f for f in os.listdir(catdir) if not f.startswith('.'))
        n = 0
        for f in files:
            ext = f.rsplit('.', 1)[-1].lower()
            if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
                continue
            n += 1
            sid = f'fy-{cat.strip("_")}-{n:02d}'
            if sid in exist:
                skipped += 1
                continue
            src = os.path.join(catdir, f)
            dst = os.path.join(STICKER_DIR, f'{sid}.{ext}')
            shutil.copyfile(src, dst)
            data.append({
                'id': sid,
                'desc': f'{label}·{n:02d}',
                'tags': [cat.strip('_'), f'场景:{scene}', '大肥鱼', '表情包'],
                'url': f'https://cdn.jsdelivr.net/gh/{REPO}@main/memes/{cat}/{f}',
                'pack': 'feiyu',
                'scene': scene,
            })
            exist.add(sid)
            added += 1
        by_cat[label] = by_cat.get(label, 0) + n

    json.dump(data, open(STICKERS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'导入完成：新增 {added} 张，跳过 {skipped}，库总量 {len(data)}')
    log('分类统计: ' + ', '.join(f'{k}{v}' for k, v in by_cat.items()))


if __name__ == '__main__':
    main()
