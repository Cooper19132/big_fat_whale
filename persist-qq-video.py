#!/usr/bin/env python3
"""QQ 视频落盘：收到视频就下载到本地，避免 CDN 链接过期后"取不出来了"。

改动：
1. store.js 加 markVideoLocal(chatKey, mid, localPath) —— 把本地路径写回该条消息
2. app.js 入库后异步下载视频（≤80MB），写完回填路径
3. tools.js 的 videoSourceOf 优先用 localPath
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = r'D:\dshworks\qqbot\qq-agent\src'
results = []


def patch(fname, name, old, new, count=1):
    p = f'{BASE}\\{fname}'
    s = open(p, encoding='utf-8').read()
    n = s.count(old)
    if n != count:
        raise SystemExit(f'✗ {name}: 期望 {count} 处，实际 {n} 处')
    open(p, 'w', encoding='utf-8').write(s.replace(old, new, count))
    results.append(f'✓ {name}')


# ── 1) store.js：回填本地路径 ──
patch('store.js', 'store 加 markVideoLocal',
      """  findByLocalId(chatKey, localId) {""",
      """  /** 把已下载的视频本地路径写回消息（CDN 链接会过期，本地路径才长久）。 */
  markVideoLocal(chatKey, mid, localPath) {
    const st = this.#state(chatKey);
    const entry = st.messages.find((m) => String(m.mid) === String(mid));
    if (!entry) return false;
    let hit = false;
    for (const m of entry.media || []) {
      if (m.kind === 'video') { m.localPath = localPath; hit = true; }
    }
    if (hit) saveChat(st);
    return hit;
  }

  findByLocalId(chatKey, localId) {""")

# ── 2) app.js：入库后异步落盘 ──
patch('app.js', 'ingest 后异步下载视频',
      """    emit('chat-update', chatKey);""",
      """    emit('chat-update', chatKey);
    // 视频落盘：QQ 的视频直链会过期，收到就存一份（失败不影响主流程）
    if (media.some((m) => m.kind === 'video' && (m.url || m.file))) {
      persistVideo(chatKey, event.message_id, media).catch((e) => log('[视频] 落盘失败:', e?.message ?? e));
    }""")

# 插入 persistVideo 函数（放在 allowAutoWake 之前）
patch('app.js', '新增 persistVideo 实现',
      """  // 群聊「自主接话」节流：概率 + 最小间隔 + 每日上限""",
      """  /** 把视频下载到 data/inbox/video-<mid>.mp4 并回填路径。 */
  async function persistVideo(chatKey, mid, media) {
    const src = media.find((m) => m.kind === 'video' && (m.url || m.file));
    if (!src) return;
    const url = /^https?:\\/\\//i.test(String(src.url || '')) ? String(src.url) : '';
    if (!url) return;
    const dir = path.join(DATA_DIR, 'inbox');
    fs.mkdirSync(dir, { recursive: true });
    const dest = path.join(dir, `video-${String(mid || Date.now())}.mp4`);
    if (fs.existsSync(dest) && fs.statSync(dest).size > 1024) {
      store.markVideoLocal(chatKey, mid, dest);
      return;
    }
    const res = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0' },
      signal: AbortSignal.timeout(180000)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    if (!buf.length) throw new Error('空文件');
    if (buf.length > 80 * 1024 * 1024) throw new Error(`超过 80MB（${Math.round(buf.length / 1048576)}MB）`);
    fs.writeFileSync(dest, buf);
    store.markVideoLocal(chatKey, mid, dest);
    log(`[视频] 已落盘 ${path.basename(dest)}（${Math.round(buf.length / 1024)}KB）`);
  }

  // 群聊「自主接话」节流：概率 + 最小间隔 + 每日上限""")

# ── 3) tools.js：优先本地路径 ──
patch('tools.js', 'videoSourceOf 优先本地文件',
      """function videoSourceOf(media) {
  const m = (media || []).find((x) => x.kind === 'video' && (x.url || x.file));
  if (!m) return null;""",
      """function videoSourceOf(media) {
  const m = (media || []).find((x) => x.kind === 'video' && (x.localPath || x.url || x.file));
  if (!m) return null;
  // 已经落盘的优先用本地文件（CDN 链接会过期）
  const localPath = String(m.localPath || '').trim();
  if (localPath && path.isAbsolute(localPath) && fs.existsSync(localPath)) {
    const stat = fs.statSync(localPath);
    if (stat.isFile() && stat.size > 1024) return { kind: 'file', value: localPath };
  }""")

print('\n'.join(results))
