#!/bin/bash
# 修一下 GitHub 仓库描述（之前因参数拆词只写进去了一个 token）
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
NAME=CAMPUS-INTERNET
DESC='校园网 PPPoE 回收 / 蓝屏归因 / 远控卡顿 的长期排查归档'
DB=$(printf '%s' "$DESC" | base64 | tr -d '\n')
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "DB=$DB NAME=$NAME bash -s" <<'REMOTE' 2>&1
DESC=$(printf '%s' "$DB" | base64 -d)
TOK=$(cat /home/admin/.gh-token)
BODY=$(NAME="$NAME" DESC="$DESC" python3 -c 'import json,os;print(json.dumps({"description":os.environ["DESC"],"homepage":""}))')
curl -s -m 25 -X PATCH "https://api.github.com/repos/Cooper19132/$NAME" \
  -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.github+json" \
  -H 'Content-Type: application/json' -d "$BODY" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('  描述已设为:',d.get('description') or d.get('message'))"
REMOTE
