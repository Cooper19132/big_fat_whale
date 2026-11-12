import { buildPastState, buildTriggerBlock } from '/opt/qq-agent/src/prompt.js';
const mk = (i, img) => ({ id: `c-${i}`, mid: 900000 + i, chatKey: 'group:1', senderId: 246695065, senderName: '主人',
  text: img ? '[图片]' : `第${i}条纯文本`, ts: Date.now() - (40 - i) * 60000,
  media: img ? [{ kind: 'image', url: `https://gchat.qpic.cn/gchatpic_new/0/0-0-ABCDEF${i}/0?term=2` }] : [] });
const msgs = Array.from({ length: 40 }, (_, i) => mk(i, i === 33 || i === 37));
const store = { recent: () => msgs };
const past = buildPastState(store, 'group:1');
console.log('=== 已读尾部 ===');
console.log(past.text.split('\n').slice(-5).join('\n'));
const trig = buildTriggerBlock([mk(38, true), mk(39, false)], { selfNickname: '大肥鱼', persona: { botName: '大肥鱼' } });
console.log('=== 本次唤醒 ===');
console.log(trig);
