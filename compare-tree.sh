#!/bin/bash
# 比对 GitHub main 的 commit/tree 与本地 HEAD，确认内容一致（SHA 可能因快照重写而不同）
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
cd /d/dshworks/default-workspace
echo "  本地 HEAD : $(git rev-parse HEAD)"
echo "  本地 tree : $(git rev-parse 'HEAD^{tree}')"
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" \
 "TOK=\$(cat /home/admin/.gh-token); curl -s -m 25 -H \"Authorization: Bearer \$TOK\" https://api.github.com/repos/Cooper19132/CAMPUS-INTERNET/commits/main | python3 -c \"import sys,json;d=json.load(sys.stdin);print('  GitHub HEAD:',d['sha']);print('  GitHub tree:',d['commit']['tree']['sha']);print('  message    :',d['commit']['message'].splitlines()[0])\"" 2>&1
