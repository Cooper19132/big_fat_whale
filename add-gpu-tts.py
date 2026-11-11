#!/usr/bin/env python3
"""给小鲸鱼加爱弥斯音色的语音能力：gpu_tts。

链路（和 gpu_draw 同一套）：
  她说一句话 → gpu_tts 派给 DSH
      → DSH 跑 IndexTTS-2 合成 wav
      → scp 到服务器 /tmp/qqbot-out/<token>.wav
      → 服务器这边发成 QQ 语音
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'gpu_tts',
      description: '用主人电脑上的显卡合成语音（爱弥斯音色）并发成 QQ 语音。别人要你"用语音说/说句话/念出来"，或者你自己想用声音说话时用它。text 是你要说的话（口语、别带表情符号和 Markdown，≤100 字）。需要主人电脑开着，通常 30~60 秒；超过两分钟会说"还在合成"，好了会自动发出来。',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: '要说的话，纯口语文本，不要表情符号' }
        },
        required: ['text']
      },
      async execute(ctx, args) {
        let text = String(args.text || '').trim();
        if (!text) return err('要说什么呀？给我一句话');
        const { submitDshTask } = await import('./dsh-task.js');
        text = text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').slice(0, 100).trim();
        const token = 'QQTTS-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        const remote = `/tmp/qqbot-out/${token}.wav`;
        const taskText = [
          `语音合成任务 ${token}，请立刻执行，不要做别的事：`,
          `1. 在 D:\\dshworks\\tools\\index-tts 目录下运行：`,
          `   .venv\\Scripts\\python.exe D:\\dshworks\\voice\\tts_synth.py "${text.replace(/"/g, "'")}" D:\\dshworks\\voice\\${token}.wav`,
          `2. 命令跑完、确认 ${token}.wav 存在后，用这条命令传到服务器：`,
          `   scp -i "D:\\dshworks\\qqbot\\ssh\\id_ed25519" -o StrictHostKeyChecking=accept-new "D:\\dshworks\\voice\\${token}.wav" admin@116.62.149.191:${remote}`,
          `3. 退出码 0 后，回复里只写一行：已上传 ${token}`
        ].join('\n');

        const kind = ctx.kind;
        const chatId = ctx.chatId;
        try {
          await submitDshTask(taskText, { taskName: 'tts-' + token.slice(-4) });
        } catch (e) {
          return err(`派活失败（主人电脑上的 DSH 没连上）：${e?.message ?? e}`);
        }

        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const deadline = Date.now() + 150000;
        while (Date.now() < deadline) {
          if (fs.existsSync(remote)) {
            try {
              const buf = await fs.promises.readFile(remote);
              await ctx.onebot.sendRecord(kind, chatId, buf);
              ctx.session.sent.push({ type: 'voice', text: '[语音]' + text.slice(0, 30), at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
              ctx.emit('session-update', ctx.session.id);
              try { fs.unlinkSync(remote); } catch { /* 忽略 */ }
              return ok({ spoken: true, note: '语音已发出。' });
            } catch (e) {
              return err(`语音合成好了但发送失败：${e?.message ?? e}`);
            }
          }
          await sleep(3000);
        }
        pendingVoices.push({ remote, kind, chatId, deadline: Date.now() + 8 * 60 * 1000, onebot: ctx.onebot, session: ctx.session, emit: ctx.emit, text });
        ensureVoicePoller();
        return ok({ pending: true, note: '还在合成（显卡那边要 30~60 秒），好了我直接发语音出来。' });
      }
    },
'''

anchor = "    {\n      name: 'gpu_draw',"
assert s.count(anchor) == 1, 'gpu_draw 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)

# 语音待发队列 + 轮询器
anchor2 = "/** GPU 画图的待发队列 + 后台轮询（图到就发，不需要再唤醒模型）。 */"
assert s.count(anchor2) == 1, 'poller 锚点不符'
voice_poller = '''/** GPU 语音的待发队列 + 后台轮询。 */
const pendingVoices = [];
let voicePoller = null;

function ensureVoicePoller() {
  if (voicePoller) return;
  voicePoller = setInterval(async () => {
    const now = Date.now();
    for (let i = pendingVoices.length - 1; i >= 0; i--) {
      const job = pendingVoices[i];
      try {
        if (fs.existsSync(job.remote)) {
          const buf = await fs.promises.readFile(job.remote);
          await job.onebot.sendRecord(job.kind, job.chatId, buf);
          try { fs.unlinkSync(job.remote); } catch { /* 忽略 */ }
          if (job.session?.sent) {
            job.session.sent.push({ type: 'voice', text: '[语音]' + String(job.text || '').slice(0, 30), at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          }
          try { job.emit?.('session-update', job.session?.id); } catch { /* 忽略 */ }
          pendingVoices.splice(i, 1);
        } else if (now > job.deadline) {
          pendingVoices.splice(i, 1);
          console.log('[gpu_tts] 超时放弃:', job.remote);
        }
      } catch (e) {
        console.log('[gpu_tts] 轮询异常:', e?.message ?? e);
        pendingVoices.splice(i, 1);
      }
    }
    if (!pendingVoices.length && voicePoller) { clearInterval(voicePoller); voicePoller = null; }
  }, 5000);
}

'''
s = s.replace(anchor2, voice_poller + anchor2, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已加入 gpu_tts 工具 + 语音轮询器')
