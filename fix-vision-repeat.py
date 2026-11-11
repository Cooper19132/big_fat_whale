#!/usr/bin/env python3
"""修「群里的老表情包反复识图」：
  ① 图片按内容哈希（sha256）指纹，不按 URL（QQ 每次重发都换签名 URL，URL 去重必然失败）
  ② 第一次看 → 返回图 + 提示她调用 remember_image 记一句特征
  ③ 以后同哈希 → 直接返回缓存的一句话描述，不再走视觉（省 token、省时间）
  ④ 新增 remember_image 工具写缓存
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

# ── ① 下载函数额外返回 hash（改为返回对象，但保留旧调用兼容） ──
old_dl = """async function downloadImageAsDataUrl(url, timeoutMs = 30000) {
  const safeUrl = await validateImageUrl(url);
  const delays = [600, 1500, 3000];
  let lastError = null;
  for (let attempt = 0; attempt <= delays.length; attempt++) {
    try {
      const { buffer, contentType } = await safeFetchBinary(safeUrl);
      if (!buffer || !buffer.length) throw new Error("图片内容为空");
      const mime = detectMime(buffer) || String(contentType || "image/jpeg").split(";")[0];
      return `data:${mime};base64,${buffer.toString("base64")}`;
    } catch (e) {
      lastError = e;
      if (attempt < delays.length) await new Promise((r) => setTimeout(r, delays[attempt]));
    }
  }
  throw lastError ?? new Error("图片下载失败");
}"""
new_dl = """async function downloadImageAsDataUrl(url, timeoutMs = 30000) {
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
}"""
assert s.count(old_dl) == 1, 'downloadImage 锚点不符'
s = s.replace(old_dl, new_dl, 1)

# ── ② get_message_images：命中缓存就不发图 ──
old_gmi = """          const urls = (entry.media || []).filter((m) => m.kind === 'image' && m.url).map((m) => m.url);
          if (!urls.length) return ok(`消息 ${args.messageId} 没有可查看的图片`);
          const dataUrls = [];
          const failed = [];
          for (const url of urls) {
            try { dataUrls.push(await downloadImageAsDataUrl(url)); } catch (e) { failed.push(String(e?.message ?? e)); }
          }
          if (!dataUrls.length) return err(`图片获取失败：${failed.join('；')}`);
          const note = failed.length ? `（另有 ${failed.length} 张获取失败）` : '';
          return { content: imageParts(`消息 ${args.messageId} 的图片内容${note}：`, dataUrls) };"""
new_gmi = """          const urls = (entry.media || []).filter((m) => m.kind === 'image' && m.url).map((m) => m.url);
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
                note: `这几张你都看过了，不用再看一遍：\\n` + known.map((k) => `· ${k.caption}（见过 ${k.times} 次）`).join('\\n')
              });
            }
            return err(`图片获取失败：${failed.join('；')}`);
          }
          const note = failed.length ? `（另有 ${failed.length} 张获取失败）` : '';
          const hashTip = freshHashes.length
            ? `\\n（新图指纹：${freshHashes[0]}。看完用 remember_image(hash="${freshHashes[0]}", caption="一句话特征") 记下来，下次同一张就不用再看了）`
            : '';
          const knownTip = known.length ? `\\n（另有 ${known.length} 张是老图：` + known.map((k) => k.caption).join('；') + '）' : '';
          return { content: imageParts(`消息 ${args.messageId} 的图片内容${note}${hashTip}${knownTip}：`, dataUrls) };"""
assert s.count(old_gmi) == 1, 'get_message_images 锚点不符'
s = s.replace(old_gmi, new_gmi, 1)

open(P, 'w', encoding='utf-8').write(s)
print('✓ 图片指纹 + 识图缓存已接入 get_message_images')
