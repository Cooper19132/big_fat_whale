#!/usr/bin/env python3
"""把 gpu_tts 改成直连本机常驻 TTS 服务（经隧道），不再绕 DSH 派活。

延迟从 150 秒+ 降到约 20~25 秒，且不消耗 LLM token。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

START = "    {\n      name: 'gpu_tts',"
END = "    {\n      name: 'gpu_draw',"
i = s.find(START)
j = s.find(END, i + 1)
assert i > 0 and j > i, f'定位失败 ({i}, {j})'

NEW = r'''    {
      name: 'gpu_tts',
      description: '用主人电脑上的显卡合成语音（爱弥斯音色）并发成 QQ 语音。别人要你"用语音说/说句话/念出来"，或你自己想用声音说话时用它。text 是口语文本，别带表情符号和 Markdown，≤100 字。需要主人电脑开着，通常 20~30 秒；超时会说"还在合成"，好了自动发出来。',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: '要说的话，纯口语，不要表情符号' }
        },
        required: ['text']
      },
      async execute(ctx, args) {
        let text = String(args.text || '').trim();
        if (!text) return err('要说什么呀？给我一句话');
        text = text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').slice(0, 100).trim();
        const cfg = getConfig().ttsGpu || {};
        const base = String(cfg.baseUrl || 'http://127.0.0.1:9900').replace(/\/+$/, '');
        try {
          const res = await fetch(`${base}/tts`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ text }),
            signal: AbortSignal.timeout(Number(cfg.timeoutMs) || 180000)
          });
          if (!res.ok) {
            const detail = await res.text().catch(() => '');
            return err(`语音服务返回 ${res.status}：${detail.slice(0, 120)}`);
          }
          const buf = Buffer.from(await res.arrayBuffer());
          if (!buf.length) return err('语音服务返回了空音频');
          await ctx.onebot.sendRecord(ctx.kind, ctx.chatId, buf);
          ctx.session.sent.push({ type: 'voice', text: '[语音]' + text.slice(0, 30), at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ spoken: true, bytes: buf.length, note: '语音已发出。' });
        } catch (error) {
          const msg = String(error?.message || error);
          if (/ECONNREFUSED|fetch failed|aborted|ETIMEDOUT/i.test(msg)) {
            return err('语音服务没响应——主人电脑可能没开，或者 TTS 服务没起。可以先说一句"语音那边没连上，我先打字"。');
          }
          return err(`语音合成失败：${msg}`);
        }
      }
    },
'''

s = s[:i] + NEW + s[j:]

# config 默认值
C = r'D:\dshworks\qqbot\qq-agent\src\config.js'
c = open(C, encoding='utf-8').read()
if 'ttsGpu' not in c:
    anchor = "  // 生图（未配置 key 时不挂载 image_gen 工具）"
    assert c.count(anchor) == 1
    c = c.replace(anchor, "  // GPU 语音（本机常驻 TTS 服务，经反向隧道调用）\n  ttsGpu: { baseUrl: 'http://127.0.0.1:9900', timeoutMs: 180000 },\n" + anchor, 1)
    open(C, 'w', encoding='utf-8').write(c)
    print('✓ config.js 增加 ttsGpu 默认值')

open(P, 'w', encoding='utf-8').write(s)
print('✓ gpu_tts 改为直连 TTS 服务')
