// 群里收到的斗图/表情包自动入库（"待认领"池）。
// 设计取向来自几个成熟实现（astrbot_plugin_stealer / nonebot-plugin-sticker-collector）：
//   - 只收"表情"类图片（image 段的 sub_type=1、商城 mface），普通照片/截图不收；
//   - 内容哈希去重，文件按哈希命名，元数据（谁发的、哪个群、什么时候）留在条目里；
//   - 一律进 pending：不进提示词、不许直接发；她要先 get_sticker_image 看图 + sticker_note
//     写一句"这是什么表情"，才算认领（labeled），之后 send_sticker 才放行。
// 这样不会因为她瞎发一堆自己都不认识的图而显得抽风。
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { DATA_DIR, getConfig } from './config.js';
import { loadStickerStore, saveStickerStore, nowIso } from './stickers.js';

const STICKER_DIR = path.join(DATA_DIR, 'stickers');
const STATE_FILE = path.join(DATA_DIR, 'sticker-autocollect.json');

const MAGIC = [
  { ext: 'jpg', test: (b) => b.length > 3 && b[0] === 0xff && b[1] === 0xd8 && b[2] === 0xff },
  { ext: 'png', test: (b) => b.length > 8 && b.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) },
  { ext: 'gif', test: (b) => b.length > 6 && b.subarray(0, 3).toString('latin1') === 'GIF' },
  { ext: 'webp', test: (b) => b.length > 12 && b.subarray(0, 4).toString('latin1') === 'RIFF' && b.subarray(8, 12).toString('latin1') === 'WEBP' },
  { ext: 'bmp', test: (b) => b.length > 2 && b.subarray(0, 2).toString('latin1') === 'BM' }
];

function settings() {
  const cfg = getConfig()?.sticker?.autoCollect || {};
  return {
    enabled: cfg.enabled !== false,
    minBytes: Math.max(0, Number(cfg.minBytes ?? 1024)),
    maxBytes: Math.max(1024, Number(cfg.maxBytes ?? 5242880)),
    perChatDailyCap: Math.max(0, Number(cfg.perChatDailyCap ?? 80)),
    globalMax: Math.max(1, Number(cfg.globalMax ?? 300)),
    timeoutMs: Math.max(2000, Number(cfg.timeoutMs ?? 15000)),
    maxPerMessage: Math.max(1, Math.min(4, Number(cfg.maxPerMessage ?? 2)))
  };
}

function dayKey() {
  return new Date().toISOString().slice(0, 10);
}

export function loadState() {
  try {
    const parsed = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
    return {
      seen: parsed?.seen && typeof parsed.seen === 'object' ? parsed.seen : {},
      day: String(parsed?.day || ''),
      perChat: parsed?.perChat && typeof parsed.perChat === 'object' ? parsed.perChat : {}
    };
  } catch {
    return { seen: {}, day: '', perChat: {} };
  }
}

export function saveState(state) {
  try {
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    // seen 只留最近 4000 条，避免无限增长
    const keys = Object.keys(state.seen || {});
    if (keys.length > 4000) {
      keys.sort((a, b) => (state.seen[a] || 0) - (state.seen[b] || 0));
      for (const k of keys.slice(0, keys.length - 4000)) delete state.seen[k];
    }
    fs.writeFileSync(STATE_FILE, JSON.stringify(state), 'utf8');
  } catch { /* 记账失败不影响主流程 */ }
}

export function sniffImage(buffer) {
  for (const item of MAGIC) {
    try { if (item.test(buffer)) return item.ext; } catch { /* 忽略 */ }
  }
  return '';
}

/** 判断一条 media 是不是"表情/斗图"而不是普通照片。 */
export function isStickerMedia(media) {
  if (!media || media.kind !== 'image') return false;
  if (Number(media.subType ?? 0) === 1) return true;      // OneBot/NapCat: sub_type=1 = 表情
  if (media.mface === true) return true;                  // 商城表情
  const summary = String(media.summary || '');
  if (/动画表情|表情|贴纸|meme/i.test(summary)) return true;
  return false;
}

async function downloadBuffer(url, timeoutMs) {
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'image/*,*/*' },
    signal: AbortSignal.timeout(timeoutMs)
  });
  if (!res.ok) throw new Error(`下载失败 HTTP ${res.status}`);
  const buf = Buffer.from(await res.arrayBuffer());
  return buf;
}

function hashOf(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function pruneOverflow(entries, globalMax) {
  const autos = entries.filter((e) => e.source === 'auto');
  if (autos.length <= globalMax) return [];
  // 先删最老的 pending，再删最老的整体
  const removed = [];
  const sorted = [...autos].sort((a, b) => String(a.createdAt).localeCompare(String(b.createdAt)));
  const need = autos.length - globalMax;
  const victims = [
    ...sorted.filter((e) => e.status !== 'labeled'),
    ...sorted.filter((e) => e.status === 'labeled')
  ].slice(0, need);
  for (const victim of victims) {
    const idx = entries.findIndex((e) => e.id === victim.id);
    if (idx >= 0) entries.splice(idx, 1);
    try {
      if (victim.localFile) fs.unlinkSync(path.join(DATA_DIR, victim.localFile));
    } catch { /* 文件早没了就算了 */ }
    removed.push(victim.id);
  }
  return removed;
}

/**
 * 把一条消息里"像表情"的图片落盘入池。永不抛错（调用方是 fire-and-forget）。
 * @returns {Promise<{added: string[], skipped: string[]}>}
 */
export async function autoCollectIncoming({ chatKey, media, senderId = '', senderName = '', mid = null } = {}) {
  const out = { added: [], skipped: [] };
  try {
    const cfg = settings();
    if (!cfg.enabled) { out.skipped.push('disabled'); return out; }
    const candidates = (Array.isArray(media) ? media : [])
      .filter(isStickerMedia)
      .filter((m) => m.url)
      .slice(0, cfg.maxPerMessage);
    if (!candidates.length) return out;

    const state = loadState();
    const today = dayKey();
    if (state.day !== today) { state.day = today; state.perChat = {}; }
    const chatStat = state.perChat[chatKey] || { day: today, count: 0 };
    if (chatStat.day !== today) { chatStat.day = today; chatStat.count = 0; }

    const entries = loadStickerStore();
    const known = new Set(entries.map((e) => e.id));
    const hashSet = new Set(entries.map((e) => String(e.hash || '')).filter(Boolean));

    for (const mediaItem of candidates) {
      if (cfg.perChatDailyCap > 0 && chatStat.count >= cfg.perChatDailyCap) {
        out.skipped.push('per-chat-cap');
        break;
      }
      let buf;
      try {
        buf = await downloadBuffer(mediaItem.url, cfg.timeoutMs);
      } catch (error) {
        out.skipped.push(`download:${String(error?.message ?? error).slice(0, 60)}`);
        continue;
      }
      if (buf.length < cfg.minBytes) { out.skipped.push('too-small'); continue; }
      if (buf.length > cfg.maxBytes) { out.skipped.push('too-large'); continue; }
      const ext = sniffImage(buf);
      if (!ext) { out.skipped.push('unsupported-format'); continue; }
      const fullHash = hashOf(buf);
      const hash8 = fullHash.slice(0, 8);
      const id = `auto_${hash8}`;
      if (known.has(id) || hashSet.has(fullHash) || state.seen[hash8]) {
        out.skipped.push('duplicate');
        continue;
      }

      fs.mkdirSync(STICKER_DIR, { recursive: true });
      const fileName = `${id}.${ext}`;
      const abs = path.join(STICKER_DIR, fileName);
      fs.writeFileSync(abs, buf);

      entries.push({
        id,
        resId: id,
        url: '',
        md5: '',
        desc: '',
        localNote: '',
        tags: [],
        usage: '',
        source: 'auto',
        status: 'pending',
        hash: fullHash,
        bytes: buf.length,
        localFile: path.posix.join('stickers', fileName),
        from: { chatKey, senderId: String(senderId || ''), senderName: String(senderName || ''), mid: mid == null ? null : String(mid) },
        useCount: 0,
        lastUsedAt: 0,
        lastContext: '',
        createdAt: nowIso(),
        updatedAt: nowIso()
      });
      known.add(id);
      hashSet.add(fullHash);
      state.seen[hash8] = Date.now();
      chatStat.count += 1;
      out.added.push(id);
    }

    if (out.added.length) {
      pruneOverflow(entries, cfg.globalMax);
      saveStickerStore(entries);
    }
    state.perChat[chatKey] = chatStat;
    saveState(state);
  } catch (error) {
    out.skipped.push(`error:${String(error?.message ?? error).slice(0, 80)}`);
  }
  return out;
}

/** 统计（面板/自检用）：自动收了多少、其中待认领多少。 */
export function autoCollectStats() {
  try {
    const entries = loadStickerStore();
    const autos = entries.filter((e) => e.source === 'auto');
    return {
      total: autos.length,
      pending: autos.filter((e) => e.status !== 'labeled').length,
      labeled: autos.filter((e) => e.status === 'labeled').length
    };
  } catch {
    return { total: 0, pending: 0, labeled: 0 };
  }
}
