// 上课前提醒：每 60 秒扫一次课表，临近上课时给主人发一条提醒。
//
// 为什么不用「定时任务」：scheduler 只支持一次性任务，一学期几百节课会塞爆；
// 这里做成常驻循环 + 去重状态文件，按 schedule.json 的日期/时间实时判断。
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR, getConfig } from './config.js';
import { loadSchedule, localDate } from './schedule-query.js';

const STATE_FILE = path.join(DATA_DIR, 'state', 'class-reminders.json');

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    return { sent: {} };
  }
}

function saveState(state) {
  try {
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 1), 'utf8');
  } catch { /* 状态写失败不影响提醒本身 */ }
}

const keyOf = (dateStr, item) => `${dateStr}|${item.course}|${item.time_start}`;

/** 距离上课还有多少分钟（>0 表示还没开始）。 */
function minutesUntil(dateStr, timeStr, now = new Date()) {
  const m = /^(\d{2}):(\d{2})$/.exec(String(timeStr || ''));
  if (!m) return null;
  const start = new Date(`${dateStr}T${m[1]}:${m[2]}:00`);
  if (Number.isNaN(start.getTime())) return null;
  return Math.round((start.getTime() - now.getTime()) / 60000);
}

/**
 * 启动提醒循环。
 * @param {object} opts
 * @param {object} opts.onebot  OneBot 客户端（sendText）
 * @param {number|string} opts.masterQQ 主人 QQ
 * @param {number} [opts.advanceMin] 提前多少分钟提醒（默认 30）
 * @param {number} [opts.intervalMs] 轮询间隔（默认 60 秒）
 */
export function startClassReminder({ onebot, masterQQ, advanceMin, intervalMs = 60000, log = console.log } = {}) {
  const cfg = getConfig().classReminder || {};
  if (cfg.enabled === false) return { stop: () => {} };
  const advance = Number(advanceMin ?? cfg.advanceMin ?? 30);
  const windowMin = 1;                      // 只在「提前量 ±1 分钟」的窗口内发，避免重复
  let timer = null;

  async function tick() {
    try {
      if (!masterQQ) return;
      const data = loadSchedule();
      if (!data) return;
      const today = localDate();
      const items = Array.isArray(data.by_date?.[today]) ? data.by_date[today] : [];
      if (!items.length) return;
      const state = loadState();
      const now = new Date();
      for (const item of items) {
        const left = minutesUntil(today, item.time_start, now);
        if (left === null) continue;
        if (left > advance || left < advance - windowMin) continue;
        const key = keyOf(today, item);
        if (state.sent[key]) continue;
        const room = item.room ? ` @ ${item.room}` : '';
        const teacher = item.teacher ? `（${item.teacher}）` : '';
        const span = item.time_span ? ` ${item.time_span}` : '';
        const text = `主人，${left} 分钟后有课啦：${item.course}${span}${room}${teacher}`;
        try {
          await onebot.sendText('private', String(masterQQ), text);
          state.sent[key] = Date.now();
          saveState(state);
          log(`[上课提醒] 已发送：${text}`);
        } catch (e) {
          log('[上课提醒] 发送失败:', e?.message ?? e);
        }
      }
      // 清理 7 天前的状态，避免文件无限增长
      const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
      let dirty = false;
      for (const [k, ts] of Object.entries(state.sent || {})) {
        if (Number(ts) < cutoff) { delete state.sent[k]; dirty = true; }
      }
      if (dirty) saveState(state);
    } catch (e) {
      log('[上课提醒] 循环异常:', e?.message ?? e);
    }
  }

  timer = setInterval(tick, intervalMs);
  tick();
  log(`[上课提醒] 已启动：提前 ${advance} 分钟，每 ${Math.round(intervalMs / 1000)} 秒检查一次`);
  return { stop: () => { if (timer) clearInterval(timer); timer = null; } };
}
