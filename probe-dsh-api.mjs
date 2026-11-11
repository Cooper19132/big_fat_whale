// 探测 DSH 0.2.x 实际存在的 RPC 方法名
import { dshCookie } from '/opt/qq-agent/src/dsh-task.js';

const BASE = process.env.DSH_BASE_URL || 'http://127.0.0.1:4598';
const cookie = dshCookie(true);

const METHODS = [
  'workspace.create', 'workspace/list', 'workspace.list',
  'session.create', 'session/create', 'sessions.create',
  'session.selectModel', 'session.list',
  'status', 'system.status', 'app.status',
  'agent.preset.list', 'model.list',
];

for (const method of METHODS) {
  const url = `${BASE}/api/${method}`;
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json', cookie },
      body: JSON.stringify({ type: 'client-request', rpcId: 'probe', method, payload: {} }),
      signal: AbortSignal.timeout(10000),
    });
    const text = (await res.text()).slice(0, 160).replace(/\s+/g, ' ');
    console.log(`${res.status}  ${method}  ${text}`);
  } catch (e) {
    console.log(`ERR ${method}  ${e.message}`);
  }
}
