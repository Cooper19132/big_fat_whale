#!/bin/bash
# 把 default-workspace 接到服务器中转 bare，再由钩子同步到 GitHub 私有仓库
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
NAME=CAMPUS-INTERNET
HOST=admin@116.62.149.191
SSHCMD="ssh -i $KEYDIR/id_ed25519 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=$KEYDIR/known_hosts -o BatchMode=yes -o ConnectTimeout=20"

cd /d/dshworks/default-workspace || { echo "目标目录不存在"; exit 1; }

echo "[1/4] 重置 origin → 服务器中转"
git remote remove origin 2>/dev/null
git remote add origin "ssh://$HOST/home/admin/git-relay/$NAME.git"
git config core.sshCommand "$SSHCMD"
git remote -v | sed 's/^/    /'

echo "[2/4] 确认工作区已提交"
git status --porcelain | head -5
echo "    未提交条数: $(git status --porcelain | wc -l)"

echo "[3/4] 推送 main（55 MB 首次传输，慢一点正常）"
git push -u origin main 2>&1 | tail -20
echo "    push 退出码: ${PIPESTATUS[0]}"

echo "[4/4] 校验服务器端 refs"
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes "$HOST" \
  "git -C /home/admin/git-relay/$NAME.git for-each-ref --format='    %(refname) %(objectname:short)' refs/heads 2>&1; echo '    --- GitHub 侧 ---'; TOK=\$(cat /home/admin/.gh-token); curl -s -m 20 -H \"Authorization: Bearer \$TOK\" https://api.github.com/repos/Cooper19132/$NAME | python3 -c \"import sys,json;d=json.load(sys.stdin);print('    repo:',d.get('full_name'),'private:',d.get('private'),'size:',d.get('size'),'KB')\"; curl -s -m 20 -H \"Authorization: Bearer \$TOK\" https://api.github.com/repos/Cooper19132/$NAME/branches | python3 -c \"import sys,json;d=json.load(sys.stdin);print('    branches:',[b['name'] for b in d] if isinstance(d,list) else d)\"" 2>&1
