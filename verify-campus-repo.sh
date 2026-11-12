#!/bin/bash
# 校验：中转 bare 的 HEAD 与 GitHub 上最新提交是否一致
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
NAME=CAMPUS-INTERNET
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" "
TOK=\$(cat /home/admin/.gh-token)
echo '--- GitHub 最新 3 次提交 ---'
curl -s -m 25 -H \"Authorization: Bearer \$TOK\" 'https://api.github.com/repos/Cooper19132/$NAME/commits?per_page=3' \
 | python3 -c \"import sys,json;d=json.load(sys.stdin);[print('   ',c['sha'][:7],c['commit']['author']['date'],c['commit']['message'].splitlines()[0][:60]) for c in d] if isinstance(d,list) else print(d)\"
echo '--- 仓库统计 ---'
curl -s -m 25 -H \"Authorization: Bearer \$TOK\" https://api.github.com/repos/Cooper19132/$NAME \
 | python3 -c \"import sys,json;d=json.load(sys.stdin);print('   ',d.get('full_name'),'private=',d.get('private'),'default_branch=',d.get('default_branch'),'size=',d.get('size'),'KB','pushed_at=',d.get('pushed_at'))\"
echo '--- 私有仓库页面 ---'
curl -s -o /dev/null -w '    html_url -> %{http_code}\n' -m 25 \"https://api.github.com/repos/Cooper19132/$NAME\"
" 2>&1
