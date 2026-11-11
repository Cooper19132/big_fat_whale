#!/usr/bin/env python3
"""修画风：给 gpu_draw 加「风格预设 + 画质后缀 + 默认负向词 + 更高步数」。

原来：prompt 原样透传，negative 空，steps 25 → 模型走最省事的扁平插画。
现在：
  · 自动追加画质后缀（杰作/超高细节/光影/景深…）
  · 支持 style 参数：anime / realistic / cinematic / painterly / flat(手动要扁平才给)
  · 默认负向词压掉「简笔画/扁平/水印/文字」
  · steps 默认 30，megapixels 默认 1.3
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ---------- 1) 参数加 style ----------
old_params = """          reference: { type: 'string', description: '参考图（可选）：别人发的图片消息的 #数字，或 http(s) 图片直链。给了就走图生图——保留参考图里的角色/画风，按 prompt 改姿势、换环境、换衣服。' }"""
new_params = """          reference: { type: 'string', description: '参考图（可选）：别人发的图片消息的 #数字，或 http(s) 图片直链。给了就走图生图——保留参考图里的角色/画风，按 prompt 改姿势、换环境、换衣服。' },
          style: { type: 'string', description: '画风（可选）：anime=日系动漫 / realistic=写实摄影 / cinematic=电影感 / painterly=厚涂油画 / flat=扁平卡通。不给就按 prompt 自动判断（提动漫二次元走 anime，提照片写实走 realistic，其余走 detailed 高细节）' }"""
assert s.count(old_params) == 1, '参数锚点不符'
s = s.replace(old_params, new_params, 1)

# ---------- 2) 拼风格后缀与负向词 ----------
old_head = """        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');"""
new_head = """        let prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');

        // 画风预设：后缀 = 风格 + 画质，负向词压掉扁平/水印
        const STYLES = {
          anime: { suffix: '，日系动漫插画风格，赛璐璐上色，精致线稿，柔和明暗，高细节', neg: '低质量，简笔画，粗糙线条，扁平色块，模糊，变形，水印，文字，签名' },
          realistic: { suffix: '，写实摄影风格，真实材质纹理，自然光影，85mm 镜头，浅景深，超精细', neg: '卡通，简笔画，扁平色块，扭曲，模糊，水印，文字，签名，多余手指' },
          cinematic: { suffix: '，电影感画面，戏剧性布光，宽银幕构图，胶片颗粒，色彩分级，超精细', neg: '扁平，简笔画，呆板构图，模糊，水印，文字，签名' },
          painterly: { suffix: '，厚涂油画质感，丰富笔触，色彩层次，画布纹理，艺术感', neg: '扁平色块，简笔画，矢量图，模糊，水印，文字' },
          flat: { suffix: '，扁平卡通风格，干净色块，简洁造型', neg: '低质量，模糊，水印，文字' },
          detailed: { suffix: '，杰作，超高细节，精致光影，专业级插画质感，柔和景深，8k', neg: '低质量，简笔画，扁平色块，粗糙，模糊，变形，水印，文字，签名' }
        };
        const autoStyle = (() => {
          if (/动漫|二次元|插画|漫画|赛璐璐|anime/i.test(prompt)) return 'anime';
          if (/写实|照片|摄影|真实|photoreal/i.test(prompt)) return 'realistic';
          if (/电影|cinematic|剧情画面/i.test(prompt)) return 'cinematic';
          if (/油画|厚涂|painterly/i.test(prompt)) return 'painterly';
          return 'detailed';
        })();
        const styleKey = STYLES[String(args.style || '').toLowerCase()] ? String(args.style).toLowerCase() : autoStyle;
        const styleSpec = STYLES[styleKey];
        const finalPrompt = prompt + styleSpec.suffix;
        const finalNegative = String(args.negative || '').trim() || styleSpec.neg;"""
assert s.count(old_head) == 1, '头部锚点不符'
s = s.replace(old_head, new_head, 1)

# ---------- 3) 任务文本用 finalPrompt / negative / steps / megapixels ----------
s = s.replace("""          `   prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',""",
"""          `   prompt 用下面这段（原样，别改写）：`,
          finalPrompt,
          `   negative 参数用这段（原样）：${finalNegative}`,
          `   steps 用 30`,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `   megapixels 用 1.3`,""", 1)

s = s.replace("""          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          prompt,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',""",
"""          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          finalPrompt,
          `   negative 参数用这段（原样）：${finalNegative}`,
          `   steps 用 30`,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `   megapixels 用 1.3`,""", 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ gpu_draw 已加：风格预设 + 画质后缀 + 负向词 + steps30 + 1.3MP')
