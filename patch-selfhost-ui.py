p = '/opt/qq-agent/ui/app.js'
s = open(p, encoding='utf-8').read()
bak = p + '.bak-selfhost'
open(bak, 'w', encoding='utf-8').write(s)

# 1. 菜单项
old_menu = "    ['chat', '聊天设置'],\n    ['desktop', '桌面端'],"
assert s.count(old_menu) == 1, f"菜单锚点 {s.count(old_menu)}"
s = s.replace(old_menu, "    ['chat', '聊天设置'],\n    ['selfhost', '自持运维'],\n    ['desktop', '桌面端'],")

# 2. sections 分派
old_sec = "    chat: () => renderChatSection(c),\n    desktop: () => renderDesktopSection(c),"
assert s.count(old_sec) == 1, f"分派锚点 {s.count(old_sec)}"
s = s.replace(old_sec, "    chat: () => renderChatSection(c),\n    selfhost: () => renderSelfhostSection(c),\n    desktop: () => renderDesktopSection(c),")

# 3. renderSettings 末尾触发加载
old_render = """  box.innerHTML = `
    ${renderSettingsSection(c)}`;
  bindSettingsEvents(c);
}"""
assert s.count(old_render) == 1, f"renderSettings 锚点 {s.count(old_render)}"
new_render = """  box.innerHTML = `
    ${renderSettingsSection(c)}`;
  bindSettingsEvents(c);
  if ((state.settingsSection || 'api') === 'selfhost') hookSelfhostSection();
}"""
s = s.replace(old_render, new_render)

# 4. 新函数插到 renderOnebotSection 之前
anchor = "function renderOnebotSection(c) {"
assert s.count(anchor) == 1
block = r"""function renderSelfhostSection(c) {
  return `
    <h3 id="settings-selfhost">自持运维</h3>
    <div class="hint" style="margin-bottom:10px">上游 NapCat 已于 2026-11-12 停止维护（README 只剩「Ending · 到这里告一段落」）。这里盯的是<b>本地实际文件是否还等于基线</b>：变了就说明 QQ 或 NapCat 被换过，注入点可能失效。</div>
    <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px">
      <button class="btn btn-small" id="selfhost-run-btn">立即检查</button>
      <span id="selfhost-result" class="muted"></span>
    </div>
    <div id="selfhost-box" class="muted">加载中…</div>
    <div class="hint" style="margin-top:14px">离线件固定在私有库 <code>big_fat_whale</code> 的 release <code>vendor-2026-11-12</code>（NapCat 运行时 34MB + 依赖 1.1MB + manifest），服务器与本地各留一份。每日 05:00 自动跑一次检查，发现漂移会私聊通知。</div>`;
}

function hookSelfhostSection() {
  const btn = $('#selfhost-run-btn');
  if (btn) {
    btn.addEventListener('click', async () => {
      const out = $('#selfhost-result');
      btn.disabled = true;
      if (out) out.textContent = '检查中…';
      try {
        const r = await fetch('/api/selfhost/run', { method: 'POST' }).then((x) => x.json());
        if (out) out.textContent = r && r.ok ? '完成' : '失败';
      } catch (e) {
        if (out) out.textContent = '失败：' + String((e && e.message) || e);
      } finally {
        btn.disabled = false;
        loadSelfhost();
      }
    });
  }
  loadSelfhost();
}

async function loadSelfhost() {
  const box = $('#selfhost-box');
  if (!box) return;
  try {
    const d = await fetch('/api/selfhost').then((r) => r.json());
    if (d.error) {
      box.innerHTML = `<div class="hint">${esc(d.error)}</div>`;
      return;
    }
    const row = (ok, label, detail) => `<div class="rs-row"><span class="dot ${ok ? 'dot-on' : 'dot-off'}"></span><span>${esc(label)}</span><span class="muted" style="margin-left:8px">${esc(detail || '')}</span></div>`;
    const svc = Object.entries(d.services || {}).map(([k, v]) => `${k}:${v}`).join(' · ');
    const bks = (d.backups || []).slice(0, 4).map((b) => `${esc(b.name)}（${(b.size / 1048576).toFixed(1)}MB · ${b.ageDays} 天前）`).join('<br>');
    const drift = (d.drift || []).length ? d.drift.join('、') : '无';
    box.innerHTML = `
      <div class="settings-runstate">
        <div class="rs-title">上游一致性 · 检查于 ${esc(d.checkedAt || '?')}</div>
        ${row(!!(d.qq && d.qq.ok), `QQ ${(d.qq && d.qq.version) || ''}`, d.qq && d.qq.ok ? '与基线一致' : '已变化')}
        ${row(!!(d.napcat && d.napcat.ok), `NapCat ${(d.napcat && d.napcat.version) || ''}`, d.napcat && d.napcat.ok ? '与基线一致' : '已变化')}
        ${row(!(d.drift || []).length, '漂移项', drift)}
        <div class="rs-row muted">服务：${esc(svc)}</div>
        <div class="rs-row muted">磁盘已用：${esc(d.diskUsedPct || '?')}</div>
        <div class="rs-row muted">基线清单：${esc(d.manifest || '?')}</div>
        <div class="rs-row muted">最近备份：<br>${bks || '无'}</div>
      </div>`;
  } catch (e) {
    box.innerHTML = `<div class="hint">读取失败：${esc(String((e && e.message) || e))}</div>`;
  }
}

"""
s = s.replace(anchor, block + anchor)
open(p, 'w', encoding='utf-8').write(s)
print("  UI 补丁完成：菜单 + 分派 + hookSelfhostSection/loadSelfhost")
