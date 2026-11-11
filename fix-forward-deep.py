#!/usr/bin/env python3
"""修复合并转发读取：支持嵌套转发（raw_message 里的 [CQ:forward,id=...]）。

实测 NapCat 返回结构：
  { data: { messages: [ { sender:{nickname,card}, raw_message:"[CQ:forward,id=xxx,...]" | 文本 } ] } }
正文可能在下一层转发里，所以要按 id 递归拉取（深度上限 4）。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

start = s.index("/** 把合并转发的 resData 展平成「昵称: 内容」多行文本（有上限）。 */")
end = s.index("const BILI_UA =")

NEW = r'''/** 把一条 raw_message（CQ 码）转成可读文本；遇到嵌套转发返回其 id。 */
function cqToReadable(raw) {
  let text = String(raw ?? '');
  const nested = [];
  text = text.replace(/\[CQ:forward,id=([^,\]]+)[^\]]*\]/g, (_, id) => {
    nested.push(String(id));
    return '[这里面还有一层转发]';
  });
  text = text
    .replace(/\[CQ:image[^\]]*\]/g, '[图片]')
    .replace(/\[CQ:face[^\]]*\]/g, '[表情]')
    .replace(/\[CQ:record[^\]]*\]/g, '[语音]')
    .replace(/\[CQ:video[^\]]*\]/g, '[视频]')
    .replace(/\[CQ:file[^\]]*\]/g, '[文件]')
    .replace(/\[CQ:at,qq=([^\]]+)\]/g, '@$1')
    .replace(/\[CQ:[^\]]*\]/g, '')
    .replace(/&#91;/g, '[').replace(/&#93;/g, ']').replace(/&#44;/g, ',')
    .replace(/&amp;/g, '&');
  return { text: text.replace(/\s+/g, ' ').trim(), nested };
}

/** 从一条转发节点里取正文（优先 message 数组，退回 raw_message）。 */
function nodeText(n) {
  const segs = n?.message ?? n?.content ?? n?.data?.content;
  if (Array.isArray(segs) && segs.length) {
    let text = '';
    const nested = [];
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
        const fid = d.id ?? d.forward_id ?? d.res_id;
        if (fid) { nested.push(String(fid)); text += '[这里面还有一层转发]'; }
      }
    }
    return { text: text.replace(/\s+/g, ' ').trim(), nested };
  }
  return cqToReadable(n?.raw_message ?? n?.content ?? '');
}

/**
 * 递归读取合并转发（含嵌套层）。
 * @returns {Promise<{text:string,count:number,total:number,depth:number}>}
 */
export async function readForwardDeep(onebot, id, { maxItems = 30, maxChars = 2000, depth = 0, budget = { left: maxItems } } = {}) {
  const lines = [];
  let total = 0;
  let chars = 0;
  if (depth > 4 || budget.left <= 0 || !id) return { text: '', count: 0, total: 0, depth };

  const payload = await onebot.call('get_forward_msg', { id: String(id), message_id: String(id) }, 30000);
  const nodes = payload?.data?.messages || payload?.messages || (Array.isArray(payload) ? payload : []) || [];
  total = nodes.length;

  for (const n of nodes) {
    if (budget.left <= 0 || chars >= maxChars) break;
    if (depth === 0) budget.left -= 1;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const { text, nested } = nodeText(n);
    if (text) {
      const line = `${'  '.repeat(depth)}${sender}: ${text}`;
      if (chars + line.length > maxChars) break;
      lines.push(line);
      chars += line.length;
    }
    for (const nid of nested) {
      if (budget.left <= 0 || chars >= maxChars) break;
      try {
        const sub = await readForwardDeep(onebot, nid, { maxItems, maxChars: maxChars - chars, depth: depth + 1, budget });
        if (sub.text) {
          lines.push(sub.text);
          chars += sub.text.length;
        }
      } catch (e) {
        lines.push(`${'  '.repeat(depth + 1)}[这一层拉取失败：${e?.message ?? e}]`);
      }
    }
  }
  return { text: lines.join('\n'), count: lines.length, total, depth };
}

'''
s = s[:start] + NEW + s[end:]

# read_forward 工具改用递归版
old_tool = """          const payload = await ctx.onebot.call('get_forward_msg', { id: fid, message_id: fid }, 30000);
          const flat = flattenForward(payload);
          if (!flat.count) return err('这条转发没读出内容（可能是空记录或 NapCat 不支持）');
          return ok(`合并转发共 ${flat.total} 条，读出前 ${flat.count} 条：\\n${flat.text}`);"""
new_tool = """          const flat = await readForwardDeep(ctx.onebot, fid, { maxItems: 30, maxChars: 2500 });
          if (!flat.text) return err('这条转发没读出内容（可能全是图片，或 NapCat 不支持）');
          return ok(`合并转发（含嵌套层）读出 ${flat.count} 行：\\n${flat.text}`);"""
assert s.count(old_tool) == 1, f'工具锚点 {s.count(old_tool)} 处'
s = s.replace(old_tool, new_tool, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ tools.js: 改为 readForwardDeep（支持嵌套）')

# app.js 自动展开也改用递归版
P2 = r'D:\dshworks\qqbot\qq-agent\src\app.js'
s2 = open(P2, encoding='utf-8').read()
old2 = """          const payload = await onebot.call('get_forward_msg', { id: fid, message_id: fid }, 20000);
          const flat = flattenForward(payload, { maxItems: 30, maxChars: 1500 });
          if (flat.count) parts.push(`[合并转发 ${flat.total} 条，选读 ${flat.count} 条]\\n${flat.text}`);"""
new2 = """          const flat = await readForwardDeep(onebot, fid, { maxItems: 24, maxChars: 1500 });
          if (flat.text) parts.push(`[合并转发（含嵌套）]\\n${flat.text}`);"""
assert s2.count(old2) == 1, f'app 锚点 {s2.count(old2)} 处'
s2 = s2.replace(old2, new2, 1)
s2 = s2.replace("import { flattenForward } from './tools.js';", "import { readForwardDeep } from './tools.js';", 1)
open(P2, 'w', encoding='utf-8').write(s2)
print('✓ app.js: 自动展开改用 readForwardDeep')
