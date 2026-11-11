#!/usr/bin/env python3
"""合并转发最终修复：内层正文在 forward 段的 data.content 里（实测 48 条），
直接就地展平，不再依赖 get_forward_msg 拉内层（NapCat 会报"内层消息无法获取"）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

start = s.index("/** 从一条转发节点里取正文（优先 message 数组，退回 raw_message）。 */")
end = s.index("const BILI_UA =")

NEW = r'''/** 从一条转发节点里取正文；遇到嵌套转发返回 {inline: [...子节点]} 或 {id}。 */
function nodeParts(n) {
  const segs = n?.message ?? n?.content ?? n?.data?.content;
  if (Array.isArray(segs) && segs.length) {
    let text = '';
    const inline = [];
    const ids = [];
    for (const seg of segs) {
      const t = seg?.type;
      const d = seg?.data ?? {};
      if (t === 'text') text += d.text ?? '';
      else if (t === 'image') text += '[图片]';
      else if (t === 'face') text += '[表情]';
      else if (t === 'record') text += '[语音]';
      else if (t === 'video') text += '[视频]';
      else if (t === 'file') text += `[文件 ${d.name ?? ''}]`;
      else if (t === 'forward') {
        // 关键：content 里就是内层全部消息（实测 48 条），就地展开不再请求接口
        if (Array.isArray(d.content) && d.content.length) inline.push(d.content);
        else {
          const fid = d.id ?? d.forward_id ?? d.res_id;
          if (fid) ids.push(String(fid));
          text += '[这里面还有一层转发]';
        }
      }
    }
    return { text: text.replace(/\s+/g, ' ').trim(), inline, ids };
  }
  const r = cqToReadable(n?.raw_message ?? n?.content ?? '');
  return { text: r.text, inline: [], ids: r.nested };
}

/**
 * 递归展平一组转发节点（就地展开内层 content；拿不到再按 id 请求一次）。
 */
async function flattenNodes(onebot, nodes, { maxItems = 30, maxChars = 2000, depth = 0, budget, lines, chars }) {
  for (const n of nodes) {
    if (budget.left <= 0 || chars.v >= maxChars) break;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const { text, inline, ids } = nodeParts(n);
    if (text) {
      const line = `${'  '.repeat(depth)}${sender}: ${text}`;
      if (chars.v + line.length > maxChars) break;
      lines.push(line);
      chars.v += line.length;
      budget.left -= 1;
    }
    for (const sub of inline) {
      if (budget.left <= 0 || chars.v >= maxChars) break;
      await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars });
    }
    for (const id of ids) {
      if (budget.left <= 0 || chars.v >= maxChars) break;
      try {
        const payload = await onebot.call('get_forward_msg', { id: String(id), message_id: String(id) }, 30000);
        const sub = payload?.data?.messages || payload?.messages || [];
        await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars });
      } catch (e) {
        lines.push(`${'  '.repeat(depth + 1)}[这一层拿不到：${e?.message ?? e}]`);
      }
    }
  }
}

/** 读取一条合并转发（支持内层就地展开）。 */
export async function readForwardDeep(onebot, id, { maxItems = 30, maxChars = 2000 } = {}) {
  const payload = await onebot.call('get_forward_msg', { id: String(id), message_id: String(id) }, 30000);
  const nodes = payload?.data?.messages || payload?.messages || (Array.isArray(payload) ? payload : []) || [];
  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars });
  return { text: lines.join('\n'), count: lines.length, total: nodes.length };
}

/** 直接把一段 message 段数组（含 forward → content）展平，用于收到消息时自动展开。 */
export async function flattenSegmentsInline(onebot, segments, { maxItems = 24, maxChars = 1500 } = {}) {
  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  for (const seg of segments || []) {
    if (seg?.type !== 'forward') continue;
    const d = seg.data ?? {};
    if (Array.isArray(d.content) && d.content.length) {
      await flattenNodes(onebot, d.content, { maxItems, maxChars, depth: 0, budget, lines, chars });
    } else {
      const fid = d.id ?? d.forward_id ?? d.res_id;
      if (fid) {
        try {
          const payload = await onebot.call('get_forward_msg', { id: String(fid), message_id: String(fid) }, 30000);
          const nodes = payload?.data?.messages || payload?.messages || [];
          await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars });
        } catch (e) {
          lines.push(`[转发拿不到：${e?.message ?? e}]`);
        }
      }
    }
  }
  return { text: lines.join('\n'), count: lines.length };
}

'''
s = s[:start] + NEW + s[end:]
open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js: 内层就地展开（forward.data.content）')

# app.js：自动展开直接用 flattenSegmentsInline(segments)
P2 = r'D:\dshworks\qqbot\qq-agent\src\app.js'
s2 = open(P2, encoding='utf-8').read()
start2 = s2.index("    // 合并转发：自动展开内容写进文本")
end2 = s2.index("    const chatKey = kind + ':' + id;")
NEW2 = """    // 合并转发：自动展开内容写进文本（含内层 content，限条数/字数）
    if (segments && segments.some((x) => x?.type === 'forward')) {
      try {
        const flat = await flattenSegmentsInline(onebot, segments, { maxItems: 24, maxChars: 1500 });
        if (flat.text) text = `${text ? text + '\\n' : ''}[合并转发内容]\\n${flat.text}`;
      } catch (e) {
        log('[转发] 展开失败:', e?.message ?? e);
      }
    }
"""
s2 = s2[:start2] + NEW2 + s2[end2:]
s2 = s2.replace("import { readForwardDeep } from './tools.js';",
                "import { readForwardDeep, flattenSegmentsInline } from './tools.js';", 1)
open(P2, 'w', encoding='utf-8').write(s2)
print('✓ app.js: 自动展开改为 flattenSegmentsInline')
