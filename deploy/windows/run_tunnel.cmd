@echo off
rem Lolypoly 고정 주소 터널 실행 (작업 스케줄러 Lolypoly-Tunnel 이 부팅 시 호출, 끊기면 cloudflared 가 스스로 재연결)
rem 인증: wrangler login(OAuth, 자동 갱신)으로 Cloudflare 에서 터널 실행 키를 받아 cloudflared 에 넘긴다. 키는 화면·파일에 남기지 않는다.
rem 터널 ID 는 비밀이 아니다(실행에는 계정 인증이 필요).
set PATH=D:\lolypoly\tools\node;D:\lolypoly\tools\cloudflared;%PATH%
cd /d D:\lolypoly\app\deploy\cloudflare-worker
echo %date% %time% tunnel start >> D:\lolypoly\logs\tunnel.log
node node_modules\wrangler\bin\wrangler.js tunnel run 6c3bcc42-e0a2-437b-9711-6be4d960efeb --log-level info >> D:\lolypoly\logs\tunnel.log 2>&1
