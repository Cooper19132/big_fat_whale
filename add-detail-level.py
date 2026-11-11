#!/usr/bin/env python3
"""加「细节档位」：detail=normal | high | ultra
更细的提示词 + 更多步数 + 更高分辨率，同时教她怎么写详细 prompt。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# 1) 参数加 detail
old = """          style: { type: 'string', description: '画风（可选）：anime=日系动漫 / realistic=写实摄影 / cinematic=电影感 / painterly=厚涂油画 / flat=扁平卡通。不给就按 prompt 自动判断（提动漫二次元走 anime，提照片写实走 realistic，其余走 detailed 高细节）' }"""
new = """          style: { type: 'string', description: '画风（可选）：anime=日系动漫 / realistic=写实摄影 / cinematic=电影感 / painterly=厚涂油画 / flat=扁平卡通。不给就按 prompt 自动判断' },
          detail: { type: 'string', description: '细节档位（可选）：normal=常规 / high=更精细 / ultra=极致细节（步数更多、分辨率更高、更慢）。默认 high' }"""
assert s.count(old) == 1, '参数锚点不符'
s = s.replace(old, new, 1)

# 2) 细节档位 → 后缀 / steps / megapixels
old2 = """        const styleKey = STYLES[String(args.style || '').toLowerCase()] ? String(args.style).toLowerCase() : autoStyle;
        const styleSpec = STYLES[styleKey];
        const finalPrompt = prompt + styleSpec.suffix;
        const finalNegative = String(args.negative || '').trim() || styleSpec.neg;"""
new2 = """        const styleKey = STYLES[String(args.style || '').toLowerCase()] ? String(args.style).toLowerCase() : autoStyle;
        const styleSpec = STYLES[styleKey];

        // 细节档位：决定追加的细节词、步数、像素量
        const DETAIL = {
          normal: { extra: '，细节清晰', steps: 30, mp: 1.3 },
          high: { extra: '，丰富细节，精细材质纹理，多层景深，微妙光影过渡，高保真', steps: 40, mp: 1.6 },
          ultra: { extra: '，极致细节，微距级纹理，复杂层次，体积光与散射，电影级色彩分级，锐利对焦，超高清', steps: 50, mp: 2.0 }
        };
        const detailKey = DETAIL[String(args.detail || '').toLowerCase()] ? String(args.detail).toLowerCase() : 'high';
        const detailSpec = DETAIL[detailKey];

        const finalPrompt = prompt + styleSpec.suffix + detailSpec.extra;
        const finalNegative = String(args.negative || '').trim() || styleSpec.neg;
        const finalSteps = detailSpec.steps;
        const finalMP = detailSpec.mp;"""
assert s.count(old2) == 1, '风格锚点不符'
s = s.replace(old2, new2, 1)

# 3) 任务文本改用变量
s = s.replace("          `   steps 用 30`,\n          sizeArg ? `   size 参数用 ${sizeArg}` : '',\n          `   megapixels 用 1.3`,",
              "          `   steps 用 ${finalSteps}`,\n          sizeArg ? `   size 参数用 ${sizeArg}` : '',\n          `   megapixels 用 ${finalMP}`,", 1)
s = s.replace("          `   steps 用 30`,\n          sizeArg ? `   size 参数用 ${sizeArg}` : '',\n          `   megapixels 用 1.3`,",
              "          `   steps 用 ${finalSteps}`,\n          sizeArg ? `   size 参数用 ${sizeArg}` : '',\n          `   megapixels 用 ${finalMP}`,", 1)

# 兜底：如果还有硬编码 30 / 1.3 的残留（文生图分支）
s = s.replace("`   steps 用 30`", "`   steps 用 ${finalSteps}`")
s = s.replace("`   megapixels 用 1.3`", "`   megapixels 用 ${finalMP}`")

open(P, 'w', encoding='utf-8').write(s)
print('✓ gpu_draw 加 detail 档位（normal/high/ultra）')
print('  steps 硬编码残留:', s.count('steps 用 30'))
