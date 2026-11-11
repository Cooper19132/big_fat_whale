#!/usr/bin/env python3
"""给小鲸鱼加 SDXL 出图工具：二次元/写实向，质量比 Qwen-Image 高一个档。

链路：服务器工具 → http://127.0.0.1:9906/draw（隧道→PC 的 sdxl_bridge） → ComfyUI(8189)
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'draw_sdxl',
      timeoutMs: 300000,
      description: '画二次元/写实风格的图（SDXL + Illustrious 系模型，画风更精细、更贴二次元）。要画动漫角色、人物立绘、涩图、或者需要精细人体/姿势时用它，比 gpu_draw 更合适；gpu_draw 更适合日常场景、写实照片感、以及需要参考图的图生图。出图后直接把图发出来。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，英文 tag 效果最好，也接受中文（主体+外貌+服装+姿势+场景+光线+画风）' },
          negative: { type: 'string', description: '可选：不想要的内容（英文）。不填用默认质量词' },
          size: { type: 'string', description: '可选：3:4（832x1216，默认）/ 2:3（832x1216）/ 1:1（1024x1024）/ 16:9（1216x832）/ 4:3（1152x864）' },
          steps: { type: 'number', description: '可选：采样步数，默认 28（20~40）' },
          cfg: { type: 'number', description: '可选：提示词强度，默认 5.5（4~8）' },
          seed: { type: 'number', description: '可选：随机种子，想让同一张图可复现就传' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我描述');
        const SIZE = {
          '3:4': [832, 1216], '2:3': [832, 1216], '1:1': [1024, 1024],
          '16:9': [1216, 832], '4:3': [1152, 864], '9:16': [768, 1344]
        };
        const dims = SIZE[String(args.size || '').trim()] || [832, 1216];
        const base = String(process.env.SDXL_URL || 'http://127.0.0.1:9906').replace(/\/+$/, '');
        const payload = {
          prompt,
          negative: args.negative ? String(args.negative) : undefined,
          width: dims[0], height: dims[1],
          steps: Number(args.steps) || 28,
          cfg: Number(args.cfg) || 5.5,
          seed: Number(args.seed) || undefined,
          inline: true
        };
        let json;
        try {
          const r = await fetch(`${base}/draw`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(280000)
          });
          json = await r.json();
        } catch (e) {
          return err(`出图失败（画图服务没连上）：${e?.message ?? e}`);
        }
        if (!json?.ok || !json?.b64) {
          return err(`出图失败：${json?.error || '没有返回图片'}`);
        }
        try {
          const buf = Buffer.from(json.b64, 'base64');
          const replyMid = (() => {
            if (!String(ctx.chatKey || '').startsWith('group:')) return null;
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
            return last ? last.mid : null;
          })();
          await ctx.onebot.sendImageBuffer(ctx.kind, ctx.chatId, buf, { replyToMessageId: replyMid });
          ctx.session?.sent?.push?.({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit?.('session-update', ctx.session?.id);
          return ok({
            drawn: true, model: json.model, seed: json.seed, size: json.size,
            costSec: json.costSec, note: '画好了，已经发出来了。'
          });
        } catch (e) {
          return err(`图出来了但发送失败：${e?.message ?? e}`);
        }
      }
    },
'''

anchor = "    {\n      name: 'search_meme_wiki',"
assert s.count(anchor) == 1, 'search_meme_wiki 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js: 新增 draw_sdxl')
