/**
 * 把 HTML 变成人能读的正文。
 *
 * 为什么需要：web_fetch 之前直接把原始 HTML 丢给模型（<!DOCTYPE html>...），
 * 模型要在几千行标签里找正文，遇到 SPA（小黑盒/知乎/微博）就只能看到空壳，
 * 表现成「看不了网页」。
 *
 * 策略：去脚本/样式 → 块级标签转换行 → 去标签 → 解实体 → 压缩空行。
 * 不做 DOM 解析（无依赖），但足够把正文抠出来。
 */

const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  ldquo: '“', rdquo: '”', lsquo: '‘', rsquo: '’', hellip: '…', mdash: '—', ndash: '–',
  middot: '·', times: '×', divide: '÷', copy: '©', reg: '®', trade: '™', deg: '°'
};

function decodeEntities(text) {
  return String(text)
    .replace(/&#x([0-9a-f]+);/gi, (_, h) => safeChar(parseInt(h, 16)))
    .replace(/&#(\d+);/g, (_, d) => safeChar(parseInt(d, 10)))
    .replace(/&([a-z]+);/gi, (m, name) => {
      const v = ENTITIES[name.toLowerCase()];
      return v === undefined ? m : v;
    });
}

function safeChar(code) {
  try {
    return Number.isFinite(code) && code > 0 && code < 0x110000 ? String.fromCodePoint(code) : '';
  } catch {
    return '';
  }
}

/** 是不是 JSON / XML / 纯文本（就不要当 HTML 处理） */
export function looksStructured(body, contentType = '') {
  const ct = String(contentType).toLowerCase();
  if (ct.includes('json') || ct.includes('xml') || ct.includes('plain') || ct.includes('csv')) return true;
  const head = String(body).trimStart().slice(0, 1);
  return head === '{' || head === '[';
}

/**
 * @param {string} html 原始 HTML
 * @returns {{ text: string, thin: boolean }} thin=正文太少，可能是 JS 渲染页
 */
export function htmlToText(html) {
  let s = String(html || '');

  // 整块丢掉
  s = s.replace(/<!--[\s\S]*?-->/g, ' ');
  s = s.replace(/<script[\s\S]*?<\/script>/gi, ' ');
  s = s.replace(/<style[\s\S]*?<\/style>/gi, ' ');
  s = s.replace(/<noscript[\s\S]*?<\/noscript>/gi, ' ');
  s = s.replace(/<svg[\s\S]*?<\/svg>/gi, ' ');
  s = s.replace(/<iframe[\s\S]*?<\/iframe>/gi, ' ');
  s = s.replace(/<template[\s\S]*?<\/template>/gi, ' ');
  // 导航/页头/页脚/侧栏整块丢掉——它们最占字符又没信息（正文提取的大头噪音）
  s = s.replace(/<nav[\s\S]*?<\/nav>/gi, ' ');
  s = s.replace(/<header[\s\S]*?<\/header>/gi, ' ');
  s = s.replace(/<footer[\s\S]*?<\/footer>/gi, ' ');
  s = s.replace(/<aside[\s\S]*?<\/aside>/gi, ' ');
  s = s.replace(/<form[\s\S]*?<\/form>/gi, ' ');

  // 只保留 body 里的内容（有的话）
  const bodyMatch = /<body[^>]*>([\s\S]*)<\/body>/i.exec(s);
  if (bodyMatch) s = bodyMatch[1];

  // 块级结构 → 换行
  s = s.replace(/<br\s*\/?>/gi, '\n');
  s = s.replace(/<\/(p|div|section|article|header|footer|li|tr|h[1-6]|blockquote|pre|td|dd|dt)>/gi, '\n');
  s = s.replace(/<(li)[^>]*>/gi, '\n· ');
  s = s.replace(/<h([1-6])[^>]*>/gi, '\n\n');

  // 去掉剩下的标签
  s = s.replace(/<[^>]+>/g, ' ');

  s = decodeEntities(s);

  // 行内空白压缩 + 去空行
  s = s.split('\n').map((line) => line.replace(/[ \t\u00a0]+/g, ' ').trim()).filter(Boolean).join('\n');
  s = s.replace(/\n{3,}/g, '\n\n');

  return { text: s.trim(), thin: s.trim().length < 200 };
}

/** 从 HTML 里抠 <title> 和 meta description，正文太薄时至少给点线索 */
export function extractMeta(html) {
  const s = String(html || '');
  const title = (/<title[^>]*>([\s\S]*?)<\/title>/i.exec(s) || [])[1] || '';
  const desc =
    (/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i.exec(s) || [])[1] ||
    (/<meta[^>]+property=["']og:description["'][^>]+content=["']([^"']*)["']/i.exec(s) || [])[1] ||
    '';
  return { title: decodeEntities(title).trim(), description: decodeEntities(desc).trim() };
}
