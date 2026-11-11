// 本机对照：用 DSH 自带 node + 同一份密钥铸造 Cookie，打本地 DSH
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';

const DSH_BASE = process.env.DSH_BASE || 'http://127.0.0.1:4598';
const SECRET_FILE = process.argv[2] || path.join(os.homedir(), '.dsh', '.credentials.yaml');

let raw;
const text = fs.readFileSync(SECRET_FILE, 'utf8');
const m = /client-connection\/browser-session:[\s\S]*?secret:\s*(\S+)/.exec(text);
if (!m) { console.error('找不到 secret'); process.exit(1); }
raw = m[1].trim();
console.log('secret 字符串长度:', raw.length);

const secret = Buffer.from(raw.replaceAll('-', '+').replaceAll('_', '/'), 'base64');
console.log('secret 字节数:', secret.byteLength);

const b64url = (buf) => Buffer.from(buf).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const authority = new URL(DSH_BASE).host;
const issuedAt = Date.now();
const expiresAt = issuedAt + 60 * 60 * 1000;
const payload = b64url(Buffer.from(JSON.stringify({ version: 1, authority, issuedAt, expiresAt }), 'utf8'));
const sig = b64url(crypto.createHmac('sha256', secret).update(payload).digest());
const name = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(authority).digest());
const cookie = `${name}=v1.${payload}.${sig}`;
console.log('authority:', authority, '| cookie 长度:', cookie.length);

const r = await fetch(DSH_BASE + '/', { headers: { cookie } });
console.log('本机 fetch →', r.status);
const r2 = await fetch(DSH_BASE + '/');
console.log('不带 cookie →', r2.status);
