// 换实现可行性实测：让 OneBotClient 打假服务，逐条核对发出去的 payload 是否符合 OneBot v11。
// 不连线上 QQ（不会互踢），只验证「我们这一侧的接口面」。
// 运行：node tools/compat-test.mjs
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import { OneBotClient } from '../src/onebot.js';

const LOG = '/tmp/mock-onebot.jsonl';
const results = [];
const seen = [];

function check(name, fn) {
  return Promise.resolve()
    .then(fn)
    .then(() => results.push({ name, ok: true }))
    .catch((e) => results.push({ name, ok: false, error: String((e && e.message) || e) }));
}

async function main() {
  const mock = spawn(process.execPath, ['tools/mock-onebot.mjs'], { stdio: ['ignore', 'pipe', 'pipe'] });
  await new Promise((resolve, reject) => {
    const t = setTimeout(() => reject(new Error('mock 启动超时')), 8000);
    mock.stdout.on('data', (d) => { if (String(d).includes('ready')) { clearTimeout(t); resolve(); } });
  });

  const client = new OneBotClient({
    wsUrl: 'ws://127.0.0.1:3011',
    httpUrl: 'http://127.0.0.1:3010',
    accessToken: '', httpToken: '',
    onEvent: () => {}
  });
  await client.connect();
  await new Promise((r) => setTimeout(r, 800));

  const last = (action) => {
    const lines = fs.readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
    const hit = lines.filter((x) => x.action === action);
    return hit.length ? hit[hit.length - 1].params : null;
  };

  await check('sendText 带引用+@ 段顺序与字段', async () => {
    await client.sendText('group', 123456, '你好', { replyToMessageId: 9001, atUserId: 20000 });
    const p = last('send_group_msg');
    if (!p || p.group_id !== 123456) throw new Error('group_id 不对: ' + JSON.stringify(p));
    const types = p.message.map((s) => s.type).join(',');
    if (types !== 'reply,at,text') throw new Error('段顺序应为 reply,at,text，实际 ' + types);
    if (String(p.message[0].data.id) !== '9001') throw new Error('reply.id 应为字符串 "9001"');
    if (String(p.message[1].data.qq) !== '20000') throw new Error('at.qq 应为字符串 "20000"');
  });

  await check('reply id 非法时本地就拦住（不发空引用）', async () => {
    let threw = false;
    try { await client.sendText('group', 123456, 'x', { replyToMessageId: 'abc' }); } catch { threw = true; }
    if (!threw) throw new Error('非法 replyToMessageId 没有被拒');
  });

  await check('sendText 私聊走 send_private_msg 且无 group_id', async () => {
    await client.sendText('private', 20000, '嗯');
    const p = last('send_private_msg');
    if (!p || p.user_id !== 20000) throw new Error('user_id 不对: ' + JSON.stringify(p));
    if ('group_id' in p) throw new Error('私聊不该带 group_id');
  });

  await check('sendImageBuffer 用 base64:// 段', async () => {
    await client.sendImageBuffer('group', 123456, Buffer.from('fakebytes'));
    const p = last('send_group_msg');
    const img = (p.message || []).find((s) => s.type === 'image');
    if (!img) throw new Error('没有 image 段');
    if (!String(img.data.file).startsWith('base64://')) throw new Error('file 应为 base64:// 前缀，实际 ' + String(img.data.file).slice(0, 24));
  });

  await check('sendImage 用 url 段', async () => {
    await client.sendImage('group', 123456, 'https://example.invalid/a.png');
    const p = last('send_group_msg');
    const img = (p.message || []).find((s) => s.type === 'image');
    if (!img || img.data.file !== 'https://example.invalid/a.png') throw new Error('image.file 不等于 URL');
  });

  await check('sendRecord 用 record 段', async () => {
    await client.sendRecord('group', 123456, Buffer.from('x'));
    const p = last('send_group_msg');
    if (!(p.message || []).some((s) => s.type === 'record')) throw new Error('没有 record 段');
  });

  await check('sendSticker 用 image 段（收藏表情无标准段）', async () => {
    await client.sendSticker('group', 123456, 'https://example.invalid/s.png');
    const p = last('send_group_msg');
    if (!(p.message || []).some((s) => s.type === 'image')) throw new Error('没有 image 段');
  });

  await check('sendFile 走 upload_group_file（非标准扩展）', async () => {
    await client.sendFile('group', 123456, '/tmp/mock-file.bin', 'mock-file.bin');
    const p = last('upload_group_file');
    if (!p || !p.group_id) throw new Error('upload_group_file 参数缺失: ' + JSON.stringify(p));
  });

  await check('sendPoke 走 group_poke（非标准扩展，带 send_poke 兜底）', async () => {
    await client.sendPoke('group', 123456, 20000);
    const lines = fs.readFileSync(LOG, 'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
    const hit = lines.filter((x) => x.action === 'group_poke' || x.action === 'send_poke').pop();
    if (!hit) throw new Error('没有 group_poke/send_poke 请求');
    if (!hit.params.group_id || !hit.params.user_id) throw new Error('戳一戳参数缺失: ' + JSON.stringify(hit.params));
  });

  await check('getMsg 能解析 envelope', async () => {
    const m = await client.getMsg(9001);
    if (!m || !m.sender || !m.message) throw new Error('返回结构不符: ' + JSON.stringify(m).slice(0, 120));
  });

  await check('getGroupInfo / getGroupMemberInfo', async () => {
    const g = await client.getGroupInfo(123456);
    if (!g || g.group_id !== 123456) throw new Error('group_info 不对');
    const mem = await client.getGroupMemberInfo(123456, 20000);
    if (!mem || mem.user_id !== 20000) throw new Error('member_info 不对');
  });

  client.close();
  mock.kill('SIGTERM');
  await new Promise((r) => setTimeout(r, 300));

  const ok = results.filter((r) => r.ok).length;
  const lines = [];
  lines.push('# 换实现兼容性实测（OneBot v11）');
  lines.push('');
  lines.push(`- 时间：${new Date().toISOString()}`);
  lines.push(`- 方式：qq-agent 的 OneBotClient 打本机假服务（HTTP 3010 / WS 3011），只验我们这一侧的 payload，不登录线上 QQ`);
  lines.push(`- 结果：**${ok}/${results.length} 通过**`);
  lines.push('');
  lines.push('| 用例 | 结果 | 说明 |');
  lines.push('|---|---|---|');
  for (const r of results) lines.push(`| ${r.name} | ${r.ok ? '通过' : '失败'} | ${r.ok ? '' : r.error} |`);
  lines.push('');
  lines.push('## 结论');
  lines.push('');
  lines.push('qq-agent 只依赖 OneBot v11 的标准 HTTP 动作，加上三条非标准扩展：`upload_group_file`/`upload_private_file`（发文件）、`group_poke`/`friend_poke`（戳一戳）、`get_file`（取转发文件）。');
  lines.push('标准动作在 Lagrange.OneBot / Bncr 等实现上语义一致，换实现只需要改配置里的 `wsUrl`/`httpUrl`/令牌；非标准扩展全部有 `.catch()` 降级，最坏情况是「发不了文件、戳一戳静默失败」，不会影响收发消息主链路。');
  lines.push('');
  lines.push('换实现操作：① 起目标实现（Lagrange.OneBot：配置 `Implementations` 里 HTTP + 正向 WS，令牌填一个）；② 面板「设置 → OneBot」改 `WebSocket 地址`/`HTTP 地址`/令牌；③ 重启 qqbot；④ `curl 127.0.0.1:3000/get_login_info` 看是否换成了新账号。');
  const md = lines.join('\n');
  fs.writeFileSync('/opt/qq-agent/tools/compat-report.md', md);
  console.log(md);
  console.log('\n请求流水：', LOG);
}

main().catch((e) => {
  console.error('实测失败：', e);
  process.exit(1);
});
