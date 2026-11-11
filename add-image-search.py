#!/usr/bin/env python3
"""给小鲸鱼加自主搜图能力：search_image。

数据源：cn.bing.com/images/async（百度 acjson 已被封，实测 forbid）
用途：找到图片直链 → 交给 gpu_draw 的 reference 参数走图生图。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'search_image',
      description: '搜参考图：按关键词找到可用的图片直链。想画某个角色/场景/风格但手头没有参考图时，先用它搜，再把拿到的某个链接传给 gpu_draw 的 reference 参数，就能照着画。返回 3~8 条直链（已过滤死链）。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '搜什么图，中文英文都行，例如「鲸鱼娘 动漫」「赛博朋克 街道 夜景」' },
          count: { type: 'number', description: '要几条（默认 5，最多 8）' }
        },
        required: ['query']
      },
      async execute(ctx, args) {
        const q = String(args.query || '').trim();
        if (!q) return err('要搜什么图呀？给我关键词');
        const want = Math.max(3, Math.min(8, Number(args.count) || 5));
        const url = `https://cn.bing.com/images/async?q=${encodeURIComponent(q)}&first=0&count=${want * 4}&mmasync=1`;
        let html = '';
        try {
          const res = await fetch(url, {
            headers: {
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
              'Accept-Language': 'zh-CN,zh;q=0.9',
              Referer: 'https://cn.bing.com/images/search'
            },
            signal: AbortSignal.timeout(20000)
          });
          if (!res.ok) return err(`搜图请求失败 HTTP ${res.status}`);
          html = await res.text();
        } catch (e) {
          return err(`搜图失败：${e?.message ?? e}`);
        }

        // 从 murl&quot;:&quot;<url>&quot; 里抠图床直链
        const found = [];
        const re = /murl&quot;:&quot;([^&]+?)&quot;/g;
        let m;
        while ((m = re.exec(html)) !== null) {
          let u = m[1];
          try { u = decodeURIComponent(u); } catch { /* 保持原样 */ }
          u = u.replace(/\\u0026/g, '&');
          if (!/^https?:\/\//i.test(u)) continue;
          if (found.includes(u)) continue;
          found.push(u);
          if (found.length >= want * 3) break;
        }
        if (!found.length) return ok('没搜到可用图片，换个关键词试试（或直接用文字描述画）。');

        // 轻量校验：能被 fetch 到且不是 1x1 占位图
        const images = [];
        for (const u of found) {
          if (images.length >= want) break;
          try {
            const r = await fetch(u, {
              headers: { 'User-Agent': 'Mozilla/5.0', Referer: 'https://cn.bing.com/' },
              signal: AbortSignal.timeout(6000)
            });
            if (!r.ok) continue;
            const buf = Buffer.from(await r.arrayBuffer());
            if (buf.length < 12 * 1024) continue;
            images.push({ url: u, sizeKB: Math.round(buf.length / 1024) });
          } catch { /* 跳过死链 */ }
        }
        if (!images.length) return ok('搜到链接但都打不开（可能图床防盗链），换个关键词再试。');

        const lines = images.map((x, i) => `${i + 1}. ${x.url}  (${x.sizeKB}KB)`);
        return ok({
          query: q,
          images: images.map((x) => x.url),
          note: `把其中一条传给 gpu_draw 的 reference 参数就能照着画。列表：\n${lines.join('\n')}`
        });
      }
    },
'''

anchor = "    {\n      name: 'watch_video',"
assert s.count(anchor) == 1, '锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已加入 search_image 工具')
