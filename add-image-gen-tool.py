#!/usr/bin/env python3
"""给 qq-agent 加 image_gen 工具（openai-compat / dashscope 双适配），未配置时不挂载。

配置（config.json）：
  "imageGen": {
    "enabled": true,
    "provider": "openai-compat",      // 或 dashscope（通义万相）
    "baseUrl": "https://api.xxx.com/v1",
    "apiKey": "sk-...",
    "model": "gpt-image-1",
    "size": "1024x1024"
  }
未 enabled 或没 key 时，工具不注册（不占 schema token）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

TOOLS = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
CONF = r'D:\dshworks\qqbot\qq-agent\src\config.js'

result = []

# ── 1) config.js 默认值 ──
s = open(CONF, encoding='utf-8').read()
anchor = "  // 群聊只回复 @ 机器人的消息"
add_cfg = '''  // 生图（未配置 key 时不挂载 image_gen 工具）
  imageGen: {
    enabled: false,
    provider: 'openai-compat',   // openai-compat | dashscope
    baseUrl: '',
    apiKey: '',
    model: '',
    size: '1024x1024',
  },
'''
assert s.count(anchor) == 1, 'config 锚点不符'
s = s.replace(anchor, add_cfg + anchor, 1)
open(CONF, 'w', encoding='utf-8').write(s)
result.append('✓ config.js 新增 imageGen 默认配置')

# ── 2) tools.js 注入工具（放在 send_image 之前） ──
s = open(TOOLS, encoding='utf-8').read()

TOOL = r'''    {
      name: 'image_gen',
      description: '生成图片：把文字描述画成一张图并发出来。别人说"画一张/帮我生成图/来张图/画个表情包"时用它。prompt 尽量具体（主体、动作、风格、配色），中英文都行，不要带引号。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，越具体越好' },
          size: { type: 'string', description: '可选：1024x1024（默认）/ 1024x1536 / 1536x1024' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        const cfg = getConfig().imageGen || {};
        if (!cfg.enabled || !cfg.apiKey || !cfg.model) {
          return err('生图功能还没配置好（缺 key 或 model），跟对方说一声"我这边画图还没接好"。');
        }
        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('prompt 不能为空');
        const size = String(args.size || cfg.size || '1024x1024');
        const provider = String(cfg.provider || 'openai-compat');
        const timeoutMs = 180000;
        try {
          let buffer = null;
          let imageUrl = '';
          if (provider === 'openai-compat') {
            const base = String(cfg.baseUrl || '').replace(/\/+$/, '');
            const res = await fetch(`${base}/images/generations`, {
              method: 'POST',
              headers: { 'content-type': 'application/json', authorization: `Bearer ${cfg.apiKey}` },
              body: JSON.stringify({ model: cfg.model, prompt, n: 1, size }),
              signal: AbortSignal.timeout(timeoutMs)
            });
            const text = await res.text();
            let data = null;
            try { data = JSON.parse(text); } catch { /* 非 JSON */ }
            if (!res.ok) {
              const msg = data?.error?.message || text.slice(0, 160);
              return err(`生图接口返回 ${res.status}：${msg}`);
            }
            const first = data?.data?.[0] || {};
            if (first.b64_json) buffer = Buffer.from(first.b64_json, 'base64');
            else if (first.url) imageUrl = first.url;
            else return err('生图接口没有返回图片数据');
          } else if (provider === 'dashscope') {
            // 通义万相：异步任务，提交后轮询
            const submit = await fetch('https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis', {
              method: 'POST',
              headers: {
                'content-type': 'application/json',
                authorization: `Bearer ${cfg.apiKey}`,
                'X-DashScope-Async': 'enable'
              },
              body: JSON.stringify({
                model: cfg.model || 'wanx2.1-t2i-turbo',
                input: { prompt },
                parameters: { size: size.replace('x', '*'), n: 1 }
              }),
              signal: AbortSignal.timeout(60000)
            });
            const sj = await submit.json().catch(() => null);
            if (!submit.ok || !sj?.output?.task_id) {
              return err(`生图提交失败：${sj?.message || submit.status}`);
            }
            const taskId = sj.output.task_id;
            for (let i = 0; i < 30; i++) {
              await new Promise((r) => setTimeout(r, 4000));
              const q = await fetch(`https://dashscope.aliyuncs.com/api/v1/tasks/${taskId}`, {
                headers: { authorization: `Bearer ${cfg.apiKey}` },
                signal: AbortSignal.timeout(30000)
              });
              const qj = await q.json().catch(() => null);
              const status = qj?.output?.task_status;
              if (status === 'SUCCEEDED') {
                const r0 = qj.output?.results?.[0];
                imageUrl = r0?.url || '';
                break;
              }
              if (status === 'FAILED') return err(`生图失败：${qj?.output?.message || '未知原因'}`);
            }
            if (!buffer && !imageUrl) return err('生图超时，没有拿到图片');
          } else {
            return err(`不支持的生图 provider：${provider}`);
          }

          // 发送：本地 buffer 优先（不依赖图床），否则用 URL
          let replyMid = args.replyToMessageId ?? null;
          if ((replyMid === null || replyMid === '') && String(ctx.chatKey || '').startsWith('group:')
              && getConfig().groupQuoteReply !== false) {
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
            if (last) replyMid = last.mid;
          }
          let r;
          if (buffer) {
            r = await ctx.onebot.sendImageBuffer(ctx.kind, ctx.chatId, buffer, { replyToMessageId: replyMid });
          } else {
            r = await ctx.onebot.sendImage(ctx.kind, ctx.chatId, imageUrl, { replyToMessageId: replyMid });
          }
          ctx.session.sent.push({ type: 'image', text: '[生成的图片]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ generated: true, messageId: r?.message_id ?? null, note: '图片已发出。' });
        } catch (error) {
          return err(`生图失败：${error?.message ?? error}`);
        }
      }
    },
'''

anchor2 = "    {\n      name: 'send_image',"
assert s.count(anchor2) == 1, 'send_image 锚点不符'
s = s.replace(anchor2, TOOL + anchor2, 1)

# ── 3) 未配置时不注册（省 schema token） ──
anchor3 = "  return [\n    {\n      name: 'send_message',"
if anchor3 in s:
    new_head = """  const defs = [
    {
      name: 'send_message',"""
    s = s.replace(anchor3, new_head, 1)
    # 找到本函数返回处，改为过滤后返回
    anchor4 = "\n/** 转成 OpenAI tools 参数格式。 */"
    assert s.count(anchor4) == 1, '返回处锚点不符'
    s = s.replace(anchor4,
                  "\n  // 生图工具只在配置了 key+model 时挂载（未配置就不占 token）\n"
                  "  const igc = getConfig().imageGen || {};\n"
                  "  return defs.filter((d) => d && (d.name !== 'image_gen' || (igc.enabled && igc.apiKey && igc.model)));\n"
                  "}\n" + anchor4, 1)
    # 原来末尾的 "  ];\n}" 需要去掉（改为 return defs 后不再需要）
    s = s.replace("      }\n    }\n  ];\n}\n\n  // 生图工具只在配置了", "      }\n    }\n\n  // 生图工具只在配置了", 1)
    result.append('✓ tools.js 新增 image_gen 工具（未配置时不挂载）')
else:
    raise SystemExit('buildToolDefs 起始锚点不符')

open(TOOLS, 'w', encoding='utf-8').write(s)
print('\n'.join(result))
