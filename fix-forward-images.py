#!/usr/bin/env python3
"""修「合并转发里的图片看不到」：

现状：flatten 把每张图片压成 [图片]，丢了 url → 她只能看到 "QQ用户: [图片]"。
改法：
  ① nodeParts 收集图片 url（file/url 都收）
  ② flattenNodes 把图写成 [图1] 这样的短标记，并在末尾附一张「图号 = 直链」的对照表
  ③ 新增 view_image 工具：给直链就能看图（也可以用 #消息id）
  ④ 人设补一句：转发里的 [图N] 用 view_image 看
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ── ① nodeParts：收集图片地址 ────────────────────────────────
old_np = """    let text = '';
    const inline = [];
    const ids = [];
    for (const seg of segs) {
      const t = seg?.type;
      const d = seg?.data ?? {};
      if (t === 'text') text += d.text ?? '';
      else if (t === 'image') text += '[图片]';"""
new_np = """    let text = '';
    const inline = [];
    const ids = [];
    const images = [];
    for (const seg of segs) {
      const t = seg?.type;
      const d = seg?.data ?? {};
      if (t === 'text') text += d.text ?? '';
      else if (t === 'image') {
        text += '[图片]';
        const u = String(d.url || d.file || d.path || '').trim();
        if (/^https?:\\/\\//i.test(u)) images.push(u);
      }"""
assert s.count(old_np) == 1, 'nodeParts 锚点不符'
s = s.replace(old_np, new_np, 1)

old_ret = """    return { text: text.replace(/\\s+/g, ' ').trim(), inline, ids };"""
new_ret = """    return { text: text.replace(/\\s+/g, ' ').trim(), inline, ids, images };"""
assert s.count(old_ret) == 1, 'nodeParts 返回锚点不符'
s = s.replace(old_ret, new_ret, 1)

# ── ② flattenNodes：图号 + 末尾对照表 ───────────────────────
old_fn_sig = """async function flattenNodes(onebot, nodes, { maxItems = 30, maxChars = 2000, depth = 0, budget, lines, chars }) {
  for (const n of nodes) {
    if (budget.left <= 0 || chars.v >= maxChars) break;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const { text, inline, ids } = nodeParts(n);
    if (text) {
      const line = `${'  '.repeat(depth)}${sender}: ${text}`;"""
new_fn_sig = """async function flattenNodes(onebot, nodes, { maxItems = 30, maxChars = 2000, depth = 0, budget, lines, chars, gallery }) {
  for (const n of nodes) {
    if (budget.left <= 0 || chars.v >= maxChars) break;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const { text, inline, ids, images } = nodeParts(n);
    // 把这一条里的图片编号，正文里只留 [图1] 这种短标记，直链统一放末尾（省字符）
    let shown = text;
    if (images && images.length) {
      const marks = [];
      for (const u of images) {
        if (gallery.size >= 8) break;           // 最多 8 张，避免撑爆上下文
        const no = gallery.size + 1;
        gallery.set(no, u);
        marks.push(`[图${no}]`);
      }
      shown = shown.replace(/\\[图片\\]/g, () => marks.shift() || '[图片]');
    }
    if (shown) {
      const line = `${'  '.repeat(depth)}${sender}: ${shown}`;"""
assert s.count(old_fn_sig) == 1, 'flattenNodes 锚点不符'
s = s.replace(old_fn_sig, new_fn_sig, 1)

# 递归调用补 gallery
s = s.replace("await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars });",
              "await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars, gallery });")

# ③ 两个入口创建 gallery 并把对照表拼到末尾
old_entry1 = """  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  for (const seg of segments || []) {"""
new_entry1 = """  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  const gallery = new Map();
  for (const seg of segments || []) {"""
assert s.count(old_entry1) == 1, 'flattenSegmentsInline 头部锚点不符'
s = s.replace(old_entry1, new_entry1, 1)
s = s.replace("      await flattenNodes(onebot, d.content, { maxItems, maxChars, depth: 0, budget, lines, chars });",
              "      await flattenNodes(onebot, d.content, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });")
s = s.replace("          await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars });",
              "          await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });")

old_ret2 = """  return { text: lines.join('\\n'), count: lines.length };
}

const BILI_UA ="""
new_ret2 = """  if (gallery.size) {
    const tail = [...gallery.entries()].map(([no, u]) => `图${no} = ${u}`).join('\\n');
    lines.push('[转发里的图片（要看用 view_image 传对应链接）]');
    lines.push(tail);
  }
  return { text: lines.join('\\n'), count: lines.length };
}

const BILI_UA ="""
assert s.count(old_ret2) == 1, 'flatten 返回锚点不符'
s = s.replace(old_ret2, new_ret2, 1)

# readForwardDeep 同样处理
old_rf = """  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars });
  return { text: lines.join('\\n'), count: lines.length, total: nodes.length };"""
new_rf = """  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  const gallery = new Map();
  await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });
  if (gallery.size) {
    lines.push('[转发里的图片（要看用 view_image 传对应链接）]');
    lines.push([...gallery.entries()].map(([no, u]) => `图${no} = ${u}`).join('\\n'));
  }
  return { text: lines.join('\\n'), count: lines.length, total: nodes.length };"""
assert s.count(old_rf) == 1, 'readForwardDeep 锚点不符'
s = s.replace(old_rf, new_rf, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ flatten 现在会保留转发内图片的直链（最多 8 张，正文用 [图N] 标记）')
