# Lolypoly 운영 가이드 (학교 PC 1대 · 시범 운영)

작성 2026-11-04. 이 문서의 절차는 **파일 작성과 문법·로컬 검증까지** 했고, 학교 PC에서 실제로 실행한 기록은 `docs/PROGRESS.md`의 "상태표"를 본다. 없는 것을 한 것처럼 쓰지 않는다.

## 1. 구조 (누가 무엇을 맡나)

| 역할 | 위치 | 비고 |
|---|---|---|
| Django 웹앱(Gunicorn) | 학교 PC, `lolypoly-web.service` (127.0.0.1:8000) | 부팅 후 자동 실행, 죽으면 3초 뒤 재시작 |
| Nginx | 학교 PC, `deploy/nginx/lolypoly.conf` | 80포트, 속도 제한, 접속자 주소 전달 |
| 수집기(Playwright) | 같은 PC, systemd timer | 학생 요청과 분리. 한 번에 하나만(flock) |
| 외부 공개 | Cloudflare Tunnel(학교 허용 시) 또는 직접 공개 | 터널은 통로일 뿐, Django는 학교 PC에서 실행 |
| 공개 정보 DB(식단·일정·공지) + 의견 | SQLite `DJANGO_SQLITE_PATH` (코드 폴더 밖) | 이번 시범 기본값 |
| 회원 DB | Supabase Postgres (D-038) | **미구현·대기**: 회원 기능 자체가 아직 없음 |

DB별 저장 위치 표

| 데이터 | 지금(시범) | 계획(D-038) |
|---|---|---|
| 식단·학사일정·공지·수집 기록 | SQLite (영구 경로) | 그대로 SQLite |
| 학생 의견(`campus_feedback`) | SQLite (영구 경로) | Supabase 이전은 별도 결정 |
| 회원·세션 | 없음(미구현) | Supabase Postgres |

## 2. 설치 순서 (Ubuntu 24.04, 관리자 권한)

실행 전 확인: 관리 권한·상시 전원·유선망·절전 끔. **모르는 항목은 미확인으로 적는다.**

```bash
# 1) 실행 사용자와 폴더
sudo adduser --system --group --home /srv/lolypoly lolypoly
sudo -u lolypoly git clone https://github.com/chanmini584-ux/LOLYPOLY /srv/lolypoly/app
cd /srv/lolypoly/app && sudo -u lolypoly git checkout claude/quirky-euler-j7dwrg   # 검토 후 main 병합 시 main
sudo timedatectl set-timezone Asia/Seoul && timedatectl   # NTP active 확인
```
```bash
# 2) 가상환경·의존성·브라우저 (기존 .env·DB는 덮어쓰지 않음)
sudo -u lolypoly python3 scripts/setup.py
sudo -u lolypoly .venv/bin/python -m playwright install --with-deps chromium   # --with-deps 는 sudo 필요할 수 있음
```
```bash
# 3) 운영 .env (비밀값은 Git에 넣지 않는다)
sudo -u lolypoly nano /srv/lolypoly/app/.env
#  DJANGO_DEBUG=False
#  DJANGO_SECRET_KEY=<긴 무작위 값>   (생성: python -c "from django.core.management.utils import get_random_secret_key as g; print(g())")
#  DJANGO_ALLOWED_HOSTS=lolypoly.com,www.lolypoly.com,localhost,127.0.0.1
#  DJANGO_CSRF_TRUSTED_ORIGINS=https://lolypoly.com,https://www.lolypoly.com
#  DJANGO_HTTPS=True
#  LOLYPOLY_TRUST_PROXY_IP=True
#  DJANGO_SQLITE_PATH=/var/lib/lolypoly/db.sqlite3
#  LOLYPOLY_INTERVAL_MEALS=1 / EVENTS=1 / NOTICES=1
sudo install -d -o lolypoly -g lolypoly -m 750 /var/lib/lolypoly
cd /srv/lolypoly/app && sudo -u lolypoly .venv/bin/python manage.py migrate
sudo -u lolypoly .venv/bin/python manage.py collectstatic --noinput
sudo -u lolypoly .venv/bin/python manage.py createsuperuser     # 의견 확인용 관리자
sudo -u lolypoly .venv/bin/python manage.py check --deploy
```
```bash
# 4) 서비스·타이머 등록 (웹앱 + 수집 3종 + 백업)
sudo ./deploy/systemd/install.sh /srv/lolypoly/app lolypoly /var/lib/lolypoly
sudo -u lolypoly .venv/bin/python manage.py collect_all        # 첫 수집(공식 사이트에 약 8페이지 요청)
# 5) Nginx
sudo apt install -y nginx
sudo cp deploy/nginx/lolypoly.conf /etc/nginx/sites-available/lolypoly
sudo ln -sf /etc/nginx/sites-available/lolypoly /etc/nginx/sites-enabled/lolypoly
sudo rm -f /etc/nginx/sites-enabled/default && sudo nginx -t && sudo systemctl reload nginx
curl -sI http://127.0.0.1/ -H 'Host: lolypoly.com' | head -3     # 로컬 확인: 200 이어야 함 (Nginx가 X-Forwarded-Proto: https 를 붙여 HTTPS 이동이 안 걸림)
```
기존 DB가 있는 PC라면 3)의 `DJANGO_SQLITE_PATH`로 **기존 파일을 복사**해 쓰고, 먼저 `backup_db`로 백업한다.

## 3. 외부 HTTPS와 lolypoly.com 연결

먼저 **학교 담당자에게** 외부 공개·터널 허용 여부를 확인한다(우회 금지). 소유·DNS 권한은 도메인 관리 페이지에서 확인한다 — **현재 미확인**.

A) Cloudflare Tunnel — **도메인 구매가 필요**(사용자 결정으로 현재 보류). (학교가 허용하고, 도메인 DNS를 Cloudflare에서 관리할 때)
1. Cloudflare 대시보드 → Zero Trust → Networks → Tunnels → 터널 생성 → 안내된 `cloudflared` 설치 명령을 학교 PC에서 실행(서비스로 등록됨).
2. Public hostname: `lolypoly.com` → Service `HTTP` `localhost:80`. (필요하면 `www`도 추가)
3. **연결 전 DNS를 기록**한다(스크린샷 또는 레코드 목록). 메일(MX/TXT) 등 관련 없는 레코드는 건드리지 않는다.
4. 확인: 학교 Wi-Fi가 아닌 **휴대폰 LTE/5G**에서 `https://lolypoly.com` 열기.
- 요금·한도는 계정 화면에서 확인(미확인). 임시 무작위 `trycloudflare.com` 주소는 QR에 쓰지 않는다.

C) **무료·도메인 없이: Tailscale Funnel** (현재 선택, D-045)
1. 학교 PC에 Tailscale 설치(Windows 앱 또는 WSL), 사용자가 무료 계정으로 로그인. 관리 콘솔(https://login.tailscale.com/admin)에서 HTTPS 인증서와 Funnel 사용을 켠다.
2. `tailscale funnel --bg 80` 류 명령으로 로컬 포트를 공개(정확한 옵션은 설치된 버전의 `tailscale funnel --help`와 공식 문서로 확인, 2026-11-04 기준 공식 문서는 Funnel을 beta로 표기).
3. 얻은 `https://<기기이름>.<tailnet>.ts.net` 이 고정 주소. 기기 이름·tailnet 이름을 바꾸면 주소가 바뀌므로 정한 뒤 바꾸지 않는다.
4. `.env`에 `DJANGO_ALLOWED_HOSTS`·`DJANGO_CSRF_TRUSTED_ORIGINS`에 위 호스트 추가. 접속자 주소가 앱에 안 전달되면 `LOLYPOLY_FEEDBACK_HOURLY_LIMIT=60`.
5. 한계(공식 문서·검색 기준, 2026-11-04): 무료 플랜에서 사용 가능, 대역폭 한도 비공개, beta, 외부에서 열 수 있는 포트는 443/8443/10000. 학교망이 Tailscale 연결을 막으면 동작하지 않음 → LTE로 실제 확인 필수.
6. 롤백: `tailscale funnel reset`(공개 해제), Tailscale 로그아웃.

B) 직접 공개(공인 IP·포트포워딩 가능할 때만): 공유기/학교 방화벽 변경은 담당자 몫. 80·443만 열고 8000은 열지 않는다. `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx -d lolypoly.com`.

**되돌리기**: DNS 변경 직전 레코드로 복원 / 터널 hostname 삭제 / `sudo systemctl stop cloudflared`. Render는 새 서버 검증 끝나기 전 삭제·중단하지 않는다.

## 4. 매일 쓰는 명령

| 하고 싶은 것 | 명령 |
|---|---|
| 상태 | `systemctl status lolypoly-web --no-pager` / `systemctl list-timers 'lolypoly-*'` |
| 재시작·중지 | `sudo systemctl restart lolypoly-web` / `sudo systemctl stop lolypoly-web` |
| 웹 로그 | `journalctl -u lolypoly-web --since today --no-pager` (요청 주소만, 입력 내용 없음) |
| 수집 결과 | `journalctl -u 'lolypoly-collect@*' --since today --no-pager`, 관리자 화면 `/admin/` → 수집 기록 |
| 지금 수집 | `sudo systemctl start lolypoly-collect@notices.service` |
| 업데이트 | `cd /srv/lolypoly/app && sudo -u lolypoly git pull && sudo -u lolypoly .venv/bin/pip install -r requirements.txt && sudo -u lolypoly .venv/bin/python manage.py migrate && sudo -u lolypoly .venv/bin/python manage.py collectstatic --noinput && sudo systemctl restart lolypoly-web` (업데이트 전 백업) |
| 의견 보기 | `/admin/` → 학생 의견 |
| 로그 크기 제한 | `sudo journalctl --vacuum-size=200M` (또는 `/etc/systemd/journald.conf`의 `SystemMaxUse=200M`) |

## 5. 백업·복원

- 자동: `lolypoly-backup.timer` 매일 03:30(서울), 최근 7개 보관, `/var/lib/lolypoly/backups/*.sqlite3.gz` (권한 600).
- 수동: `sudo -u lolypoly .venv/bin/python manage.py backup_db`
- 복원 시험(원본 안 건드림): `python manage.py backup_db --verify <백업파일>`
- 실제 복원: `sudo systemctl stop lolypoly-web` → 현재 DB를 `.before-restore`로 이름 변경 → `gunzip -c <백업> > /var/lib/lolypoly/db.sqlite3` → 소유자 `lolypoly` 확인 → `systemctl start lolypoly-web`.
- **같은 디스크 사본은 외부 백업이 아니다.** 승인된 다른 장치(예: 학교 NAS, 본인 PC)로 주 1회 복사하는 것을 권장 — **현재 외부 백업 미확보**. 임의의 외부 계정에 학생 데이터를 올리지 않는다.

## 6. 장애 대응

| 증상 | 확인 순서 |
|---|---|
| 접속 안 됨 | 학교 PC 전원·망 → `systemctl status lolypoly-web nginx cloudflared` → `curl -I http://127.0.0.1:8000/` → 터널 상태 |
| 화면은 열리는데 정보가 오래됨 | 화면의 "수집 실패/오래된 데이터" 띠 → 수집 로그 → 공식 사이트 구조 변경 여부(이전 정상 데이터는 유지됨) |
| 의견이 안 보내짐(403) | 시간·`DJANGO_CSRF_TRUSTED_ORIGINS`에 `https://lolypoly.com` 포함 여부 |
| 메모리 부족 | 수집이 겹쳤는지(flock으로 방지됨) `free -h`, Chromium 프로세스 |
| 재부팅 후 | 서비스·타이머는 자동 시작(`systemctl is-enabled`). 놓친 수집은 `Persistent=true`로 부팅 후 실행 |

## 7. 시범 운영 한도와 비용 (확인된 것과 미확인)

- 비용 발생 없음: 새 유료 서비스를 가입하지 않았다. 도메인 연간 비용, Cloudflare 플랜, Supabase 무료 한도는 **계정 화면에서 확인 필요(미확인)**.
- Supabase 무료는 저활동 7일이면 일시 정지, 90일 내 복구 가능(D-038, 2026-11-03 기록). 현재 프로젝트 상태는 INACTIVE(2026-11-04 확인).
- 학교 PC의 상시 전원·밤/주말/방학 인터넷 유지·관리 책임자: **미확인**.
- 도메인 소유자·DNS 관리 계정: **미확인(사용자 확인 필요)**.

## 8. Windows 직접 실행 (강의실 PC 현재 구성, D-047)

BIOS 가상화가 꺼져 있어 Linux(2절) 대신 이 방식으로 설치함. 위치: `D:\lolypoly\app`(코드·`.env`), `data`(DB·백업), `logs`, `browsers`(Playwright).

| 하고 싶은 것 | 명령 (PowerShell) |
|---|---|
| 작업 등록·갱신 (관리자 PowerShell) | `powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\install.ps1` |
| 상태 | `Get-ScheduledTask Lolypoly-* \| Get-ScheduledTaskInfo` (LastTaskResult 0 = 성공) |
| 웹앱 재시작 | `Stop-ScheduledTask Lolypoly-Web; Start-ScheduledTask Lolypoly-Web` |
| 지금 수집/백업 | `Start-ScheduledTask Lolypoly-Collect-Notices` (Meals, Events, Backup 도 같음) |
| 로그 | `D:\lolypoly\logs\job-*.log` (1MB 초과 시 .old 로 교체) |
| 백업 복원 시험 | `cd D:\lolypoly\app; .venv\Scripts\python.exe manage.py backup_db --verify <D:\lolypoly\data\backups\파일>` |
| 업데이트 | `cd D:\lolypoly\app; git pull; .venv\Scripts\python.exe -m pip install -r requirements.txt waitress==3.0.2; .venv\Scripts\python.exe manage.py migrate; .venv\Scripts\python.exe manage.py collectstatic --noinput` 후 웹앱 재시작 (업데이트 전 백업) |
| 되돌리기 (관리자) | `Get-ScheduledTask Lolypoly-* \| Unregister-ScheduledTask -Confirm:$false` |

- 터널: `cloudflared` 를 Windows 서비스로 등록하고 대상은 `http://127.0.0.1:8000` (3절 A, Nginx 없음).
- 전원: 설치 스크립트가 AC 전원에서 절전·최대 절전을 끈다. 모니터는 꺼져도 된다.
- Windows 에서는 `test_backup` 의 파일 권한(600) 검사 1건이 항상 실패한다(POSIX 전용). 앱 동작과 무관.
## 9. LTE 시험과 외부 공개 방법 (2026-11-05 실측)

실측: 강의실 PC 주소 `192.168.5.6/24`(내부망), 바깥에서 보이는 주소는 학교 공용 주소(NAT). → **바깥에서 이 PC로 직접 들어올 수 없다**(교수님 설명과 같음). 반면 이 PC에서 Cloudflare 로 **나가는** 연결(TCP 7844·443)은 열려 있다 → 터널은 기술적으로 가능.

| 방법 | 학교망 변경 | 계정·비용 | 주소 | 용도 |
|---|---|---|---|---|
| ① Quick Tunnel (`test_tunnel.ps1`) | 없음(나가는 연결만) | 없음 | `https://<무작위>.trycloudflare.com`, 실행마다 바뀜 | **LTE 시험 전용**, QR 인쇄 금지 |
| ② 이름 있는 터널 + 내 도메인 | 없음 | Cloudflare 무료 계정 + 도메인 연 비용 | `https://<내 도메인>` 고정 | 시범 배부용(QR) |
| ③ 학교 전산 담당이 공인 주소·포트 개방 | 있음(담당자 작업) | 도메인 | 고정 | 학교가 원할 때 |
| ④ 기존 Render 주소 | 없음 | 없음 | `https://lolypoly.onrender.com` (2026-11-05 200, 첫 응답 약 20초) | 화면만 시험. 이 PC 데이터·의견과 별개 |

①·② 는 학교 방화벽에 구멍을 뚫지 않지만, 학교망 안의 PC를 인터넷에 공개하는 것이므로 **학교(교수님·전산 담당) 동의 후에** 연다.

① 사용법:
```powershell
powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\test_tunnel.ps1 -Start   # 주소와 D:\lolypoly\logs\test-qr.png 출력
powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\test_tunnel.ps1 -Stop    # 종료 + .env 원복 + 웹앱 재시작
```
`-Start` 는 `.env` 허용 목록에 `.trycloudflare.com`(및 CSRF `https://*.trycloudflare.com`)을 넣고 웹앱을 재시작한다. `-Stop` 이 원복한다.

cloudflared: 관리자 권한 없이 `D:\lolypoly\tools\cloudflared\cloudflared.exe` (공식 릴리스 2026.10.7, SHA256·Cloudflare 서명 검증 2026-11-05). 시험 QR 도구: `D:\lolypoly\tools\.venv`(qrcode 8.2, 앱 의존성 아님).

## 10. 고정 주소: 도메인 + Cloudflare Named Tunnel (중단 없이 옮기기)

현재: Quick Tunnel(`test_tunnel.ps1`) — 계정 없음, **주소가 매번 바뀜, 재부팅 후 자동으로 다시 열리지 않음** → 시험 전용.
목표: `https://<도메인>` → Cloudflare(HTTPS) → Named Tunnel(Windows 서비스, 자동 재연결) → 이 PC `127.0.0.1:8000`(waitress) → Django → SQLite.

도메인 후보 (2026-11-05 조회, 가격은 등록처 화면에서 결제 전 재확인):

| 도메인 | 상태 | 대략 비용 | Cloudflare 연결 |
|---|---|---|---|
| lolypoly.app | **이미 등록됨** (2026-09-12, Hostinger, NS=Cloudflare, 접속 시 525). 사용자 소유 근거 없음(2026-11-05 메일함·저장소 확인), lovesome0405 소유 여부 미확인 | 소유자에게 받지 않으면 사용 불가 | 소유자 계정에서만 가능 |
| lolypoly.kr | 등록 기록 없음(KISA RDAP 404) | 국내 등록대행 약 2만 원/년(가비아 정상가 기준, 2023 자료) | 국내에서 사고 네임서버를 Cloudflare로 변경 (Cloudflare Registrar는 .kr 미지원) |
| lolypoly.site | 등록 기록 없음 | Cloudflare 약 $27.70/년(집계 사이트) | Cloudflare에서 바로 구매·연결 |

**자동 연결 스크립트**(2~5단계를 대신함, 도메인이 Cloudflare 에서 활성화된 뒤):
`powershell -ExecutionPolicy Bypass -File D:\lolypolypp\deploy\windows\connect_domain.ps1 -Domain <도메인>`
→ 브라우저에서 도메인 선택·Authorize 1번, 관리자 승인 창 '예' 1번. 터널은 대시보드 토큰 대신 이 PC의 자격 증명 파일(`D:\lolypoly	unnel`, 사용자·관리자만 접근)로 실행되고, 작업 스케줄러 `Lolypoly-Tunnel` 이 부팅 시 자동 시작한다. 같은 이름의 기존 DNS 레코드는 덮어쓰지 않고 멈춘다.

옮기는 순서 (수동, 기존 시험 터널은 마지막에 끔):
1. (사용자) 도메인을 Cloudflare 계정에 추가(Add a domain) → 등록처에서 네임서버를 Cloudflare가 준 2개로 변경 → 활성화 메일 확인.
2. (사용자) Cloudflare 대시보드 → Zero Trust → Networks → Tunnels → **Create a tunnel**(Cloudflared) → 이름 `lolypoly` → Windows 설치 명령의 **토큰**은 대화·Git에 남기지 않는다.
3. 관리자 PowerShell: `D:\lolypoly\tools\cloudflared\cloudflared.exe service install <토큰>` → Windows 서비스 `cloudflared` 자동 시작.
4. (대시보드) Public Hostname: `<도메인>` → Service `HTTP` / `127.0.0.1:8000`. (www를 쓸 거면 같은 대상으로 추가)
5. `.env`: `DJANGO_ALLOWED_HOSTS` 에 `<도메인>`, `DJANGO_CSRF_TRUSTED_ORIGINS` 에 `https://<도메인>` 추가 → `Stop-ScheduledTask Lolypoly-Web; Start-ScheduledTask Lolypoly-Web`.
6. 확인: 휴대폰 **LTE**로 `https://<도메인>/` → 식단·의견 제출·설치 시트. `curl -I https://<도메인>/sw.js` 가 `no-cache`.
7. `scripts\make_distribution.py https://<도메인>/` → QR·안내 이미지 생성·디코딩 검증 → 인쇄물 실기기 스캔.
8. 시험 터널 종료: `test_tunnel.ps1 -Stop`. 2주 뒤 HSTS(`DJANGO_HSTS_SECONDS=2592000`) 검토.

Cloudflare 캐시: HTML은 기본 캐시 안 함, `/sw.js`·매니페스트는 `no-cache`로 통과, `/static/`은 `max-age=60`이라 새 버전이 1분 안에 반영된다. 서비스워커가 정적 파일을 버전(내용 해시)별 캐시로 관리한다.
되돌리기: 대시보드에서 Public Hostname 삭제 → `cloudflared service uninstall`(관리자). DNS는 Cloudflare가 터널 레코드만 추가하므로 그 레코드만 지우면 된다.

## 11. 부하 실측 (2026-11-05, 강의실 PC 내부 127.0.0.1, waitress 스레드 8, 요청 사이 0.3초, 8개 경로)

| 동시 | 요청 | 처리량 | p50 | p95 | 오류 |
|---|---|---|---|---|---|
| 10명 | 400 | 32건/초 | 5ms | 30ms | 0 |
| 30명 | 1200 | 95건/초 | 5ms | 27ms | 0 |
| 60명 | 2400 | 167건/초 | 13ms | 170ms | 0 |

Cloudflare 구간(외부에서 측정 0.3~1.1초)·수집 동시 실행은 포함하지 않음. 300명 동시 접속을 보장한다는 뜻이 아니다.

## 12. 현재 공개 구조: workers.dev + Workers VPC + Named Tunnel (2026-11-05, D-051)

공개 주소: **https://lolypoly.lolypoly.workers.dev** (무료, 고정). 학생 휴대폰 → Cloudflare HTTPS → Worker `lolypoly`(`deploy/cloudflare-worker/src/index.js`) → Workers VPC 서비스 `lolypoly-pc` → Tunnel `lolypoly`(ID 5d947b5d-…) → 이 PC `127.0.0.1:8000`(waitress) → Django → SQLite.

| 구성 | 위치 | 자동 복구 |
|---|---|---|
| 터널 연결기 | 작업 스케줄러 `Lolypoly-Tunnel` → `deploy\windows\run_tunnel.cmd`(wrangler → cloudflared 2026.10.7), 로그 `D:\lolypoly\logs\tunnel-run.log` | 부팅 시 시작, 끊기면 cloudflared 재연결, 프로세스 종료 시 1분 뒤 재시작 |
| Worker | 사용자 Cloudflare 계정. 배포: `cd D:\lolypoly\app\deploy\cloudflare-worker; npx wrangler deploy` | Cloudflare 운영. PC·터널이 꺼지면 503 안내(학교 공식 홈페이지 링크) |
| 도구 | Node v26.13.0 `D:\lolypoly\tools\node`, wrangler 4.151.3(고정) | — |

- 인증: `wrangler login`(OAuth, 자동 갱신). 토큰은 `%APPDATA%\xdg.config\.wrangler` 에만 있고 Git·로그에 없다. **터널이 inactive 이면** `tunnel-run.log` 확인 → 인증 만료면 `wrangler login` 다시.
- 상태: `npx wrangler tunnel info lolypoly`(healthy), `curl -I https://lolypoly.lolypoly.workers.dev/`. 이 PC의 curl 은 인증서 폐기 확인이 느려 `--ssl-no-revoke` 가 필요할 수 있다(휴대폰과 무관).
- 한도: Workers 무료 하루 10만 요청. Workers VPC 는 베타 기간 무료(공식 문서, 2026-11-05) — 정식 전환 시 요금 확인.
- 되돌리기: `npx wrangler delete`, `npx wrangler vpc service delete <id>`, `npx wrangler tunnel delete lolypoly`, `Unregister-ScheduledTask Lolypoly-Tunnel`(관리자).
- 시험용 Quick Tunnel(`test_tunnel.ps1`)은 종료함.

### 12-1. 운영 점검 결과 (2026-11-05 12시, 실측)
- **고침**: 작업 `Lolypoly-Tunnel` 을 멈추면 cmd 만 끝나고 cloudflared 가 남아(형 계정 시절 것 포함 2개) 로그를 잡고 있어 재시작이 실패(결과 1)하던 문제 → `run_tunnel.cmd` 가 시작 때 남은 cloudflared 를 정리. 멈춤→시작 후 연결기 1개·공개 주소 200 확인.
- 의견 도배 제한은 **학생 실제 IP 기준**으로 동작(Worker 가 넘긴 주소 해시 = 시험 PC 공인 IP 확인). 단, 학교 Wi-Fi 처럼 한 공인 IP 뒤의 여러 명은 같은 제한을 나눠 쓴다.
- 한글 의견 UTF-8 저장 정상. 비브라우저 요청(파이썬 기본 UA)은 Cloudflare 가 403 으로 막음(브라우저는 정상).
- 시험으로 넣은 의견 2건은 ID 로만 골라 삭제, 현재 0건.

## 13. 계정·커뮤니티 운영 (2026-11-10, D-059~D-067)

> 이 장의 스크립트(`update.ps1`·`rollback.ps1`)는 클라우드 Linux 작업 환경에서 작성했고 **PowerShell 실행 검증은 하지 못했다**(행 수 세는 부분만 Python으로 실행 확인). 처음 실행은 `-DryRun`으로 확인부터 한다.

### 13-1. 학교 PC에 반영하기

GitHub에 올라간 코드는 학교 PC에 자동으로 적용되지 않는다. 학교 PC에서 **관리자 PowerShell**로:

```powershell
# 처음 가져오기(update.ps1 이 아직 PC 에 없을 때 한 번): 스크립트만 임시 폴더로 꺼내 확인 모드로 실행
git -C D:\lolypoly\app fetch origin main
cmd /c "git -C D:\lolypoly\app show origin/main:deploy/windows/update.ps1 > %TEMP%\lolypoly-update.ps1"   # cmd 로 꺼내야 한글이 깨지지 않는다
powershell -ExecutionPolicy Bypass -File $env:TEMP\lolypoly-update.ps1 -DryRun     # 바꾸지 않고 상태만 확인
powershell -ExecutionPolicy Bypass -File $env:TEMP\lolypoly-update.ps1             # 실제 반영
# 다음부터
powershell -ExecutionPolicy Bypass -File D:\lolypoly\app\deploy\windows\update.ps1
```

스크립트가 하는 일: 미커밋 변경 확인(있으면 멈춤) → 지금 코드로 DB 백업·검증 + `preupdate-…` 사본 → fast-forward로만 코드 가져오기(강제 pull/reset 없음) → `pip install -r requirements.txt`(Django 5.2.19·Pillow·Waitress) → `check` → `migrate`(표·칸 추가만) → 표별 행 수가 줄지 않았는지 확인 → `collectstatic` → `Lolypoly-Web` 재시작 → 127.0.0.1:8000 응답 확인. `.env`·Cloudflare·작업 스케줄러 등록은 건드리지 않는다. Worker 코드는 바뀌지 않았으므로 Cloudflare 재배포는 필요 없다.

반영 전 `.env` 확인(값은 화면에 출력하지 말 것):
- `DJANGO_HTTPS=True` — 로그인 쿠키를 HTTPS에서만 보내게 한다. 꺼져 있으면 켠다.
- `DJANGO_SQLITE_PATH=D:\lolypoly\data\db.sqlite3` — 사진은 자동으로 그 옆 `D:\lolypoly\data\media`에 저장된다(코드 폴더 밖, 업데이트·재시작과 무관하게 보존).
- `DJANGO_CSRF_TRUSTED_ORIGINS`에 공개 주소(`https://lolypoly.lolypoly.workers.dev`)가 들어 있어야 가입·글쓰기 POST가 통과한다(의견 폼이 이미 동작 중이면 충족).
- 버스 화면(main에서 합쳐짐)의 실시간 정보는 `TAGO_SERVICE_KEY`가 있어야 한다. 없으면 시간표 안내만 나온다. 노선 수집은 `python manage.py collect_bus --if-empty` (작업 스케줄러 등록은 아직 없음 — 필요하면 `install.ps1`에 추가).

반영 뒤 사람이 확인할 것: 공개 주소에서 홈·식단 열림 → MY → 가입 → 전체 게시판에 시험 글+사진 → 삭제. (실제 사용자가 보는 곳이므로 시험 글은 바로 지운다.)

### 13-2. 운영자 지정·학과 관리

- 슈퍼유저(관리자 화면 `/admin/`): `python manage.py createsuperuser`. 학과 추가·이름 수정·**사용 중지**(지우지 않음), 계정의 학과 변경·이용 제한은 `/admin/accounts/`.
- 신고 처리 담당: `/admin/`에서 해당 계정을 **`커뮤니티 운영자` 그룹**에 넣는다. 그 계정은 MY에 '신고 관리'가 보이고 `/community/manage/`만 쓸 수 있다(관리자 화면 접근 권한은 없음).
- 학과 목록 출처: 춘천캠퍼스 홈페이지 학과안내 메뉴(2026-11-10): AI융합과·미디어크리에이터과·바이오의약공정과·에너지설비과·전기과·전기자동차과('과'를 붙이기로 2026-11-10 확정, accounts 0004). 같은 이름은 과정(2년제·전문기술·하이테크)이 달라도 게시판 하나로 묶었다. **미확정**: 과정별로 나눌지 — 필요하면 관리자 화면에서 이름을 고치거나 학과를 추가한다(추가하면 게시판이 자동 생성).
- 학과 변경 요청: 학생이 '의견 보내기'로 요청 → 관리자 화면에서 변경. 자기 신고 값이며 재학 인증이 아니다. 옮긴 뒤 예전 글은 본인이 수정·삭제할 수 있고, 예전 학과 게시판에 새 글·댓글은 못 쓴다.
- 한계(학생 안내 화면 `/community/rules/`에도 적음): 초대코드·재학 인증이 없어 **학교 밖 사람도 가입할 수 있다**. 익명은 화면 표시일 뿐 DB에서는 계정과 글이 연결돼 있다.

### 13-3. 신고 처리

`/community/manage/` → 글·댓글 선택 → 내용·신고 이유 확인 → 숨기기 / 복구 / 삭제 확정 / 문제없음 / 작성 계정 이용 제한(기간)·해제. 모든 처리에 사유를 적어야 하고 운영 기록(`/admin/community/moderationlog/`)에 남는다. 화면에는 작성자 아이디가 나오지 않는다. 서로 다른 계정의 신고가 5건(`LOLYPOLY_REPORT_AUTOHIDE`) 모이면 운영자 확인 전까지 임시로 숨겨지고, 문제없으면 '복구'로 되돌린다. 신고 수만으로 계정이 제한되지는 않는다.

### 13-4. 백업·복구 (DB + 사진)

- 매일 03:30 `Lolypoly-Backup`: `backup_db --keep 7` → `D:\lolypoly\data\backups\lolypoly-<시각>.sqlite3.gz`(7개) + 사진 사본 `backups\media\`(바뀐 것만 복사) + 지워진 사진 `backups\media-removed\<날짜>\`(7일 뒤 삭제). 이어서 `purge_community`(보관 기간 지난 내용·주인 없는 사진·끝난 세션 정리).
- 검증(원본을 건드리지 않고 임시 위치에 풀어 확인): `python manage.py backup_db --verify D:\lolypoly\data\backups\<파일>` → DB 무결성·표별 건수 + 그 DB가 가리키는 사진 파일이 사본에 모두 있는지.
- **같은 D: 디스크의 사본이라 외부 백업이 아니다.** 디스크가 고장 나면 함께 잃는다. 외부 보관은 아직 없다(개인정보가 든 파일이므로 옮길 곳은 사용자가 정한다).
- 문제가 생겼을 때 순서:
  1. **코드만 되돌리기(기본)**: `rollback.ps1 -To <이전 커밋>`. DB·사진은 그대로 둔다. 새 표·칸은 옛 코드가 무시한다. 그 사이에 생긴 가입·글·의견·수집 데이터가 보존된다.
  2. DB 자체가 깨졌을 때만 DB 복구: 먼저 지금 DB를 다른 이름으로 복사해 두고(`db.sqlite3` → `db-broken-<날짜>.sqlite3`), 웹앱·수집 작업을 멈춘 뒤, 검증한 백업을 풀어 넣고, `backups\media`(+필요하면 `media-removed`)를 `data\media`로 복사, `python manage.py migrate`, 재시작. **백업 시각 뒤에 생긴 가입·글·댓글·의견은 사라진다** — 덮기 전에 깨진 DB 사본에서 살릴 수 있는지 먼저 본다.

### 13-5. 설정값(환경변수) — `.env.example` 끝부분 참고

사진: 5장·10MiB·60MP·1920px. 도배: 글 10분 5개, 댓글 5분 20개(계정 기준). 로그인 실패: 아이디당 10분 8회. 가입: 같은 주소 1시간 60건(보조). SQLite는 잠금 대기 20초 + 쓰기 트랜잭션 즉시 잠금. 24명 동시 공감·20명 동시 첫 댓글에서 오류 0·수 일치 확인(2026-11-10, 클라우드 Linux). 학교 PC에서의 동시 쓰기 실측은 아직 없다 — `database is locked`가 로그에 보이면 WAL 모드 또는 PostgreSQL 이전을 검토한다.

