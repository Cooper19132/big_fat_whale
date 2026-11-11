@echo off
chcp 65001 >nul
title 大肥鱼控制台隧道（关掉这个窗口 = 断开控制台）
echo.
echo   正在建立到 116.62.149.191 的 SSH 隧道...
echo   保持本窗口开着；关掉就断开了。
echo.
start "" /min ssh -i "%~dp0ssh\id_ed25519" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=%~dp0ssh\known_hosts -o ServerAliveInterval=30 -N -L 3210:127.0.0.1:3210 -L 6099:127.0.0.1:6099 admin@116.62.149.191
timeout /t 4 >nul
start "" http://127.0.0.1:3210
echo   控制台: http://127.0.0.1:3210
echo   NapCat : http://127.0.0.1:6099/webui
echo.
pause
