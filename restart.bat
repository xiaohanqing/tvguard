@echo off
cd /d D:\codings\tvguard

echo ==^> Stopping running TVGuard (port 8787 only)...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8787 ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
ping -n 2 127.0.0.1 >nul

echo ==^> Starting TVGuard...
start "TVGuard" /min python run.py

ping -n 4 127.0.0.1 >nul
curl -s -m 3 http://127.0.0.1:8787/api/status >nul 2>&1
if %errorlevel%==0 (
    echo ==^> OK: panel at http://127.0.0.1:8787
) else (
    echo ==^> WARN: service not responding, check TVGuard window
)
