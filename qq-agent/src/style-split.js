/**
 * 「空格两段式」物理终结器。
 *
 * 背景：她 54.3% 的发言是「前半句 空格 后半句」的一整条，而真人群友中位 6 字、
 * 58.9% 的消息 ≤8 字、连发 2~4 条短句。提示词里写「别用空格分句」效果有限
 * （正例本身都在用空格），所以改在发送口按物理规则拆条：
 *   「取反加一那步 我第一次看也觉得是玄学 结果真能算对」
 *   → 「取反加一那步」「我第一次看也觉得是玄学」「结果真能算对」
 * 拆出来的片段长度中位 7 字，正好是群友的节奏。
 *
 * 只处理中文与中文之间的空格；英文单词、数字、代码（如 `DeepSeek V3`）不受影响。
 */

const CJK_SPACE = /(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])/;
const MAX_BUBBLES = 4;

export function splitOne(text) {
  const t = String(text ?? '').trim();
  if (!t || !CJK_SPACE.test(t)) return [t].filter(Boolean);
  const parts = t.split(CJK_SPACE).map((s) => s.trim()).filter(Boolean);
  if (parts.length <= 1) return parts;
  if (parts.length > MAX_BUBBLES) {
    const head = parts.slice(0, MAX_BUBBLES - 1);
    const tail = parts.slice(MAX_BUBBLES - 1).join('，');
    return [...head, tail];
  }
  return parts;
}

export function splitOnCjkSpace(messages) {
  const out = [];
  for (const m of Array.isArray(messages) ? messages : [messages]) {
    for (const piece of splitOne(m)) out.push(piece);
  }
  return out;
}

export function countSpacePairs(text) {
  const t = String(text ?? '');
  return (t.match(new RegExp(CJK_SPACE.source, 'g')) || []).length;
}
