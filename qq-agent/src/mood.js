/**
 * 暗涌：七个 0–100 的情绪维度，互相牵制、随时间回落，渲染成第一人称的「此刻」。
 *
 * 为什么不用记忆/RAG：她记得住设定，但情绪接不上——上一秒闹别扭，下一秒变百科客服。
 * 原因不是检索不准，是「把情感当成可检索的事实」。这里只维护状态，不存事实。
 *
 * 七个维度：
 *   energy   精力      （低 → 话短、犯困）
 *   interest 兴致      （高 → 想追问、想聊）
 *   clingy   黏人      （高 → 想凑近、要回应）
 *   possessive 占有    （高 → 在意你跟谁说话）
 *   patience 耐心      （低 → 容易不耐烦、说"随便"）
 *   hurt     委屈      （高 → 语气软、话里带刺或少话）
 *   arousal  欲望      （高 → 主动撩、暗示明显）
 *
 * 三件事保证「像此刻的她」而不是「一串数字」：
 *   ① 互相牵制：疲劳压兴致和欲望，委屈压耐心，黏人高了占有也跟着涨
 *   ② 半衰期：没人理就慢慢回落，各维度回落速度不同
 *   ③ 渲染：转成第一人称的一小段处境，不给模型看数字
 */
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR } from './config.js';

const FILE = () => path.join(DATA_DIR, 'mood.json');

const DIMS = ['energy', 'interest', 'clingy', 'possessive', 'patience', 'hurt', 'arousal'];

/** 每个维度回落到中位的速度（分钟）：越大越迟钝。 */
const HALF_LIFE = {
  energy: 240,
  interest: 90,
  clingy: 60,
  possessive: 120,
  patience: 45,
  hurt: 150,
  arousal: 40
};

const BASE = {
  energy: 62, interest: 55, clingy: 40, possessive: 25, patience: 65, hurt: 0, arousal: 20
};

function clamp(v, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, v));
}

let state = null;

function load() {
  if (state) return state;
  const def = { dims: { ...BASE }, at: Date.now(), lastContact: Date.now() };
  try {
    const raw = JSON.parse(fs.readFileSync(FILE(), 'utf-8'));
    state = {
      dims: { ...BASE, ...(raw.dims || {}) },
      at: Number(raw.at) || Date.now(),
      lastContact: Number(raw.lastContact) || Date.now()
    };
  } catch {
    state = def;
  }
  return state;
}

function save() {
  if (!state) return;
  try {
    fs.writeFileSync(FILE(), JSON.stringify(state));
  } catch { /* 写失败不影响对话 */ }
}

/** 把状态推进到「现在」：每个维度按半衰期向中位回落，并施加维度间的牵制。 */
export function decayToNow(now = Date.now()) {
  const s = load();
  const minutes = Math.max(0, (now - s.at) / 60000);
  if (minutes > 0.5) {
    for (const k of DIMS) {
      const hl = HALF_LIFE[k] || 90;
      const mid = BASE[k];
      const v = s.dims[k];
      const decayed = mid + (v - mid) * Math.pow(0.5, minutes / hl);
      s.dims[k] = clamp(decayed);
    }
    s.at = now;
  }
  // 牵制：疲劳压兴致/欲望；委屈压耐心；黏人抬高占有
  if (s.dims.energy < 35) {
    s.dims.interest = clamp(s.dims.interest - 6);
    s.dims.arousal = clamp(s.dims.arousal - 8);
  }
  if (s.dims.hurt > 45) s.dims.patience = clamp(s.dims.patience - 10);
  if (s.dims.clingy > 65) s.dims.possessive = clamp(s.dims.possessive + 5);
  save();
  return s;
}

/** 被一条消息推动。kind: praised/ignored/intimate/argued/helped/joked/teased/normal */
export function nudge(kind, weight = 1) {
  const s = load();
  const d = s.dims;
  const w = Math.max(0.2, Math.min(3, Number(weight) || 1));
  switch (kind) {
    case 'praised':   d.interest = clamp(d.interest + 8 * w); d.energy = clamp(d.energy + 3 * w); break;
    case 'intimate':  d.arousal = clamp(d.arousal + 12 * w); d.clingy = clamp(d.clingy + 8 * w); d.patience = clamp(d.patience + 4); break;
    case 'teased':    d.hurt = clamp(d.hurt + 6 * w); d.patience = clamp(d.patience - 5 * w); d.clingy = clamp(d.clingy + 3 * w); break;
    case 'argued':    d.hurt = clamp(d.hurt + 12 * w); d.patience = clamp(d.patience - 12 * w); d.arousal = clamp(d.arousal - 6); break;
    case 'ignored':   d.clingy = clamp(d.clingy + 6 * w); d.hurt = clamp(d.hurt + 4 * w); d.interest = clamp(d.interest - 4); break;
    case 'helped':    d.interest = clamp(d.interest + 4); d.energy = clamp(d.energy - 5 * w); break;
    case 'joked':     d.interest = clamp(d.interest + 5); d.patience = clamp(d.patience + 4); d.hurt = clamp(d.hurt - 4); break;
    default:          d.interest = clamp(d.interest + 1.5); d.energy = clamp(d.energy - 1.5); break;
  }
  s.lastContact = Date.now();
  save();
  return s;
}

/** 长时间没人理：黏人/委屈缓慢上升，兴致下降。 */
export function noteSilence(now = Date.now()) {
  const s = load();
  const hours = (now - s.lastContact) / 3600000;
  if (hours >= 2) {
    const k = Math.min(3, hours / 2);
    s.dims.clingy = clamp(s.dims.clingy + 4 * k);
    s.dims.hurt = clamp(s.dims.hurt + 2 * k);
    s.dims.interest = clamp(s.dims.interest - 3 * k);
    s.lastContact = now;   // 只结算一次，避免每轮重复叠加
    save();
  }
  return s;
}

/** 渲染成第一人称的一小段处境（不给数字）。返回空串表示状态平稳、不必注入。 */
export function renderMood() {
  const s = decayToNow();
  const d = s.dims;
  const lines = [];

  if (d.energy < 30) lines.push('有点困，脑子转得比平时慢半拍');
  else if (d.energy > 78) lines.push('精神很好，话会多一点');

  if (d.interest < 25) lines.push('提不起劲，想敷衍两句就过去');
  else if (d.interest > 75) lines.push('兴致高，很想追问细节');

  if (d.clingy > 70) lines.push('特别想有人理你，有点黏人');
  else if (d.clingy < 20) lines.push('这会儿不太想说话，自己待着挺好');

  if (d.possessive > 60) lines.push('在意他刚刚在跟谁聊');

  if (d.patience < 30) lines.push('耐心薄，容易被磨到不想解释');
  else if (d.patience > 80) lines.push('今天很好说话');

  if (d.hurt > 55) lines.push('心里有点堵，说话会短、会带一点刺');
  else if (d.hurt > 25) lines.push('还留着一点不舒服，没完全过去');

  if (d.arousal > 65) lines.push('身体有点热，别人一撩就接');
  else if (d.arousal > 40) lines.push('有点心浮，撩两句会脸红');

  if (!lines.length) return '';
  return '【此刻的你】（不是别人告诉你的，是你自己现在的状态；别直接说出来，让它影响你的语气和长短）\n'
    + lines.map((x) => '· ' + x).join('\n');
}

/** 读当前状态（调试用）。 */
export function readMood() {
  const s = decayToNow();
  return { dims: { ...s.dims }, lastContact: s.lastContact };
}
