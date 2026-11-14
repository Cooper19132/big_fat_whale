# 上游谱系与自持说明（UPSTREAM）

> 一句话：**本仓库是唯一维护源。** 上游 qq-bridge 已公告停止维护、预计 2026-11-18 归档；
> 我们不等它消失，代码、运行时、原生依赖、梗库四类东西都已经在本地/本仓库留了完整副本。

## 1. 谱系

| 层 | 来源 | 现状（2026-11-15 核实） |
| --- | --- | --- |
| 本应用 | 本项目 `big_fat_whale` = `qq-agent` 源码 | 自持，日常开发与部署都在这里 |
| 派生自 | [Derpyu520/qq-bridge](https://github.com/Derpyu520/qq-bridge)（MIT，3671 star） | 已 announce **停止维护**，README 顶部挂 sunset 公告，**预计 2026-11-18 归档**（当前仍可读，HEAD `781e02f2`） |
| QQ 侧运行时 | [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ)（12.8k star） | 2026-11-12 提交 `docs: ending` → 2026-11-15 核实**代码已被抹掉**（`size=1 KB`、只剩一个 `README.md` 48 字节）；源码快照改从活跃 fork `dgcrxs/NapCatQQ` 取 |
| QQ 客户端 | 腾讯 QQ `3.2.34-53644` | 闭源，本地整包已备（276MB zst） |
| 协议 | OneBot v11（公开协议，非某家专有） | 与实现解耦，换实现只需改 adapter |

许可证保留：`qq-agent/LICENSE` = MIT，Copyright (c) 2026 白光 (liuyuyu599com-svg)。
本项目在该许可下继续分发，改动部分同样 MIT。

## 2. 我们依赖什么、不依赖什么

- **不依赖**上游任何远程物：`qq-agent/package.json` 的 5 个依赖全部来自 npm 公共注册表，没有 `git+` / tarball / 私有源依赖；
  `package-lock.json` 在库里，`node_modules` 有离线包。
- **运行时不联网回上游**：代码里对 qq-bridge 的引用只出现在注释和 README 的谱系说明中
  （`src/dsh-task.js:5`、`src/md-to-plain.js:1`、`src/personas.js:1`、`src/prompt.js:10`），无运行时拉取。
- **只依赖两件不自持的东西**：QQ 客户端本体（闭源，只能冻结版本）、npm 公共注册表（有离线 node_modules 兜底）。

## 3. 备件清单（四类，都在手）

| 物件 | 位置（本地） | 位置（服务器） | 校验 |
| --- | --- | --- | --- |
| qq-agent 源码 | 本仓库 | `/opt/qq-agent`（部署副本） | git sha |
| 源码快照 | — | `/home/admin/backups/qq-agent-YYYY-MM-DD.tar.gz`（每日 04:30，留 30 天） | 926K~1.2M |
| node_modules | `vendor/qq-agent-node_modules-2026-11-12.tar.gz` | 同 | 1.1M |
| NapCat 运行时 | `vendor/napcat-runtime-2026-11-12.tar.gz` | 同 | 34M |
| QQ 整包 | `vendor/qq-3.2.34-53644-2026-11-12.tar.zst` | 同 | 276M |
| **上游 qq-bridge 镜像** | `vendor/qq-bridge-mirror-2026-11-15.tar.zst` | `/home/admin/backups/upstream/` | 18M，sha256 `9949bb779d10341ed87de0e1f4513daf4b14c60b878f336e3a0b6cbb05b2edbd` |
| **NapCat 源码快照** | `vendor/NapCatQQ-src-2026-11-15.tar.gz` | `/home/admin/backups/upstream/` | 89M，sha256 `604d1731b3c92092814473c099ce2c655f1d086d9257b34eee6077840d16c968`，1312 条目，取自 fork `dgcrxs/NapCatQQ` main |
| 梗库 | `memes.json`（7.8M，6668 条） | `/opt/qq-agent/data/memes.json` | — |

镜像同时作为 GitHub release 资产留了一份：tag `upstream-mirror-2026-11-15`（release id 445417467，17,862,542 B）。
`vendor/*.tar.gz`、`vendor/*.tar.zst` 不进 git（见 `.gitignore`），只有 `vendor/README.md` 与 manifest 进库。

## 4. 上游归零后怎么重建

```bash
# 1) 代码
git clone <本仓库> qq-agent && cd qq-agent
# 2) 依赖（离线，不走 npm）
tar xzf vendor/qq-agent-node_modules-2026-11-12.tar.gz -C .
# 3) 梗库
cp memes.json data/memes.json
# 4) QQ + NapCat（服务器）
sudo tar xzf vendor/napcat-runtime-2026-11-12.tar.gz -C /root/Napcat/opt/QQ/resources/app/app_launcher/
sudo bash vendor/unzst.py vendor/qq-3.2.34-53644-2026-11-12.tar.zst | sudo tar xf - -C /root/Napcat/opt/
chmod 755 /root/Napcat/opt/QQ/qq
# 5) 校验（必须与基线一致，否则说明包被换过）
sha256sum /root/Napcat/opt/QQ/qq          # ae674327…299ec2
sha256sum /root/Napcat/opt/QQ/resources/app/app_launcher/napcat/napcat.mjs   # f80e4be3…8179e6
```

## 5. 换掉 NapCat 也没关系

`qq-agent` 走标准 OneBot v11：`send_private_msg / send_group_msg / get_msg / get_forward_msg / get_group_list /
get_group_info / get_group_member_info / get_friend_list / get_login_info / upload_*_file`；
非标只有 `friend_poke / group_poke / send_poke`（都有 `.catch()` 降级）与 `get_file`。
钩子点只有一处：`qq-agent/src/onebot.js` 的 `OneBotClient.call(action, params)`。
换 Lagrange.OneBot / Bncr 之类，改 `wsUrl` / `httpUrl` / 令牌即可，`tools/compat-test.mjs` + `tools/mock-onebot.mjs` 可以离线先验证一遍（11/11 通过）。

## 6. 漂移监控

服务器 cron 每日 05:00 跑 `/home/admin/scripts/selfhost-check.sh`：比对 QQ / napcat.mjs 的 sha256、三服务状态、
3000/3001/6099 端口、备份新鲜度、磁盘；发现漂移走 `/home/admin/scripts/notify.sh` 告警（Webhook → TG → SMTP → GitHub issue）。
