#!/bin/bash
# 服务器端备份：只打包「重装必需」的东西
#   代码(src/scripts/ui/test/render/fishtalk) + 配置与状态(data/*.json，排除图片缓存/贴纸/sessions/memes)
# 大件排除：node_modules 6M、models 216M、.venv-asr 484M、data/inbox 761M、data/stickers 93M
set -u
mkdir -p /home/admin/backups
tar_cmd() {
  local out="$1"
  cd /opt || exit 1
  sudo tar czf "$out" \
    --exclude='qq-agent/node_modules' \
    --exclude='qq-agent/data/inbox' \
    --exclude='qq-agent/data/stickers' \
    --exclude='qq-agent/data/sessions' \
    --exclude='qq-agent/data/memes.json' \
    --exclude='qq-agent/models' \
    --exclude='qq-agent/.venv-asr' \
    --exclude='qq-agent/src.bak-*' \
    --exclude='qq-agent/dsh-work' \
    qq-agent
  sudo chown admin:admin "$out"
}
LINE='30 4 * * * sudo tar czf /home/admin/backups/qq-agent-$(date +\%F).tar.gz --exclude=qq-agent/node_modules --exclude=qq-agent/data/inbox --exclude=qq-agent/data/stickers --exclude=qq-agent/data/sessions --exclude=qq-agent/data/memes.json --exclude=qq-agent/models --exclude=qq-agent/.venv-asr --exclude="qq-agent/src.bak-*" --exclude=qq-agent/dsh-work -C /opt qq-agent && sudo chown admin:admin /home/admin/backups/*.tar.gz && find /home/admin/backups -name "qq-agent-*.tar.gz" -mtime +30 -delete'
( crontab -l 2>/dev/null | grep -v 'qq-agent-\$(date' ; echo "$LINE" ) | crontab -

sudo rm -f /home/admin/backups/qq-agent-2026-11-12.tar.gz
tar_cmd /home/admin/backups/qq-agent-$(date +%F).tar.gz
echo "--- cron ---"
crontab -l | grep -v '^#' | tail -2
echo "--- 产物 ---"
ls -lh /home/admin/backups/ | tail -3
echo "--- 包内抽样 ---"
sudo tar tzf /home/admin/backups/qq-agent-$(date +%F).tar.gz | grep -cE '^qq-agent/' | sed 's/^/  条目数: /'
sudo tar tzf /home/admin/backups/qq-agent-$(date +%F).tar.gz | grep -E 'src/(tools|orchestrator|mood)\.js$|data/(mood|scheduled-tasks|billing)\.json$' | head -6
df -h / | tail -1