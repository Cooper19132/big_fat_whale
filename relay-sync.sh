#!/bin/sh
# 服务器中转同步：把 /home/admin/git-relay/<REPO>.git 推到 GitHub
# 用法：relay-sync.sh <REPO>      （由各 bare 仓库的 hooks/post-receive 后台调用）
# 特点：退避重试、分叉单独判定、日志落盘、告警去重（同库 30 分钟一次）

set -u
REPO="${1:?用法: relay-sync.sh <仓库名>}"
OWNER=Cooper19132
BASE=/home/admin/git-relay
BARE="$BASE/$REPO.git"
LOG="$BASE/relay.log"
STAMP="$BASE/.alert-$REPO"
TOK_FILE=/home/admin/.gh-token

ts() { date '+%F %T'; }
log() { echo "$(ts) $REPO $*" >> "$LOG"; }

[ -d "$BARE" ] || { log "跳过：没有 $BARE"; exit 0; }
[ -s "$TOK_FILE" ] || { log "失败：token 文件缺失或为空"; exit 1; }
TOK=$(tr -d '\r\n' < "$TOK_FILE")
URL="https://x-access-token:$TOK@github.com/$OWNER/$REPO.git"

# 日志超过 2MB 就切一份旧的
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 2097152 ]; then
  mv -f "$LOG" "$LOG.1"
fi

attempts=0
last_out=""
fatal_kind=""
for delay in 0 5 20 60 180 300; do
  [ "$delay" -gt 0 ] && sleep "$delay"
  attempts=$((attempts + 1))
  last_out=$(cd "$BARE" && GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/true \
      timeout 120 git push --quiet "$URL" 'refs/heads/*:refs/heads/*' 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    log "同步成功（第 ${attempts} 次尝试）"
    rm -f "$STAMP"
    exit 0
  fi
  one_line=$(printf '%s' "$last_out" | tail -2 | tr '\n' ' ' | cut -c1-300)
  log "第 ${attempts} 次失败 rc=${rc}: $one_line"
  # 分叉 / 权限 / 认证问题：重试没用，立刻收手，交给人工
  case "$last_out" in
    *non-fast-forward*|*"fetch first"*|*"failed to push some refs"*)
      fatal_kind="分叉"; break ;;
    *Authentication*failed*|*Permission*denied*|*"not found"*|*403*)
      fatal_kind="认证或权限"; break ;;
  esac
done

# 告警：同库 30 分钟内只报一次
now=$(date +%s)
if [ ! -f "$STAMP" ] || [ $((now - $(stat -c %Y "$STAMP"))) -gt 1800 ]; then
  touch "$STAMP"
  reason="${fatal_kind:-网络}"
  brief=$(printf '%s' "$last_out" | tail -1 | tr -d '"\\' | cut -c1-200)
  msg="[git relay] ${REPO} 推 GitHub 失败（${reason}，共试 ${attempts} 次）：${brief}"
  curl -s -m 10 -X POST http://127.0.0.1:3000/send_private_msg \
    -H 'Content-Type: application/json' \
    -d "{\"user_id\":246695065,\"message\":\"${msg}\"}" >/dev/null 2>&1
  log "已私聊告警（${reason}）"
fi
exit 0
