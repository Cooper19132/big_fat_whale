#!/bin/bash
# 自持运维检查 v2：上游漂移 + 服务 + 端口 + 备份新鲜度 + 磁盘
# 输出：① 人类可读文本（stdout）② 结构化 JSON → /home/admin/backups/selfhost-status.json（面板读它）
# 用法：ssh ... 'bash -s' < selfhost-check.sh   （以 admin 身份，需 sudo -n 读 root 文件）
set -u
NC=/root/Napcat/opt/QQ/resources/app/app_launcher/napcat
QQD=/root/Napcat/opt/QQ
B=/home/admin/backups
OUT=$B/selfhost-status.json
M=$(ls -1t "$B"/manifest-*.txt 2>/dev/null | head -1)
NOW=$(date +%s)
ISO=$(date -Iseconds)

qq_ver=$(sudo -n cat "$QQD/resources/app/package.json" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin).get("version","?"))' 2>/dev/null || echo "?")
nc_ver=$(sudo -n grep -ho '4\.[0-9]\+\.[0-9]\+' "$NC/package.json" 2>/dev/null | head -1)
[ -n "${nc_ver:-}" ] || nc_ver="?"

want_qq=""; want_nc=""
if [ -n "${M:-}" ]; then
  want_qq=$(grep -m1 qq_sha256 "$M" | awk '{print $2}')
  want_nc=$(grep -m1 napcat.mjs_sha256 "$M" | awk '{print $2}')
fi
now_qq=$(sudo -n sha256sum "$QQD/qq" 2>/dev/null | cut -d' ' -f1)
now_nc=$(sudo -n sha256sum "$NC/napcat.mjs" 2>/dev/null | cut -d' ' -f1)

qq_ok=false; nc_ok=false
[ -n "$want_qq" ] && [ "$want_qq" = "$now_qq" ] && qq_ok=true
[ -n "$want_nc" ] && [ "$want_nc" = "$now_nc" ] && nc_ok=true
drift=""
[ "$qq_ok" = true ] || drift="$drift QQ二进制"
[ "$nc_ok" = true ] || drift="$drift NapCat入口"

echo "== 基准清单：${M:-无} =="
echo "   QQ 版本      $qq_ver   sha ${now_qq:-读不到}"
echo "   NapCat 版本  $nc_ver   sha ${now_nc:-读不到}"
$qq_ok && echo "   QQ 二进制   一致" || echo "   ⚠ QQ 二进制   变了！${want_qq:-无基线} → ${now_qq:-读不到}"
$nc_ok && echo "   NapCat 入口 一致" || echo "   ⚠ NapCat 入口 变了！${want_nc:-无基线} → ${now_nc:-读不到}"

svc_json="{"
first=1
for s in napcat qqbot qqbot-render; do
  st=$(systemctl is-active "$s" 2>/dev/null)
  printf "   %-14s %s\n" "$s" "$st"
  [ $first -eq 1 ] || svc_json="$svc_json,"
  first=0
  svc_json="$svc_json\"$s\":\"$st\""
done
svc_json="$svc_json}"

ports=$(ss -ltn 2>/dev/null | awk '/:3000 |:3001 |:6099 /{print $4}' | tr '\n' ' ')
echo "== 端口 == $ports"

bk_json="["; first=1
while read -r f; do
  [ -z "$f" ] && continue
  sz=$(stat -c %s "$f" 2>/dev/null || echo 0)
  mt=$(stat -c %Y "$f" 2>/dev/null || echo 0)
  age=$(( (NOW - mt) / 86400 ))
  [ $first -eq 1 ] || bk_json="$bk_json,"
  first=0
  bk_json="$bk_json{\"name\":\"$(basename "$f")\",\"size\":$sz,\"ageDays\":$age}"
done < <(ls -1t "$B"/*.tar.gz "$B"/*.tar.zst 2>/dev/null | head -6)
bk_json="$bk_json]"

disk=$(df -P / | tail -1 | awk '{print $5}')

python3 - "$OUT" "$ISO" "$qq_ver" "$nc_ver" "$want_qq" "$now_qq" "$qq_ok" "$want_nc" "$now_nc" "$nc_ok" "$svc_json" "$bk_json" "$disk" "$drift" "$(basename "${M:-无}")" <<'PY'
import sys, json, os
(out, iso, qqv, ncv, wqq, nqq, qqok, wnc, nnc, ncok, svc, bk, disk, drift, man) = sys.argv[1:16]
def b(x): return x == "true"
doc = {
    "checkedAt": iso,
    "manifest": man,
    "qq": {"version": qqv, "expectSha": wqq, "actualSha": nqq, "ok": b(qqok)},
    "napcat": {"version": ncv, "expectSha": wnc, "actualSha": nnc, "ok": b(ncok)},
    "services": json.loads(svc),
    "backups": json.loads(bk),
    "diskUsedPct": disk,
    "drift": [d for d in drift.split() if d],
}
tmp = out + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
os.replace(tmp, out)
print("   JSON → " + out)
PY

if [ -n "${drift// /}" ]; then
  curl -s -m 8 -X POST http://127.0.0.1:3000/send_private_msg -H 'Content-Type: application/json' \
    -d "{\"user_id\":246695065,\"message\":\"[自持运维] 上游变了：$drift（QQ $qq_ver / NapCat $nc_ver）。注入可能失效，看 /var/log/qqbot-selfhost.log\"}" >/dev/null 2>&1 \
    && echo "   已私聊告警" || echo "   告警发送失败（OneBot 未就绪？）"
fi
echo "== 磁盘 == 已用 ${disk}"
