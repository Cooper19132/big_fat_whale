#!/bin/bash
# 从服务器侧探 github 可达性，判断是偶发还是被卡
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s' <<'REMOTE' 2>&1
echo "--- DNS ---"
getent hosts github.com | head -3
echo "--- https 状态码 ---"
for u in https://github.com https://api.github.com; do
  printf '  %-26s -> ' $u
  curl -s -o /dev/null -w '%{http_code}  %{time_total}s\n' --max-time 20 -4 $u
done
echo "--- 443 端口直连（IPv4）---"
timeout 10 bash -c 'exec 3<>/dev/tcp/140.82.112.3/443 && echo "  140.82.112.3:443 OK" || echo "  140.82.112.3:443 不通"'
echo "--- git ls-remote 计时 ---"
TOK=$(cat /home/admin/.gh-token)
time timeout 40 git ls-remote "https://x-access-token:$TOK@github.com/Cooper19132/CAMPUS-INTERNET.git" 2>&1 | tail -3
REMOTE
