#!/bin/bash
# git 传输层哪种参数能通（HTTP/1.1 vs 2、有无 token）
set -uo pipefail
KEYDIR=D:/dshworks/qqbot/ssh
HOST=admin@116.62.149.191
ssh -i "$KEYDIR/id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KEYDIR/known_hosts" -o BatchMode=yes -o ConnectTimeout=20 "$HOST" 'bash -s' <<'REMOTE' 2>&1
TOK=$(cat /home/admin/.gh-token)
run() { desc="$1"; shift; printf '  %-34s ' "$desc"; s=$(date +%s); out=$(timeout 30 "$@" 2>&1 | tail -1); e=$(date +%s); echo "($((e-s))s) ${out:0:90}"; }
run "公开库 HTTP/2 默认" git ls-remote https://github.com/git/git.git HEAD
run "公开库 强制 HTTP/1.1" git -c http.version=HTTP/1.1 ls-remote https://github.com/git/git.git HEAD
run "私有库 无 token(应 401 快返)" git -c http.version=HTTP/1.1 ls-remote https://github.com/Cooper19132/CAMPUS-INTERNET.git HEAD
run "私有库 带 token HTTP/1.1" git -c http.version=HTTP/1.1 ls-remote "https://x-access-token:$TOK@github.com/Cooper19132/CAMPUS-INTERNET.git" HEAD
REMOTE
