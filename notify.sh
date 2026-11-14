#!/bin/bash
# 统一告警出口（服务器侧，不依赖小鲸鱼本人）
# 用法：notify.sh "标题" "正文"
# 通道优先级：notify.env 里配了哪个用哪个（WEBHOOK_URL / TG_* / SMTP_*），
#            都没配 → 退回 GitHub issue（用 /home/admin/.gh-token，会在 GitHub 发通知）
# 同一标题 30 分钟内只发一次，避免刷屏
set -u

TITLE="${1:-告警}"
BODY="${2:-}"
[ -z "$BODY" ] && BODY="(无正文)"

DIR=/home/admin/backups/notify
mkdir -p "$DIR"
# JSON 安全化：去换行、双引号换单引号
SAFE_TITLE=$(printf '%s' "$TITLE" | tr -d '\r\n' | tr '"' "'")
SAFE_BODY=$(printf '%s' "$BODY" | tr -d '\r\n' | tr '"' "'")

KEY=$(printf '%s' "$SAFE_TITLE" | md5sum | cut -c1-10)
STAMP="$DIR/$KEY.last"
NOW=$(date +%s)
if [ -f "$STAMP" ]; then
  LAST=$(cat "$STAMP" 2>/dev/null || echo 0)
  if [ $((NOW - LAST)) -lt 1800 ]; then
    echo "$(date '+%F %T') [skip-dup] $SAFE_TITLE" >> "$DIR/notify.log"
    exit 0
  fi
fi
echo "$NOW" > "$STAMP"

if [ -f /home/admin/notify.env ]; then . /home/admin/notify.env; fi

sent=0

if [ -n "${WEBHOOK_URL:-}" ]; then
  if curl -s -m 10 -X POST "$WEBHOOK_URL" -H 'Content-Type: application/json' \
      -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"[$SAFE_TITLE] $SAFE_BODY\"}}" >/dev/null 2>&1; then
    sent=1
  fi
fi

if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
  if curl -s -m 10 "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TG_CHAT_ID}" --data-urlencode "text=[$SAFE_TITLE] $SAFE_BODY" >/dev/null 2>&1; then
    sent=1
  fi
fi

if [ -n "${SMTP_HOST:-}" ] && [ -n "${SMTP_USER:-}" ] && [ -n "${SMTP_PASS:-}" ] && [ -n "${SMTP_TO:-}" ]; then
  if TITLE="$SAFE_TITLE" BODY="$SAFE_BODY" python3 - <<'PY'
import os, smtplib, ssl
from email.mime.text import MIMEText
host = os.environ.get('SMTP_HOST', '')
port = int(os.environ.get('SMTP_PORT', '465'))
user = os.environ.get('SMTP_USER', '')
pwd = os.environ.get('SMTP_PASS', '')
to = [x.strip() for x in os.environ.get('SMTP_TO', '').split(',') if x.strip()]
msg = MIMEText(os.environ.get('BODY', ''), 'plain', 'utf-8')
msg['Subject'] = '[小鲸鱼] ' + os.environ.get('TITLE', '')
msg['From'] = user
msg['To'] = ','.join(to)
try:
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
        s.login(user, pwd)
        s.sendmail(user, to, msg.as_string())
except Exception:
    raise SystemExit(1)
PY
  then
    sent=1
  fi
fi

if [ "$sent" = 0 ] && [ -r /home/admin/.gh-token ]; then
  TOK=$(cat /home/admin/.gh-token)
  if curl -s -m 15 -o /dev/null -X POST \
      -H "Authorization: token $TOK" -H 'Accept: application/vnd.github+json' \
      https://api.github.com/repos/Cooper19132/big_fat_whale/issues \
      -d "{\"title\":\"[告警] $SAFE_TITLE\",\"body\":\"$SAFE_BODY\"}" 2>/dev/null; then
    sent=1
  fi
fi

echo "$(date '+%F %T') [$SAFE_TITLE] sent=$sent $SAFE_BODY" >> "$DIR/notify.log"
exit 0
