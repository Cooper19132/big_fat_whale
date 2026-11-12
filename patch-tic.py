import os, shutil
p = '/opt/qq-agent/src/prompt.js'
s = open(p, encoding='utf-8').read()
if not os.path.exists(p + '.bak-tic'):
    shutil.copy(p, p + '.bak-tic')

# 1) 统计工具：最近若干条自己说过的话里，哪些「工整结构」用滥了
anchor = "function triggerLabels(entry, ctx) {"
assert s.count(anchor) == 1, f"triggerLabels 锚点 {s.count(anchor)}"
helper = '''/** 她自己的口头结构配额：最近 N 条自己消息里，「比…还」「一…就」这类工整句式用了几次。 */
const TIC_PATTERNS = [
  [/比[^，。]{1,12}还/, '「比…还…」的对比'],
  [/一[^，。]{1,5}就/, '「一…就…」的句式'],
  [/[^？?。]{0,10}(挺|很|还算)(?!不)[^，。]{1,4}/, '「挺/很＋形容词」的评价']
];

export function recentTics(store, chatKey, { limit = 60 } = {}) {
  try {
    const mine = store.recent(chatKey, { limit }).filter((m) => m && m.self);
    if (mine.length < 12) return [];
    const hits = [];
    for (const [re, name] of TIC_PATTERNS) {
      const n = mine.filter((m) => re.test(String(m.text || ''))).length;
      const pct = (n / mine.length) * 100;
      if (n >= 3 && pct >= 3) hits.push(`${name}最近 ${mine.length} 条里用了 ${n} 次（${pct.toFixed(0)}%）`);
    }
    return hits;
  } catch { return []; }
}

'''
s = s.replace(anchor, helper + anchor)

# 2) 注入到用户消息里
anchor2 = "  // 暗涌：情绪是状态不是记忆——这里给的是「此刻的她」，不是检索回来的过去"
assert s.count(anchor2) == 1, "暗涌锚点"
inject = """  // 口头结构配额：她自己的话里哪几种句式已经用滥了，直接摆出来让她换（比写在人设里更硬）
  try {
    const tics = recentTics(ctx.store, ctx.chatKey, { limit: 60 });
    if (tics.length) {
      parts.push(`【换个说法】${tics.join('；')}。这条别再用了，换成具体动作、次数或你自己的反应。`);
    }
  } catch { /* 统计坏了不影响说话 */ }

"""
s = s.replace(anchor2, inject + anchor2)
open(p, 'w', encoding='utf-8').write(s)
print("  prompt.js 改完（recentTics + 注入）")
