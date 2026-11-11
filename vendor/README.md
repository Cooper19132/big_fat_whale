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
| `qq-3.2.34-53644-2026-11-12.tar.zst` | 275M | **整个 QQ 客户端（726M 解压后）**，含 `QQ/qq` 主程序、`resources/app/`（Electron 壳 + 已注入的 napcat 目录）、全部 `.so`。**为了版本断了还能重装** | `/root/Napcat/opt/QQ`（zstd -3，2396 条目，20 秒打完，sha256 `5943d594…a2aa0f`） |
| `napcat-runtime-2026-11-12.tar.gz` | 34M | NapCat 运行时整目录（`native/` 100M 压缩后主要部分、`static/`、`node_modules/`、`napcat.mjs`、`loadNapCat.js`、`config/`），已排除 `cache/` `logs/` | `/root/Napcat/opt/QQ/resources/app/app_launcher/napcat` |
| `qq-agent-node_modules-2026-11-12.tar.gz` | 1.1M | qq-agent 的 node_modules + package-lock.json（4 个依赖：js-yaml qrcode undici ws，全是公开 npm 包） | `/opt/qq-agent` |
| `manifest-2026-11-12.txt` | — | 版本与校验和基准：QQ 二进制 sha256、napcat.mjs sha256、loadNapCat.js sha256、依赖表、node/python/chrome/ffmpeg 版本 | 生成脚本自动写 |
| `unzst.py` | — | **Windows 没装 zstd CLI 时用它拆包**：`python vendor/unzst.py vendor/qq-….tar.zst` → 同目录出 `.tar`，再用任意解压工具开。实测前 160MB 解码正常（1483 条目可读，尾部截断告警 2 行是预期） | 本机 zstandard 0.25.0 |

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

- **`/opt/qq-agent` 源码**：在 git（`Cooper19132/big_fat_whale`），不用备。
- **`data/` 运行态**：每日 tar 备份（`/home/admin/backups/qq-agent-*.tar.gz`，926K，留 30 天）。
- **QQ 的账号登录态**：在 `QQ/napcat/config` 之外的 `QQ/data` 里是有 db 的，已在 QQ 整包内；但**登录态过期要重新扫码**，这个备份救不回来。

## 恢复流程（服务器重建时）

```bash
# 1. QQ 整包还原（不用去官网找老版本了）
sudo rm -rf /root/Napcat/opt/QQ.bak && sudo mv /root/Napcat/opt/QQ /root/Napcat/opt/QQ.bak
sudo mkdir -p /root/Napcat/opt && sudo tar --use-compress-program="zstd -d" -xf qq-3.2.34-53644-YYYY-MM-DD.tar.zst -C /root/Napcat/opt
sudo chmod 755 /root/Napcat/opt/QQ/qq
# 校验必须是这一版
sha256sum /root/Napcat/opt/QQ/qq   # 期望 ae67432744180adc2b6567aa61b9575b14b28745f57b377a2853a1b744299ec2

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
