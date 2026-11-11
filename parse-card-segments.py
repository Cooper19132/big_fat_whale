#!/usr/bin/env python3
"""① 卡片消息解析：从 OneBot 的 json/ark 段里提取标题、描述、链接。

原来只输出一句「[卡片消息]」，标题和 URL 全丢，导致她说「打不开内容」。
现在：
  - segmentsToText  → "[卡片] 标题 - 描述 链接"
  - extractMediaFromSegments → 追加 {kind:'card', title, desc, url}

QQ 的卡片结构有好几种，统一用「递归找第一个带 title/desc/jumpUrl 的对象」兜底。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\onebot.js'
s = open(P, encoding='utf-8').read()
result = []

# ── 1) 插入解析辅助函数（放在 extractMediaFromSegments 之前） ──
anchor = 'export function extractMediaFromSegments(segments) {'
assert s.count(anchor) == 1, 'extractMediaFromSegments 锚点不符'

helper = '''/** 在卡片 JSON 里递归找第一个带 title 的对象（QQ 卡片结构五花八门）。 */
function findCardNode(node, depth = 0) {
  if (!node || typeof node !== 'object' || depth > 6) return null;
  if (typeof node.title === 'string' && node.title.trim()) return node;
  for (const v of Object.values(node)) {
    const hit = findCardNode(v, depth + 1);
    if (hit) return hit;
  }
  return null;
}

/** 解析卡片段（json / ark）→ { title, desc, url } ；解析不出来返回 null。 */
export function parseCardSegment(data) {
  let obj = data;
  if (typeof obj === 'string') {
    const raw = obj.trim();
    if (!raw) return null;
    try { obj = JSON.parse(raw); } catch { return null; }
  }
  if (!obj || typeof obj !== 'object') return null;
  let node = findCardNode(obj, 0);
  // ark 段常见结构：{ app, desc, prompt, meta }，没有 title 时用 prompt 兜底
  const prompt = typeof obj.prompt === 'string' ? obj.prompt.trim() : '';
  if (!node && !prompt) return null;
  const pick = (...keys) => {
    for (const k of keys) {
      const v = node?.[k];
      if (typeof v === 'string' && v.trim()) return v.trim();
    }
    return '';
  };
  const title = pick('title', 'name', 'nickname') || prompt.replace(/^\\[/, '').replace(/\\]$/, '');
  const desc = pick('desc', 'summary', 'content');
  const url = pick('jumpUrl', 'jump_url', 'qqdocurl', 'url', 'link');
  if (!title && !url) return null;
  return { title, desc, url };
}

'''

s = s.replace(anchor, helper + anchor, 1)
result.append('✓ onebot.js 新增 parseCardSegment')

# ── 2) segmentsToText：json 段输出标题/描述/链接 ──
old_case = "      case 'json': out.push('[卡片消息]'); break;"
assert s.count(old_case) == 1, 'json 分支锚点不符'
new_case = """      case 'json': {
        const card = parseCardSegment(d.data ?? d);
        if (card) {
          const bits = [`[卡片]${card.title}`];
          if (card.desc) bits.push(card.desc);
          if (card.url) bits.push(card.url);
          out.push(bits.join(' | '));
        } else {
          out.push('[卡片消息]');
        }
        break;
      }
      case 'ark': {
        const card2 = parseCardSegment(d.data ?? d);
        out.push(card2 ? `[卡片]${card2.title}${card2.url ? ' | ' + card2.url : ''}` : '[卡片消息]');
        break;
      }"""
s = s.replace(old_case, new_case, 1)
result.append('✓ segmentsToText 解析卡片标题/描述/链接')

# ── 3) extractMediaFromSegments：卡片存进 media ──
old_media = """    } else if (seg.type === 'video') {
      media.push({ kind: 'video', file: String(d.file ?? ''), url: String(d.url ?? '') });
    }
  }"""
assert s.count(old_media) == 1, 'video 分支锚点不符'
new_media = """    } else if (seg.type === 'video') {
      media.push({ kind: 'video', file: String(d.file ?? ''), url: String(d.url ?? '') });
    } else if (seg.type === 'json' || seg.type === 'ark') {
      const card = parseCardSegment(d.data ?? d);
      if (card) {
        media.push({ kind: 'card', title: card.title, desc: card.desc, url: card.url });
      }
    }
  }"""
s = s.replace(old_media, new_media, 1)
result.append('✓ extractMediaFromSegments 存卡片')

open(P, 'w', encoding='utf-8').write(s)
print('\n'.join(result))
