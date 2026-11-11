@echo off
chcp 65001 >nul
echo ===== %date% %time% ===== >> "D:\dshworks\qqbot\sync-world-view.log"
"C:\Users\cooper\.dsh\bili-duty\.venv\Scripts\python.exe" "D:\dshworks\qqbot\sync-world-view.py" >> "D:\dshworks\qqbot\sync-world-view.log" 2>&1
echo [exit %errorlevel%] >> "D:\dshworks\qqbot\sync-world-view.log"
