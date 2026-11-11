#!/usr/bin/env python3
"""给小鲸鱼加「自己刷视频」的能力：
  1) 新工具 search_video —— B站搜索，她可以自己挑片子看
  2) 定时任务支持 interval —— 每 N 小时给一次「想刷就刷」的机会
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'search_video',
      timeoutMs: 60000,
      description: '搜视频：按关键词在 B站 搜视频，返回标题 / BV号 / 播放量 / 时长 / UP主。自己闲着想刷视频、或者别人说"找个讲XX的视频"时用它，挑一个再用 watch_video 看（传 BV 号）。',
      parameters: {
        type: 'object',
        properties: {
          keyword: { type: 'string', description: '搜什么，比如「中世纪 历史 纪录片」「编程 技术 讲解」' },
          count: { type: 'number', description: '返回几条（默认 6，最多 10）' },
          order: { type: 'string', description: '排序：totalrank=综合（默认）/ click=播放多 / pubdate=最新 / dm=弹幕多' }
        },
        required: ['keyword']
      },
      async execute(ctx, args) {
        const kw = String(args.keyword || '').trim();
        if (!kw) return err('要搜什么视频呀？给我关键词');
        const want = Math.max(3, Math.min(10, Number(args.count) || 6));
        const order = ['totalrank', 'click', 'pubdate', 'dm'].includes(String(args.order))
          ? String(args.order) : 'totalrank';
        const sessdata = String(getConfig().bili?.sessdata || '').trim();
        const cookie = String(getConfig().bili?.cookie || '').trim();
        let j;
        try {
          const q = await biliWbiSign(
            { search_type: 'video', keyword: kw, order, page: 1, page_size: want },
            { sessdata, cookie }
          );
          j = await biliGet(`https://api.bilibili.com/x/web-interface/wbi/search/type?${q}`, { sessdata, cookie });
        } catch (e) {
          // WBI 失败就退回老接口（有时还能用）
          try {
            const qs = new URLSearchParams({ search_type: 'video', keyword: kw, order, page: '1', page_size: String(want) });
            j = await biliGet(`https://api.bilibili.com/x/web-interface/search/type?${qs}`, { sessdata, cookie });
          } catch (e2) {
            return err(`搜视频失败：${e2?.message ?? e2}`);
          }
        }
        const list = j?.data?.result || [];
        if (!list.length) return ok(`没搜到「${kw}」的视频，换个词试试。`);
        const items = list.filter((x) => x.bvid).slice(0, want).map((x) => ({
          bvid: x.bvid,
          title: String(x.title || '').replace(/<[^>]+>/g, ''),
          up: String(x.author || ''),
          play: Number(x.play) || 0,
          dur: String(x.duration || ''),
          pub: Number(x.pubdate) ? new Date(Number(x.pubdate) * 1000).toISOString().slice(0, 10) : ''
        }));
        const lines = items.map((x, i) =>
          `${i + 1}. ${x.title}\n   ${x.bvid} | ${x.up} | 播放 ${x.play} | ${x.dur}${x.pub ? ' | ' + x.pub : ''}`);
        return ok({
          keyword: kw,
          count: items.length,
          videos: items,
          note: `挑一个用 watch_video(target="BV号") 看。列表：\n${lines.join('\n')}`
        });
      }
    },
'''

anchor = "    {\n      name: 'check_usage',"
assert s.count(anchor) == 1, 'check_usage 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js: 新增 search_video')

# ── 定时任务支持 interval ─────────────────────────────────
P2 = r'D:\dshworks\qqbot\qq-agent\src\scheduled-tasks.js'
s2 = open(P2, encoding='utf-8').read()

old_new = """export function addTask({ chatKey, text, at, repeat = 'none', kind = 'reminder', meta = {} }) {"""
new_new = """export function addTask({ chatKey, text, at, repeat = 'none', kind = 'reminder', meta = {} }) {
  // repeat 支持：none | daily | weekly | interval（配合 meta.everyMinutes 与 meta.hours）"""
assert s2.count(old_new) == 1, 'addTask 锚点不符'
s2 = s2.replace(old_new, new_new, 1)

old_rep = "    repeat: ['none', 'daily', 'weekly'].includes(repeat) ? repeat : 'none',"
new_rep = "    repeat: ['none', 'daily', 'weekly', 'interval'].includes(repeat) ? repeat : 'none',"
assert s2.count(old_rep) == 1, 'repeat 校验锚点不符'
s2 = s2.replace(old_rep, new_rep, 1)
open(P2, 'w', encoding='utf-8').write(s2)
print('✓ scheduled-tasks.js: 允许 repeat=interval')
