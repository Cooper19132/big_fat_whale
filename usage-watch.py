#!/usr/bin/env python3
"""真实消费监测（服务器侧，cron 每 10 分钟跑一次）。

DeepSeek 只开放 /user/balance（没有用量历史接口），所以用**余额差值**算真实花费：
  今日真实花费 = 当日首次采样余额 - 当前余额 + 当日充值额

产出 data/billing.json：
{
  "dayKey": "2026-10-29",
  "currency": "CNY",
  "firstBalance": 53.48,     # 当日首次采样余额
  "balance": 53.10,          # 最近一次余额
  "topUps": 0,               # 当日充值（余额上涨时自动识别）
  "spent": 0.38,             # 今日真实花费
  "sampledAt": 1793...,      # 最近采样时间戳（毫秒）
  "samples": [ {at, balance} ... ]   # 当日采样（保留最近 200 条）
}

异常处理：
  · 余额上涨（充值）→ 记入 topUps，且把 firstBalance 同步抬高，避免把充值当"负花费"
  · 接口失败 → 保留上次结果，只在 sampledAt 不变的情况下由上层判定"数据陈旧"
"""
import json
import os
import sys
import time
import urllib.request

DATA = '/opt/qq-agent/data'
OUT = os.path.join(DATA, 'billing.json')
HIST = os.path.join(DATA, 'billing-history.jsonl')


def load_cfg():
    with open(os.path.join(DATA, 'config.json'), encoding='utf-8') as f:
        return json.load(f)


def balance_cny(api_key):
    req = urllib.request.Request(
        'https://api.deepseek.com/user/balance',
        headers={'Authorization': f'Bearer {api_key}', 'Accept': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read().decode('utf-8'))
    for b in d.get('balance_infos') or []:
        if str(b.get('currency', '')).upper() == 'CNY':
            return float(b.get('total_balance') or 0)
    infos = d.get('balance_infos') or []
    return float(infos[0].get('total_balance') or 0) if infos else None


def main():
    cfg = load_cfg()
    key = str((cfg.get('api') or {}).get('apiKey') or '').strip()
    if not key:
        print('没有 apiKey，退出')
        return

    today = time.strftime('%Y-%m-%d')
    now_ms = int(time.time() * 1000)

    try:
        bal = balance_cny(key)
    except Exception as e:
        print(f'余额查询失败: {e}')
        return
    if bal is None:
        print('余额返回为空')
        return

    state = {}
    if os.path.exists(OUT):
        try:
            state = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            state = {}

    if state.get('dayKey') != today:
        state = {
            'dayKey': today, 'currency': 'CNY',
            'firstBalance': bal, 'balance': bal,
            'topUps': 0.0, 'spent': 0.0,
            'sampledAt': now_ms, 'samples': []
        }
    else:
        prev = float(state.get('balance') or bal)
        # 余额上涨超过 0.01 → 视为充值
        if bal - prev > 0.01:
            top = round(bal - prev, 2)
            state['topUps'] = round(float(state.get('topUps') or 0) + top, 2)
            state['firstBalance'] = round(float(state.get('firstBalance') or 0) + top, 2)
        state['balance'] = bal
        state['sampledAt'] = now_ms

    first = float(state.get('firstBalance') or bal)
    topups = float(state.get('topUps') or 0)
    state['spent'] = round(max(0.0, first - bal) + 0.0, 2)   # firstBalance 已含充值补偿
    # 采样明细（保留最近 200 条）
    samples = state.get('samples') or []
    samples.append({'at': now_ms, 'balance': bal})
    state['samples'] = samples[-200:]

    tmp = OUT + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)

    with open(HIST, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'at': now_ms, 'day': today, 'balance': bal,
                            'spent': state['spent'], 'topUps': topups}, ensure_ascii=False) + '\n')

    print(f"{today} 余额 {bal:.2f} | 今日真实花费 {state['spent']:.2f} 元 | 充值 {topups:.2f}")


if __name__ == '__main__':
    main()
