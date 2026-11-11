#!/usr/bin/env python3
"""修复 B站字幕接口：加 WBI 签名 + 归属校验 + 多接口回退。

改 tools.js：
1) 新增 WBI 签名工具（nav 取 img_key/sub_key → mixinKey → md5）
2) 字幕请求改为 ondemand 签名，依次尝试 wbi(签名) → wbi(无签名) → player/v2
3) 每条字幕必须校验 URL 含 "aid+cid"，否则丢弃（防止串到别人的字幕）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ---------- 1) 插入 WBI 签名工具 ----------
anchor = "async function biliGet(url, { sessdata = '', cookie = '' } = {}) {"
assert s.count(anchor) == 1, 'biliGet 锚点不符'

WBI = r'''// ---------- B站 WBI 签名（字幕接口的正确姿势） ----------
// 未签名的 player/v2 对部分视频会返回**别的视频的字幕**（实测踩过），wbi 签名版才是准的。
const WBI_TAB = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
  33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
  26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
  20, 34, 44, 52
];
let _wbiKeys = { at: 0, img: '', sub: '' };

function md5Hex(str) {
  return createHash('md5').update(str, 'utf8').digest('hex');
}

async function biliWbiKeys({ sessdata = '', cookie = '' } = {}) {
  if (_wbiKeys.img && Date.now() - _wbiKeys.at < 6 * 3600 * 1000) return _wbiKeys;
  const nav = await biliGet('https://api.bilibili.com/x/web-interface/nav', { sessdata, cookie });
  const wbi = (nav?.data?.wbi_img) || {};
  const img = String(wbi.img_url || '').split('/').pop().split('.')[0];
  const sub = String(wbi.sub_url || '').split('/').pop().split('.')[0];
  if (!img || !sub) throw new Error('拿不到 WBI 密钥（nav 接口未返回 wbi_img）');
  _wbiKeys = { at: Date.now(), img, sub };
  return _wbiKeys;
}

async function biliWbiSign(params, { sessdata = '', cookie = '' } = {}) {
  const { img, sub } = await biliWbiKeys({ sessdata, cookie });
  const raw = img + sub;
  const mixin = WBI_TAB.map((i) => raw[i] || '').join('').slice(0, 32);
  const wts = Math.floor(Date.now() / 1000);
  const query = Object.keys(params)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(params[k]).replace(/[!'()*]/g, ''))}`)
    .join('&');
  const wRid = md5Hex(query + mixin + wts);
  return `${query}&w_rid=${wRid}&wts=${wts}`;
}

// 取某视频的字幕列表：签名接口优先，且只接受归属于本视频的 URL
async function biliFetchSubtitles(d, { sessdata = '', cookie = '' } = {}) {
  const expectKey = `${d.aid}${d.cid}`;
  const attempts = [];
  try {
    const q = await biliWbiSign({ bvid: d.bvid, cid: d.cid }, { sessdata, cookie });
    attempts.push(['wbi+sig', `https://api.bilibili.com/x/player/wbi/v2?${q}`]);
  } catch (e) {
    attempts.push(['wbi(无签名)', `https://api.bilibili.com/x/player/wbi/v2?bvid=${d.bvid}&cid=${d.cid}`]);
  }
  attempts.push(['player/v2', `https://api.bilibili.com/x/player/v2?aid=${d.aid}&cid=${d.cid}`]);

  const rejected = [];
  for (const [label, url] of attempts) {
    let player = null;
    try {
      player = await biliGet(url, { sessdata, cookie });
    } catch (e) {
      rejected.push(`${label}:请求失败`);
      continue;
    }
    if (player?.code !== 0) {
      rejected.push(`${label}:code=${player?.code}`);
      continue;
    }
    const subs = (((player.data || {}).subtitle || {}).subtitles) || [];
    // 归属校验：字幕 URL 里必含 aid+cid
    const ok = subs.filter((x) => String(x.subtitle_url || '').includes(expectKey));
    const bad = subs.filter((x) => !String(x.subtitle_url || '').includes(expectKey));
    if (bad.length) rejected.push(`${label}:丢弃 ${bad.length} 条不属于本视频的字幕`);
    if (ok.length) {
      const pick = ok.find((x) => /^ai-zh/i.test(String(x.lan || '')))
        || ok.find((x) => /^zh/i.test(String(x.lan || '')))
        || ok[0];
      return { pick, entries: ok, via: label, rejected };
    }
  }
  return { pick: null, entries: [], via: null, rejected };
}

'''
s = s.replace(anchor, WBI + anchor, 1)

# ---------- 2) 替换字幕抓取逻辑 ----------
start = s.index('          // 字幕接口有两个版本：非 wbi 版（player/v2）对部分视频会返回**别的视频的字幕**，')
end = s.index('          let subUrl = String(pick.subtitle_url || \'\');')
new_block = '''          // 字幕：走 biliFetchSubtitles（WBI 签名 + aid/cid 归属校验 + 多接口回退）
          const subRes = await biliFetchSubtitles(d, { sessdata, cookie: biliCookie });
          const pick = subRes.pick;
          const forceFrames = process.env.FORCE_FRAMES === '1';
          for (const msg of subRes.rejected) lines.push(`（字幕接口：${msg}）`);
          if (!pick || forceFrames) {
            lines.push(forceFrames
              ? '（强制抽帧模式）'
              : '（拿不到归属于本视频的字幕，改用抽帧看画面）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          lines.push(`字幕来源：${subRes.via}`);
'''
s = s[:start] + new_block + s[end:]

open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js 已加 WBI 签名 + 归属校验')
