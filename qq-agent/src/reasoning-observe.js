// 推理内容观测：把模型每轮的 reasoning 单独记一份 JSONL，用来统计"思考的口吻"。
// 背景：DeepSeek 目前不支持给 reasoning 预填充前缀（实测 4 种传法都被忽略），
// 所以先做纯观测——看它是否书面腔、是否和最终回复同构，再决定要不要干预。
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR, getConfig } from './config.js';

const FILE = path.join(DATA_DIR, 'reasoning.jsonl');
const MAX_BYTES = 4 * 1024 * 1024;

function enabled() {
  try {
    return getConfig()?.observe?.reasoning !== false;
  } catch {
    return true;
  }
}

export function recordReasoning(chatKey, text) {
  if (!enabled()) return;
  const body = String(text || '').trim();
  if (!body) return;
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    try {
      const st = fs.statSync(FILE);
      if (st.size > MAX_BYTES) fs.renameSync(FILE, FILE + '.1');
    } catch { /* 文件还不存在 */ }
    const row = {
      ts: Date.now(),
      chatKey: String(chatKey || ''),
      chars: body.length,
      // 只留 1500 字，够看口吻和长度；真要看全文再去会话记录里找
      text: body.slice(0, 1500)
    };
    fs.appendFileSync(FILE, JSON.stringify(row) + '\n', 'utf8');
  } catch { /* 记不下来就算了，绝不影响对话 */ }
}

/** 粗略统计：书面腔词、口语词、长度、和回复是否同长。 */
export function reasoningStats(limit = 300) {
  let rows = [];
  try {
    const lines = fs.readFileSync(FILE, 'utf8').split('\n').filter(Boolean);
    rows = lines.slice(-limit).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch {
    return { samples: 0 };
  }
  if (!rows.length) return { samples: 0 };
  const bookish = /用户|需要|应当|综上|因此|目的是|避免|确保|保持|引导|策略|分析|场景|语气轻松|简洁自然/;
  const spoken = /嗯|啊|吧|嘛|哈哈|草|有点|感觉|好像|这不|咋|啥呢/;
  const hits = rows.map((r) => ({
    chars: r.chars,
    book: (r.text.match(new RegExp(bookish.source, 'g')) || []).length,
    spok: (r.text.match(new RegExp(spoken.source, 'g')) || []).length,
    text: r.text
  }));
  const avg = (arr) => Math.round((arr.reduce((a, b) => a + b, 0) / arr.length) * 10) / 10;
  return {
    samples: rows.length,
    from: new Date(rows[0].ts).toISOString(),
    to: new Date(rows[rows.length - 1].ts).toISOString(),
    avgChars: avg(hits.map((h) => h.chars)),
    avgBookishPer100Chars: Math.round((hits.reduce((a, h) => a + h.book, 0) / hits.reduce((a, h) => a + h.chars, 0)) * 1000) / 10,
    avgSpokenPer100Chars: Math.round((hits.reduce((a, h) => a + h.spok, 0) / hits.reduce((a, h) => a + h.chars, 0)) * 1000) / 10,
    samplesWithSpoken: hits.filter((h) => h.spok > 0).length,
    longest: hits.sort((a, b) => b.chars - a.chars).slice(0, 2).map((h) => ({ chars: h.chars, head: h.text.slice(0, 120) }))
  };
}
