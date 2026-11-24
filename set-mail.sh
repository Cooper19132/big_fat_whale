#!/bin/bash
# 一条命令接入邮件告警通道（QQ 邮箱 / 163 / 企业邮箱）
# 用法：
#   ./set-mail.sh "发件邮箱" "授权码" ["收件邮箱，默认发给发件人自己"]
# 例：
#   ./set-mail.sh "123456@qq.com" "abcdefghijklmnop"
#   ./set-mail.sh "123456@qq.com" "abcdefghijklmnop" "my@outlook.com"
# 会做：写 /home/admin/notify.env（600）→ 立刻发一封自检邮件 → 打印结果
set -eu

USER_ADDR="${1:-}"
PASS="${2:-}"
TO_ADDR="${3:-$USER_ADDR}"

if [ -z "$USER_ADDR" ] || [ -z "$PASS" ]; then
  echo "用法: $0 <发件邮箱> <授权码> [收件邮箱]" >&2
  exit 2
fi

DOMAIN="${USER_ADDR#*@}"
case "$DOMAIN" in
  qq.com)        HOST=smtp.qq.com ;;
  163.com)       HOST=smtp.163.com ;;
  126.com)       HOST=smtp.126.com ;;
  exmail.qq.com) HOST=smtp.exmail.qq.com ;;
  gmail.com)     HOST=smtp.gmail.com ;;
  outlook.com|hotmail.com) HOST=smtp-mail.outlook.com ;;
  *)             HOST="smtp.$DOMAIN" ;;
esac

umask 077
cat > /home/admin/notify.env <<EOF
# 邮件告警通道（本文件由 set-mail.sh 生成，权限 600）
SMTP_HOST=$HOST
SMTP_PORT=465
SMTP_USER=$USER_ADDR
SMTP_PASS=$PASS
SMTP_TO=$TO_ADDR
EOF
chmod 600 /home/admin/notify.env

echo "已写入 /home/admin/notify.env"
echo "  发件: $USER_ADDR"
echo "  收件: $TO_ADDR"
echo "  服务器: $HOST:465 (SSL)"
echo "--- 自检（会真发一封邮件）---"
FORCE_OUT=$(/home/admin/scripts/notify.sh --test 2>&1 || true)
echo "$FORCE_OUT"

case "$FORCE_OUT" in
  *chans=*smtp*)
    echo "✅ 邮件确实发出去了（chans 里带 smtp），去收件箱和垃圾箱找「[小鲸鱼] 告警通道自检」" ;;
  *"sent=1"*)
    echo "⚠ 没走邮件通道，只落到了 GitHub issue 兜底。看报错："
    sed -n '1,12p' /home/admin/backups/notify/smtp-last-error.txt 2>/dev/null || echo "  (没有 smtp-last-error.txt)"
    echo "  常见原因：授权码错（不是 QQ 密码）/ 邮箱没开 SMTP 服务 / 端口被收件方拦" ;;
  *)
    echo "⚠ 完全没发出去。看 /home/admin/backups/notify/notify.log 与 smtp-last-error.txt" ;;
esac
