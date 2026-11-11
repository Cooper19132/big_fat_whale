#!/usr/bin/env python3
"""路线A：B站视频没有字幕时，自动抽帧看画面。

流程：playurl 拿低清直链 → 下载（限 40MB）→ ffmpeg 抽 8 帧 → 交给视觉模型。
有字幕时不抽帧（省流量），除非显式传 frames 参数。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ── 1) 新增 playurl 解析函数（放在 biliGet 之后） ──
anchor = "/** 生成一个 B站 batche 用的 buvid3（服务器 IP 常因缺它被 412）。 */"
assert s.count(anchor) == 1, 'buvid3 锚点不符'

helper = '''/** 取 B站视频的低清播放直链（无字幕时用来抽帧）。返回 { url, quality, sizeMb } 或 null。 */
async function biliPlayUrl(bvid, cid, { sessdata = '', cookie = '' } = {}) {
  // fnval=0 走 durl（mp4 直链），qn=32 是 480p，比 DASH 简单且省流量
  const api = `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=32&fnval=0&fourk=0`;
  const j = await biliGet(api, { sessdata, cookie });
  if (j.code !== 0 || !j.data) return null;
  const durl = (j.data.durl || [])[0];
  if (durl?.url) {
    return { url: durl.url, quality: j.data.quality || 0, sizeMb: Math.round((Number(durl.size) || 0) / 1048576) };
  }
  // 兜底：DASH 轨里挑码率最低的视频流
  const videos = (j.data.dash && j.data.dash.video) || [];
  if (!videos.length) return null;
  const best = videos.slice().sort((a, b) => (a.bandwidth || 0) - (b.bandwidth || 0))[0];
  const u = best.baseUrl || (best.base_url);
  return u ? { url: u, quality: best.id || 0, sizeMb: 0 } : null;
}

'''

s = s.replace(anchor, helper + anchor, 1)
print('✓ 新增 biliPlayUrl')

# ── 2) 工具参数加 frames ──
old_params = """        properties: { target: { type: 'string', description: 'BV 号（如 BV1d8pU6xEZX）或完整 B站链接' } },
        required: ['target']"""
assert s.count(old_params) == 1, '参数锚点不符'
new_params = """        properties: {
          target: { type: 'string', description: 'BV 号（如 BV1d8pU6xEZX）或完整 B站链接' },
          frames: { type: 'number', description: '可选：抽几帧看画面（默认 8；没有字幕时会自动抽，有字幕时默认不抽）' }
        },
        required: ['target']"""
s = s.replace(old_params, new_params, 1)
print('✓ 参数加 frames')

# ── 3) 无字幕时自动抽帧 ──
old_nosub = """          if (!pick) {
            lines.push('（这个视频没有可用字幕）');
            return ok(lines.join('\\n'));
          }"""
assert s.count(old_nosub) == 1, '无字幕分支锚点不符'
new_nosub = """          if (!pick) {
            lines.push('（这个视频没有可用字幕，改用抽帧看画面）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }"""
s = s.replace(old_nosub, new_nosub, 1)
print('✓ 无字幕时自动抽帧')

# ── 4) 新增抽帧执行函数（放在工具数组之前，供两处调用） ──
anchor2 = "export function buildToolDefs() {"
assert s.count(anchor2) == 1, 'buildToolDefs 锚点不符'
frames_fn = '''/** 下载 B站视频并抽帧，返回 imageParts（带元信息文本）。失败时退回纯文本。 */
async function biliFramesResult(d, lines, args, creds) {
  const want = Math.max(3, Math.min(16, Number(args?.frames) || 8));
  try {
    const play = await biliPlayUrl(d.bvid, d.cid, creds);
    if (!play?.url) {
      lines.push('（拿不到播放地址，只能提供上面的元信息）');
      return ok(lines.join('\\n'));
    }
    if (play.sizeMb > 40) {
      lines.push(`（视频约 ${play.sizeMb}MB，超过抽帧上限，跳过了）`);
      return ok(lines.join('\\n'));
    }
    const dataUrls = await extractVideoFrames({ kind: 'url', value: play.url }, want);
    if (!dataUrls.length) {
      lines.push('（抽帧没成功）');
      return ok(lines.join('\\n'));
    }
    const head = lines.join('\\n') + `\\n（以上是文字信息；下面 ${dataUrls.length} 张是按时间顺序抽的画面帧，` +
      '只能看出画面里有什么，听不到说话内容，别当成完整内容。）';
    return { content: imageParts(head, dataUrls) };
  } catch (error) {
    lines.push(`（抽帧失败：${error?.message ?? error}）`);
    return ok(lines.join('\\n'));
  }
}

'''
s = s.replace(anchor2, frames_fn + anchor2, 1)
print('✓ 新增 biliFramesResult')

open(P, 'w', encoding='utf-8').write(s)
