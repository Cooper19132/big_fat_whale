#!/usr/bin/env python3
"""彻底移除课表相关功能（工具 / 提示词 / 调度器 / 接线）。

每处替换都带断言，任何一处对不上就整体中止并报错，避免改出半截状态。
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = r'D:\dshworks\qqbot\qq-agent\src'
results = []


def patch(fname, name, old, new, count=1):
    path = f'{BASE}\\{fname}'
    s = open(path, encoding='utf-8').read()
    n = s.count(old)
    if n != count:
        raise SystemExit(f'✗ [{fname}] {name}: 期望 {count} 处，实际 {n} 处')
    s = s.replace(old, new, count)
    open(path, 'w', encoding='utf-8').write(s)
    results.append(f'✓ [{fname}] {name}')


def cut_between(fname, name, start_marker, end_marker, keep_end=True):
    """删掉 start_marker 到 end_marker 之间的内容（end_marker 默认保留）。"""
    path = f'{BASE}\\{fname}'
    s = open(path, encoding='utf-8').read()
    i = s.find(start_marker)
    j = s.find(end_marker, i + 1) if i >= 0 else -1
    if i < 0 or j < 0:
        raise SystemExit(f'✗ [{fname}] {name}: 找不到标记 (start={i}, end={j})')
    tail = s[j:] if keep_end else s[j + len(end_marker):]
    s = s[:i] + tail
    open(path, 'w', encoding='utf-8').write(s)
    results.append(f'✓ [{fname}] {name}')


# ─────────────── prompt.js ───────────────
patch('prompt.js', '正例去掉课表播报',
      "正例（这样才对）：「主人～课表播报做好了，每天 21 点我主动告诉你明天的课，没课也会说一声。代码还没往生产上放，等你点个头。」",
      "正例（这样才对）：「主人～群文件归档做好了，按月份分了目录，旧文件都留着。要不要现在部署，等你点个头。」")

cut_between('prompt.js', '删除「课程播报」注入块',
            "  // 定时任务注入：课程播报（每晚由应用内调度器触发，主人并没有发消息）",
            "  // 定时任务注入：主人在 QQ 里下的提醒（到点由调度器唤醒）")
patch('prompt.js', '补回 pushTask 取值',
      "  // 定时任务注入：主人在 QQ 里下的提醒（到点由调度器唤醒）",
      "  const pushTask = ctx.pushTask || null;\n\n  // 定时任务注入：主人在 QQ 里下的提醒（到点由调度器唤醒）")

cut_between('prompt.js', '删除课表查询 + ics 引导段',
            "    '【课表查询 · 用原生工具秒回，别派 DSH】',",
            "    '4. 导入后跟主人确认一句：导入了多少节、覆盖到哪天、有哪些课。'",
            keep_end=False)
# 收尾：紧跟着的换行/结尾数组括号修一下
s = open(f'{BASE}\\prompt.js', encoding='utf-8').read()
s = s.replace("    '只有涉及「重新解析课表 / 改播报逻辑 / 部署」这类要动代码或重算数据的活，才用 dsh_task。',\n", '')
s = s.replace("  ].join('\\n'));\n\n\n  // 文件消息专项引导", "  ].join('\\n'));\n\n  // 文件消息专项引导")
open(f'{BASE}\\prompt.js', 'w', encoding='utf-8').write(s)
results.append('✓ [prompt.js] 收尾清理')

# ─────────────── tools.js ───────────────
patch('tools.js', '去掉 ics-import 引用',
      "import { parseIcs, saveSchedule, summarize as summarizeIcs } from './ics-import.js';\n", '')

cut_between('tools.js', '删除 schedule_query 工具',
            "    {\n      name: 'schedule_query',",
            "    {\n      name: 'write_handover',")
cut_between('tools.js', '删除 import_schedule_ics 工具',
            "    {\n      name: 'import_schedule_ics',",
            "    {\n      name: 'write_handover',")

# ─────────────── app.js ───────────────
patch('app.js', '去掉 ScheduleNotifyScheduler 引用',
      "import { ScheduleNotifyScheduler } from './schedule-notify.js';\n", '')
patch('app.js', '去掉 startClassReminder 引用',
      "import { startClassReminder } from './class-reminder.js';\n", '')
patch('app.js', '去掉 classReminder 变量', "  let classReminder = null;\n", '')
cut_between('app.js', '去掉 scheduleNotify 实例化',
            "  // 每晚定时私聊播报次日课程（应用内调度器，不用 cron/systemd；配置见 data/config.json 的 scheduleNotify）",
            "\n  // ── 入站事件处理 ──") if False else None
patch('app.js', '去掉 scheduleNotify 实例化', """  // 每晚定时私聊播报次日课程（应用内调度器，不用 cron/systemd；配置见 data/config.json 的 scheduleNotify）
  const scheduleNotify = new ScheduleNotifyScheduler({ orchestrator, sender, onebot, log, root: ROOT });
""", '')

cut_between('app.js', '去掉 features 里的 schedule 探测',
            "          // 关键功能状态\n          let schedule = null;",
            "          const cfg = getConfig();")
patch('app.js', '去掉 features.schedule 字段', "              schedule,\n", '')
patch('app.js', '去掉 features.scheduleNotify 字段', """              scheduleNotify: {
                enabled: cfg.scheduleNotify?.enabled !== false,
                time: cfg.scheduleNotify?.time || '21:00'
              },
""", '')

cut_between('app.js', '删除 /api/schedule-notify 接口',
            "      // ── 课程播报（每晚定时私聊次日课程）──",
            "      if (pathname === '/api/pause' && method === 'POST') {")

patch('app.js', '启动处去掉 scheduleNotify.start',
      "    if (getConfig().scheduleNotify?.enabled !== false) scheduleNotify.start();   // 每晚课程播报调度器\n", '')
cut_between('app.js', '启动处去掉上课提醒循环',
            "    // 上课前提醒（按 data/schedule/schedule.json 实时判断，不占用定时任务队列）",
            "    log(`控制台已就绪：http://127.0.0.1:${port}`);")
patch('app.js', 'stop() 去掉 scheduleNotify.stop', "    scheduleNotify.stop();\n", '')
patch('app.js', 'stop() 去掉 classReminder.stop', "    try { classReminder?.stop?.(); } catch { /* ignore */ }\n", '')
patch('app.js', '返回对象去掉 scheduleNotify', "orchestrator, scheduleNotify, start", "orchestrator, start")

print('\n'.join(results))
print('\n全部通过。剩余引用检查：')
for f in ('prompt.js', 'tools.js', 'app.js'):
    txt = open(f'{BASE}\\{f}', encoding='utf-8').read()
    hits = {k: txt.count(k) for k in ('schedule_query', 'import_schedule_ics', 'scheduleNotify', 'classReminder', '课表', 'ics')}
    print(f'  {f}: ' + ', '.join(f'{k}={v}' for k, v in hits.items() if v))
