#!/usr/bin/env bash
# ============================================================================
# 赛博大肥鱼 QQ 机器人 一键部署（NapCat + qq-agent）
#
# 适配：阿里云 ECS（Ubuntu / Debian / Alibaba Cloud Linux / CentOS），root 执行
# 组成：
#   NapCat  = LinuxQQ + OneBot v11 协议端（负责登录 QQ，收发消息）
#   qq-agent= 大脑 + 控制台（事件驱动无状态 agent，接任意 OpenAI 兼容 API）
#
# 用法：
#   QQ_NUMBER=501962981 API_KEY=sk-xxx bash deploy-qqbot.sh
#   MODEL=deepseek-chat 可选，留空则自动从 /v1/models 里挑
#   UPDATE=1 重装 qq-agent 代码（保留 data/ 配置与存档）
#   FORCE_CONFIG=1 覆盖已存在的 config.json（会丢控制台里改过的设置）
#
# 幂等：重复执行只补缺失的部分，不会重复下载/装机。
# ============================================================================
set -euo pipefail

QQ_NUMBER="${QQ_NUMBER:?必须给 QQ_NUMBER，例如 QQ_NUMBER=501962981}"
API_KEY="${API_KEY:-}"
API_BASE_URL="${API_BASE_URL:-https://api.deepseek.com/v1}"
MODEL="${MODEL:-}"
GH_PROXY="${GH_PROXY:-https://ghfast.top/}"          # GitHub 加速前缀；国内服务器直连 github 常被重置
NODE_MIRROR="${NODE_MIRROR:-https://registry.npmmirror.com/-/binary/node}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
AGENT_DIR="${AGENT_DIR:-/opt/qq-agent}"
UPDATE="${UPDATE:-0}"
FORCE_CONFIG="${FORCE_CONFIG:-0}"

HOME_DIR="${HOME:-/root}"
NAPCAT_BASE="$HOME_DIR/Napcat"
NAPCAT_DIR="$NAPCAT_BASE/opt/QQ/resources/app/app_launcher/napcat"
QQ_EXE="$NAPCAT_BASE/opt/QQ/qq"
PY="$(command -v python3 || true)"

log()  { printf '\n\033[36m[%s]\033[0m %s\n' "$(date +%H:%M:%S)" "$*"; }
ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

# 带代理回退的下载：先直连，失败再套 GitHub 加速前缀
fetch() {
  local url="$1" out="$2"
  if curl -fsSL --max-time 60 -o "$out" "$url"; then return 0; fi
  warn "直连失败，改用加速前缀重试：$url"
  curl -fsSL --max-time 120 -o "$out" "${GH_PROXY}${url}"
}

# ---------------------------------------------------------------- 0. 预检
log "0/8 预检"
[ "$(id -u)" -eq 0 ] || die "请用 root 执行（sudo -i 后重跑）"
arch="$(uname -m)"
case "$arch" in
  x86_64)  NODE_ARCH=x64 ;;
  aarch64|arm64) NODE_ARCH=arm64 ;;
  *) die "不支持的架构：$arch" ;;
esac
ok "架构 $arch → node-$NODE_ARCH"
awk -F: '/^PRETTY_NAME/{print "  系统: "$2}' /etc/os-release 2>/dev/null || true
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo)
ok "内存 $((mem_kb/1024)) MB"
[ "$(df -Pm / | awk 'NR==2{print $4}')" -gt 3000 ] || die "根分区可用空间不足 3GB"

# ---------------------------------------------------------------- 1. 交换分区（小内存机器保命）
log "1/8 内存与基础环境"
if [ "$mem_kb" -lt 1900000 ] && ! swapon --show 2>/dev/null | grep -q .; then
  warn "内存 < 2G，创建 2G swap（LinuxQQ 是 Electron，容易 OOM）"
  fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "swap 2G 已启用"
else
  ok "swap 已就绪或内存充足，跳过"
fi
ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
echo "Asia/Shanghai" > /etc/timezone 2>/dev/null || true
ok "时区 Asia/Shanghai（agent 里所有时间按北京时间）"

# ---------------------------------------------------------------- 2. NapCat（LinuxQQ + OneBot）
log "2/8 NapCat 协议端"
if [ -x "$QQ_EXE" ] && [ -d "$NAPCAT_DIR" ]; then
  ok "已安装：$NAPCAT_DIR，跳过（要重装：FORCE=1 手动跑官方 installer）"
else
  log "调用官方 installer（--docker n 即 Shell 安装，自带 xvfb/GTK 依赖）"
  cd "$HOME_DIR"
  fetch "https://raw.githubusercontent.com/NapNeko/NapCat-Installer/main/script/install.sh" "$HOME_DIR/napcat.sh" \
    || die "拿不到 NapCat installer（换 GH_PROXY 再试）"
  bash "$HOME_DIR/napcat.sh" --docker n --cli n --proxy 0 --github-proxy "$GH_PROXY" \
    2>&1 | tail -40 || die "NapCat 安装失败，看上面的报错"
  [ -x "$QQ_EXE" ] || die "安装结束但找不到 $QQ_EXE"
  ok "NapCat 安装完成"
fi

# ---------------------------------------------------------------- 3. NapCat 配置
log "3/8 NapCat 配置（WebUI 只监听本机 + OneBot 端口与 QAgent 对齐）"
mkdir -p "$NAPCAT_DIR/config" "$NAPCAT_DIR/cache"
WEBUI_CFG="$NAPCAT_DIR/config/webui.json"
WEBUI_TOKEN=""
if [ -f "$WEBUI_CFG" ]; then
  WEBUI_TOKEN=$("$PY" -c "import json;print(json.load(open('$WEBUI_CFG')).get('token',''))" 2>/dev/null || true)
fi
[ -n "$WEBUI_TOKEN" ] || WEBUI_TOKEN=$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')
# host 固定 127.0.0.1：6099 绝不对公网暴露（远程用 SSH 隧道）
cat > "$WEBUI_CFG" <<JSON
{
  "host": "127.0.0.1",
  "port": 6099,
  "token": "${WEBUI_TOKEN}",
  "loginRate": 3,
  "autoLoginAccount": ""
}
JSON
chmod 600 "$WEBUI_CFG"
ok "WebUI 127.0.0.1:6099（token 已写入 webui.json）"

# OneBot 网络默认就是 127.0.0.1:3000(HTTP) / 127.0.0.1:3001(WS)，与 QAgent 默认值一致。
# 首次登录后 NapCat 会自动建 onebot11_<QQ>.json；这里预写一份兜底，避免个别版本不自动建。
for fn in "onebot11_${QQ_NUMBER}.json" "onebot_${QQ_NUMBER}.json"; do
  [ -f "$NAPCAT_DIR/config/$fn" ] || cat > "$NAPCAT_DIR/config/$fn" <<'JSON'
{
  "network": {
    "httpServers": [
      { "enable": true, "name": "HTTP", "host": "127.0.0.1", "port": 3000,
        "enableCors": true, "enableWebsocket": false, "messagePostFormat": "array",
        "token": "", "debug": false }
    ],
    "httpSseServers": [],
    "httpClients": [],
    "websocketServers": [
      { "enable": true, "name": "WebSocket", "host": "127.0.0.1", "port": 3001,
        "reportSelfMessage": false, "enableForcePushEvent": true, "messagePostFormat": "array",
        "token": "", "debug": false, "heartInterval": 30000 }
    ],
    "websocketClients": [],
    "plugins": []
  },
  "musicSignUrl": "",
  "enableLocalFile2Url": false,
  "parseMultMsg": false,
  "imageDownloadProxy": ""
}
JSON
done
ok "OneBot 预置：HTTP 127.0.0.1:3000 / WS 127.0.0.1:3001"

# systemd：napcat（xvfb 无头跑 LinuxQQ）
cat > /etc/systemd/system/napcat.service <<UNIT
[Unit]
Description=NapCat (LinuxQQ + OneBot v11)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=HOME=${HOME_DIR}
Environment=TZ=Asia/Shanghai
WorkingDirectory=${NAPCAT_BASE}/opt/QQ
ExecStart=/usr/bin/xvfb-run -a ${QQ_EXE} --no-sandbox -q ${QQ_NUMBER}
Restart=always
RestartSec=8
LimitNOFILE=65535
StandardOutput=append:/var/log/napcat.log
StandardError=append:/var/log/napcat.log

[Install]
WantedBy=multi-user.target
UNIT
ok "napcat.service 已写入"

# ---------------------------------------------------------------- 4. Node.js
log "4/8 Node.js（QAgent 要求 >= 20）"
node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "${node_major:-0}" -ge 20 ]; then
  ok "已有 node $(node -v)，跳过"
else
  cd /tmp
  got=0
  for v in v22.14.0 v22.13.0 v22.12.0 v20.18.1; do
    url="$NODE_MIRROR/$v/node-$v-linux-$NODE_ARCH.tar.xz"
    if curl -fsSL --max-time 300 -o node.tar.xz "$url"; then got=1; ok "下载 $v"; break; fi
    warn "没有 $v，换下一个"
  done
  [ "$got" = 1 ] || die "Node 二进制下载全失败（换 NODE_MIRROR）"
  rm -rf /usr/local/lib/node-standalone
  tar -xJf node.tar.xz -C /usr/local --strip-components=1
  hash -r
  node -v >/dev/null || die "node 解压后仍不可用"
  ok "node $(node -v) / npm $(npm -v)"
fi

# ---------------------------------------------------------------- 5. qq-agent
log "5/8 qq-agent 本体"
mkdir -p "$AGENT_DIR"
if [ -f "$AGENT_DIR/src/server.js" ] && [ "$UPDATE" != 1 ]; then
  ok "代码已存在，跳过下载（要更新：UPDATE=1）"
else
  [ -f "$AGENT_DIR/src/server.js" ] && cp -a "$AGENT_DIR/data" /tmp/qqagent-data-backup 2>/dev/null || true
  rm -rf /tmp/qqagent-src && mkdir -p /tmp/qqagent-src
  fetch "https://github.com/lyyde599/qq-agent/archive/refs/heads/main.tar.gz" /tmp/qq-agent.tar.gz \
    || die "下载 qq-agent 失败"
  tar xzf /tmp/qq-agent.tar.gz -C /tmp/qqagent-src --strip-components=1
  rm -rf "$AGENT_DIR/src" "$AGENT_DIR/ui" "$AGENT_DIR/electron" "$AGENT_DIR/scripts" "$AGENT_DIR/test" "$AGENT_DIR/assets"
  cp -a /tmp/qqagent-src/. "$AGENT_DIR/"
  [ -d /tmp/qqagent-data-backup ] && cp -a /tmp/qqagent-data-backup/. "$AGENT_DIR/data/" || true
  ok "代码已就位：$AGENT_DIR"
fi
log "安装依赖（js-yaml / qrcode / undici / ws，纯 JS 无需编译）"
cd "$AGENT_DIR"
if [ -f package-lock.json ]; then
  npm ci --omit=dev --no-audit --no-fund --registry="$NPM_REGISTRY" 2>&1 | tail -5 \
    || npm install --omit=dev --no-audit --no-fund --registry="$NPM_REGISTRY" 2>&1 | tail -5
else
  npm install --omit=dev --no-audit --no-fund --registry="$NPM_REGISTRY" 2>&1 | tail -5
fi
[ -d node_modules/ws ] || die "依赖安装失败（node_modules/ws 不存在）"
ok "依赖就绪"

# ---------------------------------------------------------------- 6. QAgent 配置
log "6/8 QAgent 配置（API / 白名单 / 人设）"
mkdir -p "$AGENT_DIR/data"
CFG="$AGENT_DIR/data/config.json"
if [ -f "$CFG" ] && [ "$FORCE_CONFIG" != 1 ]; then
  ok "config.json 已存在，保留（要重建：FORCE_CONFIG=1）"
  warn "若换了 API Key，请去控制台设置页改，或 FORCE_CONFIG=1 重跑"
else
  [ -n "$API_KEY" ] || die "缺少 API_KEY（DeepSeek 官方 key）"
  # 挑模型：优先 deepseek-flash（能看图、便宜），其次 deepseek-chat，再退第一个
  if [ -z "$MODEL" ]; then
    ids=$(curl -fsS --max-time 25 -H "Authorization: Bearer $API_KEY" "$API_BASE_URL/models" 2>/dev/null \
          | grep -o '"id"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/') || true
    for pref in deepseek-flash deepseek-chat deepseek-v4-flash; do
      if echo "$ids" | grep -qx "$pref"; then MODEL="$pref"; break; fi
    done
    [ -n "${MODEL:-}" ] || MODEL=$(echo "$ids" | head -1)
    [ -n "${MODEL:-}" ] || MODEL=deepseek-flash
    [ -n "$ids" ] && ok "可用模型：$(echo "$ids" | tr '\n' ' ')"
  fi
  ok "模型 $MODEL @ $API_BASE_URL"
  "$PY" - "$CFG" "$API_BASE_URL" "$API_KEY" "$MODEL" "$NAPCAT_DIR" "$QQ_NUMBER" <<'PY'
import json, sys
cfg_path, base, key, model, napcat_dir, qq = sys.argv[1:7]
cfg = {
  "api": {
    "baseUrl": base, "apiKey": key, "model": model, "provider": "deepseek",
    "vision": True, "temperature": 0.8, "maxRounds": 12, "timeoutMs": 180000,
    "priceInputPerM": 0, "priceOutputPerM": 0
  },
  # 协议端：直接复用 snowluma 段（QAgent 把它当 OneBot 端点用）
  "snowluma": {
    "dir": napcat_dir, "autoLaunch": False,
    "wsUrl": "ws://127.0.0.1:3001", "httpUrl": "http://127.0.0.1:3000",
    "accessToken": "", "httpAccessToken": ""
  },
  # fail-closed：只放行你自己的私聊；群聊等你在控制台「选择群」里勾
  "allow": {"groups": [], "private": [qq]},
  "deny": {"groups": [], "private": []},
  "allowAllWhenEmpty": False,
  "groupMentionProbability": 0.05,
  "persona": {"botName": "小鲸鱼", "selfNickname": "", "participation": "medium"},
  "server": {"port": 3210, "token": "", "autoStart": False, "closeToTray": True},
  "budget": {"dailyCostYuan": 0}
}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print("  ✓ 已写 config.json")
PY
  ok "白名单：私聊 $QQ_NUMBER；群聊待控制台勾选"
fi

# systemd：qq-agent（无头 + 指向容器外的 NapCat 目录）
cat > /etc/systemd/system/qqbot.service <<UNIT
[Unit]
Description=QQ Agent (大肥鱼大脑 + 控制台 :3210)
After=network-online.target napcat.service
Wants=napcat.service

[Service]
Type=simple
User=root
Environment=HOME=${HOME_DIR}
Environment=TZ=Asia/Shanghai
Environment=NAPCAT_DIR=${NAPCAT_DIR}
Environment=NAPCAT_QR_PATH=${NAPCAT_DIR}/cache/qrcode.png
WorkingDirectory=${AGENT_DIR}
ExecStart=$(command -v node) ${AGENT_DIR}/src/server.js
Restart=always
RestartSec=6

[Install]
WantedBy=multi-user.target
UNIT
ok "qqbot.service 已写入"

# ---------------------------------------------------------------- 7. 启动
log "7/8 启动两个服务"
systemctl daemon-reload
systemctl enable --now napcat.service
sleep 3
systemctl enable --now qqbot.service
sleep 5
systemctl is-active --quiet napcat.service && ok "napcat 运行中" || warn "napcat 没起来：journalctl -u napcat -n 50"
systemctl is-active --quiet qqbot.service && ok "qqbot 运行中" || warn "qqbot 没起来：journalctl -u qqbot -n 50"

# ---------------------------------------------------------------- 8. 自检
log "8/8 自检"
ss -lntp 2>/dev/null | grep -E ':(3000|3001|3210|6099)\b' | sed 's/^/  /' || warn "端口没全起来"
echo
curl -fsS --max-time 8 http://127.0.0.1:3210/api/status >/dev/null 2>&1 \
  && ok "控制台 3210 有响应" || warn "控制台无响应，看 journalctl -u qqbot -n 60"
curl -fsS --max-time 8 http://127.0.0.1:3000/get_login_info >/dev/null 2>&1 \
  && ok "OneBot HTTP 3000 已登录" \
  || warn "OneBot 未就绪 / QQ 还未登录（下一步扫码，这是预期的）"
if [ -s "$NAPCAT_DIR/cache/qrcode.png" ]; then
  ok "登录二维码已生成：$NAPCAT_DIR/cache/qrcode.png"
else
  warn "还没有 qrcode.png（等 10~30 秒；或看 journalctl -u napcat -n 80）"
fi

cat <<EOF

============================ 部署完成 ============================
 QQ 号        : $QQ_NUMBER
 NapCat       : $NAPCAT_DIR  (WebUI 127.0.0.1:6099)
 QAgent       : $AGENT_DIR   (控制台 127.0.0.1:3210)
 模型         : ${MODEL:-未设置} @ $API_BASE_URL
 日志         : journalctl -u napcat -f   /   journalctl -u qqbot -f

 下一步（在你自己电脑上开隧道，然后浏览器打开 http://127.0.0.1:3210）：
   ssh -N -L 3210:127.0.0.1:3210 -L 6099:127.0.0.1:6099 root@<服务器IP>
 控制台左侧「设置」→ 顶部体检卡 → 点二维码用手机 QQ 扫码登录
 登录后在「设置 → 白名单」里把目标群勾上，再去「存档」页发一条测试消息
==================================================================
EOF
