#!/bin/bash
# 诊断：本地 remote 配置 + 中转 bare 的真实 refs + 钩子日志
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
NAME=CAMPUS-INTERNET
echo "=== 本地 remote ==="
cd /d/dshworks/default-workspace && git remote -v | sed 's/^/  /'
echo "  branch.main.remote=$(git config --get branch.main.remote)"
echo "  branch.main.merge=$(git config --get branch.main.merge)"
echo ""
echo "=== 中转 bare 的 refs ==="
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "git -C /home/admin/git-relay/$NAME.git for-each-ref --format='  %(refname) %(objectname:short)'; echo '  --- 钩子是否存在 ---'; ls -l /home/admin/git-relay/$NAME.git/hooks/post-receive" 2>&1
echo ""
echo "=== 手动跑一次钩子看输出 ==="
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
  "cd /home/admin/git-relay/$NAME.git && echo 'refs/heads/main \$(git rev-parse refs/heads/main) refs/heads/main \$(git rev-parse refs/heads/main)' | sh hooks/post-receive" 2>&1 | sed 's/^/  /'
