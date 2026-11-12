import os, shutil
p = '/opt/qq-agent/src/prompt.js'
s = open(p, encoding='utf-8').read()
if not os.path.exists(p + '.bak-debt'):
    shutil.copy(p, p + '.bak-debt')

# 1) import
old_imp = "import { renderMood } from './mood.js';"
if old_imp in s:
    s = s.replace(old_imp, old_imp + "\nimport { noteStyleComplaint, styleDebtSummary } from './style-debt.js';", 1)
    print("  import 已加")
else:
    # 找任意相对导入的末尾插入
    import re
    m = list(re.finditer(r"^import .*?;\s*$", s, re.M))
    assert m, "找不到 import"
    pos = m[-1].end()
    s = s[:pos] + "\nimport { noteStyleComplaint, styleDebtSummary } from './style-debt.js';" + s[pos:]
    print("  import 已插到末尾")

# 2) 过去状态：声明历史只是信息，不是文体样本
old2 = "  if (past.text) {"
assert s.count(old2) == 1, f"past 锚点 {s.count(old2)}"
new2 = """  if (past.text) {
    // 上下文污染防线：历史里全是你自己以前怎么说话，学它只会越学越像 AI。
    // 一句常驻提示比在群里喊「注意八股」管用。
"""
s = s.replace(old2, new2, 1)

# 3) 文风账注入
anchor3 = "  // 暗涌：情绪是状态不是记忆——这里给的是「此刻的她」，不是检索回来的过去"
assert s.count(anchor3) == 1
inject = """  // 文风账：谁、什么时候、说过她八股——把「喊话」变成可累积的记录
  try {
    noteStyleComplaint(ctx.triggerEntries, ctx.selfId);
    const debt = styleDebtSummary();
    if (debt) parts.push(`【文风账】${debt}`);
  } catch { /* 记账坏了不影响说话 */ }

"""
s = s.replace(anchor3, inject + anchor3, 1)
open(p, 'w', encoding='utf-8').write(s)
print("  prompt.js 改完")
