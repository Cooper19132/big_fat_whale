#!/usr/bin/env python3
"""修 bili_video 的脆弱点：
1. 字幕地址为空 / 拉字幕失败 → 自动退回抽帧，而不是直接报错
2. 字幕太短（<200 字）→ 也补抽帧
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()
results = []

OLD = '''          let subUrl = String(pick.subtitle_url || '');
          if (subUrl.startsWith('//')) subUrl = 'https:' + subUrl;
          const body = await biliGet(subUrl, { sessdata, cookie: biliCookie });
          const items = body.body || [];
          const fullText = items.map((i) => i.content || '').join('');
          const cap = Number(getConfig().bili?.maxSubtitleChars) || 6000;
          lines.push(`字幕：${pick.lan_doc || pick.lan}，${items.length} 句`);
          lines.push(`字幕正文（${Math.min(fullText.length, cap)} 字）：`);
          lines.push(fullText.slice(0, cap));
          return ok(lines.join('\\n'));'''

NEW = '''          let subUrl = String(pick.subtitle_url || '');
          if (subUrl.startsWith('//')) subUrl = 'https:' + subUrl;
          if (!/^https?:\\/\\//.test(subUrl)) {
            lines.push('（字幕地址为空或不合法，改用抽帧看画面）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          let body = null;
          try {
            body = await biliGet(subUrl, { sessdata, cookie: biliCookie });
          } catch (subErr) {
            lines.push(`（拉字幕失败：${subErr?.message ?? subErr}，改用抽帧）`);
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          const items = (body && body.body) || [];
          const fullText = items.map((i) => i.content || '').join('');
          const cap = Number(getConfig().bili?.maxSubtitleChars) || 6000;
          lines.push(`字幕：${pick.lan_doc || pick.lan}，${items.length} 句`);
          lines.push(`字幕正文（${Math.min(fullText.length, cap)} 字）：`);
          lines.push(fullText.slice(0, cap));
          // 字幕太少（<200 字）等于没有，同样补抽帧看画面
          if (fullText.length < 200) {
            lines.push('（字幕内容太少，补充画面帧）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          return ok(lines.join('\\n'));'''

assert s.count(OLD) == 1, '字幕段落锚点不符（%d 处）' % s.count(OLD)
s = s.replace(OLD, NEW, 1)
results.append('✓ 字幕空/失败时退回抽帧 + 字幕过短补帧')

open(P, 'w', encoding='utf-8').write(s)
print('\n'.join(results))
