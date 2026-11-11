#!/usr/bin/env python3
"""改进 search_image：翻两页、放宽体积门槛、多候选，尽量凑够 5 条。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

start = s.index("        const want = Math.max(3, Math.min(8, Number(args.count) || 5));")
end = s.index("        if (!images.length) return ok('搜到链接但都打不开（可能图床防盗链），换个关键词再试。');")

NEW = r'''        const want = Math.max(3, Math.min(8, Number(args.count) || 5));
        const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';

        // 翻两页，多拿候选（Bing 首页常常只给几条可用）
        const candidates = [];
        for (const [first, host] of [[0, 'cn.bing.com'], [35, 'cn.bing.com'], [0, 'www.bing.com']]) {
          const pageUrl = `https://${host}/images/async?q=${encodeURIComponent(q)}&first=${first}&count=35&mmasync=1`;
          try {
            const res = await fetch(pageUrl, {
              headers: { 'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9', Referer: `https://${host}/images/search` },
              signal: AbortSignal.timeout(20000)
            });
            if (!res.ok) continue;
            const html = await res.text();
            const re = /murl&quot;:&quot;([^&]+?)&quot;/g;
            let m;
            while ((m = re.exec(html)) !== null) {
              let u = m[1];
              try { u = decodeURIComponent(u); } catch { /* 原样 */ }
              u = u.replace(/\\u0026/g, '&');
              if (!/^https?:\/\//i.test(u)) continue;
              if (!candidates.includes(u)) candidates.push(u);
            }
          } catch { /* 换源继续 */ }
          if (candidates.length >= want * 4) break;
        }
        if (!candidates.length) return ok('没搜到可用图片，换个关键词试试（或直接用文字描述画）。');

        // 轻量校验：能下载、体积够（>8KB 基本排除占位图/图标）
        const images = [];
        for (const u of candidates) {
          if (images.length >= want) break;
          try {
            const r = await fetch(u, {
              headers: { 'User-Agent': UA, Referer: 'https://cn.bing.com/' },
              signal: AbortSignal.timeout(6000)
            });
            if (!r.ok) continue;
            const buf = Buffer.from(await r.arrayBuffer());
            if (buf.length < 8 * 1024) continue;
            images.push({ url: u, sizeKB: Math.round(buf.length / 1024) });
          } catch { /* 跳过死链 */ }
        }
'''
s = s[:start] + NEW + s[end:]
open(P, 'w', encoding='utf-8').write(s)
print('✓ search_image 改进：翻页 + 多源 + 门槛 8KB')
