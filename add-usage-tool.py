#!/usr/bin/env python3
"""给小鲸鱼加「查余额/查消耗」能力：check_usage。

数据来源（都在服务器上）：
  · /opt/qq-agent/data/billing.json         今日真实花费（余额差值，usage-watch.py 每 10 分钟采样）
  · /opt/qq-agent/data/billing-history.jsonl 历史采样流水（按天聚合）
  · https://api.deepseek.com/user/balance   实时余额（顺手刷新一次，保证不是陈旧数据）

主人问「花了多少钱 / 余额还有多少 / 今天用了多少」时调用。
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

P = r'D:\dshworks\qqbot\qq-agent\src\tools.js'
s = open(P, encoding='utf-8').read()

TOOL = r'''    {
      name: 'check_usage',
      masterOnly: true,
      timeoutMs: 30000,
      description: '【主人专属】查 API 花费与余额：今日真实花费、当前余额、近几天每天花了多少。主人问"花了多少钱/余额还有多少/今天用了多少/还剩多少额度"时用它。数据来自 DeepSeek 余额差值（真实账单），不是估算。',
      parameters: {
        type: 'object',
        properties: {
          days: { type: 'number', description: '要回看几天（默认 7，最多 30）' }
        }
      },
      async execute(ctx, args) {
        const days = Math.max(1, Math.min(30, Number(args.days) || 7));
        const fsMod = await import('node:fs');
        const pathMod = await import('node:path');
        const { DATA_DIR } = await import('./config.js');
        const fs = fsMod.default || fsMod;
        const path = pathMod.default || pathMod;

        const billingPath = path.join(DATA_DIR, 'billing.json');
        const histPath = path.join(DATA_DIR, 'billing-history.jsonl');

        let today = null;
        try { today = JSON.parse(fs.readFileSync(billingPath, 'utf-8')); } catch { /* 没有就跳过 */ }

        // 实时余额（顺手刷新，避免展示几分钟前的数）
        let liveBalance = null;
        try {
          const key = String(getConfig().api?.apiKey || '').trim();
          if (key) {
            const r = await fetch('https://api.deepseek.com/user/balance', {
              headers: { Authorization: `Bearer ${key}`, Accept: 'application/json' },
              signal: AbortSignal.timeout(15000)
            });
            if (r.ok) {
              const d = await r.json();
              const cny = (d.balance_infos || []).find((b) => String(b.currency).toUpperCase() === 'CNY');
              liveBalance = Number((cny || (d.balance_infos || [])[0] || {}).total_balance);
            }
          }
        } catch { /* 网络失败就用 billing.json 里的 */ }

        // 近几天：从流水聚合（每天取最后一条的 spent）
        const byDay = new Map();
        try {
          const lines = fs.readFileSync(histPath, 'utf-8').split('\n');
          for (const line of lines) {
            if (!line.trim()) continue;
            try {
              const rec = JSON.parse(line);
              const day = String(rec.day || '');
              if (!day) continue;
              byDay.set(day, Number(rec.spent) || 0);
            } catch { /* 跳过坏行 */ }
          }
        } catch { /* 没有流水 */ }

        const dayList = [...byDay.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).slice(0, days);
        const spentToday = today && String(today.dayKey) === new Date().toISOString().slice(0, 10)
          ? Number(today.spent) || 0
          : (byDay.get(new Date().toISOString().slice(0, 10)) || 0);
        const balance = liveBalance ?? (today ? Number(today.balance) : null);
        const cap = Number(getConfig().budget?.dailyCostYuan) || 0;

        const lines = [];
        lines.push(`今日真实花费：¥${spentToday.toFixed(2)}` + (cap > 0 ? `（每日上限 ¥${cap}）` : ''));
        if (balance != null && Number.isFinite(balance)) lines.push(`当前余额：¥${balance.toFixed(2)}`);
        if (cap > 0 && balance != null && spentToday > 0) {
          const perDay = spentToday;
          lines.push(`按今天的水平，余额够约 ${Math.max(0, Math.floor(balance / Math.max(0.01, perDay)))} 天`);
        }
        if (dayList.length) {
          lines.push('近几天：' + dayList.map(([d, v]) => `${d.slice(5)} ¥${Number(v).toFixed(2)}`).join(' · '));
        }
        const sampled = today?.sampledAt ? Math.round((Date.now() - Number(today.sampledAt)) / 60000) : null;
        if (sampled != null) lines.push(`（真实花费由余额差值算出，最近一次采样 ${sampled} 分钟前）`);

        return ok({ todaySpent: spentToday, balance, dailyCap: cap, history: Object.fromEntries(dayList), note: lines.join('\n') });
      }
    },
'''

anchor = "    {\n      name: 'finish',"
assert s.count(anchor) == 1, 'finish 锚点不符'
s = s.replace(anchor, TOOL + anchor, 1)
open(P, 'w', encoding='utf-8').write(s)
print('✓ 已加入 check_usage 工具')
