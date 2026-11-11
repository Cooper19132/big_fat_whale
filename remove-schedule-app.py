#!/usr/bin/env python3
"""移除 app.js 里的课表接线（导入 / 实例化 / features / 接口 / 启停 / 上课提醒）。"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
P = r'D:\dshworks\qqbot\qq-agent\src\app.js'
results = []


def patch(name, old, new, count=1):
    s = open(P, encoding='utf-8').read()
    n = s.count(old)
    if n != count:
        raise SystemExit(f'✗ {name}: 期望 {count} 处，实际 {n} 处')
    open(P, 'w', encoding='utf-8').write(s.replace(old, new, count))
    results.append(f'✓ {name}')


def cut_between(name, start_marker, end_marker, keep_end=True):
    s = open(P, encoding='utf-8').read()
    i = s.find(start_marker)
    j = s.find(end_marker, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        raise SystemExit(f'✗ {name}: 找不到标记 (start={i}, end={j})')
    tail = s[j:] if keep_end else s[j + len(end_marker):]
    open(P, 'w', encoding='utf-8').write(s[:i] + tail)
    results.append(f'✓ {name}')


patch('去掉 ScheduleNotifyScheduler 引用', "import { ScheduleNotifyScheduler } from './schedule-notify.js';\n", '')
patch('去掉 startClassReminder 引用', "import { startClassReminder } from './class-reminder.js';\n", '')
patch('去掉 classReminder 变量', "  let classReminder = null;\n", '')
patch('去掉 scheduleNotify 实例化', """  // 每晚定时私聊播报次日课程（应用内调度器，不用 cron/systemd；配置见 data/config.json 的 scheduleNotify）
  const scheduleNotify = new ScheduleNotifyScheduler({ orchestrator, sender, onebot, log, root: ROOT });
""", '')

cut_between('去掉 features 里的 schedule 探测',
            "          // 关键功能状态\n          let schedule = null;",
            "          const cfg = getConfig();")
patch('去掉 features.schedule 字段', "              schedule,\n", '')
patch('去掉 features.scheduleNotify 字段', """              scheduleNotify: {
                enabled: cfg.scheduleNotify?.enabled !== false,
                time: cfg.scheduleNotify?.time || '21:00'
              },
""", '')

cut_between('删除 /api/schedule-notify 接口',
            "      // ── 课程播报（每晚定时私聊次日课程）──",
            "      if (pathname === '/api/pause' && method === 'POST') {")

patch('启动处去掉 scheduleNotify.start',
      "    if (getConfig().scheduleNotify?.enabled !== false) scheduleNotify.start();   // 每晚课程播报调度器\n", '')
cut_between('启动处去掉上课提醒循环',
            "    // 上课前提醒（按 data/schedule/schedule.json 实时判断，不占用定时任务队列）",
            "    log(`控制台已就绪：http://127.0.0.1:${port}`);")
patch('stop() 去掉 scheduleNotify.stop', "    scheduleNotify.stop();\n", '')
patch('stop() 去掉 classReminder.stop', "    try { classReminder?.stop?.(); } catch { /* ignore */ }\n", '')
patch('返回对象去掉 scheduleNotify', "orchestrator, scheduleNotify, start", "orchestrator, start")

print('\n'.join(results))
txt = open(P, encoding='utf-8').read()
for k in ('scheduleNotify', 'classReminder', 'schedule-query', 'schedule-notify', '课表'):
    print(f'  残留 {k}: {txt.count(k)}')
