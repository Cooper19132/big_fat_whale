// ics 课程表导入：把 QQ 收到的 .ics 解析成 schedule_query 能读的 schedule.json
//   schema_version=2，结构 { schema_version, date_range, by_date: { 'YYYY-MM-DD': [item] } }
//   item 字段对齐 schedule-query.js 的渲染器：course / teacher / room / time_span / time_start / time_end
import fs from 'node:fs';
import path from 'node:path';
import { DATA_DIR } from './config.js';

export const SCHEDULE_FILE = path.join(DATA_DIR, 'schedule', 'schedule.json');

/** 解 ics 的行折叠（RFC5545：续行以一个空格/制表符开头）。 */
function unfold(text) {
  return String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n[ \t]/g, '');
}

/** 解 ics 的转义：\\n \\, \\; \\\\ */
function unescapeText(s) {
  return String(s || '')
    .replace(/\\n/gi, '\n')
    .replace(/\\,/g, ',')
    .replace(/\\;/g, ';')
    .replace(/\\\\/g, '\\');
}

/** 从 DTSTART/DTEND 值里取 { date: 'YYYY-MM-DD', time: 'HH:MM' }。 */
function parseIcsDateTime(value) {
  const m = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?/.exec(String(value || '').trim());
  if (!m) return null;
  return { date: `${m[1]}-${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}` };
}

/** 解析 ics 文本 → { events, byDate, dateRange } */
export function parseIcs(text) {
  const lines = unfold(text).split('\n');
  const events = [];
  let cur = null;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.toUpperCase() === 'BEGIN:VEVENT') { cur = {}; continue; }
    if (line.toUpperCase() === 'END:VEVENT') { if (cur) events.push(cur); cur = null; continue; }
    if (!cur) continue;
    const colon = line.indexOf(':');
    if (colon < 0) continue;
    const head = line.slice(0, colon);
    const value = line.slice(colon + 1);
    const key = head.split(';')[0].toUpperCase();
    cur[key] = value;
  }

  const byDate = {};
  const allDates = [];
  const parsed = [];
  for (const ev of events) {
    const start = parseIcsDateTime(ev.DTSTART);
    if (!start) continue;
    const end = parseIcsDateTime(ev.DTEND);
    const desc = unescapeText(ev.DESCRIPTION || '');
    const teacher = (/教师[:：]\s*([^\n]+)/.exec(desc) || [])[1] || '';
    const item = {
      course: unescapeText(ev.SUMMARY || '（未命名课程）'),
      teacher: teacher.trim(),
      room: unescapeText(ev.LOCATION || '').trim(),
      time_start: start.time,
      time_end: end ? end.time : '',
      time_span: end ? `${start.time}-${end.time}` : start.time,
      uid: String(ev.UID || ''),
    };
    parsed.push({ date: start.date, item });
    allDates.push(start.date);
  }

  parsed.sort((a, b) => (a.date + a.item.time_start).localeCompare(b.date + b.item.time_start));
  for (const { date, item } of parsed) {
    (byDate[date] || (byDate[date] = [])).push(item);
  }
  allDates.sort();
  return {
    events: parsed.length,
    byDate,
    dateRange: allDates.length ? [allDates[0], allDates[allDates.length - 1]] : null,
  };
}

/** 写入 schedule.json（原子写），返回摘要。 */
export function saveSchedule(parsed, { file = SCHEDULE_FILE } = {}) {
  if (!parsed || !parsed.byDate || !Object.keys(parsed.byDate).length) {
    throw new Error('ics 里没有解析到任何课程（可能不是课程表，或格式不受支持）');
  }
  const data = {
    schema_version: 2,
    source: 'ics-import',
    imported_at: new Date().toISOString(),
    date_range: parsed.dateRange,
    by_date: parsed.byDate,
  };
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 1), 'utf8');
  fs.renameSync(tmp, file);
  const days = Object.keys(parsed.byDate).length;
  return { file, days, events: parsed.events, range: parsed.dateRange };
}

/** 人类可读摘要（给机器人回话用，不塞整份课表）。 */
export function summarize(parsed, limit = 6) {
  const dates = Object.keys(parsed.byDate).sort();
  const lines = [`共 ${parsed.events} 节课，覆盖 ${dates.length} 天（${parsed.dateRange?.[0]} ~ ${parsed.dateRange?.[1]}）`];
  const courses = new Map();
  for (const d of dates) {
    for (const it of parsed.byDate[d]) {
      const key = it.course;
      const rec = courses.get(key) || { count: 0, teacher: it.teacher, rooms: new Set(), weeks: new Set() };
      rec.count += 1;
      if (it.room) rec.rooms.add(it.room);
      courses.set(key, rec);
    }
  }
  lines.push(`课程 ${courses.size} 门：`);
  let i = 0;
  for (const [name, rec] of courses) {
    if (i++ >= limit) { lines.push(`…还有 ${courses.size - limit} 门`); break; }
    const room = [...rec.rooms].join('/');
    lines.push(`· ${name}（${rec.count} 次${rec.teacher ? '，' + rec.teacher : ''}${room ? '，' + room : ''}）`);
  }
  return lines.join('\n');
}
