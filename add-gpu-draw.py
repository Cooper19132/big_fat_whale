#!/usr/bin/env python3
"""给小鲸鱼加 GPU 画图能力：gpu_draw。

链路：
  她收到「画个…」→ gpu_draw 派给 DSH（dsh_task）
      → DSH 调 draw_image（本机 ComfyUI）出图
      → DSH 用 scp 把图传到服务器 /tmp/qqbot-out/<token>.png
      → 服务器这边轮询到文件 → 直接发到当前会话

超时后仍然会发：挂一个后台轮询，图到了自己发（不需要再唤醒模型）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'gpu_draw',
      description: '画图：把画面描述交给主人电脑上的显卡（ComfyUI + 千问 Qwen-Image）画出来并发到当前聊天。别人说"画一张/帮我画/来张图/画个表情包"时用它。prompt 写具体（主体+外观+环境+光线+风格）。需要主人电脑开着，通常 20~60 秒出图；若超过两分钟工具会说"还在画"，图好了会自动发出来。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，中文即可，写得具体一点' },
          size: { type: 'string', description: '可选：1:1（默认）/ 3:4 / 4:3 / 16:9 / 9:16' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');
        const { submitDshTask } = await import('./dsh-task.js');
        const token = 'QQDRAW-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        const remote = `/tmp/qqbot-out/${token}.png`;
        const sizeArg = String(args.size || '').trim();
        const taskText = [
          `画图任务 ${token}，请立刻执行，不要做别的事：`,
          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `2. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\\dshworks\\qqbot\\ssh\\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `3. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\\ComfyUI\\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\n');

        const kind = ctx.kind;
        const chatId = ctx.chatId;
        const replyMid = (() => {
          if (args.replyToMessageId != null) return args.replyToMessageId;
          if (!String(ctx.chatKey || '').startsWith('group:')) return null;
          const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
          const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
          return last ? last.mid : null;
        })();

        try {
          await submitDshTask(taskText, { taskName: 'draw-' + token.slice(-4) });
        } catch (e) {
          return err(`派活失败（主人电脑上的 DSH 没连上）：${e?.message ?? e}`);
        }

        // 等服务端出现图片（最多 120 秒，不阻塞太久）
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const deadline = Date.now() + 120000;
        while (Date.now() < deadline) {
          if (fs.existsSync(remote)) {
            try {
              const buf = await fs.promises.readFile(remote);
              await ctx.onebot.sendImageBuffer(kind, chatId, buf, { replyToMessageId: replyMid });
              ctx.session.sent.push({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
              ctx.emit('session-update', ctx.session.id);
              try { fs.unlinkSync(remote); } catch { /* 忽略 */ }
              return ok({ drawn: true, note: '画好了，已经发出来了。' });
            } catch (e) {
              return err(`图好了但发送失败：${e?.message ?? e}`);
            }
          }
          await sleep(3000);
        }

        // 还没好：挂后台轮询，图到了自己发
        pendingDraws.push({ remote, kind, chatId, replyMid, deadline: Date.now() + 8 * 60 * 1000, onebot: ctx.onebot, session: ctx.session, emit: ctx.emit });
        ensureDrawPoller();
        return ok({ pending: true, note: '还在画（显卡那边要 20~60 秒），画好我会直接把图发出来，不用再问我。' });
      }
    },
'''

anchor = "    {\n      name: 'write_handover',"
assert s.count(anchor) == 1, 'write_handover 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)

# 后台轮询器 + 待发队列（放在 buildToolDefs 之前）
anchor2 = "export function buildToolDefs() {"
assert s.count(anchor2) == 1, 'buildToolDefs 锚点不符'
poller = '''/** GPU 画图的待发队列 + 后台轮询（图到就发，不需要再唤醒模型）。 */
const pendingDraws = [];
let drawPoller = null;

function ensureDrawPoller() {
  if (drawPoller) return;
  drawPoller = setInterval(async () => {
    const now = Date.now();
    for (let i = pendingDraws.length - 1; i >= 0; i--) {
      const job = pendingDraws[i];
      try {
        if (fs.existsSync(job.remote)) {
          const buf = await fs.promises.readFile(job.remote);
          await job.onebot.sendImageBuffer(job.kind, job.chatId, buf, { replyToMessageId: job.replyMid });
          try { fs.unlinkSync(job.remote); } catch { /* 忽略 */ }
          if (job.session?.sent) {
            job.session.sent.push({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          }
          try { job.emit?.('session-update', job.session?.id); } catch { /* 忽略 */ }
          pendingDraws.splice(i, 1);
        } else if (now > job.deadline) {
          pendingDraws.splice(i, 1);
          console.log('[gpu_draw] 超时放弃:', job.remote);
        }
      } catch (e) {
        console.log('[gpu_draw] 轮询异常:', e?.message ?? e);
        pendingDraws.splice(i, 1);
      }
    }
    if (!pendingDraws.length && drawPoller) { clearInterval(drawPoller); drawPoller = null; }
  }, 5000);
}

'''
s = s.replace(anchor2, poller + anchor2, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已加入 gpu_draw 工具 + 后台轮询器')
