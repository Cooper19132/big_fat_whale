#!/bin/bash
# 离线重建：不联网也能把 qq-agent 恢复成能跑的状态
# 用法：bash tools/restore-offline.sh            （只恢复代码依赖）
#       bash tools/restore-offline.sh --with-qq  （连 QQ + NapCat 运行时一起恢复，需 sudo）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor"
AGENT="$ROOT/qq-agent"

say() { printf '  %s\n' "$*"; }

[ -d "$AGENT" ] || { echo "找不到 $AGENT"; exit 1; }

echo "== 1) node_modules（离线包优先，没有才联网）=="
NM_PKG=$(ls -1 "$VENDOR"/qq-agent-node_modules-*.tar.gz 2>/dev/null | tail -1 || true)
if [ -d "$AGENT/node_modules/.bin" ]; then
  say "已存在，跳过"
elif [ -n "$NM_PKG" ]; then
  tar xzf "$NM_PKG" -C "$AGENT"
  say "从 $(basename "$NM_PKG") 恢复完成"
else
  say "没有离线包，走 npm ci（需要网络）"
  ( cd "$AGENT" && npm ci --omit=dev )
fi

echo "== 2) 梗库 =="
if [ -f "$AGENT/data/memes.json" ]; then
  say "已存在，跳过"
elif [ -f "$ROOT/memes.json" ]; then
  cp "$ROOT/memes.json" "$AGENT/data/memes.json"
  say "memes.json 就位"
else
  say "缺 memes.json（查梗会退化，其他功能不影响）"
fi

echo "== 3) 语法自检 =="
for f in "$AGENT"/src/server.js "$AGENT"/src/orchestrator.js "$AGENT"/src/tools.js; do
  node --check "$f" && say "OK $(basename "$f")"
done

if [ "${1:-}" = "--with-qq" ]; then
  echo "== 4) QQ + NapCat 运行时（需要 sudo）=="
  NAPCAT_PKG=$(ls -1 "$VENDOR"/napcat-runtime-*.tar.gz 2>/dev/null | tail -1 || true)
  QQ_PKG=$(ls -1 "$VENDOR"/qq-*-*.tar.zst 2>/dev/null | tail -1 || true)
  DEST=/root/Napcat/opt
  if [ -n "$NAPCAT_PKG" ]; then
    sudo tar xzf "$NAPCAT_PKG" -C "$DEST/QQ/resources/app/app_launcher/"
    say "NapCat 运行时恢复"
  fi
  if [ -n "$QQ_PKG" ]; then
    sudo bash "$VENDOR/unzst.py" "$QQ_PKG" | sudo tar xf - -C "$DEST"
    sudo chmod 755 "$DEST/QQ/qq"
    say "QQ 整包恢复"
  fi
  echo "== 5) 校验（必须与基线一致）=="
  sudo sha256sum "$DEST/QQ/qq" | awk '{print "  qq "$1}'
  sudo sha256sum "$DEST/QQ/resources/app/app_launcher/napcat/napcat.mjs" | awk '{print "  napcat.mjs "$1}'
  say "基线：qq ae674327…299ec2 / napcat.mjs f80e4be3…8179e6"
  say "然后：sudo systemctl restart napcat qqbot"
fi

echo "完成。"
