#!/bin/bash
# 漂移检查：上游（NapCat / QQ）有没有偷偷变过 + 备份还新鲜吗
# 用法：ssh ... 'bash -s' < selfhost-check.sh
set -u
N=/root/Napcat/opt/QQ/resources/app/app_launcher/napcat
Q=/root/Napcat/opt/QQ
B=/home/admin/backups
M=$(ls -1t "$B"/manifest-*.txt 2>/dev/null | head -1)
echo "== 基准清单：${M:-无} =="
if [ -n "${M:-}" ]; then
  want_qq=$(grep -m1 qq_sha256 "$M" | awk '{print $2}')
  want_nc=$(grep -m1 napcat.mjs_sha256 "$M" | awk '{print $2}')
  now_qq=$(sudo sha256sum "$Q/qq" | cut -d' ' -f1)
  now_nc=$(sudo sha256sum "$N/napcat.mjs" | cut -d' ' -f1)
  drift=""
  [ "$want_qq" = "$now_qq" ] && echo "   QQ 二进制   一致" || { echo "   ⚠ QQ 二进制   变了！$want_qq → $now_qq"; drift="QQ 二进制"; }
  [ "$want_nc" = "$now_nc" ] && echo "   NapCat 入口 一致" || { echo "   ⚠ NapCat 入口 变了！$want_nc → $now_nc"; drift="$drift NapCat入口"; }
  if [ -n "$drift" ]; then
    curl -s -m 8 -X POST http://127.0.0.1:3000/send_private_msg -H 'Content-Type: application/json' \
      -d "{\"user_id\":246695065,\"message\":\"[自持运维] 检测到上游漂移：$drift。注入可能失效，去看 /var/log/qqbot-selfhost.log\"}" >/dev/null 2>&1 && echo "   已私聊告警主人"
  fi
fi
echo "== 服务 =="
for s in qqbot napcat qqbot-render; do
  printf "   %-14s %s\n" "$s" "$(systemctl is-active $s 2>/dev/null)"
done
echo "== OneBot 端口 =="
ss -ltnp 2>/dev/null | awk '/:3000 |:3001 |:6099 /{print "   "$4, $6}' | head -4
echo "== 备份新鲜度 =="
ls -1t "$B"/*.tar.gz 2>/dev/null | head -4 | while read f; do
  printf "   %-46s %s\n" "$(basename "$f")" "$(du -h "$f" | cut -f1)"
done
echo "   最旧一份：$(ls -1t "$B"/*.tar.gz 2>/dev/null | tail -1 | xargs -r basename)"
echo "== 磁盘 =="; df -h / | tail -1 | awk '{print "   已用", $3, "剩余", $4}'
