#!/bin/bash
# 给中转钩子加重试：服务器→github.com 的 TLS 会偶发被 reset（GnuTLS recv error -110）
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
NAME=CAMPUS-INTERNET
echo "=== 重写 post-receive（4 次重试 + HTTP/1.1）==="
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "NAME=$NAME bash -s" <<'OUTER' 2>&1
BARE=/home/admin/git-relay/$NAME.git
cat > "$BARE/hooks/post-receive" <<'EOS'
#!/bin/sh
TOK=$(cat /home/admin/.gh-token)
REPO=$(basename "$PWD" .git)
URL="https://x-access-token:$TOK@github.com/Cooper19132/$REPO.git"
i=1
LAST=""
while [ $i -le 4 ]; do
  if OUT=$(git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push --quiet "$URL" "+refs/heads/*:refs/heads/*" 2>&1); then
    echo "relay: 已同步 GitHub（第 $i 次尝试）"
    exit 0
  fi
  LAST=$OUT
  echo "relay: 第 $i 次失败，等 $((i*3))s 重试"
  sleep $((i*3))
  i=$((i+1))
done
curl -s -m 8 -X POST http://127.0.0.1:3000/send_private_msg -H 'Content-Type: application/json' \
  -d "{\"user_id\":246695065,\"message\":\"[git relay] $REPO 推 GitHub 失败：$LAST\"}" >/dev/null 2>&1
echo "relay: 失败 $LAST"
exit 0
EOS
chmod 700 "$BARE/hooks/post-receive"
echo "  已写入 $(wc -l < "$BARE/hooks/post-receive") 行"
echo "=== 立刻补推一次 ==="
cd "$BARE" && echo "refs/heads/main $(git rev-parse refs/heads/main) refs/heads/main $(git rev-parse refs/heads/main)" | sh hooks/post-receive
OUTER
