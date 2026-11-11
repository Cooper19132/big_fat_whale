#!/usr/bin/env python3
"""让「肥鱼看过的视频」出现在她 B站 账号的观看历史里。

原因：watch_video 只调 view + playurl 下载，从不打播放上报，
所以 B站 侧历史永远是 0 条，小号那端自然看不到。

补两个上报（官方网页播放器就是这么打的）：
  POST /x/click-interface/click/web/h5      ← 开始播放
  POST /x/click-interface/web/heartbeat     ← 心跳，带 played_time

参数：aid / bvid / cid / mid / csrf(bili_jct) / played_time
去重：同一 bvid 同一天只报一次（data/bili-reported.json）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

HELPER = '''
/**
 * 播放上报：让 B站 把这次观看记进「观看历史」。
 * 不打这两个接口，账号侧的 history 永远是空的（2026-11-09 查实：历史 0 条）。
 * 同一视频同一天只上报一次，避免刷记录。
 */
async function biliReportPlayed({ aid, bvid, cid, sessdata = '', cookie = '' }) {
  if (!aid || !cid) return { ok: false, reason: '缺少 aid/cid' };
  const jct = (String(cookie).match(/bili_jct=([^;]+)/) || [])[1]
    || (String(sessdata).match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!jct) return { ok: false, reason: '缺少 bili_jct（无法上报）' };

  // 去重：同一 bvid 同一天只报一次
  const fsMod = await import('node:fs');
  const pathMod = await import('node:path');
  const { DATA_DIR } = await import('./config.js');
  const fs = fsMod.default || fsMod;
  const path = pathMod.default || pathMod;
  const statePath = path.join(DATA_DIR, 'bili-reported.json');
  let state = {};
  try { state = JSON.parse(fs.readFileSync(statePath, 'utf-8')); } catch { state = {}; }
  const day = new Date().toISOString().slice(0, 10);
  const key = String(bvid);
  if (state[key] === day) return { ok: true, skipped: true };

  const headers = {
    'User-Agent': BILI_UA,
    'Content-Type': 'application/x-www-form-urlencoded',
    Referer: `https://www.bilibili.com/video/${bvid}`,
    Cookie: cookie || `SESSDATA=${sessdata}`
  };
  const post = async (url, fields) => {
    const body = new URLSearchParams(fields).toString();
    const res = await fetch(url, { method: 'POST', headers, body, signal: AbortSignal.timeout(15000) });
    return res.json().catch(() => ({}));
  };

  const common = {
    aid, bvid, cid, mid: '', csrf: jct, jsonp: 'jsonp',
    'played_time': '0', 'realtime': '0', 'real_time': '0',
    'start_ts': String(Math.floor(Date.now() / 1000)), 'type': '3', 'sub_type': '0',
    'dt': '2', 'last_play_progress_time': '0', 'max_play_progress_time': '0',
    'outer': '0', 'spmid': '333.1007.0.0'
  };
  const r1 = await post('https://api.bilibili.com/x/click-interface/click/web/h5', common);
  // 心跳：played_time 报 300 秒（我们实际看的是前 5 分钟）
  const r2 = await post('https://api.bilibili.com/x/click-interface/web/heartbeat', {
    ...common, played_time: '300', realtime: '300', real_time: '300',
    last_play_progress_time: '300', max_play_progress_time: '300'
  });
  state[key] = day;
  try { fs.writeFileSync(statePath, JSON.stringify(state)); } catch { /* 忽略 */ }
  return { ok: r1?.code === 0 || r2?.code === 0, click: r1?.code, heartbeat: r2?.code };
}
'''

# 插到 biliPlayUrl 之前
anchor = "/** 取 B站视频的低清播放直链"
assert s.count(anchor) == 1, '锚点不符'
s = s.replace(anchor, HELPER.strip() + '\n\n' + anchor, 1)

# watch_video 里：拿到播放地址后上报
old = "            const play = await biliPlayUrl(d.bvid, d.cid, { sessdata, cookie: biliCookie });"
new = """            // 播放上报：让这次观看进入 B站 观看历史（否则小号/其他设备看不到她看过什么）
            try {
              const rep = await biliReportPlayed({
                aid: d.aid, bvid: d.bvid, cid: d.cid,
                sessdata, cookie: biliCookie || cookie
              });
              if (rep?.skipped) meta.push('历史：今天已上报过这条');
              else if (rep?.ok) meta.push('历史：已记入观看历史');
              else meta.push('历史：上报未成功（' + (rep?.reason || 'code ' + rep?.click) + '）');
            } catch (e) { meta.push('历史：上报异常 ' + (e?.message ?? e)); }

            const play = await biliPlayUrl(d.bvid, d.cid, { sessdata, cookie: biliCookie });"""
assert s.count(old) == 1, 'watch_video 播放段锚点不符'
s = s.replace(old, new, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ watch_video: 增加播放上报（进观看历史）')
