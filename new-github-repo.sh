#!/bin/bash
# 在家宽 github.com 被卡的情况下，借服务器出口在 GitHub 上建仓库，并把中转链路一次配好
#
# 用法（必须在本目录下执行，ssh 用相对 key 路径）：
#   cd /d/dshworks/qqbot && bash new-github-repo.sh <仓库名> [private|public] [描述]
#
# 做完会发生：
#   1) GitHub 上建好同名仓库（token 只在服务器上用）
#   2) 服务器建 bare 仓库 /home/admin/git-relay/<名>.git + post-receive 钩子（推 GitHub）
#   3) 打印可直接用的 remote 地址
set -uo pipefail

NAME="${1:?用法: new-github-repo.sh <仓库名> [private|public] [描述]}"
VIS="${2:-private}"
DESC="${3:-}"
SSHOPT=(-i ssh/id_ed25519 -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=D:/dshworks/qqbot/ssh/known_hosts -o ConnectTimeout=15 -o BatchMode=yes)
HOST=admin@116.62.149.191

# 远端 shell 会把 ssh 命令里的参数按空格重新拆词，所以变量一律 base64 传（无空格、无引号地狱）
b64() { printf '%s' "$1" | base64 | tr -d '\n'; }
NB=$(b64 "$NAME"); VB=$(b64 "$VIS"); DB=$(b64 "$DESC")

echo "[1/3] 建 GitHub 仓库 $NAME ($VIS) …"
timeout 90 ssh "${SSHOPT[@]}" "$HOST" NB="$NB" VB="$VB" DB="$DB" 'bash -s' <<'REMOTE'
NAME=$(printf '%s' "$NB" | base64 -d)
VIS=$(printf '%s' "$VB" | base64 -d)
DESC=$(printf '%s' "$DB" | base64 -d)
TOK=$(cat /home/admin/.gh-token)
PRIV=$([ "$VIS" = private ] && echo true || echo false)
payload=$(NAME="$NAME" VIS="$VIS" DESC="$DESC" python3 -c 'import json,os;print(json.dumps({"name":os.environ["NAME"],"private":os.environ["VIS"]=="private","description":os.environ["DESC"],"auto_init":False}))')
resp=$(curl -s -m 25 -X POST https://api.github.com/user/repos \
  -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.github+json" \
  -H 'Content-Type: application/json' -d "$payload")
printf '%s' "$resp" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  →',d.get('full_name') or ('失败: '+str(d.get('message'))))"
REMOTE

echo "[2/3] 建服务器中转 bare + 钩子 …"
timeout 90 ssh "${SSHOPT[@]}" "$HOST" NB="$NB" 'bash -s' <<'REMOTE'
NAME=$(printf '%s' "$NB" | base64 -d)
BARE=/home/admin/git-relay/$NAME.git
git init --bare -q "$BARE" 2>/dev/null
if [ -x /home/admin/git-relay/relay-sync.sh ]; then
  install -m 755 /home/admin/git-relay/relay-hook.sh "$BARE/hooks/post-receive"
else
  echo "  ! 缺 /home/admin/git-relay/relay-sync.sh（先 scp 这两个脚本上去）" >&2
fi
echo "  → $BARE"
REMOTE

echo "[3/3] 本地接上（在目标仓库里执行下面两条）"
cat <<TIPS
  git remote add origin ssh://$HOST/home/admin/git-relay/$NAME.git
  git -c core.sshCommand="ssh -i D:/dshworks/qqbot/ssh/id_ed25519 -o UserKnownHostsFile=D:/dshworks/qqbot/ssh/known_hosts -o StrictHostKeyChecking=accept-new -o BatchMode=yes" push -u origin main
TIPS
