@echo off
chcp 65001 >nul
title 小鲸鱼 ↔ DSH 隧道（关掉 = 机器人无法调 DSH）
echo.
echo   把本机 DSH(4598) 反向映射到阿里云服务器的 127.0.0.1:4598
echo   保持本窗口开着；关掉后 QQ 里让机器人调 DSH 都会失败。
echo   前提：本机 DSH 正在运行（端口 4598）。
echo.
start "" /min ssh -i "%~dp0ssh\id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=%~dp0ssh\known_hosts -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -N -R 4598:127.0.0.1:4598 admin@116.62.149.191
echo   隧道已在后台建立。验证方法（服务器上）：
echo     curl -s -o /dev/null -w "%%{http_code}" http://127.0.0.1:4598/
echo   返回 401 = 通了（未带凭据）；000 = 没通。
echo.
pause
