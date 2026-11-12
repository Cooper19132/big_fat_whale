// 假 OneBot v11 服务：HTTP 3010 + WebSocket 3011
// 用途：不碰线上 QQ 的前提下，验证 qq-agent 发出去的每个请求都符合 OneBot v11 标准，
//       并据此判断「换实现（Lagrange.OneBot / Bncr 等）」需要改多少。
// 运行：node tools/mock-onebot.mjs   （打印 ready 后可用）
import http from 'node:http';
import fs from 'node:fs';
import { WebSocketServer } from 'ws';

const HTTP_PORT = Number(process.env.MOCK_HTTP_PORT || 3010);
const WS_PORT = Number(process.env.MOCK_WS_PORT || 3011);
const LOG = process.env.MOCK_LOG || '/tmp/mock-onebot.jsonl';

fs.writeFileSync(LOG, '');

const CANNED = {
  get_login_info: { user_id: 10000, nickname: 'mock-bot' },
  get_status: { online: true, good: true, stat: {} },
  send_private_msg: { message_id: 9001 },
  send_group_msg: { message_id: 9002 },
  send_msg: { message_id: 9003 },
  get_msg: {
    message_id: 9001, real_id: 9001, time: Math.floor(Date.now() / 1000),
    message_type: 'group', sender: { user_id: 20000, nickname: 'mock-user', card: 'mock-card' },
    message: [{ type: 'text', data: { text: 'mock text' } }]
  },
  get_group_info: { group_id: 123456, group_name: 'mock-group', member_count: 3 },
  get_group_member_info: { group_id: 123456, user_id: 20000, nickname: 'mock-user', card: 'mock-card', role: 'member' },
  get_friend_list: [{ user_id: 20000, nickname: 'mock-friend' }],
  get_group_list: [{ group_id: 123456, group_name: 'mock-group' }],
  upload_group_file: null,
  upload_private_file: null,
  get_file: { file: '/dev/null', file_name: 'mock.bin', file_size: 1, base64: '' },
  friend_poke: null,
  group_poke: null,
  send_poke: null
};

const records = [];
function reply(action) {
  return { status: 'ok', retcode: 0, data: action in CANNED ? CANNED[action] : null, echo: action };
}

const server = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', () => {
    const action = decodeURIComponent((req.url || '/').split('?')[0].replace(/^\//, ''));
    let params = {};
    try { params = body ? JSON.parse(body) : {}; } catch { /* 保留空 */ }
    if (action === '__emit') {
      fs.writeFileSync('/tmp/mock-emit.json', body);
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end('{"ok":true}');
      return;
    }
    records.push({ action, params, at: Date.now() });
    fs.appendFileSync(LOG, JSON.stringify({ action, params }) + '\n');
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify(reply(action)));
  });
});
server.listen(HTTP_PORT, '127.0.0.1');

const wss = new WebSocketServer({ port: WS_PORT, host: '127.0.0.1' });
wss.on('connection', (ws) => {
  ws.send(JSON.stringify({ post_type: 'meta_event', meta_event_type: 'lifecycle', sub_type: 'connect' }));
  ws.on('message', (raw) => {
    let doc = null;
    try { doc = JSON.parse(String(raw)); } catch { return; }
    if (doc && doc.action) {
      records.push({ action: doc.action, params: doc.params || {}, at: Date.now(), via: 'ws' });
      fs.appendFileSync(LOG, JSON.stringify({ action: doc.action, params: doc.params || {}, via: 'ws' }) + '\n');
      ws.send(JSON.stringify({ ...reply(doc.action), echo: doc.echo }));
    }
  });
});

server.on('listening', () => {
  console.log(`ready http=${HTTP_PORT} ws=${WS_PORT} log=${LOG}`);
});
process.on('SIGTERM', () => { try { server.close(); wss.close(); } catch { /* ignore */ } process.exit(0); });
