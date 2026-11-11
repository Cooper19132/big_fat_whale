#!/usr/bin/env python3
"""gpu_draw 成功发出图之后，立刻调用 TTS 管家的 /cleanup：
归档这次生图的 DSH 对话 + 删除生成的图片（不等 24h）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# 1) 在 gpu_draw 里定义清理函数（放在 token 生成之后）
old_anchor = """        const kind = ctx.kind;
        const chatId = ctx.chatId;"""
new_anchor = """        // 生图成功后立刻归档对话 + 删图（PC 侧 TTS 管家的 /cleanup 端点）
        const fireCleanup = async () => {
          try {
            const cfg = getConfig().ttsGpu || {};
            const base = String(cfg.baseUrl || 'http://127.0.0.1:9900').replace(/\\/+$/, '');
            await fetch(`${base}/cleanup`, {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ minAgeSeconds: 20 }),
              signal: AbortSignal.timeout(30000)
            });
          } catch { /* 清理失败不影响出图 */ }
        };

        const kind = ctx.kind;
        const chatId = ctx.chatId;"""
assert s.count(old_anchor) == 1, 'gpu_draw 上下文锚点不符'
s = s.replace(old_anchor, new_anchor, 1)

# 2) 成功分支调用它
old_ok = """              try { fs.unlinkSync(remote); } catch { /* 忽略 */ }
              return ok({ drawn: true, reference: refUrl ? refNote : '无（文生图）', note: '画好了，已经发出来了。' });"""
new_ok = """              try { fs.unlinkSync(remote); } catch { /* 忽略 */ }
              fireCleanup();
              return ok({ drawn: true, reference: refUrl ? refNote : '无（文生图）', note: '画好了，已经发出来了（对话已归档、图片已清理）。' });"""
assert s.count(old_ok) == 1, '成功分支锚点不符'
s = s.replace(old_ok, new_ok, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ gpu_draw 成功后触发 /cleanup')
print('  fireCleanup 出现:', s.count('fireCleanup'))
