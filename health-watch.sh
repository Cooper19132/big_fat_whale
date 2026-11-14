#!/bin/bash
# OneBot 探活（服务器侧，每 5 分钟一次，不依赖小鲸鱼本人）
# 判定：3001 端口在监听 且 get_status 返回 "online":true
# 连续 2 次失败（≈10 分钟）→ 判定掉线，发一次告警；恢复时再发一次
# 产出：/home/admin/backups/health.json（面板读）、health-watch.state（内部状态）
set -u

BASE=/home/admin/backups
STATE="$BASE/health-watch.state"
OUT="$BASE/health.json"
mkdir -p "$BASE"
NOW=$(date +%s)

STATUS_JSON=$(curl -s -m 8 -X POST 127.0.0.1:3000/get_status \
  -H 'Content-Type: application/json' -d '{}' 2>/dev/null)
PORT=$(ss -lnt 2>/dev/null | grep -c ':3001 ')

ONLINE=0
if [ "$PORT" -ge 1 ] && printf '%s' "$STATUS_JSON" | grep -q '"online":true'; then
  ONLINE=1
fi

FAIL=0
SINCE=0
WAS=ok
if [ -f "$STATE" ]; then
  . "$STATE"
fi

if [ "$ONLINE" = 1 ]; then
  if [ "${WAS:-ok}" = "down" ]; then
    DOWN_SEC=$((NOW - ${SINCE:-$NOW}))
    /home/admin/scripts/notify.sh "小鲸鱼已恢复" \
      "重新上线，掉线约 $((DOWN_SEC / 60)) 分钟。OneBot 3000/3001 正常，$(date '+%F %T')。"
  fi
  FAIL=0
  SINCE=0
  WAS=ok
else
  FAIL=$((FAIL + 1))
  if [ "$SINCE" -eq 0 ]; then SINCE=$NOW; fi
  if [ "$FAIL" -ge 2 ]; then
    if [ "${WAS:-ok}" != "down" ]; then
      WAS=down
      REASON="get_status 不可用"
      if [ "$PORT" -ge 1 ]; then REASON="get_status 不通（端口在但账号离线）"; fi
      if [ "$PORT" -lt 1 ]; then REASON="3001 端口未监听，NapCat 注入进程可能已死"; fi
      /home/admin/scripts/notify.sh "小鲸鱼掉线" \
        "连续 ${FAIL} 次探活失败：${REASON}。可能需要重启 napcat 或扫码登录。最后一次在线：未知$(date -d @${LAST_OK:-$NOW} '+%F %T')"
    else
      WAS=down
    fi
  fi
fi

if [ "$ONLINE" = 1 ]; then LAST_OK=$NOW; fi

cat > "$STATE" <<EOF
FAIL=$FAIL
SINCE=$SINCE
WAS=$WAS
LAST_OK=${LAST_OK:-0}
EOF

if [ "$SINCE" -gt 0 ]; then
  SINCE_TXT=$(date -d @"$SINCE" -Iseconds)
else
  SINCE_TXT=""
fi
if [ "${LAST_OK:-0}" -gt 0 ]; then
  LASTOK_TXT=$(date -d @"$LAST_OK" -Iseconds)
else
  LASTOK_TXT=""
fi
printf '{"checkedAt":"%s","online":%s,"failStreak":%s,"offlineSince":"%s","lastOnlineAt":"%s","port3001":%s}\n' \
  "$(date -Iseconds)" \
  "$([ "$ONLINE" = 1 ] && echo true || echo false)" \
  "$FAIL" "$SINCE_TXT" "$LASTOK_TXT" "$PORT" > "$OUT"
