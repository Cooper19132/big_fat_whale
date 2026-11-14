#!/bin/sh
# 每 15 分钟把所有 relay bare 仓库对账一次（补偿同步，自愈）
# 由 cron 调用：*/15 * * * * /home/admin/git-relay/relay-sync-all.sh
BASE=/home/admin/git-relay
for d in "$BASE"/*.git; do
  [ -d "$d" ] || continue
  "$BASE/relay-sync.sh" "$(basename "$d" .git)" >/dev/null 2>&1
done
exit 0
