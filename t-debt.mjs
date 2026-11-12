import { noteStyleComplaint, styleDebtSummary } from '/opt/qq-agent/src/style-debt.js';
const trig = [
  { mid: 111, senderId: 246695065, senderName: '主人', text: '怎么又把鱼八股' },
  { mid: 112, senderId: 246695065, senderName: '主人', text: '怎么又把鱼八股' },   // 重复，不该记两次
  { mid: 113, senderId: 305641312, senderName: '扶她奶昔', text: '注意八股用词' },
  { mid: 114, senderId: 305641312, senderName: '扶她奶昔', text: '今天吃啥' }        // 正常聊天，不该记
];
console.log('本轮新记:', noteStyleComplaint(trig, 501962981));
console.log('注入文案:', styleDebtSummary());
