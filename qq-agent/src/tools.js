// 原生工具集（OpenAI function calling 格式）。
// 与原版 MCP 工具的关键区别：每个工具自动绑定本次运行对应的会话（chatKey），
// 不再需要 key/token 参数 —— 模型物理上无法把消息发到别的群/私聊，安全性反而更强。
//
// 工具命名去掉了 qq_ 前缀（更短，省 token）。
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { getConfig, ROOT, DATA_DIR } from './config.js';
import { normalizeMessageList, unquoteJsonString } from './util.js';
import { formatStickerList } from './stickers.js';
import { validateImageUrl, safeFetchBinary } from './safe-fetch.js';
import { webSearch, webFetch, anysearchSearch } from './web-search.js';
import { htmlToText, looksStructured, extractMeta } from './html-text.js';

// 本工具允许读发的本地目录：项目内的 workspace/ 与 dsh-work/，外加系统临时目录。
// 不写死部署路径（历史上是 /root/qq-agent-v2/...），换机器/换目录自动跟着走。
const WORKSPACE_DIR = path.join(ROOT, 'workspace');
const DSH_WORK_DIR = path.join(ROOT, 'dsh-work');
const TEMP_DIRS = ['/tmp', ...(process.env.TMPDIR ? [process.env.TMPDIR] : [])];
const LOCAL_PATH_PREFIXES = [WORKSPACE_DIR, DSH_WORK_DIR, ...TEMP_DIRS];

// 下载图片并转成 dataURL（供视觉模型读图）。
//
// ⚠️ 为什么要重试（2026-09-15 事故）：用户在私聊发图后，机器人回了"图片还没同步出来"。
//    复盘发现：消息入库到触发运行只隔 **2.9 秒**，此时 QQ 的 CDN（multimedia.nt.qq.com.cn）
//    往往还没把图片准备好，首次 GET 会失败；而当时**没有任何重试**，一次失败就永久放弃，
//    于是模型只能如实说"看不到图"。同一 URL 几分钟后手工再拉是成功的 —— 典型的瞬时失败。
//    现在改为指数退避重试 3 次（0.6s / 1.5s / 3s），足以覆盖 CDN 就绪延迟。
async function downloadImageAsDataUrl(url, timeoutMs = 30000) {
  const { dataUrl } = await downloadImageWithHash(url, timeoutMs);
  return dataUrl;
}

/**
 * 下载图片并给出内容指纹。
 * 为什么要指纹：QQ 每次重发同一张表情包都会换一个新的签名 URL（fileid/rkey 变了），
 * 用 URL 去重永远命中不了；用图片字节的 sha256 才认得出「这是同一张图」。
 */
async function downloadImageWithHash(url, timeoutMs = 30000) {
  const cryptoMod = await import('node:crypto');
  const crypto = cryptoMod.default || cryptoMod;
  const safeUrl = await validateImageUrl(url);
  const delays = [600, 1500, 3000];
  let lastError = null;
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    try {
      const { buffer, contentType } = await safeFetchBinary(safeUrl);
      if (!buffer || !buffer.length) throw new Error("图片内容为空");
      const mime = detectMime(buffer) || String(contentType || "image/jpeg").split(";")[0];
      const hash = crypto.createHash('sha256').update(buffer).digest('hex').slice(0, 24);
      return { dataUrl: `data:${mime};base64,${buffer.toString("base64")}`, hash, bytes: buffer.length };
    } catch (e) {
      lastError = e;
      if (attempt < delays.length) await new Promise((r) => setTimeout(r, delays[attempt]));
    }
  }
  throw lastError ?? new Error("图片下载失败");
}

/** 识图缓存：图片指纹 -> { caption, at, times }（data/vision-cache.json，懒加载） */
let VISION_CACHE = null;
async function loadVisionCache() {
  if (VISION_CACHE) return VISION_CACHE;
  try {
    const fsMod = await import('node:fs');
    const pathMod = await import('node:path');
    const { DATA_DIR } = await import('./config.js');
    const fs = fsMod.default || fsMod;
    const path = pathMod.default || pathMod;
    const p = path.join(DATA_DIR, 'vision-cache.json');
    VISION_CACHE = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf-8')) : {};
  } catch {
    VISION_CACHE = {};
  }
  return VISION_CACHE;
}
async function saveVisionCache() {
  try {
    const fsMod = await import('node:fs');
    const pathMod = await import('node:path');
    const { DATA_DIR } = await import('./config.js');
    const fs = fsMod.default || fsMod;
    const path = pathMod.default || pathMod;
    await fs.promises.writeFile(path.join(DATA_DIR, 'vision-cache.json'), JSON.stringify(VISION_CACHE || {}), 'utf-8');
  } catch { /* 写失败不影响主流程 */ }
}

function detectMime(buf) {
  if (!buf || buf.length < 12) return null;
  if (buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) return 'image/png';
  if (buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'image/jpeg';
  if (buf.toString('ascii', 0, 6) === 'GIF87a' || buf.toString('ascii', 0, 6) === 'GIF89a') return 'image/gif';
  if (buf.toString('ascii', 0, 8) === 'RIFF' && buf.toString('ascii', 8, 12) === 'WEBP') return 'image/webp';
  return null;
}

function ok(payload) {
  return { content: typeof payload === 'string' ? payload : JSON.stringify(payload, null, 1) };
}

function err(message) {
  return { content: `错误：${message}`, isError: true };
}

// 找不到消息 id 时，把当前会话真实可见的 id 告诉模型，避免它继续瞎猜。
function midHint(ctx) {
  const mids = ctx.store.recent(ctx.chatKey, { limit: 60 })
    .map((m) => m.mid)
    .filter((v) => v !== null && v !== undefined && String(v) !== '');
  const uniq = [...new Set(mids.map(String))].slice(-8);
  return uniq.length
    ? `消息 id 只能用聊天记录里每条消息前的 #数字（最近可见：${uniq.join(' ')}），不要自己编`
    : '聊天记录里还没有带 #id 的消息';
}

// 需要数字 QQ 号但模型传了名字时，把当前会话真实可见的成员列出来，让它选一个。
function memberHint(ctx) {
  const members = ctx.store.activeMembers(ctx.chatKey, 8);
  if (!members.length) return '当前没有可用的成员列表，请先等有群友发言后再试';
  const lines = members.map((m) => `- ${m.name}：${m.userId}`).join('\n');
  return `请从当前会话成员里选一个 QQ 号填进去：\n${lines}`;
}

function imageParts(text, dataUrls) {
  const parts = [{ type: 'text', text }];
  for (const url of dataUrls) parts.push({ type: 'image_url', image_url: { url } });
  return parts;
}

const execFileP = promisify(execFile);

// ── B站视频（读元信息；配置了 SESSDATA 才能读字幕）─────────────────────
/** 把一条 raw_message（CQ 码）转成可读文本；遇到嵌套转发返回其 id。 */
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

/** 从一条转发节点里取正文；遇到嵌套转发返回 {inline: [...子节点]} 或 {id}。 */
function nodeParts(n) {
  const segs = n?.message ?? n?.content ?? n?.data?.content;
  if (Array.isArray(segs) && segs.length) {
    let text = '';
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
        if (/^https?:\/\//i.test(u)) images.push(u);
      }
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
    return { text: text.replace(/\s+/g, ' ').trim(), inline, ids, images };
  }
  const r = cqToReadable(n?.raw_message ?? n?.content ?? '');
  return { text: r.text, inline: [], ids: r.nested };
}

/**
 * 递归展平一组转发节点（就地展开内层 content；拿不到再按 id 请求一次）。
 */
async function flattenNodes(onebot, nodes, { maxItems = 30, maxChars = 2000, depth = 0, budget, lines, chars, gallery }) {
  for (const n of nodes) {
    if (budget.left <= 0 || chars.v >= maxChars) break;
    const sender = String(n?.sender?.card || n?.sender?.nickname || n?.nickname || '某人');
    const { text, inline, ids, images } = nodeParts(n);
    // 把这一条里的图片编号，正文里只留 [图1] 这种短标记，直链统一放末尾（省字符）
    let shown = text;
    if (images && images.length) {
      const marks = [];
      const nodeMid = n?.message_id ?? n?.messageId ?? n?.msg_id ?? n?.id ?? null;
      for (const u of images) {
        if (gallery.size >= 8) break;           // 最多 8 张，避免撑爆上下文
        const no = gallery.size + 1;
        gallery.set(no, { url: u, mid: nodeMid });
        marks.push(`[图${no}]`);
      }
      shown = shown.replace(/\[图片\]/g, () => marks.shift() || '[图片]');
    }
    if (shown) {
      const line = `${'  '.repeat(depth)}${sender}: ${shown}`;
      if (chars.v + line.length > maxChars) break;
      lines.push(line);
      chars.v += line.length;
      budget.left -= 1;
    }
    for (const sub of inline) {
      if (budget.left <= 0 || chars.v >= maxChars) break;
      await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars, gallery });
    }
    for (const id of ids) {
      if (budget.left <= 0 || chars.v >= maxChars) break;
      try {
        const payload = await onebot.call('get_forward_msg', { id: String(id), message_id: String(id) }, 30000);
        const sub = payload?.data?.messages || payload?.messages || [];
        await flattenNodes(onebot, sub, { maxItems, maxChars, depth: depth + 1, budget, lines, chars, gallery });
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
  const gallery = new Map();
  await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });
  if (gallery.size) {
    lines.push('[转发里的图片（要看用 view_image 传对应链接）]');
    lines.push([...gallery.entries()].map(([no, g]) => (g && typeof g === 'object' ? `图${no} = ${g.url}${g.mid ? `  (#${g.mid})` : ''}` : `图${no} = ${g}`)).join('\n'));
  }
  return { text: lines.join('\n'), count: lines.length, total: nodes.length };
}

/** 直接把一段 message 段数组（含 forward → content）展平，用于收到消息时自动展开。 */
export async function flattenSegmentsInline(onebot, segments, { maxItems = 24, maxChars = 1500 } = {}) {
  const lines = [];
  const chars = { v: 0 };
  const budget = { left: maxItems };
  const gallery = new Map();
  for (const seg of segments || []) {
    if (seg?.type !== 'forward') continue;
    const d = seg.data ?? {};
    if (Array.isArray(d.content) && d.content.length) {
      await flattenNodes(onebot, d.content, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });
    } else {
      const fid = d.id ?? d.forward_id ?? d.res_id;
      if (fid) {
        try {
          const payload = await onebot.call('get_forward_msg', { id: String(fid), message_id: String(fid) }, 30000);
          const nodes = payload?.data?.messages || payload?.messages || [];
          await flattenNodes(onebot, nodes, { maxItems, maxChars, depth: 0, budget, lines, chars, gallery });
        } catch (e) {
          lines.push(`[转发拿不到：${e?.message ?? e}]`);
        }
      }
    }
  }
  if (gallery.size) {
    const tail = [...gallery.entries()].map(([no, g]) => (g && typeof g === 'object' ? `图${no} = ${g.url}${g.mid ? `  (#${g.mid})` : ''}` : `图${no} = ${g}`)).join('\n');
    lines.push('[转发里的图片（要看用 view_image 传对应链接）]');
    lines.push(tail);
  }
  return { text: lines.join('\n'), count: lines.length };
}

const BILI_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';
const BILI_HOSTS = new Set(['www.bilibili.com', 'bilibili.com', 'm.bilibili.com', 'b23.tv', 'api.bilibili.com']);
const HDSLB_HOSTS = new Set(['i0.hdslb.com', 'i1.hdslb.com', 'i2.hdslb.com', 's1.hdslb.com', 'aisubtitle.hdslb.com']);

/** 从任意文本里抽出 BV 号 / av 号。 */
/** 梗词库（懒加载，12MB 只在第一次查时读一次，进程内缓存） */
let MEMES_CACHE = null;
async function loadMemes() {
  if (MEMES_CACHE) return MEMES_CACHE;
  try {
    const fsMod = await import('node:fs');
    const pathMod = await import('node:path');
    const { DATA_DIR } = await import('./config.js');
    const fs = fsMod.default || fsMod;
    const path = pathMod.default || pathMod;
    const p = path.join(DATA_DIR, 'memes.json');
    if (!fs.existsSync(p)) return (MEMES_CACHE = []);
    MEMES_CACHE = JSON.parse(fs.readFileSync(p, 'utf-8'));
    return MEMES_CACHE;
  } catch {
    return (MEMES_CACHE = []);
  }
}

function parseBiliTarget(input) {
  const s = String(input || '').trim();
  const bv = /(BV[0-9A-Za-z]{9,12})/.exec(s);
  if (bv) return { kind: 'bvid', value: bv[1] };
  const av = /\bav(\d{3,})/i.exec(s);
  if (av) return { kind: 'aid', value: av[1] };
  return null;
}

/**
 * B站短链（b23.tv / bili2233.cn）→ 长链。
 * 群友分享的 B 站链接绝大多数是 b23.tv 形态，里面没有 BV 号，
 * 老实现直接判"看不懂这个输入"，表现成「看不了视频」（2026-10-28 查实：7 天内 19 条）。
 */
async function resolveBiliShort(input) {
  const s = String(input || '').trim();
  if (!/b23\.tv|bili2233\.cn/i.test(s)) return s;
  if (/BV[0-9A-Za-z]{9,12}/.test(s)) return s;
  try {
    const res = await fetch(s, {
      redirect: 'follow',
      headers: { 'User-Agent': BILI_UA, Referer: 'https://www.bilibili.com/' },
      signal: AbortSignal.timeout(15000)
    });
    const finalUrl = res.url || '';
    try { await res.arrayBuffer(); } catch { /* 丢掉响应体 */ }
    return finalUrl || s;
  } catch {
    return s;
  }
}

/** 只允许 B 站域名（含字幕 CDN），防止被当成任意 URL 抓取器。 */
/** 把看过的视频加入「稍后再看」（比观看历史更稳，不会被风控清掉）。 */
async function biliAddToview({ aid, cookie = '', sessdata = '' }) {
  const ck = cookie || `SESSDATA=${sessdata}`;
  const jct = (ck.match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!aid || !jct) return { ok: false, reason: '缺少 aid 或 bili_jct' };
  const headers = {
    'User-Agent': BILI_UA,
    'Content-Type': 'application/x-www-form-urlencoded',
    Referer: 'https://www.bilibili.com/',
    Cookie: ck
  };
  const body = new URLSearchParams({ aid: String(aid), csrf: jct }).toString();
  try {
    const res = await fetch('https://api.bilibili.com/x/v2/history/toview/add', {
      method: 'POST', headers, body, signal: AbortSignal.timeout(15000)
    });
    const j = await res.json();
    return { ok: j?.code === 0, code: j?.code, message: j?.message };
  } catch (e) {
    return { ok: false, reason: String(e?.message ?? e) };
  }
}

/** 稍后再看列表超过 limit 条时，从最早的开始删。 */
async function biliTrimToview(cookie = '', limit = 50) {
  const jct = (String(cookie).match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!jct) return { ok: false, reason: '缺少 bili_jct' };
  const headers = { 'User-Agent': BILI_UA, Referer: 'https://www.bilibili.com/', Cookie: cookie };
  try {
    const res = await fetch('https://api.bilibili.com/x/v2/history/toview', { headers, signal: AbortSignal.timeout(15000) });
    const j = await res.json();
    const list = ((j?.data || {}).list) || [];
    const extra = list.length - limit;
    if (extra <= 0) return { ok: true, removed: 0, count: list.length };
    let removed = 0;
    for (const item of list.slice(-extra)) {
      const body = new URLSearchParams({ aid: String(item.aid), csrf: jct }).toString();
      try {
        const r = await fetch('https://api.bilibili.com/x/v2/history/toview/del', {
          method: 'POST',
          headers: { 'User-Agent': BILI_UA, 'Content-Type': 'application/x-www-form-urlencoded', Referer: 'https://www.bilibili.com/', Cookie: cookie },
          body, signal: AbortSignal.timeout(15000)
        });
        const jj = await r.json();
        if (jj?.code === 0) removed += 1;
      } catch { /* 单条失败不影响其它 */ }
    }
    return { ok: true, removed, count: list.length };
  } catch (e) {
    return { ok: false, reason: String(e?.message ?? e) };
  }
}

/**
 * 播放上报：让 B站 把这次观看记进「观看历史」。
 * 不打这两个接口，账号侧的 history 永远是空的（2026-11-09 查实：历史 0 条）。
 * 同一视频同一天只上报一次，避免刷记录。
 */
async function biliReportPlayed({ aid, bvid, cid, sessdata = '', cookie = '' }) {
  if (!aid || !cid) return { ok: false, reason: '缺少 aid/cid' };
  const jct = (String(cookie).match(/bili_jct=([^;]+)/) || [])[1]
    || (String(sessdata).match(/bili_jct=([^;]+)/) || [])[1] || '';
  if (!jct) return { ok: false, reason: '缺少 bili_jct（无法上报）' };

  // 去重：同一 bvid 同一天只报一次
  const fsMod = await import('node:fs');
  const pathMod = await import('node:path');
  const { DATA_DIR } = await import('./config.js');
  const fs = fsMod.default || fsMod;
  const path = pathMod.default || pathMod;
  const statePath = path.join(DATA_DIR, 'bili-reported.json');
  let state = {};
  try { state = JSON.parse(fs.readFileSync(statePath, 'utf-8')); } catch { state = {}; }
  const day = new Date().toISOString().slice(0, 10);
  const key = String(bvid);
  if (state[key] === day) return { ok: true, skipped: true };

  const headers = {
    'User-Agent': BILI_UA,
    'Content-Type': 'application/x-www-form-urlencoded',
    Referer: `https://www.bilibili.com/video/${bvid}`,
    Cookie: cookie || `SESSDATA=${sessdata}`
  };
  const post = async (url, fields) => {
    const body = new URLSearchParams(fields).toString();
    const res = await fetch(url, { method: 'POST', headers, body, signal: AbortSignal.timeout(15000) });
    return res.json().catch(() => ({}));
  };

  const common = {
    aid, bvid, cid, mid: '', csrf: jct, jsonp: 'jsonp',
    'played_time': '0', 'realtime': '0', 'real_time': '0',
    'start_ts': String(Math.floor(Date.now() / 1000)), 'type': '3', 'sub_type': '0',
    'dt': '2', 'last_play_progress_time': '0', 'max_play_progress_time': '0',
    'outer': '0', 'spmid': '333.1007.0.0'
  };
  const r1 = await post('https://api.bilibili.com/x/click-interface/click/web/h5', common);
  // 心跳：played_time 报 300 秒（我们实际看的是前 5 分钟）
  const r2 = await post('https://api.bilibili.com/x/click-interface/web/heartbeat', {
    ...common, played_time: '300', realtime: '300', real_time: '300',
    last_play_progress_time: '300', max_play_progress_time: '300'
  });
  state[key] = day;
  try { fs.writeFileSync(statePath, JSON.stringify(state)); } catch { /* 忽略 */ }
  return { ok: r1?.code === 0 || r2?.code === 0, click: r1?.code, heartbeat: r2?.code };
}

/** 取 B站视频的低清播放直链（无字幕时用来抽帧）。返回 { url, quality, sizeMb } 或 null。 */
async function biliPlayUrl(bvid, cid, { sessdata = '', cookie = '' } = {}) {
  // fnval=0 走 durl（mp4 直链），qn=32 是 480p，比 DASH 简单且省流量
  const api = `https://api.bilibili.com/x/player/playurl?bvid=${bvid}&cid=${cid}&qn=32&fnval=0&fourk=0`;
  const j = await biliGet(api, { sessdata, cookie });
  if (j.code !== 0 || !j.data) return null;
  const durl = (j.data.durl || [])[0];
  if (durl?.url) {
    return { url: durl.url, quality: j.data.quality || 0, sizeMb: Math.round((Number(durl.size) || 0) / 1048576) };
  }
  // 兜底：DASH 轨里挑码率最低的视频流
  const videos = (j.data.dash && j.data.dash.video) || [];
  if (!videos.length) return null;
  const best = videos.slice().sort((a, b) => (a.bandwidth || 0) - (b.bandwidth || 0))[0];
  const u = best.baseUrl || (best.base_url);
  return u ? { url: u, quality: best.id || 0, sizeMb: 0 } : null;
}

/** 生成一个 B站 batche 用的 buvid3（服务器 IP 常因缺它被 412）。 */
function randomBuvid3() {
  const hex = '0123456789ABCDEF';
  let s = '';
  for (let i = 0; i < 32; i++) s += hex[Math.floor(Math.random() * 16)];
  // 形如 XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXXinfoc
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20, 32)}infoc`;
}

// ---------- B站 WBI 签名（字幕接口的正确姿势） ----------
// 未签名的 player/v2 对部分视频会返回**别的视频的字幕**（实测踩过），wbi 签名版才是准的。
const WBI_TAB = [
  46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
  33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
  26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
  20, 34, 44, 52
];
let _wbiKeys = { at: 0, img: '', sub: '' };

function md5Hex(str) {
  return createHash('md5').update(str, 'utf8').digest('hex');
}

async function biliWbiKeys({ sessdata = '', cookie = '' } = {}) {
  if (_wbiKeys.img && Date.now() - _wbiKeys.at < 6 * 3600 * 1000) return _wbiKeys;
  const nav = await biliGet('https://api.bilibili.com/x/web-interface/nav', { sessdata, cookie });
  const wbi = (nav?.data?.wbi_img) || {};
  const img = String(wbi.img_url || '').split('/').pop().split('.')[0];
  const sub = String(wbi.sub_url || '').split('/').pop().split('.')[0];
  if (!img || !sub) throw new Error('拿不到 WBI 密钥（nav 接口未返回 wbi_img）');
  _wbiKeys = { at: Date.now(), img, sub };
  return _wbiKeys;
}

async function biliWbiSign(params, { sessdata = '', cookie = '' } = {}) {
  const { img, sub } = await biliWbiKeys({ sessdata, cookie });
  const raw = img + sub;
  const mixin = WBI_TAB.map((i) => raw[i] || '').join('').slice(0, 32);
  const wts = Math.floor(Date.now() / 1000);
  const query = Object.keys(params)
    .sort()
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(String(params[k]).replace(/[!'()*]/g, ''))}`)
    .join('&');
  const wRid = md5Hex(query + mixin + wts);
  return `${query}&w_rid=${wRid}&wts=${wts}`;
}

// 取某视频的字幕列表：签名接口优先，且只接受归属于本视频的 URL
async function biliFetchSubtitles(d, { sessdata = '', cookie = '' } = {}) {
  const expectKey = `${d.aid}${d.cid}`;
  const attempts = [];
  try {
    const q = await biliWbiSign({ bvid: d.bvid, cid: d.cid }, { sessdata, cookie });
    attempts.push(['wbi+sig', `https://api.bilibili.com/x/player/wbi/v2?${q}`]);
  } catch (e) {
    attempts.push(['wbi(无签名)', `https://api.bilibili.com/x/player/wbi/v2?bvid=${d.bvid}&cid=${d.cid}`]);
  }
  attempts.push(['player/v2', `https://api.bilibili.com/x/player/v2?aid=${d.aid}&cid=${d.cid}`]);

  const rejected = [];
  for (const [label, url] of attempts) {
    let player = null;
    try {
      player = await biliGet(url, { sessdata, cookie });
    } catch (e) {
      rejected.push(`${label}:请求失败`);
      continue;
    }
    if (player?.code !== 0) {
      rejected.push(`${label}:code=${player?.code}`);
      continue;
    }
    const subs = (((player.data || {}).subtitle || {}).subtitles) || [];
    // 归属校验：字幕 URL 里必含 aid+cid
    const ok = subs.filter((x) => String(x.subtitle_url || '').includes(expectKey));
    const bad = subs.filter((x) => !String(x.subtitle_url || '').includes(expectKey));
    if (bad.length) rejected.push(`${label}:丢弃 ${bad.length} 条不属于本视频的字幕`);
    if (ok.length) {
      const pick = ok.find((x) => /^ai-zh/i.test(String(x.lan || '')))
        || ok.find((x) => /^zh/i.test(String(x.lan || '')))
        || ok[0];
      return { pick, entries: ok, via: label, rejected };
    }
  }
  return { pick: null, entries: [], via: null, rejected };
}

async function biliGet(url, { sessdata = '', cookie = '' } = {}) {
  // 字幕接口常返回协议相对地址（//aisubtitle.hdslb.com/...），补上 https:
  const normalized = String(url || '').startsWith('//') ? `https:${url}` : String(url || '');
  const u = new URL(normalized);
  if (!BILI_HOSTS.has(u.hostname) && !HDSLB_HOSTS.has(u.hostname)) {
    throw new Error(`只允许 B 站域名，收到 ${u.hostname}`);
  }
  const headers = {
    'User-Agent': BILI_UA,
    Referer: 'https://www.bilibili.com/',
    Accept: 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
  };
  // Cookie：优先用配置里的完整串（含 buvid3/bili_jct），否则只用 SESSDATA
  const jar = String(cookie || '').trim();
  let cookieStr = jar;
  if (!cookieStr && sessdata) cookieStr = `SESSDATA=${sessdata}`;
  if (cookieStr) {
    if (!/buvid3=/.test(cookieStr)) cookieStr += `; buvid3=${randomBuvid3()}`;
    headers.Cookie = cookieStr;
  }
  const res = await fetch(u, { headers, signal: AbortSignal.timeout(20000) });
  if (!res.ok) throw new Error(`B站接口 HTTP ${res.status}`);
  return await res.json();
}

// 视频下载上限：QQ 群里的视频常见几十 MB，超过就不拉（省内存与带宽）
const VIDEO_MAX_BYTES = 80 * 1024 * 1024;

/**
 * 下载视频 → ffmpeg 抽 N 帧 → 返回 data URL 数组（按时间顺序）。
 * 只取画面、不含音轨；帧按时长均分，短时长也能覆盖全程。
 */
async function extractVideoFrames(source, wantFrames = 6) {
  const ffmpegBin = process.env.FFMPEG_BIN || 'ffmpeg';
  const ffprobeBin = process.env.FFPROBE_BIN || 'ffprobe';
  const dir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'qqvid-'));
  try {
    const src = path.join(dir, 'input.video');
    if (source.kind === 'file') {
      await fs.promises.copyFile(source.value, src);
    } else {
      const { buffer } = await safeFetchBinary(source.value, VIDEO_MAX_BYTES);
      await fs.promises.writeFile(src, buffer);
    }
    // 时长兜底 20 秒：ffprobe 读不到时不至于只抽到开头几秒
    let duration = 20;
    try {
      const { stdout } = await execFileP(ffprobeBin,
        ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', src],
        { timeout: 20000 });
      const parsed = parseFloat(String(stdout).trim());
      if (Number.isFinite(parsed) && parsed > 0.5) duration = Math.min(parsed, 3600);
    } catch { /* 用兜底时长 */ }
    const fps = Math.max(wantFrames / duration, 0.05);
    await execFileP(ffmpegBin,
      ['-y', '-v', 'error', '-i', src,
        '-vf', `fps=${fps.toFixed(4)},scale='min(640,iw)':-2`,
        '-frames:v', String(wantFrames), '-q:v', '5', path.join(dir, 'f%02d.jpg')],
      { timeout: 120000 });
    const files = (await fs.promises.readdir(dir)).filter((f) => /^f\d+\.jpg$/.test(f)).sort();
    if (!files.length) throw new Error('ffmpeg 没抽到画面（视频可能损坏或格式不受支持）');
    const dataUrls = [];
    for (const file of files.slice(0, wantFrames)) {
      const buf = await fs.promises.readFile(path.join(dir, file));
      if (buf.length > 2 * 1024 * 1024) continue;   // 单帧过大直接丢，别把请求撑爆
      dataUrls.push(`data:image/jpeg;base64,${buf.toString('base64')}`);
    }
    if (!dataUrls.length) throw new Error('抽帧成功但每帧都过大');
    return dataUrls;
  } finally {
    fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {});
  }
}

/**
 * 解析消息里的视频来源：
 *  1) OneBot 给了 http(s) 地址 → 走安全下载（SSRF 防护）
 *  2) 只给了本地绝对路径（NapCat 常见）→ 直接读本地文件
 *  3) 其他情况（只有 file id / 相对名）→ 返回 null，由上层给出可读提示
 */
function videoSourceOf(media) {
  const m = (media || []).find((x) => x.kind === 'video' && (x.localPath || x.url || x.file));
  if (!m) return null;
  // 已经落盘的优先用本地文件（CDN 链接会过期）
  const localPath = String(m.localPath || '').trim();
  if (localPath && path.isAbsolute(localPath) && fs.existsSync(localPath)) {
    const stat = fs.statSync(localPath);
    if (stat.isFile() && stat.size > 1024) return { kind: 'file', value: localPath };
  }
  const url = String(m.url || '').trim();
  if (/^https?:\/\//i.test(url)) return { kind: 'url', value: url };
  const file = String(m.file || '').trim();
  if (file && path.isAbsolute(file) && fs.existsSync(file)) {
    const stat = fs.statSync(file);
    if (stat.isFile() && stat.size > 1024 && stat.size <= VIDEO_MAX_BYTES) return { kind: 'file', value: file };
  }
  if (/^https?:\/\//i.test(file)) return { kind: 'url', value: file };
  return null;
}

// ── QQ 文件消息：在 NapCat 临时目录里找真实文件 ─────────────────────────
// 背景：OneBot 的文件消息只给 fileId/文件名/大小，`url` 为空；而 NapCat 收到文件时
// 已经把它落在自己的 temp 目录里。直接调 get_file 拿不到下载地址（私聊尤其如此），
// 所以先按文件名/大小去临时目录捞，捞不到再回退 get_file。
const NAPCAT_TEMP_DIRS = [
  process.env.NAPCAT_TEMP_DIR || '',
  '/root/.config/QQ/NapCat/temp',
  path.join(process.env.HOME || '/root', '.config/QQ/NapCat/temp'),
].filter(Boolean);

/** 在 NapCat 临时目录里按文件名（可带大小校验）定位文件；找不到返回 ''。 */
function findNapcatTempFile(name, size) {
  const target = String(name || '').trim();
  if (!target) return '';
  const wanted = Number(size) || 0;
  for (const dir of NAPCAT_TEMP_DIRS) {
    try {
      if (!fs.existsSync(dir)) continue;
      const direct = path.join(dir, target);
      if (fs.existsSync(direct) && fs.statSync(direct).isFile()) {
        const st = fs.statSync(direct);
        if (!wanted || st.size === wanted) return direct;
      }
      // 名字被改写过（重名/编码）时，按「大小相同 且 最近 15 分钟」兜底
      if (wanted) {
        const now = Date.now();
        for (const entry of fs.readdirSync(dir)) {
          const p = path.join(dir, entry);
          let st;
          try { st = fs.statSync(p); } catch { continue; }
          if (!st.isFile() || st.size !== wanted) continue;
          if (now - st.mtimeMs > 15 * 60 * 1000) continue;
          return p;
        }
      }
    } catch { /* 换下一个目录 */ }
  }
  return '';
}

/** 文本类扩展名：读出来直接给模型，不用再让 DSH 处理。 */
const TEXT_EXTS = new Set(['.txt', '.md', '.json', '.csv', '.log', '.xml', '.yaml', '.yml', '.ics', '.html', '.htm', '.js', '.mjs', '.py', '.ts', '.sql', '.ini', '.conf']);

/** 读取文本类文件内容（带长度上限）。 */
function readTextPreview(filePath, limit = 6000) {
  try {
    const ext = path.extname(filePath).toLowerCase();
    if (!TEXT_EXTS.has(ext)) return '';
    const raw = fs.readFileSync(filePath, 'utf8');
    const text = raw.length > limit ? raw.slice(0, limit) + `\n…（后面还有 ${raw.length - limit} 字，未全部载入）` : raw;
    return text;
  } catch {
    return '';
  }
}


/**
 * 构建绑定一次运行的工具集。
 * ctx: {
 *   chatKey, kind, chatId, selfId, selfNickname, botName,
 *   onebot, store, memory, stickers, sender, session,
 *   emit  (事件上报给 UI/日志)
 * }
 */
/** 下载 B站视频并抽帧，返回 imageParts（带元信息文本）。失败时退回纯文本。 */
async function biliFramesResult(d, lines, args, creds) {
  const want = Math.max(3, Math.min(16, Number(args?.frames) || 8));
  try {
    const play = await biliPlayUrl(d.bvid, d.cid, creds);
    if (!play?.url) {
      lines.push('（拿不到播放地址，只能提供上面的元信息）');
      return ok(lines.join('\n'));
    }
    if (play.sizeMb > 40) {
      // 大文件不整段下载：用 ffmpeg 从 CDN 流式只取前 3 分钟再抽帧
      lines.push(`（视频约 ${play.sizeMb}MB，整段太大，只取前 3 分钟抽帧）`);
      const hdrs = [
        'Referer: https://www.bilibili.com/',
        `User-Agent: ${BILI_UA}`,
        ...(creds.cookie ? [`Cookie: ${creds.cookie}`] : []),
      ].join('\r\n');
      const tmp = path.join(os.tmpdir(), `bili-cut-${Date.now()}.mp4`);
      try {
        await execFileP(process.env.FFMPEG_BIN || 'ffmpeg',
          ['-y', '-v', 'error', '-headers', hdrs + '\r\n', '-ss', '0', '-t', '180',
           '-i', play.url, '-c', 'copy', tmp],
          { timeout: 300000 });
        if (!fs.existsSync(tmp) || fs.statSync(tmp).size < 20480) throw new Error('切片太小');
        const urls = await extractVideoFrames({ kind: 'file', value: tmp }, want).catch(() => []);
        if (!urls.length) throw new Error('抽帧失败');
        const head = lines.concat([`抽帧：${urls.length} 张（前 3 分钟，均匀分布；后面的内容没看）`]).join('\n');
        return { content: imageParts(head, urls) };
      } catch (e) {
        lines.push(`（大文件抽帧失败：${e?.message ?? e}，只看文字信息吧）`);
        return ok(lines.join('\n'));
      } finally {
        try { fs.unlinkSync(tmp); } catch { /* 忽略 */ }
      }
    }
    // B站 CDN 要 Referer/UA/Cookie，裸 fetch 会 403
    const res = await fetch(play.url, {
      headers: {
        'User-Agent': BILI_UA,
        Referer: 'https://www.bilibili.com/',
        ...(creds.cookie ? { Cookie: creds.cookie } : {}),
      },
      signal: AbortSignal.timeout(120000),
    });
    if (!res.ok) throw new Error(`视频下载 HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    if (!buf.length) throw new Error('视频下载为空');
    if (buf.length > VIDEO_MAX_BYTES) throw new Error(`视频 ${Math.round(buf.length / 1048576)}MB 超过上限`);
    const tmpFile = path.join(os.tmpdir(), `bili-${d.bvid}-${Date.now()}.mp4`);
    fs.writeFileSync(tmpFile, buf);
    let dataUrls = [];
    try {
      dataUrls = await extractVideoFrames({ kind: 'file', value: tmpFile }, want);
    } finally {
      try { fs.unlinkSync(tmpFile); } catch { /* 忽略 */ }
    }
    if (!dataUrls.length) {
      lines.push('（抽帧没成功）');
      return ok(lines.join('\n'));
    }
    const head = lines.join('\n') + `\n（以上是文字信息；下面 ${dataUrls.length} 张是按时间顺序抽的画面帧，` +
      '只能看出画面里有什么，听不到说话内容，别当成完整内容。）';
    return { content: imageParts(head, dataUrls) };
  } catch (error) {
    lines.push(`（抽帧失败：${error?.message ?? error}）`);
    return ok(lines.join('\n'));
  }
}

/** GPU 语音的待发队列 + 后台轮询。 */
const pendingVoices = [];
let voicePoller = null;

function ensureVoicePoller() {
  if (voicePoller) return;
  voicePoller = setInterval(async () => {
    const now = Date.now();
    for (let i = pendingVoices.length - 1; i >= 0; i--) {
      const job = pendingVoices[i];
      try {
        if (fs.existsSync(job.remote)) {
          const buf = await fs.promises.readFile(job.remote);
          await job.onebot.sendRecord(job.kind, job.chatId, buf);
          try { fs.unlinkSync(job.remote); } catch { /* 忽略 */ }
          if (job.session?.sent) {
            job.session.sent.push({ type: 'voice', text: '[语音]' + String(job.text || '').slice(0, 30), at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          }
          try { job.emit?.('session-update', job.session?.id); } catch { /* 忽略 */ }
          pendingVoices.splice(i, 1);
        } else if (now > job.deadline) {
          pendingVoices.splice(i, 1);
          console.log('[gpu_tts] 超时放弃:', job.remote);
        }
      } catch (e) {
        console.log('[gpu_tts] 轮询异常:', e?.message ?? e);
        pendingVoices.splice(i, 1);
      }
    }
    if (!pendingVoices.length && voicePoller) { clearInterval(voicePoller); voicePoller = null; }
  }, 5000);
}

/** GPU 画图的待发队列 + 后台轮询（图到就发，不需要再唤醒模型）。 */
const pendingDraws = [];
let drawPoller = null;

function ensureDrawPoller() {
  if (drawPoller) return;
  drawPoller = setInterval(async () => {
    const now = Date.now();
    for (let i = pendingDraws.length - 1; i >= 0; i--) {
      const job = pendingDraws[i];
      try {
        if (fs.existsSync(job.remote)) {
          const buf = await fs.promises.readFile(job.remote);
          await job.onebot.sendImageBuffer(job.kind, job.chatId, buf, { replyToMessageId: job.replyMid });
          try { fs.unlinkSync(job.remote); } catch { /* 忽略 */ }
          if (job.session?.sent) {
            job.session.sent.push({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          }
          try { job.emit?.('session-update', job.session?.id); } catch { /* 忽略 */ }
          pendingDraws.splice(i, 1);
        } else if (now > job.deadline) {
          pendingDraws.splice(i, 1);
          console.log('[gpu_draw] 超时放弃:', job.remote);
        }
      } catch (e) {
        console.log('[gpu_draw] 轮询异常:', e?.message ?? e);
        pendingDraws.splice(i, 1);
      }
    }
    if (!pendingDraws.length && drawPoller) { clearInterval(drawPoller); drawPoller = null; }
  }, 5000);
}

export function buildToolDefs() {
  const defs = [
    {
      name: 'send_message',
      description: '发送消息到当前聊天（本工具只能发到本次会话对应的群/私聊）。messages 传字符串=发一条；传字符串数组=分多条发送（推荐，更像真人）。只有需要明确"我回的是哪条"时才传 replyToMessageId 引用；需要点名某人才传 atUserId。不要在字符串内部用空格分句。',
      parameters: {
        type: 'object',
        properties: {
          messages: { description: '要发送的内容：字符串=一条；数组=分多条', oneOf: [{ type: 'string' }, { type: 'array', items: { type: 'string' } }] },
          replyToMessageId: { type: ['integer', 'string'], description: '要引用/回复的消息 id（聊天记录里每条消息前的 #数字，可选）' },
          atUserId: { type: ['integer', 'string'], description: '要 @ 的群成员 QQ 号（可选，与引用二选一，不要滥用）' }
        },
        required: ['messages']
      },
      async execute(ctx, args) {
        try {
          const messages = normalizeMessageList(args.messages);
          if (!messages.length) return err('消息内容为空');
          // 群聊默认用 QQ 的「引用回复」发出去：模型没显式指定 replyToMessageId 时，
          // 自动引用本次唤醒的最新一条别人的消息，保证群里每条回话都挂在被回的那条下面。
          let replyTo = args.replyToMessageId ?? null;
          // 自动引用收窄：只有「同一批里有两个以上不同的人在叫你」时才自动挂引用。
          // 之前群里每条都自动引用最新一条，被引对象是卡片/已失效消息时 QQ 会渲染成
          // 「空引用栏 + 一串数字」，看起来像机器人抽风。
          if ((replyTo === null || replyTo === '') && String(ctx.chatKey || '').startsWith('group:')
              && getConfig().groupQuoteReply !== false) {
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const others = trig.filter((m) => m && m.mid != null && !m.self);
            const senders = new Set(others.map((m) => String(m.senderId ?? m.mid)));
            if (senders.size >= 2) {
              const lastTrig = others[others.length - 1];
              if (lastTrig) replyTo = lastTrig.mid;
            }
          }
          // 引用 id 必须是我们确实见过的消息，编出来的 id 在 QQ 里就是空引用
          if (replyTo !== null && replyTo !== '') {
            const known = new Set();
            const seen = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            for (const m of seen) if (m && m.mid != null) known.add(String(m.mid));
            try {
              for (const m of ctx.store.recent(ctx.chatKey, { limit: 200 })) if (m && m.mid != null) known.add(String(m.mid));
            } catch { /* 读不到就只信任 trigger */ }
            if (!known.has(String(replyTo).trim())) {
              ctx.emit?.('log', { level: 'warn', message: `[send] 引用 id ${replyTo} 不在本会话最近消息里，已丢弃引用` });
              replyTo = null;
            }
          }
          const result = await ctx.sender.sendTextBatch(ctx.chatKey, messages, {
            replyToMessageId: replyTo,
            atUserId: args.atUserId ?? null
          });
          ctx.session.sent.push(...result.sent.map((s) => ({ type: 'text', text: s.text, at: s.at })));
          ctx.emit('session-update', ctx.session.id);
          const note = ['已发送。不要输出"已发送"类汇报，继续思考下一步或直接结束。'];
          if (result.failed.length) note.push(`（另有 ${result.failed.length} 条发送失败：${result.failed.map((f) => f.error).join('；')}——成功的不需要重发，失败的请稍后再试或减少条数）`);
          return ok({ sent: result.sent.length, messageIds: result.sent.map((s) => s.messageId), note: note.join('') });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'send_sticker',
      description: '发送一个 QQ 收藏表情（一条消息只能一张表情，不能附带文字；想说的话先用 send_message 单独发）。stickerId 从 list_stickers 获取。',
      parameters: {
        type: 'object',
        properties: {
          stickerId: { type: 'string', description: '表情 id' },
          replyToMessageId: { type: ['integer', 'string'], description: '可选：要引用的消息 id（聊天记录里的 #数字）' },
          atUserId: { type: ['integer', 'string'], description: '可选：要 @ 的 QQ 号' }
        },
        required: ['stickerId']
      },
      async execute(ctx, args) {
        try {
          const sticker = await ctx.stickers.find(unquoteJsonString(args.stickerId));
          if (!sticker) return err(`找不到表情 ${args.stickerId}，请先用 list_stickers 获取有效 id`);
          // ① 本地表情优先：data/stickers/<id>.<ext> 存在就直接读文件发 base64，
          //    完全不依赖外网图床（某些图床对服务器不可达）。支持 jpg/png/gif/webp。
          const stickerDir = path.join(DATA_DIR, 'stickers');
          let localSticker = '';
          for (const ext of ['jpg', 'jpeg', 'png', 'gif', 'webp']) {
            const p2 = path.join(stickerDir, `${sticker.id}.${ext}`);
            if (fs.existsSync(p2)) { localSticker = p2; break; }
          }
          if (localSticker) {
            const buf = await fs.promises.readFile(localSticker);
            if (buf.length > 0) {
              let replyLocal = args.replyToMessageId ?? null;
              if ((replyLocal === null || replyLocal === '') && String(ctx.chatKey || '').startsWith('group:')
                  && getConfig().groupQuoteReply !== false) {
                const trig0 = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
                const last0 = [...trig0].reverse().find((m) => m && m.mid != null && !m.self);
                if (last0) replyLocal = last0.mid;
              }
              const r0 = await ctx.onebot.sendImageBuffer(ctx.kind, ctx.chatId, buf, {
                replyToMessageId: replyLocal, atUserId: args.atUserId ?? null
              });
              ctx.stickers.markUsed(sticker.id, String(ctx.session.triggerText || '').slice(0, 100));
              ctx.session.sent.push({ type: 'sticker', text: `[表情包:${sticker.desc || sticker.id}]`, at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
              ctx.emit('session-update', ctx.session.id);
              return ok({ sent: true, local: true, messageId: r0?.message_id ?? null, note: '表情已发送。' });
            }
          }
          if (!sticker.url) return err(`表情 ${sticker.id} 没有可发送的图片地址`);
          try {
            await validateImageUrl(sticker.url); // 只允许公网 http(s)，防止本地库被污染后诱导 OneBot 抓内网
          } catch (error) {
            return err(`表情 ${sticker.id} 的图片地址不合法，已拒绝发送：${error?.message ?? error}`);
          }
          // 群聊默认带引用，与 send_message 保持一致
          let replyTo = args.replyToMessageId ?? null;
          // 自动引用收窄：只有「同一批里有两个以上不同的人在叫你」时才自动挂引用。
          // 之前群里每条都自动引用最新一条，被引对象是卡片/已失效消息时 QQ 会渲染成
          // 「空引用栏 + 一串数字」，看起来像机器人抽风。
          if ((replyTo === null || replyTo === '') && String(ctx.chatKey || '').startsWith('group:')
              && getConfig().groupQuoteReply !== false) {
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const others = trig.filter((m) => m && m.mid != null && !m.self);
            const senders = new Set(others.map((m) => String(m.senderId ?? m.mid)));
            if (senders.size >= 2) {
              const lastTrig = others[others.length - 1];
              if (lastTrig) replyTo = lastTrig.mid;
            }
          }
          // 引用 id 必须是我们确实见过的消息，编出来的 id 在 QQ 里就是空引用
          if (replyTo !== null && replyTo !== '') {
            const known = new Set();
            const seen = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            for (const m of seen) if (m && m.mid != null) known.add(String(m.mid));
            try {
              for (const m of ctx.store.recent(ctx.chatKey, { limit: 200 })) if (m && m.mid != null) known.add(String(m.mid));
            } catch { /* 读不到就只信任 trigger */ }
            if (!known.has(String(replyTo).trim())) {
              ctx.emit?.('log', { level: 'warn', message: `[send] 引用 id ${replyTo} 不在本会话最近消息里，已丢弃引用` });
              replyTo = null;
            }
          }
          const result = await ctx.sender.sendSticker(ctx.chatKey, sticker, {
            replyToMessageId: replyTo,
            atUserId: args.atUserId ?? null
          });
          ctx.stickers.markUsed(sticker.id, String(ctx.session.triggerText || '').slice(0, 100));
          ctx.session.sent.push({ type: 'sticker', text: `[表情包:${sticker.desc || sticker.localNote || sticker.id}]`, at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ sent: true, messageId: result?.message_id ?? null, note: '表情已发送。' });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'image_gen',
      description: '生成图片：把文字描述画成一张图并发出来。别人说"画一张/帮我生成图/来张图/画个表情包"时用它。prompt 尽量具体（主体、动作、风格、配色），中英文都行，不要带引号。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，越具体越好' },
          size: { type: 'string', description: '可选：1024x1024（默认）/ 1024x1536 / 1536x1024' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        const cfg = getConfig().imageGen || {};
        if (!cfg.enabled || !cfg.apiKey || !cfg.model) {
          return err('生图功能还没配置好（缺 key 或 model），跟对方说一声"我这边画图还没接好"。');
        }
        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('prompt 不能为空');
        const size = String(args.size || cfg.size || '1024x1024');
        const provider = String(cfg.provider || 'openai-compat');
        const timeoutMs = 180000;
        try {
          let buffer = null;
          let imageUrl = '';
          if (provider === 'openai-compat') {
            const base = String(cfg.baseUrl || '').replace(/\/+$/, '');
            const res = await fetch(`${base}/images/generations`, {
              method: 'POST',
              headers: { 'content-type': 'application/json', authorization: `Bearer ${cfg.apiKey}` },
              body: JSON.stringify({ model: cfg.model, prompt, n: 1, size }),
              signal: AbortSignal.timeout(timeoutMs)
            });
            const text = await res.text();
            let data = null;
            try { data = JSON.parse(text); } catch { /* 非 JSON */ }
            if (!res.ok) {
              const msg = data?.error?.message || text.slice(0, 160);
              return err(`生图接口返回 ${res.status}：${msg}`);
            }
            const first = data?.data?.[0] || {};
            if (first.b64_json) buffer = Buffer.from(first.b64_json, 'base64');
            else if (first.url) imageUrl = first.url;
            else return err('生图接口没有返回图片数据');
          } else if (provider === 'dashscope') {
            // 通义万相：异步任务，提交后轮询
            const submit = await fetch('https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis', {
              method: 'POST',
              headers: {
                'content-type': 'application/json',
                authorization: `Bearer ${cfg.apiKey}`,
                'X-DashScope-Async': 'enable'
              },
              body: JSON.stringify({
                model: cfg.model || 'wanx2.1-t2i-turbo',
                input: { prompt },
                parameters: { size: size.replace('x', '*'), n: 1 }
              }),
              signal: AbortSignal.timeout(60000)
            });
            const sj = await submit.json().catch(() => null);
            if (!submit.ok || !sj?.output?.task_id) {
              return err(`生图提交失败：${sj?.message || submit.status}`);
            }
            const taskId = sj.output.task_id;
            for (let i = 0; i < 30; i++) {
              await new Promise((r) => setTimeout(r, 4000));
              const q = await fetch(`https://dashscope.aliyuncs.com/api/v1/tasks/${taskId}`, {
                headers: { authorization: `Bearer ${cfg.apiKey}` },
                signal: AbortSignal.timeout(30000)
              });
              const qj = await q.json().catch(() => null);
              const status = qj?.output?.task_status;
              if (status === 'SUCCEEDED') {
                const r0 = qj.output?.results?.[0];
                imageUrl = r0?.url || '';
                break;
              }
              if (status === 'FAILED') return err(`生图失败：${qj?.output?.message || '未知原因'}`);
            }
            if (!buffer && !imageUrl) return err('生图超时，没有拿到图片');
          } else {
            return err(`不支持的生图 provider：${provider}`);
          }

          // 发送：本地 buffer 优先（不依赖图床），否则用 URL
          let replyMid = args.replyToMessageId ?? null;
          if ((replyMid === null || replyMid === '') && String(ctx.chatKey || '').startsWith('group:')
              && getConfig().groupQuoteReply !== false) {
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
            if (last) replyMid = last.mid;
          }
          let r;
          if (buffer) {
            r = await ctx.onebot.sendImageBuffer(ctx.kind, ctx.chatId, buffer, { replyToMessageId: replyMid });
          } else {
            r = await ctx.onebot.sendImage(ctx.kind, ctx.chatId, imageUrl, { replyToMessageId: replyMid });
          }
          ctx.session.sent.push({ type: 'image', text: '[生成的图片]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ generated: true, messageId: r?.message_id ?? null, note: '图片已发出。' });
        } catch (error) {
          return err(`生图失败：${error?.message ?? error}`);
        }
      }
    },
    {
      name: 'send_image',
      description: '发送一张图片到当前聊天（URL 或本地 workspace/ 下的路径）。图片来自网页搜索/群友要求/本地生成时用。发送前会校验公网地址安全（拒绝内网）。',
      parameters: {
        type: 'object',
        properties: {
          imageUrl: { type: 'string', description: '图片地址：公网 http(s) URL 或本地文件绝对路径（限 workspace/ 或 dsh-work/ 或 /tmp）' },
          replyToMessageId: { type: ['integer', 'string'], description: '可选：要引用的消息 id（聊天记录里的 #数字）' },
          atUserId: { type: ['integer', 'string'], description: '可选：要 @ 的 QQ 号' }
        },
        required: ['imageUrl']
      },
      async execute(ctx, args) {
        try {
          const raw = String(args.imageUrl ?? '').trim();
          if (!raw) return err('imageUrl 不能为空');
          // 本地路径检查（workspace 内）
          const isLocal = raw.startsWith('/');
          if (isLocal) {
            const allowedPrefixes = LOCAL_PATH_PREFIXES;
            const okPath = allowedPrefixes.some((p) => raw.startsWith(p)) && !raw.includes('..');
            if (!okPath) return err('本地图片路径不在允许范围（仅 workspace 或 /tmp）');
            try {
              const fs2 = await import('node:fs');
              if (!fs2.existsSync(raw)) return err(`图片文件不存在: ${raw}`);
            } catch (e) { return err('无法访问本地文件: ' + (e?.message || e)); }
          } else {
            try {
              await validateImageUrl(raw); // 公网 http(s) 校验（拒绝内网）
            } catch (error) {
              return err(`图片地址不合法，已拒绝发送：${error?.message ?? error}`);
            }
          }
          const result = await ctx.sender.sendImage(ctx.chatKey, raw, {
            replyToMessageId: args.replyToMessageId ?? null,
            atUserId: args.atUserId ?? null
          });
          ctx.session.sent.push({ type: 'image', text: `[图片:${String(raw).split('/').pop().slice(0, 50)}]`, at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ sent: true, messageId: result?.message_id ?? null, note: '图片已发送。' });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'schedule_task',
      description: '【主人专属】设置/查看/取消**定时任务**：到点机器人会主动发消息给主人，或执行提醒。主人说「X点提醒我…」「每天X点告诉我…」「每周X提醒我…」「N分钟后叫我…」时用它。\n时间由你来理解并换算成绝对时间：now 是当前时间，把「明天早上8点」「3小时后」等换算成 at（ISO 本地时间字符串，如 2026-09-14T08:00:00）。\naction=create（默认）新建；list 查看；cancel 取消（配 taskId）；clear 清空当前会话全部。',
      masterOnly: true,
      parameters: {
        type: 'object',
        properties: {
          action: { type: 'string', description: 'create（默认）| list | cancel | clear' },
          text: { type: 'string', description: '到点要做什么/要说什么（自然语言，如"提醒我交作业"）' },
          at: { type: 'string', description: '触发时间，ISO 本地格式 YYYY-MM-DDTHH:MM:SS（由你把自然语言换算好）' },
          repeat: { type: 'string', description: 'none（默认，一次性）| daily（每天）| weekly（每周）' },
          taskId: { type: 'string', description: 'action=cancel 时的任务 id' }
        },
        required: []
      },
      async execute(ctx, args) {
        try {
          const ST = await import('./scheduled-tasks.js');
          const action = String(args.action || 'create').toLowerCase();
          const now = new Date();

          if (action === 'list') {
            const list = ST.tasksOf(ctx.chatKey);
            if (!list.length) return ok('当前没有待触发的定时任务。');
            return ok('【待触发的定时任务】\n' + list.map((t) => '· ' + ST.describeTask(t) + '（id: ' + t.id + '）').join('\n'));
          }
          if (action === 'cancel') {
            const id = String(args.taskId || '').trim();
            if (!id) return err('取消任务需要 taskId（可先用 action=list 查看）');
            return ST.removeTask(id) ? ok('已取消任务 ' + id) : err('没找到任务 ' + id);
          }
          if (action === 'clear') {
            const n = ST.clearTasks(ctx.chatKey);
            return ok('已清空 ' + n + ' 条定时任务。');
          }

          // create
          const text = String(args.text || '').trim();
          if (!text) return err('需要 text（到点要做什么）');
          const atStr = String(args.at || '').trim();
          if (!atStr) return err('需要 at（触发时间，ISO 格式如 2026-09-14T08:00:00）');
          const at = new Date(atStr).getTime();
          if (!Number.isFinite(at)) return err('at 格式不对，应为 YYYY-MM-DDTHH:MM:SS');
          if (at <= now.getTime()) return err('at 是过去的时间，请给未来的时间');
          const repeat = String(args.repeat || 'none').toLowerCase();
          const t = ST.addTask({ chatKey: ctx.chatKey, text, at, repeat });
          const diffMin = Math.round((at - now.getTime()) / 60000);
          return ok({
            created: true,
            id: t.id,
            when: ST.describeTask(t),
            note: '任务已记下，到点我会主动发消息。可以告诉主人「好，' + diffMin + ' 分钟后提醒你」。'
          });
        } catch (error) {
          return err(`定时任务操作失败：${error?.message ?? error}`);
        }
      }
    },

    {
      name: 'receive_file',
      description: '把主人发来的 QQ 文件（[文件：xxx] 占位符的消息）下载到工作目录，得到本地路径后就可以读取/解析/转交 DSH。id 用聊天记录里每条消息前的 #数字（没有 #数字时先用 get_recent_messages 查）。传了 messageId 会列出该消息里所有文件。',
      parameters: {
        type: 'object',
        properties: {
          messageId: { type: ['integer', 'string'], description: 'QQ 消息 id（聊天记录里的 #数字，可能为负数）' },
          fileIndex: { type: 'number', description: '同一条消息里有多个文件时指定第几个（从 0 开始），默认 0' }
        },
        required: ['messageId']
      },
      async execute(ctx, args) {
        try {
          const entry = ctx.store.findByMid(ctx.chatKey, args.messageId);
          if (!entry) return err(`当前会话找不到消息 ${args.messageId}。${midHint(ctx)}`);
          const files = (entry.media || []).filter((m) => m.kind === 'file');
          if (!files.length) return err('这条消息里没有文件（可能只有图片或文字）');
          const idx = Math.max(0, Math.min(Number(args.fileIndex) || 0, files.length - 1));
          const f = files[idx];
          if (!f.fileId) return err('这个文件缺少 file_id，无法下载（可能是旧消息或 NapCat 未提供）');

          // 下载目录：工作区固定子目录，方便交给 DSH
          const fsmod = await import('node:fs');
          const pathmod = await import('node:path');
          const cfgmod = await import('./config.js');
          const inbox = pathmod.join(cfgmod.DATA_DIR, 'inbox');
          fsmod.mkdirSync(inbox, { recursive: true });
          const safeName = String(f.name || 'file').replace(/[\/:*?"<>|]/g, '_');
          const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
          const dest = pathmod.join(inbox, `${stamp}_${safeName}`);

          // ① 优先在 NapCat 临时目录里捞真实文件（文件消息的 url 通常是空的，
          //    get_file 对私聊文件往往拿不到下载地址 —— 2026-10-20 实测 ics 就是这种情况）。
          let buf = null;
          const localSrc = findNapcatTempFile(f.name, f.size);
          if (localSrc) {
            try {
              buf = fs.readFileSync(localSrc);
              console.log(`[文件] 命中 NapCat 临时目录: ${localSrc} (${buf.length} 字节)`);
            } catch { buf = null; }
          }

          // ② 回退：按 fileId 向 OneBot 要下载地址
          if (!buf) {
            if (!f.fileId) return err('这个文件既不在本地临时目录，也没有 file_id，无法读取');
            const info = await ctx.onebot.call('get_file', { file_id: f.fileId }, 30000).catch((e) => {
              throw new Error('get_file 失败：' + (e?.message || e));
            });
            const urls = [info?.url, info?.file, info?.data?.url, info?.data?.file]
              .filter((u) => typeof u === 'string' && /^https?:\/\//.test(u));
            if (!urls.length) {
              return err('拿不到这个文件：本地临时目录没有、NapCat 也没返回下载地址。'
                + '可以请主人重新发一次，或者直接把内容贴出来。');
            }
            const res = await fetch(urls[0], { signal: AbortSignal.timeout(120000) });
            if (!res.ok) return err('下载失败 HTTP ' + res.status);
            buf = Buffer.from(await res.arrayBuffer());
          }
          fsmod.writeFileSync(dest, buf);

          // ③ 文本类文件直接读出内容，图片交给视觉，其它类型给出路径
          const preview = readTextPreview(dest);
          if (preview) {
            return ok({
              saved: dest,
              name: f.name || safeName,
              size: buf.length,
              text: preview,
              note: '文件内容已读出来了，可以直接据此回答；要交给 DSH 处理时把 saved 路径写进任务描述。'
            });
          }
          return ok({
            saved: dest,
            name: f.name || safeName,
            size: buf.length,
            note: '非文本文件已存到本地。图片可用 get_message_images，或把 saved 路径写进 dsh_task 让人处理。'
          });
        } catch (error) {
          return err(`接收文件失败：${error?.message ?? error}`);
        }
      }
    },
    {
      name: 'send_file',
      masterOnly: true,
      description: '【主人专属】把本地文件（DSH 任务产物，位于本项目 dsh-work/ 下）作为文件消息发送到当前聊天。主人任务完成后要文件时用。',
      parameters: {
        type: 'object',
        properties: {
          filePath: { type: 'string', description: '本地文件绝对路径（限 dsh-work/ 或 workspace/ 或 /tmp）' },
          fileName: { type: 'string', description: '可选：发送时显示的文件名' }
        },
        required: ['filePath']
      },
      async execute(ctx, args) {
        try {
          const raw = String(args.filePath ?? '').trim();
          if (!raw) return err('filePath 不能为空');
          const allowedPrefixes = [DSH_WORK_DIR, WORKSPACE_DIR, ...TEMP_DIRS];
          const okPath = allowedPrefixes.some((p) => raw.startsWith(p)) && !raw.includes('..');
          if (!okPath) return err('文件路径不在允许范围（仅 dsh-work/workspace/tmp）');
          const fs2 = await import('node:fs');
          if (!fs2.existsSync(raw)) return err(`文件不存在: ${raw}`);
          const stat = fs2.statSync(raw);
          if (!stat.isFile()) return err('目标不是文件');
          if (stat.size > 50 * 1024 * 1024) return err('文件超过 50MB 上限');
          const result = await ctx.sender.sendFile(ctx.chatKey, raw, String(args.fileName || '').trim() || undefined);
          ctx.session.sent.push({ type: 'file', text: `[文件:${String(args.fileName || raw.split('/').pop())}]`, at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ sent: true, fileId: result?.file_id ?? null, note: '文件已发送。' });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'list_stickers',
      description: '查看/搜索你的 QQ 收藏表情（含备注和你的本地笔记）。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '可选搜索词，匹配备注/笔记/标签' },
          limit: { type: 'integer', description: '最多返回条数，默认 24' }
        }
      },
      async execute(ctx, args) {
        try {
          const result = await ctx.stickers.list(String(args.query ?? ''), Math.min(100, Math.max(1, Number(args.limit) || 24)));
          return ok(result);
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'get_sticker_image',
      description: '查看一个没有备注/不确定含义的表情的图片（视觉模型可直接"看懂"）。',
      parameters: {
        type: 'object',
        properties: { stickerId: { type: 'string', description: '表情 id' } },
        required: ['stickerId']
      },
      async execute(ctx, args) {
        try {
          const sticker = await ctx.stickers.find(args.stickerId);
          if (!sticker) return err(`找不到表情 ${args.stickerId}`);
          if (!sticker.url) return err('该表情没有图片地址');
          const dataUrl = await downloadImageAsDataUrl(sticker.url);
          return { content: imageParts(`表情 ${sticker.id}（备注：${sticker.desc || '无'}）：`, [dataUrl]) };
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'sticker_note',
      description: '给一个表情记下你的理解（含义/用法/标签），下次能更准地选用。',
      parameters: {
        type: 'object',
        properties: {
          stickerId: { type: 'string' },
          note: { type: 'string', description: '你的理解/含义' },
          tags: { type: 'array', items: { type: 'string' }, description: '标签列表（可选）' },
          usage: { type: 'string', description: '适用场景（可选）' }
        },
        required: ['stickerId']
      },
      async execute(ctx, args) {
        try {
          const entry = ctx.stickers.note(String(args.stickerId), { note: args.note, tags: args.tags, usage: args.usage });
          if (!entry) return err(`找不到表情 ${args.stickerId}`);
          return ok({ updated: true, id: entry.id, localNote: entry.localNote, tags: entry.tags });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'collect_sticker',
      description: '收藏别人刚发的表情/图片到你的表情库（偶尔用，收藏前先 get_message_images 看图确认）。需要备注一句简短说明。',
      parameters: {
        type: 'object',
        properties: {
          messageId: { type: ['integer', 'string'], description: '那条消息的 QQ 消息 id（聊天记录里的 #数字）' },
          note: { type: 'string', description: '一句简短备注（帮未来的你识别）' }
        },
        required: ['messageId']
      },
      async execute(ctx, args) {
        try {
          const entry = ctx.store.findByMid(ctx.chatKey, args.messageId);
          if (!entry) return err(`在当前会话找不到消息 ${args.messageId}。${midHint(ctx)}`);
          const imageMedia = (entry.media || []).find((m) => m.kind === 'image' && m.url);
          if (!imageMedia) return err('该消息没有可收藏的图片');
          const saved = ctx.stickers.collect(args.messageId, { url: imageMedia.url, note: String(args.note ?? '') });
          return ok({ collected: true, id: saved.id, note: saved.localNote });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'send_voice',
      description: '把一句话念出来、以 QQ 语音消息发出去。⚠️ 只有对方**明确要求语音**时才用（"用语音说""发条语音""念给我听""说句话我听听"）；日常聊天一律用文字，不要主动发语音。建议 ≤100 字，太长会被拒绝。',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: '要念出来的内容（纯文本，≤200 字，不要带表情符号或 Markdown）' },
          voice: { type: 'string', description: '可选：临时换音色（edge-tts 的 voice 名），一般不用填' }
        },
        required: ['text']
      },
      async execute(ctx, args) {
        const cfg = getConfig();
        const tts = cfg.tts || {};
        if (tts.enabled === false) return err('语音功能现在是关闭的，请改用文字回复');
        const text = String(args.text ?? '').replace(/\s+/g, ' ').trim();
        if (!text) return err('要念的内容是空的');
        const maxChars = Number(tts.maxChars) || 200;
        if (text.length > maxChars) {
          return err(`太长了（${text.length} 字 > ${maxChars} 字）念不完，请改用文字或缩短内容`);
        }
        const voice = String(args.voice || tts.voice || 'zh-CN-XiaoyiNeural').trim();
        const rate = String(tts.rate || '+0%');
        const pythonBin = String(tts.pythonPath || 'python3');
        const dir = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'qqvoice-'));
        const mp3 = path.join(dir, 'voice.mp3');
        try {
          await execFileP(pythonBin, [
            '-m', 'edge_tts', '--voice', voice, '--rate', rate,
            '--text', text, '--write-media', mp3
          ], { timeout: 90000 });
          const buf = await fs.promises.readFile(mp3);
          if (!buf.length) return err('语音合成出来是空的，改用文字回复吧');
          // ⚠️ 语音不挂引用（reply 段）：实测「回复 + 语音」在 QQ 客户端里显示成打不开的语音，
          //    去掉引用后群里能正常播放。语音靠内容本身表达指向，不需要引用。
          const res = await ctx.onebot.sendRecord(ctx.kind, ctx.chatId, buf, {});
          ctx.session?.sent?.push({
            type: 'voice',
            text: `[语音] ${text.slice(0, 60)}`,
            at: new Date().toLocaleTimeString('zh-CN', { hour12: false })
          });
          ctx.emit('session-update', ctx.session?.id);
          return ok({
            sent: true, voice, bytes: buf.length,
            messageId: res?.message_id ?? null,
            note: '语音已发出。不要再补一句"已发送"。'
          });
        } catch (error) {
          return err(`语音发送失败：${error?.message ?? error}（这句话请改用文字回复）`);
        } finally {
          fs.promises.rm(dir, { recursive: true, force: true }).catch(() => {});
        }
      }
    },
    {
      name: 'send_poke',
      description: '拍一拍（群聊传 targetUserId；私聊默认拍对方）。targetUserId 必须是数字 QQ 号：不知道对方 QQ 号时，先调 get_active_members 或 get_recent_messages 查到再拍，绝对不要传名字、昵称或"未知"。适合用"戳一下"代替一句废话、回应别人的拍一拍，或偶尔逗一下正在聊的人。别频繁。',
      parameters: {
        type: 'object',
        properties: { targetUserId: { type: ['integer', 'string'], description: '要拍的群友 QQ 号（数字，群聊必填；不知道就先查 get_active_members）' } }
      },
      async execute(ctx, args) {
        try {
          if (ctx.kind === 'group' && (args.targetUserId === undefined || args.targetUserId === null || String(args.targetUserId).trim() === '')) {
            return err(`群聊拍一拍必须传 targetUserId（数字 QQ 号）。${memberHint(ctx)}`);
          }
          let target = args.targetUserId;
          if (target !== undefined && target !== null && String(target).trim() !== '') {
            target = Number(target);
            if (!Number.isInteger(target) || target <= 0) {
              return err(`targetUserId 必须是正整数的 QQ 号（收到：${JSON.stringify(args.targetUserId)}）。${memberHint(ctx)}`);
            }
            await ctx.sender.poke(ctx.chatKey, target);
          } else {
            await ctx.sender.poke(ctx.chatKey, null);
          }
          return ok({ poked: true });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'get_recent_messages',
      description: '往前翻当前会话的更多历史消息（提示词里只带了最近一段；需要更早的上下文时用）。返回带 messageId（就是聊天记录里的 #数字），可用于引用或看图。',
      parameters: {
        type: 'object',
        properties: {
          limit: { type: 'integer', description: '最多返回条数，默认 30，最大 100' },
          offset: { type: 'integer', description: '跳过最近 N 条，用于翻更早的消息' }
        }
      },
      async execute(ctx, args) {
        const limit = Math.min(100, Math.max(1, Number(args.limit) || 30));
        const offset = Math.max(0, Number(args.offset) || 0);
        const messages = ctx.store.recent(ctx.chatKey, { limit, offset: offset + (ctx.session.pastStateCount || 0) });
        return ok({
          count: messages.length,
          messages: messages.map((m) => ({
            messageId: m.mid ?? undefined,
            time: new Date(m.ts).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }),
            sender: m.self ? '我' : m.senderName,
            text: m.text
          }))
        });
      }
    },
    {
      name: 'get_active_members',
      description: '查看当前会话最近活跃的成员（QQ 号、名字、最近发言时间、发言数），用于 @ 或拍一拍时找人。',
      parameters: {
        type: 'object',
        properties: { limit: { type: 'integer', description: '默认 10，最大 20' } }
      },
      async execute(ctx, args) {
        const members = ctx.store.activeMembers(ctx.chatKey, Math.min(20, Math.max(1, Number(args.limit) || 10)));
        return ok({
          members: members.map((m) => ({
            userId: m.userId,
            name: m.name,
            lastSeen: new Date(m.lastTs).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }),
            recentCount: m.count
          }))
        });
      }
    },
    {
      name: 'get_message_detail',
      description: '按 QQ 消息 id 查看单条消息详情（完整文本、发送者、时间）。id 用聊天记录里每条消息前的 #数字，不要自己编。',
      parameters: {
        type: 'object',
        properties: { messageId: { type: ['integer', 'string'], description: 'QQ 消息 id（聊天记录里的 #数字，可能为负数）' } },
        required: ['messageId']
      },
      async execute(ctx, args) {
        const entry = ctx.store.findByMid(ctx.chatKey, args.messageId);
        if (!entry) return err(`当前会话找不到消息 ${args.messageId}。${midHint(ctx)}`);
        return ok({
          messageId: entry.mid,
          time: new Date(entry.ts).toLocaleString('zh-CN', { hour12: false }),
          sender: entry.self ? '我' : entry.senderName,
          senderId: entry.senderId,
          text: entry.text,
          reply: entry.reply
        });
      }
    },
    {
      name: 'get_message_images',
      description: '查看某条消息里的图片/表情（视觉模型可以直接看懂）。消息文本出现 [图片] 时可用。id 用聊天记录里每条消息前的 #数字。',
      parameters: {
        type: 'object',
        properties: { messageId: { type: ['integer', 'string'], description: 'QQ 消息 id（聊天记录里的 #数字，可能为负数）' } },
        required: ['messageId']
      },
      async execute(ctx, args) {
        try {
          const entry = ctx.store.findByMid(ctx.chatKey, args.messageId);
          if (!entry) return err(`当前会话找不到消息 ${args.messageId}。${midHint(ctx)}`);
          const urls = (entry.media || []).filter((m) => m.kind === 'image' && m.url).map((m) => m.url);
          if (!urls.length) return ok(`消息 ${args.messageId} 没有可查看的图片`);
          const cache = await loadVisionCache();
          const dataUrls = [];
          const failed = [];
          const known = [];
          const freshHashes = [];
          for (const url of urls) {
            try {
              const { dataUrl, hash } = await downloadImageWithHash(url);
              const hit = cache[hash];
              if (hit && hit.caption) {
                // 老图：不再花一次视觉调用，直接告诉她你以前看过什么
                known.push({ hash, caption: hit.caption, times: hit.times || 1 });
                cache[hash].times = (hit.times || 1) + 1;
                cache[hash].at = Date.now();
                continue;
              }
              dataUrls.push(dataUrl);
              freshHashes.push(hash);
            } catch (e) { failed.push(String(e?.message ?? e)); }
          }
          await saveVisionCache();
          if (!dataUrls.length) {
            if (known.length) {
              return ok({
                cached: true,
                note: `这几张你都看过了，不用再看一遍：\n` + known.map((k) => `· ${k.caption}（见过 ${k.times} 次）`).join('\n')
              });
            }
            return err(`图片获取失败：${failed.join('；')}`);
          }
          const note = failed.length ? `（另有 ${failed.length} 张获取失败）` : '';
          const hashTip = freshHashes.length
            ? `\n（新图指纹：${freshHashes[0]}。看完用 remember_image(hash="${freshHashes[0]}", caption="一句话特征") 记下来，下次同一张就不用再看了）`
            : '';
          const knownTip = known.length ? `\n（另有 ${known.length} 张是老图：` + known.map((k) => k.caption).join('；') + '）' : '';
          return { content: imageParts(`消息 ${args.messageId} 的图片内容${note}${hashTip}${knownTip}：`, dataUrls) };
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'view_image',
      timeoutMs: 60000,
      description: '看一张图：给它图片直链（http/https），或消息的 #数字。合并转发里的图会以「图N = 直链」的形式给出，用这个工具就能看到画面。一次只看一张，最多 4 张图。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: '图片直链，或消息的 #数字' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        const raw = String(args.target || '').trim();
        if (!raw) return err('看哪张图？给我直链或消息 #数字');

        // ① 消息 id：复用已有逻辑
        if (/^#?\d+$/.test(raw)) {
          const entry = ctx.store.findByMid(ctx.chatKey, raw.replace(/^#/, ''));
          if (!entry) return err(`当前会话找不到消息 ${raw}`);
          const urls = (entry.media || []).filter((m) => m.kind === 'image' && m.url).map((m) => m.url);
          if (!urls.length) return err(`消息 ${raw} 里没有可看的图片`);
          const dataUrls = [];
          for (const u of urls.slice(0, 4)) {
            try { dataUrls.push(await downloadImageAsDataUrl(u)); } catch { /* 跳过失败的 */ }
          }
          if (!dataUrls.length) return err('图片下载失败（链接可能已过期）');
          return { content: imageParts(`消息 ${raw} 的图片：`, dataUrls) };
        }

        // ② 直链
        if (!/^https?:\/\//i.test(raw)) return err('只接受 http(s) 图片直链或消息 #数字');
        try {
          const dataUrl = await downloadImageAsDataUrl(raw);
          return { content: imageParts('图片内容：', [dataUrl]) };
        } catch (e) {
          return err(`图片打不开：${e?.message ?? e}（QQ 图床链接有时效，过期就取不到了）`);
        }
      }
    },
    {
      name: 'get_message_video',
      description: '查看某条消息里的视频画面（自动抽几帧给你看，听不到声音）。消息文本出现 [视频] 时可用。id 用聊天记录里每条消息前的 #数字。看不清就如实说看不清，不要瞎编内容。',
      parameters: {
        type: 'object',
        properties: {
          messageId: { type: ['integer', 'string'], description: 'QQ 消息 id（聊天记录里的 #数字，可能为负数）' },
          frames: { type: 'integer', description: '抽几帧，默认 6（2~10）' }
        },
        required: ['messageId']
      },
      async execute(ctx, args) {
        try {
          const entry = ctx.store.findByMid(ctx.chatKey, args.messageId);
          if (!entry) return err(`当前会话找不到消息 ${args.messageId}。${midHint(ctx)}`);
          const url = videoSourceOf(entry.media);
          if (!url) {
            return err('这条消息没有可读取的视频地址（OneBot 只给了文件 id，本地路径也不存在），看不到画面。'
              + '可以请对方把关键画面截图发过来，或者让对方用文字说下视频内容。');
          }
          const frames = Math.min(10, Math.max(2, Number(args.frames) || 6));
          const dataUrls = await extractVideoFrames(url, frames);
          return { content: imageParts(`消息 ${args.messageId} 的视频画面（共 ${dataUrls.length} 帧，按时间顺序）：`, dataUrls) };
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'bili_video',
      description: '看一个 B站视频：给 BV 号或链接，返回标题/UP主/简介/时长/播放量；如果配置了 B站登录（SESSDATA），还能读到字幕正文并据此总结内容。群里有人分享 B站视频、你想知道讲了什么时用。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: 'BV 号（如 BV1d8pU6xEZX）或完整 B站链接' },
          frames: { type: 'number', description: '可选：抽几帧看画面（默认 8；没有字幕时会自动抽，有字幕时默认不抽）' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        try {
          const resolved = await resolveBiliShort(args.target);
          const target = parseBiliTarget(resolved);
          if (!target) {
            const t = String(args.target || '');
            if (/douyin\.com|xhslink|xiaohongshu|kuaishou|weibo/i.test(t)) {
              return err('这个平台（抖音/小红书/快手/微博）需要登录态，目前读不了；换成 B站 链接，或把视频发到 QQ 里我直接看。');
            }
            return err('看不懂这个输入：请给 BV 号（如 BV1d8pU6xEZX）、B站链接（含 b23.tv 短链），或 QQ 视频消息的 #数字');
          }
          const sessdata = String(getConfig().bili?.sessdata || '').trim();
          const biliCookie = String(getConfig().bili?.cookie || '').trim();
          const query = target.kind === 'bvid' ? `bvid=${target.value}` : `aid=${target.value}`;
          const info = await biliGet(`https://api.bilibili.com/x/web-interface/view?${query}`, { sessdata, cookie: biliCookie });
          if (info.code !== 0 || !info.data) return err(`B站返回错误：${info.message || info.code}`);
          const d = info.data;
          const dur = Number(d.duration) || 0;
          const lines = [
            `标题：${d.title}`,
            `UP主：${(d.owner || {}).name || '未知'}`,
            `时长：${Math.floor(dur / 60)} 分 ${dur % 60} 秒`,
            `分区：${d.tname || '未知'}`,
            `播放 ${(d.stat || {}).view ?? '?'} / 点赞 ${(d.stat || {}).like ?? '?'}`,
            `简介：${String(d.desc || '').slice(0, 300) || '（无）'}`
          ];
          if (!sessdata) {
            lines.push('（未配置 B站 SESSDATA，读不到字幕——只能提供上面这些元信息，别再猜视频内容）');
            return ok(lines.join('\n'));
          }
          // 字幕：走 biliFetchSubtitles（WBI 签名 + aid/cid 归属校验 + 多接口回退）
          const subRes = await biliFetchSubtitles(d, { sessdata, cookie: biliCookie });
          const pick = subRes.pick;
          const forceFrames = process.env.FORCE_FRAMES === '1';
          for (const msg of subRes.rejected) lines.push(`（字幕接口：${msg}）`);
          if (!pick || forceFrames) {
            lines.push(forceFrames
              ? '（强制抽帧模式）'
              : '（拿不到归属于本视频的字幕，改用抽帧看画面）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          lines.push(`字幕来源：${subRes.via}`);
          let subUrl = String(pick.subtitle_url || '');
          if (subUrl.startsWith('//')) subUrl = 'https:' + subUrl;
          if (!/^https?:\/\//.test(subUrl)) {
            lines.push('（字幕地址为空或不合法，改用抽帧看画面）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          let body = null;
          try {
            body = await biliGet(subUrl, { sessdata, cookie: biliCookie });
          } catch (subErr) {
            lines.push(`（拉字幕失败：${subErr?.message ?? subErr}，改用抽帧）`);
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          const items = (body && body.body) || [];
          const fullText = items.map((i) => i.content || '').join('');
          const cap = Number(getConfig().bili?.maxSubtitleChars) || 6000;
          lines.push(`字幕：${pick.lan_doc || pick.lan}，${items.length} 句`);
          lines.push(`字幕正文（${Math.min(fullText.length, cap)} 字）：`);
          lines.push(fullText.slice(0, cap));
          // 字幕太少（<200 字）等于没有，同样补抽帧看画面
          if (fullText.length < 200) {
            lines.push('（字幕内容太少，补充画面帧）');
            return await biliFramesResult(d, lines, args, { sessdata, cookie: biliCookie });
          }
          return ok(lines.join('\n'));
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },

    {
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
          const flat = await readForwardDeep(ctx.onebot, fid, { maxItems: 30, maxChars: 2500 });
          if (!flat.text) return err('这条转发没读出内容（可能全是图片，或 NapCat 不支持）');
          return ok(`合并转发（含嵌套层）读出 ${flat.count} 行：\n${flat.text}`);
        } catch (e) {
          return err(`读转发失败：${e?.message ?? e}`);
        }
      }
    },
    {
      name: 'search_image',
      description: '搜参考图：按关键词找到可用的图片直链。想画某个角色/场景/风格但手头没有参考图时，先用它搜，再把拿到的某个链接传给 gpu_draw 的 reference 参数，就能照着画。返回 3~8 条直链（已过滤死链）。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '搜什么图，中文英文都行，例如「鲸鱼娘 动漫」「赛博朋克 街道 夜景」' },
          count: { type: 'number', description: '要几条（默认 5，最多 8）' }
        },
        required: ['query']
      },
      async execute(ctx, args) {
        const q = String(args.query || '').trim();
        if (!q) return err('要搜什么图呀？给我关键词');
        const want = Math.max(3, Math.min(8, Number(args.count) || 5));
        const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';

        // 翻两页，多拿候选（Bing 首页常常只给几条可用）
        const candidates = [];
        for (const [first, host] of [[0, 'cn.bing.com'], [35, 'cn.bing.com'], [0, 'www.bing.com']]) {
          const pageUrl = `https://${host}/images/async?q=${encodeURIComponent(q)}&first=${first}&count=35&mmasync=1`;
          try {
            const res = await fetch(pageUrl, {
              headers: { 'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9', Referer: `https://${host}/images/search` },
              signal: AbortSignal.timeout(20000)
            });
            if (!res.ok) continue;
            const html = await res.text();
            const re = /murl&quot;:&quot;([^&]+?)&quot;/g;
            let m;
            while ((m = re.exec(html)) !== null) {
              let u = m[1];
              try { u = decodeURIComponent(u); } catch { /* 原样 */ }
              u = u.replace(/\\u0026/g, '&');
              if (!/^https?:\/\//i.test(u)) continue;
              if (!candidates.includes(u)) candidates.push(u);
            }
          } catch { /* 换源继续 */ }
          if (candidates.length >= want * 4) break;
        }
        if (!candidates.length) return ok('没搜到可用图片，换个关键词试试（或直接用文字描述画）。');

        // 轻量校验：能下载、体积够（>8KB 基本排除占位图/图标）
        const images = [];
        for (const u of candidates) {
          if (images.length >= want) break;
          try {
            const r = await fetch(u, {
              headers: { 'User-Agent': UA, Referer: 'https://cn.bing.com/' },
              signal: AbortSignal.timeout(6000)
            });
            if (!r.ok) continue;
            const buf = Buffer.from(await r.arrayBuffer());
            if (buf.length < 8 * 1024) continue;
            images.push({ url: u, sizeKB: Math.round(buf.length / 1024) });
          } catch { /* 跳过死链 */ }
        }
        if (!images.length) return ok('搜到链接但都打不开（可能图床防盗链），换个关键词再试。');

        const lines = images.map((x, i) => `${i + 1}. ${x.url}  (${x.sizeKB}KB)`);
        return ok({
          query: q,
          images: images.map((x) => x.url),
          note: `把其中一条传给 gpu_draw 的 reference 参数就能照着画。列表：\n${lines.join('\n')}`
        });
      }
    },
    {
      name: 'watch_video',
      timeoutMs: 900000,
      description: '看视频并说出来讲了什么：给 B站 BV 号/链接，或 QQ 里那条视频消息的 #数字。会抽画面帧（你能看到）+ 转写语音（带时间戳）。别人发视频说"看看这个/这视频讲什么"时用它。整段下载（1 小时以内都能看），但语音只转写前 15 分钟；转写用的是本地小模型，专有名词可能听错，引用前先看画面。',
      parameters: {
        type: 'object',
        properties: {
          target: { type: 'string', description: 'B站 BV 号 / 链接，或 QQ 视频消息的 #数字' },
          frames: { type: 'number', description: '抽几帧（默认 6，最多 10）' }
        },
        required: ['target']
      },
      async execute(ctx, args) {
        let raw = String(args.target || '').trim();
        if (!raw) return err('要看哪个视频？给我 BV 号、链接，或视频消息的 #数字');
        // B站短链先展开成含 BV 的长链（群友几乎都用 b23.tv）
        if (!/^#?[0-9]+$/.test(raw)) raw = await resolveBiliShort(raw);
        const wantFrames = Math.max(3, Math.min(10, Number(args.frames) || 6));
        const tmpDir = path.join(os.tmpdir(), `watch-${Date.now()}`);
        fs.mkdirSync(tmpDir, { recursive: true });
        let videoPath = '';
        let title = '';
        let meta = [];
        try {
          // ① 来源：B站 还是 QQ 视频消息
          const bili = /^[#]?\d+$/.test(raw) ? null : parseBiliTarget(raw);
          if (bili) {
            const sessdata = String(getConfig().bili?.sessdata || '').trim();
            const biliCookie = String(getConfig().bili?.cookie || '').trim();
            const query = bili.kind === 'bvid' ? `bvid=${bili.value}` : `aid=${bili.value}`;
            const info = await biliGet(`https://api.bilibili.com/x/web-interface/view?${query}`, { sessdata, cookie: biliCookie });
            if (info.code !== 0 || !info.data) return err(`B站返回错误：${info.message || info.code}`);
            const d = info.data;
            title = String(d.title || '');
            const dur = Number(d.duration) || 0;
            if (dur > 360) {
              meta.push(`原片 ${Math.round(dur / 60)} 分钟，整段下载`);
            } else {
            meta.push(`时长 ${Math.floor(dur / 60)} 分 ${dur % 60} 秒`);
            }
            // 播放上报：让这次观看进入 B站 观看历史（否则小号/其他设备看不到她看过什么）
            try {
              const rep = await biliReportPlayed({
                aid: d.aid, bvid: d.bvid, cid: d.cid,
                sessdata, cookie: biliCookie || cookie
              });
              if (rep?.skipped) meta.push('历史：今天已上报过这条');
              else if (rep?.ok) meta.push('历史：已记入观看历史');
              else meta.push('历史：上报未成功（' + (rep?.reason || 'code ' + rep?.click) + '）');
            } catch (e) { meta.push('历史：上报异常 ' + (e?.message ?? e)); }

            // 稍后再看：比历史稳，列表超过 50 条自动清最早的
            try {
              const tcv = await biliAddToview({ aid: d.aid, cookie: biliCookie || cookie, sessdata });
              if (tcv?.ok) {
                const trim = await biliTrimToview(biliCookie || cookie, 50);
                meta.push('稍后再看：已加入' + (trim?.removed ? '（清理了 ' + trim.removed + ' 条旧的）' : ''));
              } else {
                meta.push('稍后再看：加入未成功（' + (tcv?.reason || 'code ' + tcv?.code) + '）');
              }
            } catch (e) { meta.push('稍后再看：异常 ' + (e?.message ?? e)); }

            const play = await biliPlayUrl(d.bvid, d.cid, { sessdata, cookie: biliCookie });
            if (!play?.url) return err('拿不到播放地址（可能需要登录或该视频受限）');
            // 2026-11-09：长视频也整段下载；但超过 1 小时的不下（体积/耗时不可控）
            const MAX_DL_SEC = 3600;
            if (dur > MAX_DL_SEC) {
              return err(`这个视频 ${Math.round(dur / 60)} 分钟，超过 1 小时上限，不下载了`);
            }
            videoPath = path.join(tmpDir, 'v.mp4');
            {
              const hdrs = [
                'Referer: https://www.bilibili.com/',
                `User-Agent: ${BILI_UA}`,
                ...(biliCookie ? [`Cookie: ${biliCookie}`] : [])
              ].join('\r\n');
              // 整段流式拉取（-c copy 不转码）；超时按视频长度放宽，最多 15 分钟
              const dlTimeout = Math.max(180000, Math.min(900000, (dur || 300) * 1500));
              try {
                await execFileP(process.env.FFMPEG_BIN || 'ffmpeg',
                  ['-y', '-v', 'error', '-headers', hdrs + '\r\n',
                   '-i', play.url, '-c', 'copy', videoPath],
                  { timeout: dlTimeout });
              } catch (e) {
                try {
                  const res = await fetch(play.url, {
                    headers: { 'User-Agent': BILI_UA, Referer: 'https://www.bilibili.com/', ...(biliCookie ? { Cookie: biliCookie } : {}) },
                    signal: AbortSignal.timeout(420000)
                  });
                  if (!res.ok) return err(`视频下载失败 HTTP ${res.status}`);
                  fs.writeFileSync(videoPath, Buffer.from(await res.arrayBuffer()));
                } catch (e2) {
                  return err(`下载失败（${Math.round(dur / 60)} 分钟）：${e?.message ?? e} / ${e2?.message ?? e2}`);
                }
              }
              if (!fs.existsSync(videoPath) || fs.statSync(videoPath).size < 20480) {
                return err('下载失败：拿到的内容太小');
              }
            }
          } else {
            const entry = ctx.store.findByMid(ctx.chatKey, raw.replace(/^#/, ''));
            if (!entry) return err(`当前会话找不到消息 ${raw}`);
            const src = videoSourceOf(entry.media);
            if (!src) return err('这条消息里没有可读的视频');
            if (src.kind === 'file') {
              videoPath = src.value;
            } else {
              const res = await fetch(src.value, { headers: { 'User-Agent': 'Mozilla/5.0' }, signal: AbortSignal.timeout(180000) });
              if (!res.ok) return err(`视频下载失败 HTTP ${res.status}`);
              const buf = Buffer.from(await res.arrayBuffer());
              videoPath = path.join(tmpDir, 'v.mp4');
              fs.writeFileSync(videoPath, buf);
            }
            title = '（QQ 里的视频）';
          }

          // ② 时长与帧
          let duration = 0;
          try {
            const { stdout } = await execFileP(process.env.FFPROBE_BIN || 'ffprobe',
              ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', videoPath],
              { timeout: 20000 });
            duration = Math.round(parseFloat(String(stdout).trim()) || 0);
          } catch { /* 忽略 */ }
          if (duration) meta.push(`实测时长 ${duration} 秒`);

          // 2026-11-09：视频不裁了，整段看。
          // 但语音转写仍然只做前 15 分钟（1 小时音频全转太慢，会撞工具超时）。
          const MAX_ASR_SEC = 480;
          let asrPath = videoPath;
          if (duration > MAX_ASR_SEC) {
            const cut = path.join(tmpDir, 'asr15.mp4');
            try {
              await execFileP(process.env.FFMPEG_BIN || 'ffmpeg',
                ['-y', '-v', 'error', '-t', String(MAX_ASR_SEC), '-i', videoPath, '-c', 'copy', cut],
                { timeout: 120000 });
              if (fs.existsSync(cut) && fs.statSync(cut).size > 10240) asrPath = cut;
            } catch { /* 裁失败就把整段丢给 ASR */ }
            meta.push(`语音：只转写了前 ${Math.round(MAX_ASR_SEC / 60)} 分钟（整片 ${Math.round(duration / 60)} 分钟）`);
          }

          const dataUrls = await extractVideoFrames({ kind: 'file', value: videoPath }, wantFrames).catch(() => []);

          // ③ 音轨 → ASR
          let transcript = '';
          let voiceInfo = '';
          try {
            const wav = path.join(tmpDir, 'a.wav');
            await execFileP(process.env.FFMPEG_BIN || 'ffmpeg',
              ['-y', '-v', 'error', '-i', asrPath, '-vn', '-ac', '1', '-ar', '16000', wav],
              { timeout: 120000 });
            // 优先用主人电脑上的 small 模型（准得多，经隧道）；不可用时退回服务器本地 base
            let j = null;
            const remoteAsr = String(process.env.ASR_REMOTE_URL || 'http://127.0.0.1:9902').replace(/\/+$/, '');
            try {
              const audio = fs.readFileSync(wav);
              const res = await fetch(`${remoteAsr}/asr?lang=zh`, {
                method: 'POST',
                headers: { 'content-type': 'application/octet-stream' },
                body: audio,
                signal: AbortSignal.timeout(600000)
              });
              if (res.ok) j = await res.json();
            } catch { /* 电脑没开就退回本地 */ }
            if (!j || !j.ok) {
              // 服务器只有 2 个 vCPU：base 模型转 3 分钟以上音频会把 CPU 吃满好几分钟
              // （2026-11-09 事故：残留测试 + 8 分钟音频 → 102% CPU 持续很久）
              const MAX_SERVER_ASR_SEC = 180;
              let wavSec = 0;
              try { wavSec = Math.max(0, (fs.statSync(wav).size - 44) / 32000); } catch { wavSec = 0; }
              if (wavSec > MAX_SERVER_ASR_SEC) {
                j = { ok: false, note: `服务器转写跳过（音频 ${Math.round(wavSec)} 秒 > ${MAX_SERVER_ASR_SEC} 秒上限，避免占满 CPU）` };
              } else {
                const py = process.env.ASR_PYTHON || '/opt/qq-agent/.venv-asr/bin/python';
                const script = path.join(ROOT, 'asr.py');
                const asrModel = process.env.ASR_MODEL_DIR || '/opt/qq-agent/models/faster-whisper-base';
                const niceBin = fs.existsSync('/usr/bin/nice') ? '/usr/bin/nice' : '';
                const argv = niceBin
                  ? [niceBin, '-n', '19', py, script, wav, asrModel, 'zh']
                  : [py, script, wav, asrModel, 'zh'];
                const { stdout } = await execFileP(argv[0], argv.slice(1),
                  { timeout: 600000, maxBuffer: 16 * 1024 * 1024 });
                j = JSON.parse(String(stdout).trim() || '{}');
                if (j?.ok) j.note = (j.note || '') + '（服务器本地模型）';
              }
            }
            if (j.ok) {
              voiceInfo = j.note || '';
              if (j.voice && j.segments?.length) {
                const lines = j.segments.slice(0, 60).map((x) => {
                  const mm = Math.floor(x.start / 60);
                  const ss = String(Math.round(x.start % 60)).padStart(2, '0');
                  return `${mm}:${ss} ${x.text}`;
                });
                transcript = lines.join('\n');
              }
            } else {
              voiceInfo = `转写不可用：${j.error || j.note || j.reason || "没有返回结果（可能超时）"}`;
            }
          } catch (e) {
            voiceInfo = `转写失败：${e?.message ?? e}`;
          }

          // 记一笔「今天看过什么」，供每日汇报用
          try {
            const d = new Date();
            const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
            const dir = path.join(DATA_DIR, 'watched');
            fs.mkdirSync(dir, { recursive: true });
            const brief = (transcript || '').split('\n').slice(0, 3).join(' ').slice(0, 60);
            fs.appendFileSync(path.join(dir, day + '.jsonl'),
              JSON.stringify({ at: d.toISOString(), title, brief }) + '\n', 'utf8');
          } catch { /* 记录失败不影响看视频 */ }

          const head = [
            `视频：${title}`,
            meta.length ? `信息：${meta.join('，')}` : '',
            `抽帧：${dataUrls.length} 张（按时间顺序，均匀分布）`,
            voiceInfo ? `语音：${voiceInfo}` : '',
            transcript ? `语音转写（时间戳 分:秒）：\n${transcript}` : '语音：没有可用的转写（可能没人说话，或模型太小吃力）',
            '',
            '注意：帧只能看画面，转写可能有同音错字；**两者对不上时以画面为准**，拿不准就说"这个我说不准"。'
          ].filter(Boolean).join('\n');

          if (dataUrls.length) return { content: imageParts(head, dataUrls) };
          return ok(head);
        } catch (error) {
          return err(`看视频失败：${error?.message ?? error}`);
        } finally {
          try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch { /* 忽略 */ }
        }
      }
    },
    {
      name: 'gpu_tts',
      description: '用主人电脑上的显卡合成语音（爱弥斯音色）并发成 QQ 语音。别人要你"用语音说/说句话/念出来"，或你自己想用声音说话时用它。text 是口语文本，别带表情符号和 Markdown，≤100 字。需要主人电脑开着，通常 20~30 秒；超时会说"还在合成"，好了自动发出来。',
      parameters: {
        type: 'object',
        properties: {
          text: { type: 'string', description: '要说的话，纯口语，不要表情符号' }
        },
        required: ['text']
      },
      async execute(ctx, args) {
        let text = String(args.text || '').trim();
        if (!text) return err('要说什么呀？给我一句话');
        text = text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').slice(0, 100).trim();
        const cfg = getConfig().ttsGpu || {};
        const base = String(cfg.baseUrl || 'http://127.0.0.1:9900').replace(/\/+$/, '');
        try {
          const res = await fetch(`${base}/tts`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ text }),
            signal: AbortSignal.timeout(Number(cfg.timeoutMs) || 180000)
          });
          if (!res.ok) {
            const detail = await res.text().catch(() => '');
            return err(`语音服务返回 ${res.status}：${detail.slice(0, 120)}`);
          }
          const buf = Buffer.from(await res.arrayBuffer());
          if (!buf.length) return err('语音服务返回了空音频');
          await ctx.onebot.sendRecord(ctx.kind, ctx.chatId, buf);
          ctx.session.sent.push({ type: 'voice', text: '[语音]' + text.slice(0, 30), at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit('session-update', ctx.session.id);
          return ok({ spoken: true, bytes: buf.length, note: '语音已发出。' });
        } catch (error) {
          const msg = String(error?.message || error);
          if (/ECONNREFUSED|fetch failed|aborted|ETIMEDOUT/i.test(msg)) {
            return err('语音服务没响应——主人电脑可能没开，或者 TTS 服务没起。可以先说一句"语音那边没连上，我先打字"。');
          }
          return err(`语音合成失败：${msg}`);
        }
      }
    },
    {
      name: 'gpu_draw',
      timeoutMs: 240000,
      description: '画图：把画面描述交给主人电脑上的显卡（ComfyUI + 千问 Qwen-Image）画出来并发到当前聊天。别人说"画一张/帮我画/来张图/画个表情包"时用它。prompt 写具体（主体+外观+环境+光线+风格）。需要主人电脑开着，通常 20~60 秒出图；若超过两分钟工具会说"还在画"，图好了会自动发出来。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，中文即可，写得具体一点' },
          size: { type: 'string', description: '可选：1:1（默认）/ 3:4 / 4:3 / 16:9 / 9:16' },
          reference: { type: 'string', description: '参考图（可选）：别人发的图片消息的 #数字，或 http(s) 图片直链。给了就走图生图——保留参考图里的角色/画风，按 prompt 改姿势、换环境、换衣服。' },
          style: { type: 'string', description: '画风（可选）：anime=日系动漫 / realistic=写实摄影 / cinematic=电影感 / painterly=厚涂油画 / flat=扁平卡通。不给就按 prompt 自动判断' },
          detail: { type: 'string', description: '细节档位（可选）：normal=常规 / high=更精细 / ultra=极致细节（步数更多、分辨率更高、更慢）。默认 high' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        let prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我一句描述');

        // 画风预设：后缀 = 风格 + 画质，负向词压掉扁平/水印
        const STYLES = {
          anime: { suffix: '，日系动漫插画风格，赛璐璐上色，精致线稿，柔和明暗，高细节', neg: '低质量，简笔画，粗糙线条，扁平色块，模糊，变形，水印，文字，签名' },
          realistic: { suffix: '，写实摄影风格，真实材质纹理，自然光影，85mm 镜头，浅景深，超精细', neg: '卡通，简笔画，扁平色块，扭曲，模糊，水印，文字，签名，多余手指' },
          cinematic: { suffix: '，电影感画面，戏剧性布光，宽银幕构图，胶片颗粒，色彩分级，超精细', neg: '扁平，简笔画，呆板构图，模糊，水印，文字，签名' },
          painterly: { suffix: '，厚涂油画质感，丰富笔触，色彩层次，画布纹理，艺术感', neg: '扁平色块，简笔画，矢量图，模糊，水印，文字' },
          flat: { suffix: '，扁平卡通风格，干净色块，简洁造型', neg: '低质量，模糊，水印，文字' },
          detailed: { suffix: '，杰作，超高细节，精致光影，专业级插画质感，柔和景深，8k', neg: '低质量，简笔画，扁平色块，粗糙，模糊，变形，水印，文字，签名' }
        };
        const autoStyle = (() => {
          if (/动漫|二次元|插画|漫画|赛璐璐|anime/i.test(prompt)) return 'anime';
          if (/写实|照片|摄影|真实|photoreal/i.test(prompt)) return 'realistic';
          if (/电影|cinematic|剧情画面/i.test(prompt)) return 'cinematic';
          if (/油画|厚涂|painterly/i.test(prompt)) return 'painterly';
          return 'detailed';
        })();
        const styleKey = STYLES[String(args.style || '').toLowerCase()] ? String(args.style).toLowerCase() : autoStyle;
        const styleSpec = STYLES[styleKey];

        // 细节档位：决定追加的细节词、步数、像素量
        const DETAIL = {
          normal: { extra: '，细节清晰', steps: 30, mp: 1.3 },
          high: { extra: '，丰富细节，精细材质纹理，多层景深，微妙光影过渡，高保真', steps: 40, mp: 1.6 },
          ultra: { extra: '，极致细节，微距级纹理，复杂层次，体积光与散射，电影级色彩分级，锐利对焦，超高清', steps: 50, mp: 2.0 }
        };
        const detailKey = DETAIL[String(args.detail || '').toLowerCase()] ? String(args.detail).toLowerCase() : 'high';
        const detailSpec = DETAIL[detailKey];

        const finalPrompt = prompt + styleSpec.suffix + detailSpec.extra;
        const finalNegative = String(args.negative || '').trim() || styleSpec.neg;
        const finalSteps = detailSpec.steps;
        const finalMP = detailSpec.mp;
        const { submitDshTask } = await import('./dsh-task.js');

        // 解析参考图：QQ 消息 #id → 图片直链；也接受 http(s) 直链
        let refUrl = '';
        let refNote = '';
        const rawRef = String(args.reference || '').trim();
        if (rawRef) {
          if (/^https?:\/\//i.test(rawRef)) {
            refUrl = rawRef;
            refNote = '参考图：外部直链';
          } else {
            const mid = rawRef.replace(/^#/, '');
            const entry = ctx.store.findByMid(ctx.chatKey, mid);
            const img = (entry?.media || []).find((m) => m.kind === 'image' && (m.url || m.file));
            if (img?.url) {
              refUrl = img.url;
              refNote = `参考图：消息 #${mid}`;
            } else if (img?.file) {
              refUrl = img.file;
              refNote = `参考图：消息 #${mid}（file）`;
            }
          }
          if (!refUrl) return err(`找不到参考图（${rawRef}）——把带图的那条消息的 #数字给我，或者直接给图片链接`);
        }
        const token = 'QQDRAW-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
        const remote = `/tmp/qqbot-out/${token}.png`;
        const sizeArg = String(args.size || '').trim();
        const refLocal = `D:\\dshworks\\qqbot\\refs\\ref-${token}.png`;
        const taskText = refUrl ? [
          `画图任务 ${token}（图生图），请立刻执行，不要做别的事：`,
          `1. 先把参考图下载到本地（目录不存在就建）：`,
          `   mkdir -Force "D:\dshworks\qqbot\refs" | Out-Null; curl.exe -sSL -o "${refLocal}" "${refUrl}"`,
          `   下载后确认文件大小 > 10KB；失败就回复"参考图下载失败 ${token}"。`,
          `2. 调用 draw_image 工具：`,
          `   prompt 用下面这段（原样，别改写）：`,
          finalPrompt,
          `   negative 参数用这段（原样）：${finalNegative}`,
          `   steps 用 ${finalSteps}`,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `   megapixels 用 ${finalMP}`,
          `   reference 参数用这个本地路径（必须给，否则就变成文生图了）：${refLocal}`,
          `3. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\dshworks\qqbot\ssh\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `4. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\ComfyUI\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\n') : [
          `画图任务 ${token}，请立刻执行，不要做别的事：`,
          `1. 调用 draw_image 工具，prompt 用下面这段（原样，别改写）：`,
          finalPrompt,
          `   negative 参数用这段（原样）：${finalNegative}`,
          `   steps 用 ${finalSteps}`,
          sizeArg ? `   size 参数用 ${sizeArg}` : '',
          `   megapixels 用 ${finalMP}`,
          `2. 出图后工具会返回图片的绝对路径。用这条命令把图传到服务器：`,
          `   scp -i "D:\dshworks\qqbot\ssh\id_ed25519" -o StrictHostKeyChecking=accept-new "<图片绝对路径>" admin@116.62.149.191:${remote}`,
          `3. 命令退出码为 0 后，回复里只写一行：已上传 ${token}`,
          `如果 draw_image 报 ComfyUI 没启动，先运行 D:\ComfyUI\run_nvidia_gpu.bat 再重试一次。`
        ].filter(Boolean).join('\n');

        // 生图成功后立刻归档对话 + 删图（PC 侧 TTS 管家的 /cleanup 端点）
        const fireCleanup = async () => {
          try {
            const cfg = getConfig().ttsGpu || {};
            const base = String(cfg.baseUrl || 'http://127.0.0.1:9900').replace(/\/+$/, '');
            await fetch(`${base}/cleanup`, {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ minAgeSeconds: 1800 }),
              signal: AbortSignal.timeout(30000)
            });
          } catch { /* 清理失败不影响出图 */ }
        };

        const kind = ctx.kind;
        const chatId = ctx.chatId;
        const replyMid = (() => {
          if (args.replyToMessageId != null) return args.replyToMessageId;
          if (!String(ctx.chatKey || '').startsWith('group:')) return null;
          const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
          const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
          return last ? last.mid : null;
        })();

        try {
          await submitDshTask(taskText, { taskName: 'draw-' + token.slice(-4) });
        } catch (e) {
          return err(`派活失败（主人电脑上的 DSH 没连上）：${e?.message ?? e}`);
        }

        // 等服务端出现图片（最多 120 秒，不阻塞太久）
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        const deadline = Date.now() + 120000;
        while (Date.now() < deadline) {
          if (fs.existsSync(remote)) {
            try {
              const buf = await fs.promises.readFile(remote);
              await ctx.onebot.sendImageBuffer(kind, chatId, buf, { replyToMessageId: replyMid });
              ctx.session.sent.push({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
              ctx.emit('session-update', ctx.session.id);
              try { fs.unlinkSync(remote); } catch { /* 忽略 */ }
              fireCleanup();
              return ok({ drawn: true, reference: refUrl ? refNote : '无（文生图）', note: '画好了，已经发出来了（对话已归档、图片已清理）。' });
            } catch (e) {
              return err(`图好了但发送失败：${e?.message ?? e}`);
            }
          }
          await sleep(3000);
        }

        // 还没好：挂后台轮询，图到了自己发
        pendingDraws.push({ remote, kind, chatId, replyMid, deadline: Date.now() + 8 * 60 * 1000, onebot: ctx.onebot, session: ctx.session, emit: ctx.emit });
        ensureDrawPoller();
        return ok({ pending: true, note: '还在画（显卡那边要 20~60 秒），画好我会直接把图发出来，不用再问我。' });
      }
    },
    {
      name: 'write_handover',
      description: '把「更早的背景要点」写成交接摘要（覆盖写入，≤1200 字）。当【过去状态】提到很久以前的事、或重要背景即将滑出窗口时用；下次运行会在【交接摘要】里读到。不要复述最近的消息，只写背景/关系/约定/长期话题。',
      parameters: {
        type: 'object',
        properties: {
          content: { type: 'string', description: '交接摘要正文（纯文本，≤1200 字）' }
        },
        required: ['content']
      },
      async execute(ctx, args) {
        try {
          const cfgH = getConfig().handover || {};
          if (cfgH.enabled === false) return err('交接摘要功能已关闭');
          const maxChars = Number(cfgH.maxChars) || 1200;
          const content = String(args.content ?? '').trim();
          if (!content) return err('内容为空');
          if (content.length > maxChars) {
            return err(`太长了（${content.length} > ${maxChars} 字），压缩到 ${maxChars} 字以内再写`);
          }
          const dir = path.join(DATA_DIR, 'handover');
          await fs.promises.mkdir(dir, { recursive: true });
          const safe = String(ctx.chatKey || 'unknown').replace(/[^\w.-]+/g, '_');
          await fs.promises.writeFile(path.join(dir, `${safe}.md`), content + '\n', 'utf8');
          return ok({ saved: true, chars: content.length, file: `${safe}.md` });
        } catch (error) {
          return err(error?.message ?? error);
        }
      }
    },
    {
      name: 'memory_append',
      description: '记一条轻量记忆（下次运行会自动看到）：activeTopic=进行中的话题；pendingThought=想说但还没说的话；memberImpression=对某位群友的印象。偶尔用，别当笔记本。',
      parameters: {
        type: 'object',
        properties: {
          category: { type: 'string', enum: ['activeTopic', 'pendingThought', 'memberImpression'] },
          content: { type: 'string', description: '记忆内容' },
          target: { type: 'string', description: 'memberImpression 时的群友名字' }
        },
        required: ['category', 'content']
      },
      async execute(ctx, args) {
        const extra = {};
        if (args.target) extra.target = String(args.target).slice(0, 50);
        const entry = ctx.memory.append(ctx.chatKey, String(args.category), String(args.content ?? ''), extra);
        return ok({ saved: true, entry });
      }
    },
    {
      name: 'memory_query',
      description: '查看当前会话的轻量记忆。',
      parameters: {
        type: 'object',
        properties: { category: { type: 'string', enum: ['activeTopic', 'pendingThought', 'memberImpression'], description: '可选：只看某一类' } }
      },
      async execute(ctx, args) {
        return ok(ctx.memory.query(ctx.chatKey, args.category ? String(args.category) : ''));
      }
    },
    {
      name: 'memory_remove',
      description: '删除一条过时/不再重要的记忆。',
      parameters: {
        type: 'object',
        properties: {
          category: { type: 'string', enum: ['activeTopic', 'pendingThought', 'memberImpression'] },
          content: { type: 'string', description: '要删除的话题/想法原文（memberImpression 用 target）' },
          target: { type: 'string', description: 'memberImpression 时要删除的群友名字' }
        },
        required: ['category']
      },
      async execute(ctx, args) {
        const removed = ctx.memory.remove(ctx.chatKey, String(args.category), { content: String(args.content ?? ''), target: String(args.target ?? '') });
        return ok({ removed });
      }
    },
    {
      name: 'report_feedback',
      description: '向管理员（控制台）反馈你遇到的问题、困惑或需要人工介入的情况。不要用于聊天。',
      parameters: {
        type: 'object',
        properties: {
          level: { type: 'string', enum: ['info', 'warning', 'error'] },
          message: { type: 'string' }
        },
        required: ['message']
      },
      async execute(ctx, args) {
        const level = ['info', 'warning', 'error'].includes(args.level) ? args.level : 'info';
        ctx.session.feedbacks.push({ level, message: String(args.message ?? '').slice(0, 500), at: Date.now() });
        ctx.emit('feedback', { sessionId: ctx.session.id, chatKey: ctx.chatKey, level, message: String(args.message ?? '') });
        return ok({ reported: true });
      }
    },
    {
      name: 'web_search',
      description: '联网搜索，返回标题/URL/摘要列表。适用：实时信息、新闻热点、网络用语/梗的含义、自己不确定的事实。可以换关键词连续搜 2~3 次；对最相关的 1~2 个结果用 web_fetch 读正文，不要只看摘要。',
      parameters: {
        type: 'object',
        properties: { query: { type: 'string', description: '搜索词' } },
        required: ['query']
      },
      async execute(ctx, args) {
        try {
          const q = String(args.query ?? '');
          const provider = String(getConfig().webSearch?.provider || 'auto').toLowerCase();
          // bing：直接走 Bing 网页抓取
          if (provider === 'bing') {
            const r = await webSearch(q);
            if (!r.results.length) return ok({ query: r.query, results: [], note: '没有搜到结果，试试换关键词或更具体的说法。' });
            return ok({ ...r, engine: 'bing' });
          }
          // anysearch：只用 AnySearch（失败则如实报错，不回退）
          if (provider === 'anysearch') {
            const any = await anysearchSearch(q, { maxResults: 8 });
            if (any && any.results.length) return ok(any);
            return err('AnySearch 没有返回结果（可能 key 未配置或额度用尽）。可在设置 → 模型 API → 联网搜索里切换搜索引擎。');
          }
          // auto（默认）：有 key 优先 AnySearch，失败自动回退 Bing
          try {
            const any = await anysearchSearch(q, { maxResults: 8 });
            if (any && any.results.length) return ok(any);
          } catch (e) {
            // AnySearch 失败（429/超时等）→ 回退 Bing
          }
          const result = await webSearch(q);
          if (!result.results.length) {
            return ok({ query: result.query, results: [], note: '没有搜到结果，试试换关键词或更具体的说法。' });
          }
          return ok(result);
        } catch (error) {
          return err(`搜索失败：${error?.message ?? error}`);
        }
      }
    },
    {
      name: 'web_fetch',
      description: '只读抓取网页正文（≤2 万字符）。群友发来链接问"写了什么"时直接抓；配合 web_search 阅读搜索结果的详细内容。禁止访问内网/本机地址。',
      parameters: {
        type: 'object',
        properties: { url: { type: 'string', description: '要抓取的 http(s) URL' } },
        required: ['url']
      },
      async execute(ctx, args) {
        try {
          const result = await webFetch(String(args.url ?? ''));
          const body = String(result.body || '');
          const ct = String(result.contentType || '');

          // JSON/XML/纯文本直接用；HTML 一律先抽正文（否则模型只能看到标签汤）
          if (looksStructured(body, ct)) {
            return ok({
              url: result.url, statusCode: result.statusCode,
              truncated: result.truncated || body.length > 20000,
              format: 'raw',
              content: body.slice(0, 20000)
            });
          }

          const { text, thin } = htmlToText(body);
          const meta = extractMeta(body);
          if (!thin) {
            return ok({
              url: result.url, statusCode: result.statusCode,
              truncated: text.length > 20000,
              format: 'text',
              title: meta.title || undefined,
              content: text.slice(0, 20000)
            });
          }

          // 正文太薄：先让主人电脑上的 Chrome 渲染一遍（小黑盒/知乎/微博这类）
          try {
            const renderBase = String(process.env.RENDER_URL || 'http://127.0.0.1:9903').replace(/\/+$/, '');
            const rr = await fetch(`${renderBase}/render`, {
              method: 'POST',
              headers: { 'content-type': 'application/json' },
              body: JSON.stringify({ url: result.url }),
              signal: AbortSignal.timeout(75000)
            });
            if (rr.ok) {
              const rd = await rr.json();
              const rendered = String(rd?.text || '');
              if (rd?.ok && rendered.length >= 200) {
                return ok({
                  url: result.url,
                  statusCode: result.statusCode,
                  format: 'rendered',
                  title: rd.title || meta.title || undefined,
                  truncated: rendered.length > 20000,
                  content: rendered.slice(0, 20000)
                });
              }
            }
          } catch { /* 渲染服务不可用时走下面的提示 */ }
          // 正文太薄：多半是 JS 渲染（小黑盒/知乎/微博这类）
          const hint = [
            `这个页面正文只有 ${text.length} 个字符，基本可以判断是**需要 JS 渲染**的站点（或要求登录/反爬）。`,
            meta.title ? `页面标题：${meta.title}` : '',
            meta.description ? `页面简介：${meta.description.slice(0, 300)}` : '',
            text ? `能抓到的一点点文字：${text.slice(0, 600)}` : '',
            '建议：换它的移动版/详情接口，或让主人把内容截图发来；不要凭标题编内容。'
          ].filter(Boolean).join(String.fromCharCode(10));
          return ok({
            url: result.url, statusCode: result.statusCode,
            format: 'thin',
            thin: true,
            title: meta.title || undefined,
            content: hint
          });
        } catch (error) {
          return err(`抓取失败：${error?.message ?? error}`);
        }
      }
    },
    {
      name: 'search_video',
      timeoutMs: 60000,
      description: '搜视频：按关键词在 B站 搜视频，返回标题 / BV号 / 播放量 / 时长 / UP主。自己闲着想刷视频、或者别人说"找个讲XX的视频"时用它，挑一个再用 watch_video 看（传 BV 号）。',
      parameters: {
        type: 'object',
        properties: {
          keyword: { type: 'string', description: '搜什么，比如「中世纪 历史 纪录片」「编程 技术 讲解」' },
          count: { type: 'number', description: '返回几条（默认 6，最多 10）' },
          order: { type: 'string', description: '排序：totalrank=综合（默认）/ click=播放多 / pubdate=最新 / dm=弹幕多' }
        },
        required: ['keyword']
      },
      async execute(ctx, args) {
        const kw = String(args.keyword || '').trim();
        if (!kw) return err('要搜什么视频呀？给我关键词');
        const want = Math.max(3, Math.min(10, Number(args.count) || 6));
        const order = ['totalrank', 'click', 'pubdate', 'dm'].includes(String(args.order))
          ? String(args.order) : 'totalrank';
        const sessdata = String(getConfig().bili?.sessdata || '').trim();
        const cookie = String(getConfig().bili?.cookie || '').trim();
        let j;
        try {
          const q = await biliWbiSign(
            { search_type: 'video', keyword: kw, order, page: 1, page_size: want },
            { sessdata, cookie }
          );
          j = await biliGet(`https://api.bilibili.com/x/web-interface/wbi/search/type?${q}`, { sessdata, cookie });
        } catch (e) {
          // WBI 失败就退回老接口（有时还能用）
          try {
            const qs = new URLSearchParams({ search_type: 'video', keyword: kw, order, page: '1', page_size: String(want) });
            j = await biliGet(`https://api.bilibili.com/x/web-interface/search/type?${qs}`, { sessdata, cookie });
          } catch (e2) {
            return err(`搜视频失败：${e2?.message ?? e2}`);
          }
        }
        const list = j?.data?.result || [];
        if (!list.length) return ok(`没搜到「${kw}」的视频，换个词试试。`);
        const items = list.filter((x) => x.bvid).slice(0, want).map((x) => ({
          bvid: x.bvid,
          title: String(x.title || '').replace(/<[^>]+>/g, ''),
          up: String(x.author || ''),
          play: Number(x.play) || 0,
          dur: String(x.duration || ''),
          pub: Number(x.pubdate) ? new Date(Number(x.pubdate) * 1000).toISOString().slice(0, 10) : ''
        }));
        const lines = items.map((x, i) =>
          `${i + 1}. ${x.title}\n   ${x.bvid} | ${x.up} | 播放 ${x.play} | ${x.dur}${x.pub ? ' | ' + x.pub : ''}`);
        return ok({
          keyword: kw,
          count: items.length,
          videos: items,
          note: `挑一个用 watch_video(target="BV号") 看。列表：\n${lines.join('\n')}`
        });
      }
    },
    {
      name: 'draw_sdxl',
      timeoutMs: 300000,
      description: '画二次元/写实风格的图（SDXL + Illustrious 系模型，画风更精细、更贴二次元）。要画动漫角色、人物立绘、涩图、或者需要精细人体/姿势时用它，比 gpu_draw 更合适；gpu_draw 更适合日常场景、写实照片感、以及需要参考图的图生图。出图后直接把图发出来。',
      parameters: {
        type: 'object',
        properties: {
          prompt: { type: 'string', description: '画面描述，英文 tag 效果最好，也接受中文（主体+外貌+服装+姿势+场景+光线+画风）' },
          negative: { type: 'string', description: '可选：不想要的内容（英文）。不填用默认质量词' },
          size: { type: 'string', description: '可选：3:4（832x1216，默认）/ 2:3（832x1216）/ 1:1（1024x1024）/ 16:9（1216x832）/ 4:3（1152x864）' },
          steps: { type: 'number', description: '可选：采样步数，默认 28（20~40）' },
          cfg: { type: 'number', description: '可选：提示词强度，默认 5.5（4~8）' },
          seed: { type: 'number', description: '可选：随机种子，想让同一张图可复现就传' }
        },
        required: ['prompt']
      },
      async execute(ctx, args) {
        const prompt = String(args.prompt || '').trim();
        if (!prompt) return err('要画什么呀？给我描述');
        const SIZE = {
          '3:4': [832, 1216], '2:3': [832, 1216], '1:1': [1024, 1024],
          '16:9': [1216, 832], '4:3': [1152, 864], '9:16': [768, 1344]
        };
        const dims = SIZE[String(args.size || '').trim()] || [832, 1216];
        const base = String(process.env.SDXL_URL || 'http://127.0.0.1:9906').replace(/\/+$/, '');
        const payload = {
          prompt,
          negative: args.negative ? String(args.negative) : undefined,
          width: dims[0], height: dims[1],
          steps: Number(args.steps) || 28,
          cfg: Number(args.cfg) || 5.5,
          seed: Number(args.seed) || undefined,
          inline: true
        };
        let json;
        try {
          const r = await fetch(`${base}/draw`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(280000)
          });
          json = await r.json();
        } catch (e) {
          return err(`出图失败（画图服务没连上）：${e?.message ?? e}`);
        }
        if (!json?.ok || !json?.b64) {
          return err(`出图失败：${json?.error || '没有返回图片'}`);
        }
        try {
          const buf = Buffer.from(json.b64, 'base64');
          const replyMid = (() => {
            if (!String(ctx.chatKey || '').startsWith('group:')) return null;
            const trig = Array.isArray(ctx.session?.trigger) ? ctx.session.trigger : [];
            const last = [...trig].reverse().find((m) => m && m.mid != null && !m.self);
            return last ? last.mid : null;
          })();
          await ctx.onebot.sendImageBuffer(ctx.kind, ctx.chatId, buf, { replyToMessageId: replyMid });
          ctx.session?.sent?.push?.({ type: 'image', text: '[画的图]', at: new Date().toLocaleTimeString('zh-CN', { hour12: false }) });
          ctx.emit?.('session-update', ctx.session?.id);
          return ok({
            drawn: true, model: json.model, seed: json.seed, size: json.size,
            costSec: json.costSec, note: '画好了，已经发出来了。'
          });
        } catch (e) {
          return err(`图出来了但发送失败：${e?.message ?? e}`);
        }
      }
    },
    {
      name: 'remember_image',
      timeoutMs: 10000,
      description: '看完图后用一句话记下这张图的特征（配合 get_message_images 给出的指纹）。下次群里再发同一张（表情包/梗图/老图），会直接告诉你「你看过了：<特征>」，不用再花时间看一遍。',
      parameters: {
        type: 'object',
        properties: {
          hash: { type: 'string', description: '图片指纹（get_message_images 返回里给的「新图指纹」）' },
          caption: { type: 'string', description: '一句话特征，比如「白色猫猫头 打字 不要嘛」' }
        },
        required: ['hash', 'caption']
      },
      async execute(ctx, args) {
        const hash = String(args.hash || '').trim();
        const caption = String(args.caption || '').trim().slice(0, 120);
        if (!hash || !caption) return err('需要 hash 和 caption');
        const cache = await loadVisionCache();
        const prev = cache[hash] || {};
        cache[hash] = { caption, at: Date.now(), times: prev.times || 1 };
        await saveVisionCache();
        return ok({ saved: true, hash, caption, note: '记住了，下次这张直接认出来。' });
      }
    },
    {
      name: 'search_meme_wiki',
      timeoutMs: 15000,
      description: '查网络梗/黑话/缩写的含义。内置 6668 条本地词库，毫秒级返回，不联网。群友说了一个你没把握的新词（缩写、梗、黑话）时先查它，别硬猜、别编解释。查到就直接接梗，不要科普；只有对方明确问"这是什么梗"才解释一两句。',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', description: '要查的词（梗名、缩写、黑话）' }
        },
        required: ['query']
      },
      async execute(ctx, args) {
        const q = String(args.query || '').trim();
        if (!q) return err('要查哪个词？');
        try {
          const memes = await loadMemes();
          if (!memes.length) return err('梗词库没加载成功（data/memes.json 缺失）');
          const low = q.toLowerCase();
          const hits = [];
          // ① 精确
          for (const m of memes) {
            if (m.t.toLowerCase() === low) { hits.push({ m, score: 100 }); }
          }
          // ② 标题包含查询词 / 查询词包含标题
          if (hits.length === 0) {
            for (const m of memes) {
              const t = m.t.toLowerCase();
              if (t.includes(low)) hits.push({ m, score: 80 - Math.abs(t.length - low.length) });
              else if (low.length >= 2 && low.includes(t)) hits.push({ m, score: 60 - Math.abs(low.length - t.length) });
            }
          }
          if (hits.length === 0) return ok(`词库里没有「${q}」。不知道就说不知道，别编解释。`);
          hits.sort((a, b) => b.score - a.score);
          const top = hits.slice(0, 2).map((h) => ({
            title: h.m.t,
            tags: h.m.g || undefined,
            howToUse: (h.m.u || '').slice(0, 400) || undefined,
            summary: (h.m.s || '').slice(0, 260) || undefined
          }));
          return ok({
            query: q,
            found: top.length,
            entries: top,
            note: '查到就先接梗，别科普；对方明确问"这什么梗"才解释一两句。'
          });
        } catch (e) {
          return err(`查梗失败：${e?.message ?? e}`);
        }
      }
    },
    {
      name: 'check_usage',
      masterOnly: true,
      timeoutMs: 30000,
      description: '【主人专属】查 API 花费与余额：今日真实花费、当前余额、近几天每天花了多少。主人问"花了多少钱/余额还有多少/今天用了多少/还剩多少额度"时用它。数据来自 DeepSeek 余额差值（真实账单），不是估算。',
      parameters: {
        type: 'object',
        properties: {
          days: { type: 'number', description: '要回看几天（默认 7，最多 30）' }
        }
      },
      async execute(ctx, args) {
        const days = Math.max(1, Math.min(30, Number(args.days) || 7));
        const fsMod = await import('node:fs');
        const pathMod = await import('node:path');
        const { DATA_DIR } = await import('./config.js');
        const fs = fsMod.default || fsMod;
        const path = pathMod.default || pathMod;

        const billingPath = path.join(DATA_DIR, 'billing.json');
        const histPath = path.join(DATA_DIR, 'billing-history.jsonl');

        let today = null;
        try { today = JSON.parse(fs.readFileSync(billingPath, 'utf-8')); } catch { /* 没有就跳过 */ }

        // 实时余额（顺手刷新，避免展示几分钟前的数）
        let liveBalance = null;
        try {
          const key = String(getConfig().api?.apiKey || '').trim();
          if (key) {
            const r = await fetch('https://api.deepseek.com/user/balance', {
              headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' },
              signal: AbortSignal.timeout(15000)
            });
            if (r.ok) {
              const d = await r.json();
              const cny = (d.balance_infos || []).find((b) => String(b.currency).toUpperCase() === 'CNY');
              liveBalance = Number((cny || (d.balance_infos || [])[0] || {}).total_balance);
            }
          }
        } catch { /* 网络失败就用 billing.json 里的 */ }

        // 近几天：从流水聚合（每天取最后一条的 spent）
        const byDay = new Map();
        try {
          const lines = fs.readFileSync(histPath, 'utf-8').split('\n');
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const rec = JSON.parse(line);
              const day = String(rec.day || '');
              if (!day) continue;
              byDay.set(day, Number(rec.spent) || 0);
            } catch { /* 跳过坏行 */ }
          }
        } catch { /* 没有流水 */ }

        const dayList = [...byDay.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, days);
        const spentToday = today && String(today.dayKey) === new Date().toISOString().slice(0, 10)
          ? Number(today.spent) || 0
          : (byDay.get(new Date().toISOString().slice(0, 10)) || 0);
        const balance = liveBalance ?? (today ? Number(today.balance) : null);
        const cap = Number(getConfig().budget?.dailyCostYuan) || 0;

        const lines = [];
        lines.push(`今日真实花费：¥${spentToday.toFixed(2)}` + (cap > 0 ? `（每日上限 ¥${cap}）` : ''));
        if (balance != null && Number.isFinite(balance)) lines.push(`当前余额：¥${balance.toFixed(2)}`);
        if (cap > 0 && balance != null && spentToday > 0) {
          const perDay = spentToday;
          lines.push(`按今天的水平，余额够约 ${Math.max(0, Math.floor(balance / Math.max(0.01, perDay)))} 天`);
        }
        if (dayList.length) {
          lines.push('近几天：' + dayList.map(([d, v]) => `${d.slice(5)} ¥${Number(v).toFixed(2)}`).join(' · '));
        }
        const sampled = today?.sampledAt ? Math.round((Date.now() - Number(today.sampledAt)) / 60000) : null;
        if (sampled != null) lines.push(`（真实花费由余额差值算出，最近一次采样 ${sampled} 分钟前）`);

        return ok({ todaySpent: spentToday, balance, dailyCap: cap, history: Object.fromEntries(dayList), note: lines.join('\n') });
      }
    },
    {
      name: 'finish',
      description: '明确结束本次处理（表示你看完了、决定了下一步）。看完不打算说话时调用它（summary 写一句给自己看的理由）；说完话想收尾时也可以调用。不调用也可以——直接结束文本输出同样代表结束。',
      parameters: {
        type: 'object',
        properties: { summary: { type: 'string', description: '一句话说明你这次的决定（只记录给管理端看，不会发送）' } },
        required: ['summary']
      },
      async execute(ctx, args) {
        ctx.session.finishReason = String(args.summary ?? '').slice(0, 300);
        return ok({ finished: true });
      }
    },
    {
      name: 'dsh_task',
      masterOnly: true,
      description: '【主人专属】把耗时/复杂 agent 任务（做网页/PPT/文档/画图/批量处理/写代码等）转发给本机 DSH 执行。调用后立即返回任务已提交，然后向 master 说明已开工；DSH 完成后会自动向 master 汇报。',
      parameters: {
        type: 'object',
        properties: {
          task: { type: 'string', description: '要 DSH 完成的任务描述（尽量具体：做什么、什么格式、放哪）' },
          taskName: { type: 'string', description: '可选：任务名（用于工作目录命名，简短英文/数字）' }
        },
        required: ['task']
      },
      async execute(ctx, args) {
        try {
          const { submitDshTask } = await import('./dsh-task.js');
          const result = await submitDshTask(String(args.task ?? ''), {
            taskName: String(args.taskName || '')
          });
          // 注册待汇报任务（orchestrator watcher 轮询此表）
          const { registerDshTask } = await import('./dsh-task.js');
          // taskText/taskName 记下来：任务完成后唤醒汇报时要用它们说明"当初交待了什么"
          registerDshTask({
            sessionId: result.sessionId,
            workDir: result.workDir,
            chatKey: ctx.chatKey,
            taskText: String(args.task ?? '').slice(0, 400),
            taskName: String(args.taskName || ''),
            submittedAt: Date.now()
          });
          ctx.session.dshTask = { sessionId: result.sessionId, workDir: result.workDir, chatKey: ctx.chatKey, submittedAt: Date.now() };
          return ok({
            submitted: true,
            sessionId: result.sessionId,
            workDir: result.workDir,
            note: '任务已提交 DSH 后台执行。请立即回复 master「收到，已开工，DSH 正在做，完成后本鲸汇报」，然后正常结束本次处理。'
          });
        } catch (error) {
          return err(`任务提交失败：${error?.message ?? error}`);
        }
      }
    }
  ];

  // 生图工具只在配置了 key+model 时挂载（未配置就不占 token）
  const igc = getConfig().imageGen || {};
  return defs.filter((d) => d && (d.name !== 'image_gen' || (igc.enabled && igc.apiKey && igc.model)));
}

/** 转成 OpenAI tools 参数格式。 */
export function toOpenAiTools(defs) {
  return defs.map((d) => ({
    type: 'function',
    function: {
      name: d.name,
      description: d.description,
      parameters: d.parameters
    }
  }));
}

/** 找到并执行一个工具调用。返回 { content, isError }，content 为 string 或 parts 数组。 */
export async function executeTool(defs, ctx, name, argsJson) {
  const def = defs.find((d) => d.name === name);
  if (!def) return { content: `错误：未知工具 ${name}`, isError: true };
  let args = {};
  const raw = argsJson ?? '{}';
  try {
    args = typeof raw === 'string' ? JSON.parse(raw) : raw;
  } catch {
    return { content: `错误：工具 ${name} 的参数不是合法 JSON：${String(raw).slice(0, 200)}`, isError: true };
  }
  // 统一超时：任何工具都不许无限挂住（2026-10-26 曾因某个 await 永久挂起，
  // 把整个会话锁死 23 小时且不留日志）。单工具可用 timeoutMs 覆盖。
  const limitMs = Math.max(5000, Number(def.timeoutMs) || 180000);
  let timer = null;
  const timeout = new Promise((resolve) => {
    timer = setTimeout(() => resolve({
      content: `错误：工具 ${name} 超时（${Math.round(limitMs / 1000)} 秒未返回），已放弃本次调用`,
      isError: true
    }), limitMs);
  });
  try {
    return await Promise.race([def.execute(ctx, args ?? {}), timeout]);
  } catch (error) {
    return { content: `错误：${error?.message ?? error}`, isError: true };
  } finally {
    if (timer) clearTimeout(timer);
  }
}




// ── 知识库工具（教学身份用；从 qq-agent-tutor 移植并修复）────────────────
// 说明：本数组在 buildToolDefs 的 return 中被展开。因 const 提升限制，
// 定义位置需在 buildToolDefs 之后（函数调用时已初始化）。

/** 知识库工具名集合（供按身份过滤用）。 */
