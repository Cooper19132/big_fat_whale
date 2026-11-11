#!/usr/bin/env python3
"""给小鲸鱼接「梗百科」：本地词库 6668 条，查梗不联网。

来源：thawline/dsh-memewiki（DSH 插件，MIT）词库由 cnmeme.wiki 整理。
这里把 SQLite 导出成 JSON，给 qq-agent 加一个 search_meme_wiki 工具。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'search_meme_wiki',
      timeoutMs: 15000,
      description: '查网络梗/黑话/缩写的含义。内置 6668 条本地词库，毫秒级返回，不联网。群友说了一个你没把握的新词（缩写、梗、黑话）时先查它，别硬猜、别编解释。查到就直接接梗，不要科普；只有对方明确问"这是什么梗"才解释一两句。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '要查的词（梗名、缩写、黑话）' }
        },
        required: ['query']
      },
      async execute(ctx, args) {
        const q = String(args.query || '').trim();
        if (!q) return err('要查哪个词？');
        try {
          const memes = await loadMemes();
          if (!memes.length) return err('梗词库没加载成功（data/memes.json 缺失）');
          const low = q.toLowerCase();
          const hits = [];
          // ① 精确
          for (const m of memes) {
            if (m.t.toLowerCase() === low) { hits.push({ m, score: 100 }); }
          }
          // ② 标题包含查询词 / 查询词包含标题
          if (hits.length === 0) {
            for (const m of memes) {
              const t = m.t.toLowerCase();
              if (t.includes(low)) hits.push({ m, score: 80 - Math.abs(t.length - low.length) });
              else if (low.length >= 2 && low.includes(t)) hits.push({ m, score: 60 - Math.abs(low.length - t.length) });
            }
          }
          if (hits.length === 0) return ok(`词库里没有「${q}」。不知道就说不知道，别编解释。`);
          hits.sort((a, b) => b.score - a.score);
          const top = hits.slice(0, 2).map((h) => ({
            title: h.m.t,
            tags: h.m.g || undefined,
            howToUse: (h.m.u || '').slice(0, 400) || undefined,
            summary: (h.m.s || '').slice(0, 260) || undefined
          }));
          return ok({
            query: q,
            found: top.length,
            entries: top,
            note: '查到就先接梗，别科普；对方明确问"这什么梗"才解释一两句。'
          });
        } catch (e) {
          return err(`查梗失败：${e?.message ?? e}`);
        }
      }
    },
'''

anchor = "    {\n      name: 'check_usage',"
assert s.count(anchor) == 1, 'check_usage 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)

# 加懒加载函数（放在 parseBiliTarget 之前）
anchor2 = "function parseBiliTarget(input) {"
loader = '''/** 梗词库（懒加载，12MB 只在第一次查时读一次，进程内缓存） */
let MEMES_CACHE = null;
async function loadMemes() {
  if (MEMES_CACHE) return MEMES_CACHE;
  try {
    const fsMod = await import('node:fs');
    const pathMod = await import('node:path');
    const { DATA_DIR } = await import('./config.js');
    const fs = fsMod.default || fsMod;
    const path = pathMod.default || pathMod;
    const p = path.join(DATA_DIR, 'memes.json');
    if (!fs.existsSync(p)) return (MEMES_CACHE = []);
    MEMES_CACHE = JSON.parse(fs.readFileSync(p, 'utf-8'));
    return MEMES_CACHE;
  } catch {
    return (MEMES_CACHE = []);
  }
}

''' + anchor2
assert s.count(anchor2) == 1, 'parseBiliTarget 锚点不符'
s = s.replace(anchor2, loader, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js: 新增 search_meme_wiki（本地词库，懒加载）')
