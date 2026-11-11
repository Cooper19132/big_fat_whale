// 铸一张长效 Cookie 并打印（供跨机验证用）
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';

const DSH_BASE = process.env.DSH_BASE || 'http://127.0.0.1:4598';
const text = fs.readFileSync(path.join(os.homedir(), '.dsh', '.credentials.yaml'), 'utf8');
const m = /client-connection\/browser-session:[\s\S]*?secret:\s*(\S+)/.exec(text);
const secret = Buffer.from(m[1].trim().replaceAll('-', '+').replaceAll('_', '/'), 'base64');
const b64url = (buf) => Buffer.from(buf).toString('base64').replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const authority = new URL(DSH_BASE).host;
const issuedAt = Date.now();
const expiresAt = issuedAt + 20 * 24 * 60 * 60 * 1000;   // 20 天
const payload = b64url(Buffer.from(JSON.stringify({ version: 1, authority, issuedAt, expiresAt }), 'utf8'));
const sig = b64url(crypto.createHmac('sha256', secret).update(payload).digest());
const name = 'dsh-auth-' + b64url(crypto.createHash('sha256').update(authority).digest());
console.log(`${name}=v1.${payload}.${sig}`);
