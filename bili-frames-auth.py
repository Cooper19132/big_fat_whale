#!/usr/bin/env python3
"""修抽帧 403：B站 CDN 要求 Referer/UA/Cookie，改成带鉴权头下载到临时文件再抽帧。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

OLD = """    const dataUrls = await extractVideoFrames({ kind: 'url', value: play.url }, want);
    if (!dataUrls.length) {
      lines.push('（抽帧没成功）');
      return ok(lines.join('\\n'));
    }"""

NEW = """    // B站 CDN 要 Referer/UA/Cookie，裸 fetch 会 403
    const res = await fetch(play.url, {
      headers: {
        'User-Agent': BILI_UA,
        Referer: 'https://www.bilibili.com/',
        ...(creds.cookie ? { Cookie: creds.cookie } : {}),
      },
      signal: AbortSignal.timeout(120000),
    });
    if (!res.ok) throw new Error(`视频下载 HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    if (!buf.length) throw new Error('视频下载为空');
    if (buf.length > VIDEO_MAX_BYTES) throw new Error(`视频 ${Math.round(buf.length / 1048576)}MB 超过上限`);
    const tmpFile = path.join(os.tmpdir(), `bili-${d.bvid}-${Date.now()}.mp4`);
    fs.writeFileSync(tmpFile, buf);
    let dataUrls = [];
    try {
      dataUrls = await extractVideoFrames({ kind: 'file', value: tmpFile }, want);
    } finally {
      try { fs.unlinkSync(tmpFile); } catch { /* 忽略 */ }
    }
    if (!dataUrls.length) {
      lines.push('（抽帧没成功）');
      return ok(lines.join('\\n'));
    }"""

assert s.count(OLD) == 1, '抽帧调用锚点不符（%d 处）' % s.count(OLD)
s = s.replace(OLD, NEW, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 抽帧改为带鉴权头下载')
