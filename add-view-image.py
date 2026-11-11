#!/usr/bin/env python3
"""新增 view_image 工具：给直链就能看图。

用途：合并转发里的图片被压成 [图1]/[图2]，正文末尾会附「图N = 直链」，
她拿这个直链就能看。也支持传 #消息id（等价 get_message_images）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'view_image',
      timeoutMs: 60000,
      description: '看一张图：给它图片直链（http/https），或消息的 #数字。合并转发里的图会以「图N = 直链」的形式给出，用这个工具就能看到画面。一次只看一张，最多 4 张图。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: '图片直链，或消息的 #数字' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        const raw = String(args.target || '').trim();
        if (!raw) return err('看哪张图？给我直链或消息 #数字');

        // ① 消息 id：复用已有逻辑
        if (/^#?\d+$/.test(raw)) {
          const entry = ctx.store.findByMid(ctx.chatKey, raw.replace(/^#/, ''));
          if (!entry) return err(`当前会话找不到消息 ${raw}`);
          const urls = (entry.media || []).filter((m) => m.kind === 'image' && m.url).map((m) => m.url);
          if (!urls.length) return err(`消息 ${raw} 里没有可看的图片`);
          const dataUrls = [];
          for (const u of urls.slice(0, 4)) {
            try { dataUrls.push(await downloadImageAsDataUrl(u)); } catch { /* 跳过失败的 */ }
          }
          if (!dataUrls.length) return err('图片下载失败（链接可能已过期）');
          return { content: imageParts(`消息 ${raw} 的图片：`, dataUrls) };
        }

        // ② 直链
        if (!/^https?:\/\//i.test(raw)) return err('只接受 http(s) 图片直链或消息 #数字');
        try {
          const dataUrl = await downloadImageAsDataUrl(raw);
          return { content: imageParts('图片内容：', [dataUrl]) };
        } catch (e) {
          return err(`图片打不开：${e?.message ?? e}（QQ 图床链接有时效，过期就取不到了）`);
        }
      }
    },
'''

anchor = "    {\n      name: 'get_message_video',"
assert s.count(anchor) == 1, 'get_message_video 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已新增 view_image 工具')
