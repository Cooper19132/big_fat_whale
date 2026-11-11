#!/usr/bin/env python3
"""让小鲸鱼能读「合并转发」的内容。

改动：
1) onebot.js：把 forward 段抽成 media {kind:'forward', id}
2) tools.js：新增 read_forward 工具（按 id 拉取并展平成文本）
3) app.js：收到合并转发时自动展开（限 30 条 / 2000 字），写进消息文本
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ---------- 1) onebot.js: 媒体提取里加 forward ----------
P1 = r'D:\dshworks\qqbot\qq-agent\src\onebot.js'
s1 = open(P1, encoding='utf-8').read()
old1 = """    } else if (seg.type === 'json' || seg.type === 'ark') {
      const card = parseCardSegment(d.data ?? d);
      if (card) {
        media.push({ kind: 'card', title: card.title, desc: card.desc, url: card.url });
      }
    }"""
new1 = """    } else if (seg.type === 'json' || seg.type === 'ark') {
      const card = parseCardSegment(d.data ?? d);
      if (card) {
        media.push({ kind: 'card', title: card.title, desc: card.desc, url: card.url });
      }
    } else if (seg.type === 'forward') {
      const fid = forwardIdFromData(d);
      if (fid) media.push({ kind: 'forward', id: String(fid) });
    }"""
assert s1.count(old1) == 1, 'onebot 媒体锚点不符'
open(P1, 'w', encoding='utf-8').write(s1.replace(old1, new1, 1))
print('✓ onebot.js: forward 段 → media')

# ---------- 2) tools.js: 新增 read_forward + 展平函数 ----------
P2 = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s2 = open(P2, encoding='utf-8').read()

helper = r'''/** 把合并转发的 resData 展平成「昵称: 内容」多行文本（有上限）。 */
export function flattenForward(payload, { maxItems = 30, maxChars = 2000 } = {}) {
  const nodes = payload?.messages
    || payload?.data?.messages
    || payload?.message
    || (Array.isArray(payload) ? payload : [])
    || [];
  const out = [];
  let chars = 0;
  for (const n of nodes) {
    if (out.length >= maxItems || chars >= maxChars) break;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const segs = n?.message ?? n?.content ?? [];
    let text = '';
    if (typeof segs === 'string') {
      text = segs;
    } else if (Array.isArray(segs)) {
      for (const seg of segs) {
        const t = seg?.type;
        const d = seg?.data ?? {};
        if (t === 'text') text += d.text ?? '';
        else if (t === 'image') text += '[图片]';
        else if (t === 'face') text += '[表情]';
        else if (t === 'record') text += '[语音]';
        else if (t === 'video') text += '[视频]';
        else if (t === 'file') text += `[文件 ${d.name ?? ''}]`;
        else if (t === 'forward') text += '[嵌套转发]';
      }
    }
    text = String(text).replace(/\s+/g, ' ').trim();
    if (!text) continue;
    const line = `${sender}: ${text}`;
    if (chars + line.length > maxChars) break;
    out.push(line);
    chars += line.length;
  }
  return { text: out.join('\n'), count: out.length, total: nodes.length };
}

'''
anchor2 = "const BILI_UA ="
assert s2.count(anchor2) == 1
s2 = s2.replace(anchor2, helper + anchor2, 1)

TOOL = r'''    {
      name: 'read_forward',
      description: '读「合并转发」聊天记录的内容。消息里出现 [转发消息 id=xxx] 或对方发来一坨转发记录时用它，传那个 id（或消息的 #数字）。返回每条「谁说了什么」，最多 30 条。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: '转发消息 id，或当前会话里消息的 #数字' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        const raw = String(args.target || '').trim();
        if (!raw) return err('要读哪条转发？把 id 或消息的 #数字给我');
        let fid = raw.replace(/^#/, '');
        if (/^\d+$/.test(fid)) {
          const entry = ctx.store.findByMid(ctx.chatKey, fid);
          const fw = (entry?.media || []).find((m) => m.kind === 'forward');
          if (fw?.id) fid = fw.id;
        }
        try {
          const payload = await ctx.onebot.call('get_forward_msg', { id: fid, message_id: fid }, 30000);
          const flat = flattenForward(payload);
          if (!flat.count) return err('这条转发没读出内容（可能是空记录或 NapCat 不支持）');
          return ok(`合并转发共 ${flat.total} 条，读出前 ${flat.count} 条：\n${flat.text}`);
        } catch (e) {
          return err(`读转发失败：${e?.message ?? e}`);
        }
      }
    },
'''
anchor3 = "    {\n      name: 'watch_video',"
assert s2.count(anchor3) == 1
s2 = s2.replace(anchor3, TOOL + anchor3, 1)
open(P2, 'w', encoding='utf-8').write(s2)
print('✓ tools.js: 新增 flattenForward + read_forward 工具')
