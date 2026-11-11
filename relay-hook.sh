#!/bin/sh
# 收到推送后转手同步到 GitHub（家宽到 github.com 不稳，用服务器中转）
TOK=$(cat /home/admin/.gh-token 2>/dev/null)
[ -z "$TOK" ] && { echo "relay: 没有 token"; exit 0; }
cd /home/admin/git-relay/big_fat_whale.git || exit 0
URL="https://x-access-token:$TOK@github.com/Cooper19132/big_fat_whale.git"
OUT=$(git push --quiet "$URL" 'refs/heads/*:refs/heads/*' 2>&1)
RC=$?
if [ $RC -eq 0 ]; then
  echo "relay: 已同步 GitHub"
else
  echo "relay: 同步失败 rc=$RC $OUT"
  curl -s -m 8 -X POST http://127.0.0.1:3000/send_private_msg -H 'Content-Type: application/json' \
    -d "{\"user_id\":246695065,\"message\":\"[git relay] 推 GitHub 失败：$OUT\"}" >/dev/null 2>&1
fi
exit 0
