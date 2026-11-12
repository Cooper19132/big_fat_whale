#!/bin/sh
# 通用 post-receive：只做一件事——把收到的推送转交给后台同步脚本
# 装在 /home/admin/git-relay/<REPO>.git/hooks/post-receive，chmod 755
# 不阻塞推送方：逻辑在 relay-sync.sh 里跑，带退避重试与日志

cat >/dev/null 2>&1 || true
REPO=$(basename "$PWD" .git)
setsid /home/admin/git-relay/relay-sync.sh "$REPO" >/dev/null 2>&1 &
exit 0
