# vendor/ — 自持运维的离线备件

上游（NapCat、QQ 客户端）随时可能转私有或断更，所以关键运行时在这里留一份可用副本。
**tarball 不进 git**（见 .gitignore），只有清单和说明进仓库；二进制在下面两个位置各存一份：

```
PC       D:\dshworks\qqbot\vendor\
服务器   /home/admin/backups\
```

## 现在有什么

| 文件 | 大小 | 内容 | 来源 |
|---|---|---|---|
| `napcat-runtime-2026-11-12.tar.gz` | 34M | NapCat 运行时整目录（`native/` 100M 压缩后主要部分、`static/`、`node_modules/`、`napcat.mjs`、`loadNapCat.js`、`config/`），已排除 `cache/` `logs/` | `/root/Napcat/opt/QQ/resources/app/app_launcher/napcat` |
| `qq-agent-node_modules-2026-11-12.tar.gz` | 1.1M | qq-agent 的 node_modules + package-lock.json（4 个依赖：js-yaml qrcode undici ws，全是公开 npm 包） | `/opt/qq-agent` |
| `manifest-2026-11-12.txt` | — | 版本与校验和基准：QQ 二进制 sha256、napcat.mjs sha256、loadNapCat.js sha256、依赖表、node/python/chrome/ffmpeg 版本 | 生成脚本自动写 |

## 版本基线（2026-11-12）

```
QQ 客户端      3.2.34-53644   二进制 204,344,328 B  mtime 2026-09-22
               sha256 ae67432744180adc2b6567aa61b9575b14b28745f57b377a2853a1b744299ec2
NapCat         4.18.38（取自 napcat.mjs 内嵌版本串）
               napcat.mjs  sha256 f80e4be3e8640369d23846cf3e8bcfd2a5b6dc5920f50d7ad733d7cca18179e6
               loadNapCat.js sha256 3d272756b14175c1e603261da6d8180e69f3435cbbd73baaf0542ea52f12330f
OneBot         127.0.0.1:3000 HTTP / 3001 WS / 6099 WebUI   均 token 为空、仅本机
系统           Ubuntu 22.04, Node v22.14.0, Python 3.10.12, Chrome 156.0.8078.73, ffmpeg 4.4.2
```

## 没在这儿的（有意）

- **QQ 主体 482M + 195M**：太大，只记 sha256。真要重装，去 QQ 官网下 **必须同版本** 的 linux deb/tar，版本对不上注入就崩。
- **`/opt/qq-agent` 源码**：在 git（`Cooper19132/big_fat_whale`），不用备。
- **`data/` 运行态**：每日 tar 备份（`/home/admin/backups/qq-agent-*.tar.gz`，926K，留 30 天）。

## 恢复流程（服务器重建时）

```bash
# 1. QQ 装回 3.2.34-53644，确认 /root/Napcat/opt/QQ/qq 的 sha256 与清单一致
sha256sum /root/Napcat/opt/QQ/qq

# 2. 解 NapCat 运行时（覆盖到同一路径）
sudo tar xzf napcat-runtime-YYYY-MM-DD.tar.gz -C /root/Napcat/opt/QQ/resources/app/app_launcher/

# 3. 校验注入入口没被换过
sudo sha256sum /root/Napcat/opt/QQ/resources/app/app_launcher/napcat/napcat.mjs

# 4. 起服务
sudo systemctl restart napcat && sleep 5 && ss -ltn | grep -E ':3000|:3001|:6099'

# 5. qq-agent 依赖（离线）
tar xzf qq-agent-node_modules-YYYY-MM-DD.tar.gz -C /opt/qq-agent/
sudo systemctl restart qqbot

# 6. 跑漂移检查，三项全绿才算恢复
bash /home/admin/scripts/selfhost-check.sh
```

## 定期任务（服务器 cron）

```
0 5 * * 1     selfhost-check.sh    # 每周一：比对 QQ/NapCat sha256，变了就私聊告警主人
10 5 1 * *    selfhost-backup.sh   # 每月 1 号：重新打 NapCat 运行时 + 依赖 + 清单
30 4 * * *    qq-agent tar 备份    # 每天：源码 + data 状态
```

日志 `/var/log/qqbot-selfhost.log`。

## 换掉 NapCat 的成本（重要）

qq-agent 只用标准 OneBot v11 的这十几个 action：

```
send_private_msg  send_group_msg  send_msg  get_msg  get_forward_msg
get_group_info  get_group_list  get_group_member_info  get_friend_list  get_login_info
upload_group_file  upload_private_file
```

非标准的只有 **poke 三件套**（`friend_poke` / `group_poke` / `send_poke`）和文件下载（`get_file`）。也就是说
换成 Lagrange.OneBot 或别的 OneBot v11 实现，改动面 ≈ 一个 adapter 文件，不用重写机器人。
