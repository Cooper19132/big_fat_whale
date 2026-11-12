#!/bin/bash
# 直连调试：在 bare 里手动 push，打印逐行 porcelain 结果
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s' <<'REMOTE' 2>&1
BARE=/home/admin/git-relay/CAMPUS-INTERNET.git
TOK=$(cat /home/admin/.gh-token)
URL="https://x-access-token:$TOK@github.com/Cooper19132/CAMPUS-INTERNET.git"
cd $BARE
echo "--- 本地 bare main: $(git rev-parse main) ---"
echo "--- GitHub 侧 main（push 前）---"
git -c http.version=HTTP/1.1 ls-remote "$URL" refs/heads/main 2>&1 | sed 's/^/  /'
echo "--- push --porcelain ---"
git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push --porcelain "$URL" "+refs/heads/main:refs/heads/main" 2>&1 | sed 's/^/  /'
echo "--- GitHub 侧 main（push 后）---"
git -c http.version=HTTP/1.1 ls-remote "$URL" refs/heads/main 2>&1 | sed 's/^/  /'
REMOTE
