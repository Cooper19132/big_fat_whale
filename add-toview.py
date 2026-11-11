#!/usr/bin/env python3
"""给 watch_video 加「稍后再看」：看完顺手加入 B站 稍后再看，超过 50 条自动清最早的。

接口：
  加入  POST /x/v2/history/toview/add   （aid + csrf）
  列表  GET  /x/v2/history/toview       （取 aid 列表）
  删除  POST /x/v2/history/toview/del   （aid + csrf，一次一个）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

HELPER = '''
/** 把看过的视频加入「稍后再看」（比观看历史更稳，不会被风控清掉）。 */
async function biliAddToview({ aid, cookie = '', sessdata = '' }) {
  const ck = cookie || `SESSDATA=${sessdata}`;
  const jct = (ck.match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!aid || !jct) return { ok: false, reason: '缺少 aid 或 bili_jct' };
  const headers = {
    'User-Agent': BILI_UA,
    'Content-Type': 'application/x-www-form-urlencoded',
    Referer: 'https://www.bilibili.com/',
    Cookie: ck
  };
  const body = new URLSearchParams({ aid: String(aid), csrf: jct }).toString();
  try {
    const res = await fetch('https://api.bilibili.com/x/v2/history/toview/add', {
      method: 'POST', headers, body, signal: AbortSignal.timeout(15000)
    });
    const j = await res.json();
    return { ok: j?.code === 0, code: j?.code, message: j?.message };
  } catch (e) {
    return { ok: false, reason: String(e?.message ?? e) };
  }
}

/** 稍后再看列表超过 limit 条时，从最早的开始删。 */
async function biliTrimToview(cookie = '', limit = 50) {
  const jct = (String(cookie).match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!jct) return { ok: false, reason: '缺少 bili_jct' };
  const headers = { 'User-Agent': BILI_UA, Referer: 'https://www.bilibili.com/', Cookie: cookie };
  try {
    const res = await fetch('https://api.bilibili.com/x/v2/history/toview', { headers, signal: AbortSignal.timeout(15000) });
    const j = await res.json();
    const list = ((j?.data || {}).list) || [];
    const extra = list.length - limit;
    if (extra <= 0) return { ok: true, removed: 0, count: list.length };
    let removed = 0;
    for (const item of list.slice(-extra)) {
      const body = new URLSearchParams({ aid: String(item.aid), csrf: jct }).toString();
      try {
        const r = await fetch('https://api.bilibili.com/x/v2/history/toview/del', {
          method: 'POST',
          headers: { 'User-Agent': BILI_UA, 'Content-Type': 'application/x-www-form-urlencoded', Referer: 'https://www.bilibili.com/', Cookie: cookie },
          body, signal: AbortSignal.timeout(15000)
        });
        const jj = await r.json();
        if (jj?.code === 0) removed += 1;
      } catch { /* 单条失败不影响其它 */ }
    }
    return { ok: true, removed, count: list.length };
  } catch (e) {
    return { ok: false, reason: String(e?.message ?? e) };
  }
}
'''

anchor = "async function biliReportPlayed("
assert s.count(anchor) == 1, 'biliReportPlayed 锚点不符'
# 插在 biliReportPlayed 的定义之前（注释块之后）
idx = s.index('/**\n * 播放上报')
s = s[:idx] + HELPER.strip() + '\n\n' + s[idx:]

# 在播放上报成功后，顺手加稍后再看 + 清理
old = """            try {
              const rep = await biliReportPlayed({
                aid: d.aid, bvid: d.bvid, cid: d.cid,
                sessdata, cookie: biliCookie || cookie
              });
              if (rep?.skipped) meta.push('历史：今天已上报过这条');
              else if (rep?.ok) meta.push('历史：已记入观看历史');
              else meta.push('历史：上报未成功（' + (rep?.reason || 'code ' + rep?.click) + '）');
            } catch (e) { meta.push('历史：上报异常 ' + (e?.message ?? e)); }"""
new = """            try {
              const rep = await biliReportPlayed({
                aid: d.aid, bvid: d.bvid, cid: d.cid,
                sessdata, cookie: biliCookie || cookie
              });
              if (rep?.skipped) meta.push('历史：今天已上报过这条');
              else if (rep?.ok) meta.push('历史：已记入观看历史');
              else meta.push('历史：上报未成功（' + (rep?.reason || 'code ' + rep?.click) + '）');
            } catch (e) { meta.push('历史：上报异常 ' + (e?.message ?? e)); }

            // 稍后再看：比历史稳，列表超过 50 条自动清最早的
            try {
              const tcv = await biliAddToview({ aid: d.aid, cookie: biliCookie || cookie, sessdata });
              if (tcv?.ok) {
                const trim = await biliTrimToview(biliCookie || cookie, 50);
                meta.push('稍后再看：已加入' + (trim?.removed ? '（清理了 ' + trim.removed + ' 条旧的）' : ''));
              } else {
                meta.push('稍后再看：加入未成功（' + (tcv?.reason || 'code ' + tcv?.code) + '）');
              }
            } catch (e) { meta.push('稍后再看：异常 ' + (e?.message ?? e)); }"""
assert s.count(old) == 1, '上报段落锚点不符'
s = s.replace(old, new, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ watch_video: 加「稍后再看」+ 超 50 条自动清理')
