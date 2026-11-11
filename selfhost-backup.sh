#!/bin/bash
# 自持运维快照：NapCat 运行时 + qq-agent 依赖清单
# 用法：ssh ... 'bash -s' < selfhost-backup.sh
set -u
N=/root/Napcat/opt/QQ/resources/app/app_launcher/napcat
Q=/root/Napcat/opt/QQ
B=/home/admin/backups
D=$(date +%F)
mkdir -p "$B"

echo "== 1. NapCat 运行时快照（排除 cache/logs）=="
sudo tar czf "$B/napcat-runtime-$D.tar.gz" \
  --exclude="napcat/cache" --exclude="napcat/logs" \
  -C "$(dirname "$N")" napcat 2>/dev/null
sudo chown admin:admin "$B/napcat-runtime-$D.tar.gz"
ls -lh "$B/napcat-runtime-$D.tar.gz" | awk '{print "   ", $5, $9}'

echo "== 2. 清单 + 校验和 =="
{
  echo "date: $D"
  echo "host: $(hostname) $(uname -r)"
  echo "qq_binary: $(sudo stat -c '%s bytes, mtime %y' $Q/qq 2>/dev/null)"
  echo "qq_sha256: $(sudo sha256sum $Q/qq | cut -d' ' -f1)"
  echo "napcat.mjs_sha256: $(sudo sha256sum $N/napcat.mjs | cut -d' ' -f1)"
  echo "loadNapCat_sha256: $(sudo sha256sum $N/loadNapCat.js | cut -d' ' -f1)"
  echo "native:"; sudo ls -1 $N/native | sed 's/^/  - /'
  echo "onebot11.json:"; sudo cat $N/config/onebot11.json 2>/dev/null
  echo "qq-agent deps:"; sudo node -e "console.log(JSON.stringify(require('/opt/qq-agent/package.json').dependencies))" 2>/dev/null
  echo "node: $(node -v)  npm: $(npm -v 2>/dev/null)  python: $(python3 -V 2>&1)"
  echo "chrome: $(google-chrome --version 2>/dev/null)"
  echo "ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
} > "$B/manifest-$D.txt" 2>/dev/null
chmod 644 "$B/manifest-$D.txt"
echo "    manifest $(wc -l < "$B/manifest-$D.txt") 行"

echo "== 2b. QQ 整包（仅当版本 sha 变了才重打，留最近 2 份）=="
QSH=$(sudo sha256sum $Q/qq | cut -d' ' -f1)
if ls "$B"/qq-*.tar.zst >/dev/null 2>&1 && grep -l "$QSH" "$B"/qq-*.tar.zst.sha256 2>/dev/null | head -1 | grep -q .; then
  # sha256 文件里不会写 qq 二进制的 sha，这里改用 manifest 里的 qq_sha256 比对
  if grep -q "qq_sha256: $QSH" "$B"/manifest-*.txt 2>/dev/null; then
    echo "    已有同版本 QQ 包，跳过"
  fi
else
  VER=$(sudo sh -c "grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+-[0-9]\+' /root/Napcat/opt/QQ/resources/app/package.json | head -1")
  VER=${VER:-unknown}
  echo "    打包 QQ $VER …"
  nice -n 15 sudo tar --use-compress-program="zstd -3 -T2" -cf "$B/qq-$VER-$D.tar.zst" -C /root/Napcat/opt QQ
  sudo chown admin:admin "$B/qq-$VER-$D.tar.zst"
  sha256sum "$B/qq-$VER-$D.tar.zst" > "$B/qq-$VER-$D.tar.zst.sha256"
  ls -lh "$B/qq-$VER-$D.tar.zst" | awk '{print "   ", $5, $9}'
  ls -1t "$B"/qq-*.tar.zst 2>/dev/null | tail -n +3 | xargs -r sudo rm -f
fi

echo "== 3. qq-agent 依赖冻结包 =="
sudo tar czf "$B/qq-agent-node_modules-$D.tar.gz" -C /opt/qq-agent node_modules package-lock.json 2>/dev/null
sudo chown admin:admin "$B/qq-agent-node_modules-$D.tar.gz"
ls -lh "$B/qq-agent-node_modules-$D.tar.gz" | awk '{print "   ", $5, $9}'

echo "== 4. 现有备份 =="
ls -1t "$B" | head -8 | sed 's/^/   /'
df -h /home | tail -1 | awk '{print "   磁盘剩余", $4}'
