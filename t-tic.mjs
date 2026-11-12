import { recentTics } from '/opt/qq-agent/src/prompt.js';
const mk = (i, t) => ({ id: `c${i}`, mid: 1 + i, self: true, text: t, ts: Date.now() - (60 - i) * 60000 });
const many = ['老黄这背心一穿 比发新卡还吓人', '他那张嘴比模型迭代还快', '这比我吃白饭还便宜', '这鸭子还挺横'];
const hi = Array.from({ length: 60 }, (_, i) => mk(i, i < 6 ? many[i % many.length] : `第${i}条普通的话`));
console.log('高频率（60 条里 6 条带结构）:', recentTics({ recent: () => hi }, 'group:1'));
const lo = Array.from({ length: 60 }, (_, i) => mk(i, i === 3 ? many[0] : `第${i}条普通的话`));
console.log('真实频率（60 条里 1 条）:', recentTics({ recent: () => lo }, 'group:1'));
console.log('样本太小（10 条）:', recentTics({ recent: () => hi.slice(0, 10) }, 'group:1'));
