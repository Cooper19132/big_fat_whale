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

echo "[1/3] 建 GitHub 仓库 $NAME ($VIS) …"
timeout 90 ssh "${SSHOPT[@]}" "$HOST" NAME="$NAME" VIS="$VIS" DESC="$DESC" 'bash -s' <<'REMOTE'
TOK=$(cat /home/admin/.gh-token)
PRIV=$([ "$VIS" = private ] && echo true || echo false)
payload=$(printf '{"name":"%s","private":%s,"description":"%s","auto_init":false}' "$NAME" "$PRIV" "$DESC")
resp=$(curl -s -m 25 -X POST https://api.github.com/user/repos \
  -H "Authorization: Bearer $TOK" -H "Accept: application/vnd.github+json" \
  -H 'Content-Type: application/json' -d "$payload")
printf '%s' "$resp" | python3 -c "import sys,json;d=json.load(sys.stdin);print('  →',d.get('full_name') or ('失败: '+str(d.get('message'))))"
REMOTE

echo "[2/3] 建服务器中转 bare + 钩子 …"
timeout 90 ssh "${SSHOPT[@]}" "$HOST" NAME="$NAME" 'bash -s' <<'REMOTE'
BARE=/home/admin/git-relay/$NAME.git
git init --bare -q "$BARE" 2>/dev/null
cat > "$BARE/hooks/post-receive" <<'EOS'
#!/bin/sh
TOK=$(cat /home/admin/.gh-token)
REPO=$(basename "$PWD" .git)
cd "$PWD" || exit 0
OUT=$(git push --quiet "https://x-access-token:$TOK@github.com/Cooper19132/$REPO.git" "refs/heads/*:refs/heads/*" 2>&1) || {
  curl -s -m 8 -X POST http://127.0.0.1:3000/send_private_msg -H 'Content-Type: application/json' \
    -d "{\"user_id\":246695065,\"message\":\"[git relay] $REPO 推 GitHub 失败：$OUT\"}" >/dev/null 2>&1
  echo "relay: 失败 $OUT"; exit 0
}
echo "relay: 已同步 GitHub"
EOS
chmod 700 "$BARE/hooks/post-receive"
echo "  → $BARE"
REMOTE

echo "[3/3] 本地接上（在目标仓库里执行下面两条）"
cat <<TIPS
  git remote add origin ssh://$HOST/home/admin/git-relay/$NAME.git
  git -c core.sshCommand="ssh -i ssh/id_ed25519" push -u origin main
TIPS
