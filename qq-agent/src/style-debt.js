/**
 * 文风账：群友/主人当面指出「八股」「AI 味」「端着」时，记一笔。
 *
 * 为什么要有这个：光在群里喊一句「注意八股」，模型下一轮就忘了——
 * 喊话是对话里的一次性事件，不进持久状态。这里把喊话变成一条可累积的记录，
 * 下一轮构造提示词时带出来，让她自己看得见「我被指出过几次」。
 */
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR } from './config.js';

const FILE = path.join(DATA_DIR, 'style-debt.json');
const KEEP_DAYS = 7;

/** 判定「被指出文风问题」的关键词。宁可漏，不要误伤正常聊天。 */
const COMPLAINT = /八股|AI\s*味|ai\s*味|端着|模板腔|大模型味|不像(?:人|活人)|机器人腔|又在摆谱/;

function read() {
  try {
    const raw = fs.readFileSync(FILE, 'utf8');
    const data = JSON.parse(raw);
    if (data && Array.isArray(data.hits)) return data;
  } catch { /* 没有就从头记 */ }
  return { hits: [] };
}

function write(data) {
  try {
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    fs.writeFileSync(FILE, JSON.stringify(data));
  } catch { /* 记账失败不能影响说话 */ }
}

/**
 * 从这一轮的触发消息里找「被指出八股」。同一条消息只记一次（按 mid 去重）。
 * @returns {number} 这次新记了几笔
 */
export function noteStyleComplaint(triggerEntries, selfId) {
  if (!Array.isArray(triggerEntries) || !triggerEntries.length) return 0;
  const data = read();
  const seen = new Set(data.hits.map((h) => String(h.mid)));
  let added = 0;
  for (const m of triggerEntries) {
    if (!m || m.self) continue;
    if (selfId != null && String(m.senderId) === String(selfId)) continue;
    const text = String(m.text || '');
    if (!COMPLAINT.test(text)) continue;
    const mid = String(m.mid ?? m.id ?? '');
    if (mid && seen.has(mid)) continue;
    seen.add(mid);
    data.hits.push({
      at: Date.now(),
      mid,
      senderId: String(m.senderId ?? ''),
      senderName: String(m.senderName ?? ''),
      text: text.slice(0, 60)
    });
    added += 1;
  }
  if (added) {
    const cutoff = Date.now() - KEEP_DAYS * 86400000;
    data.hits = data.hits.filter((h) => h.at >= cutoff).slice(-30);
    write(data);
  }
  return added;
}

/**
 * 给提示词用的一句话；最近 7 天没人提过就返回空字符串（不要每轮都念）。
 */
export function styleDebtSummary() {
  const data = read();
  const cutoff = Date.now() - KEEP_DAYS * 86400000;
  const hits = data.hits.filter((h) => h.at >= cutoff);
  if (!hits.length) return '';
  const last = hits[hits.length - 1];
  const who = last.senderName || '有人';
  const when = new Date(last.at);
  const hh = String(when.getHours()).padStart(2, '0');
  const mm = String(when.getMinutes()).padStart(2, '0');
  return `最近 ${KEEP_DAYS} 天里，被人当面说说话八股/端着 ${hits.length} 次。最近一次是 ${who} 在 ${hh}:${mm} 说的：「${last.text}」。` +
    '这一轮别再摆那套结构，也不用道歉表态——直接说得具体点就行。';
}
