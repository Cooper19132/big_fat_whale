#!/usr/bin/env python3
"""给 gpu_draw 加参考图（图生图）。

用法（小鲸鱼视角）：
  gpu_draw(prompt="把这只猫改成穿西装", reference="#12345")
  —— reference 可以是 QQ 消息的 #数字（带图），也可以是 http(s) 图片直链

链路：
  服务器拿到 QQ 图片 URL → 写进 DSH 任务文本
  → DSH 先 curl 下载到本地 refs/ 目录
  → 调 draw_image(prompt, reference=本地路径) 走图生图
  → 出图后 scp 回服务器（原有流程）
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ---------- 1) 参数加 reference ----------
old_params = """          prompt: { type: 'string', description: '画面描述，中文即可，写得具体一点' },
          size: { type: 'string', description: '可选：1:1（默认）/ 3:4 / 4:3 / 16:9 / 9:16' }
        },
        required: ['prompt']"""
new_params = """          prompt: { type: 'string', description: '画面描述，中文即可，写得具体一点' },
          size: { type: 'string', description: '可选：1:1（默认）/ 3:4 / 4:3 / 16:9 / 9:16' },
          reference: { type: 'string', description: '参考图（可选）：别人发的图片消息的 #数字，或 http(s) 图片直链。给了就走图生图——保留参考图里的角色/画风，按 prompt 改姿势、换环境、换衣服。' }
        },
        required: ['prompt']"""
assert s.count(old_params) == 1, '参数锚点不符'
s = s.replace(old_params, new_params, 1)

# ---------- 2) 解析 reference ----------
old_head = """        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');
        const { submitDshTask } = await import('./dsh-task.js');"""
new_head = """        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');
        const { submitDshTask } = await import('./dsh-task.js');

        // 解析参考图：QQ 消息 #id → 图片直链；也接受 http(s) 直链
        let refUrl = '';
        let refNote = '';
        const rawRef = String(args.reference || '').trim();
        if (rawRef) {
          if (/^https?:\\/\\//i.test(rawRef)) {
            refUrl = rawRef;
            refNote = '参考图：外部直链';
          } else {
            const mid = rawRef.replace(/^#/, '');
            const entry = ctx.store.findByMid(ctx.chatKey, mid);
            const img = (entry?.media || []).find((m) => m.kind === 'image' && (m.url || m.file));
            if (img?.url) {
              refUrl = img.url;
              refNote = `参考图：消息 #${mid}`;
            } else if (img?.file) {
              refUrl = img.file;
              refNote = `参考图：消息 #${mid}（file）`;
            }
          }
          if (!refUrl) return err(`找不到参考图（${rawRef}）——把带图的那条消息的 #数字给我，或者直接给图片链接`);
        }"""
assert s.count(old_head) == 1, '头部锚点不符'
s = s.replace(old_head, new_head, 1)

# ---------- 3) 任务文本加下载参考图步骤 ----------
old_task = """        const taskText = [
          `画图任务 ${token}，请立刻执行，不要做别的事：`,
          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `2. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\\\\dshworks\\\\qqbot\\\\ssh\\\\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `3. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\\\\ComfyUI\\\\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\\n');"""
new_task = """        const refLocal = `D:\\\\dshworks\\\\qqbot\\\\refs\\\\ref-${token}.png`;
        const taskText = refUrl ? [
          `画图任务 ${token}（图生图），请立刻执行，不要做别的事：`,
          `1. 先把参考图下载到本地（目录不存在就建）：`,
          `   mkdir -Force "D:\\dshworks\\qqbot\\refs" | Out-Null; curl.exe -sSL -o "${refLocal}" "${refUrl}"`,
          `   下载后确认文件大小 > 10KB；失败就回复"参考图下载失败 ${token}"。`,
          `2. 调用 draw_image 工具：`,
          `   prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `   reference 参数用这个本地路径（必须给，否则就变成文生图了）：${refLocal}`,
          `3. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\\dshworks\\qqbot\\ssh\\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `4. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\\ComfyUI\\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\\n') : [
          `画图任务 ${token}，请立刻执行，不要做别的事：`,
          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `2. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\\dshworks\\qqbot\\ssh\\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `3. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\\ComfyUI\\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\\n');"""
assert s.count(old_task) == 1, '任务文本锚点不符'
s = s.replace(old_task, new_task, 1)

# ---------- 4) 结果里带上参考图信息 ----------
s = s.replace("return ok({ drawn: true, note: '画好了，已经发出来了。' });",
              "return ok({ drawn: true, reference: refUrl ? refNote : '无（文生图）', note: '画好了，已经发出来了。' });", 1)
s = s.replace("return ok({ pending: true, note: '还在画（显卡那边 20~60 秒），好了我直接发图出来。' });",
              "return ok({ pending: true, reference: refUrl ? refNote : '无（文生图）', note: '还在画（显卡那边 20~60 秒），好了我直接发图出来。' });", 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ gpu_draw 已支持 reference（图生图）')
