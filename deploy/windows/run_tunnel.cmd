@echo off
rem Lolypoly fixed-URL tunnel (Task Scheduler "Lolypoly-Tunnel" runs this at boot; cloudflared reconnects by itself).
rem Auth: wrangler login (OAuth, auto-refresh) fetches the tunnel run token and hands it to cloudflared. Not written to disk.
rem See docs/OPERATIONS.md section 12. ASCII only: cmd.exe reads this file in the system code page.
set PATH=D:\lolypoly\tools\node;D:\lolypoly\tools\cloudflared;%PATH%
cd /d D:\lolypoly\app\deploy\cloudflare-worker
echo %date% %time% tunnel start >> D:\lolypoly\logs\tunnel-run.log
node node_modules\wrangler\bin\wrangler.js tunnel run 5d947b5d-b17f-475d-a700-6fc0a2706f53 --log-level info >> D:\lolypoly\logs\tunnel-run.log 2>&1
