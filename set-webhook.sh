#!/bin/bash
# 一条命令接入群机器人告警通道
# 用法：
#   ./set-webhook.sh "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"
#   ./set-webhook.sh "https://oapi.dingtalk.com/robot/send?access_token=xxxx"
#   ./set-webhook.sh "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
# 会做：写 /home/admin/notify.env（600）→ 立刻发一条自检 → 打印结果
set -eu

URL="${1:-}"
if [ -z "$URL" ]; then
  echo "用法: $0 <webhook地址>" >&2
  exit 2
fi

case "$URL" in
  *qyapi.weixin.qq.com*) KIND=wechat ;;
  *oapi.dingtalk.com*)   KIND=dingtalk ;;
  *open.feishu.cn*)      KIND=feishu ;;
  *open.larksuite.com*)  KIND=feishu ;;
  *)                     KIND=wechat ;;
esac

umask 077
cat > /home/admin/notify.env <<EOF
# 群机器人告警通道（本文件由 set-webhook.sh 生成，权限 600）
WEBHOOK_URL=$URL
WEBHOOK_KIND=$KIND
EOF
chmod 600 /home/admin/notify.env

echo "已写入 /home/admin/notify.env（kind=$KIND）"
echo "--- 自检 ---"
FORCE_OUT=$(/home/admin/scripts/notify.sh --test)
echo "$FORCE_OUT"

case "$FORCE_OUT" in
  *"sent=1"*) echo "✅ 通道打通，以后掉线/恢复告警会直接发到群里" ;;
  *)          echo "⚠ 没打通，看 /home/admin/backups/notify/notify.log 里的 webhook-fail 行" ;;
esac
