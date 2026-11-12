import io, sys
p = '/opt/qq-agent/src/app.js'
s = open(p, encoding='utf-8').read()
anchor = "      // ── SnowLuma 进程管理 ──"
assert s.count(anchor) == 1, f"锚点数量异常: {s.count(anchor)}"
block = """      // ── 自持运维：上游漂移 / 服务 / 备份 / 一键检查 ──
      if (pathname === '/api/selfhost' && method === 'GET') {
        const p = '/home/admin/backups/selfhost-status.json';
        try {
          if (!fs.existsSync(p)) return json(res, 200, { error: '还没有检查记录，点「立即检查」或等每日 05:00' });
          return json(res, 200, JSON.parse(fs.readFileSync(p, 'utf8')));
        } catch (err) {
          return json(res, 500, { error: String(err.message || err) });
        }
      }

      if (pathname === '/api/selfhost/run' && method === 'POST') {
        const out = await new Promise((resolve) => {
          const child = spawn('/bin/bash', ['/home/admin/scripts/selfhost-check.sh'], { timeout: 120000 });
          let buf = '';
          child.stdout.on('data', (d) => { buf += d.toString(); });
          child.stderr.on('data', (d) => { buf += d.toString(); });
          child.on('close', (code) => resolve(`exit=${code}\\n${buf}`));
          child.on('error', (e) => resolve(`启动失败：${e.message}`));
        });
        return json(res, 200, { ok: true, output: out.slice(-4000) });
      }

"""
open(p + '.bak-selfhost', 'w', encoding='utf-8').write(s)
s = s.replace(anchor, block + anchor)
open(p, 'w', encoding='utf-8').write(s)
print("  已插入 /api/selfhost 与 /api/selfhost/run")
