@echo off
rem Lolypoly fixed-URL tunnel (Task Scheduler "Lolypoly-Tunnel" runs this at boot; cloudflared reconnects by itself).
rem Auth: wrangler login (OAuth, auto-refresh) fetches the tunnel run token and hands it to cloudflared. Not written to disk.
rem See docs/OPERATIONS.md section 12. ASCII only: cmd.exe reads this file in the system code page.
rem Stopping the task only ends cmd.exe; cloudflared survives and keeps the log open. Clean up stale connectors first.
set PATH=D:\lolypoly\tools\node;D:\lolypoly\tools\cloudflared;%PATH%
set LOG=D:\lolypoly\logs\tunnel-run.log
taskkill /F /IM cloudflared.exe >nul 2>&1
ping -n 4 127.0.0.1 >nul
for %%F in ("%LOG%") do if %%~zF GTR 5000000 move /y "%LOG%" "%LOG%.old" >nul 2>&1
cd /d D:\lolypoly\app\deploy\cloudflare-worker
echo %date% %time% tunnel start >> "%LOG%"
node node_modules\wrangler\bin\wrangler.js tunnel run 5d947b5d-b17f-475d-a700-6fc0a2706f53 --log-level info >> "%LOG%" 2>&1
