# Lolypoly

한국폴리텍대학 춘천캠퍼스 공식 홈페이지의 공개 생활정보(식단·학사일정·공지)를
로그인 없이 모바일에서 쉽게 확인하도록 모으는 **학생 프로토타입** 웹 서비스입니다.
학교 공식 서비스가 아니며, 정보의 기준은 [공식 홈페이지](https://www.kopo.ac.kr/chuncheon/index.do)입니다.

> 현재 상태 (2026-11-07): 식단·학사일정·공지는 공식 홈페이지 **실제 데이터**, 학교 버스는 국토교통부 TAGO **실시간 데이터**,
> 시간표·MY는 Mock입니다. 공개 주소: **https://lolypoly-x7a3.onrender.com** (Render 무료, 저장소 `chanmini584-ux/LOLYPOLY`의 `main`).
> 자세한 상태는 [docs/PROGRESS.md](docs/PROGRESS.md), 결정 기록은 [docs/DECISIONS.md](docs/DECISIONS.md).

## 최근 작업 기록 (2026-11-05 ~ 11-07) — 팀원 공유용

함께 작업하는 사람이 먼저 읽을 요약입니다. 상태는 **실제 구현 / Mock / 미구현**으로 구분합니다.

- 공동 작업 저장소: **https://github.com/chanmini584-ux/LOLYPOLY** (chanmini584·lovesome 공동작업자). 예전 문서의 `lovesome0405/Lolypoly` 주소는 이 저장소로 바꿨습니다.
- 예전 주소로 받아 둔 폴더가 있다면 그 폴더에서 한 번만: `git remote set-url origin https://github.com/chanmini584-ux/LOLYPOLY.git` → `git pull`

### 1. 학교 버스 (실제 구현, 실시간)
- 홈 바로가기 **학교 버스** → `/bus/`. 노선 탭 7개(901, 남산2-1, 동산1~5)
- 칸 2개: **학교 가는 버스**(시내 → 폴리텍대학), **시내 가는 버스**(폴리텍대학·폴리텍입구 → 시내).
  학교 정류장 앞 8개 정류장 줄그림 위에 실제 버스 아이콘이 30초마다 움직이며 "N정거장 전"을 표시
- 데이터: 국토교통부 TAGO OpenAPI(공공데이터포털). 춘천 cityCode 32010. 노선·정류장은 `collect_bus`로 수집(노선 18개, 정류장 1,706개),
  운행 시각만 「춘천시내버스 노선안내」(2026.09.30) PDF에서 손으로 옮김
- 학교 정류장: TAGO '폴리텍대학'(2곳)·'폴리텍입구'. 사용자 확인 완료 (2026-11-07)
- 2026-11-07 08시 실제 운행 버스로 확인(마을버스도 실시간 제공). 공개 주소에서도 동작 확인
- 결정: D-040(데이터 출처), D-041(실시간 호출 예외·캐시), D-042(홈 버스는 도착정보 1회·호출은 차례로)

### 2. 홈 화면 개편 — 플래너 2단계 (실제 구현, 사용자 시안 승인)
- **이번 주 밥**: 요일 동그라미 7개(오늘 = 노란 형광펜, 메뉴 있는 날 = 초록 테두리), 누르면 새로고침 없이 그날 메뉴로 바뀜
- **학교 가는 버스** 한 줄: 폴리텍대학 정류장에 가장 먼저 오는 버스 "약 N분 · N정거장 전" (홈 열 때 1회, 서버 1분 캐시)
- **남은 날**: 학사일정 D-day를 파스텔 동그라미 스티커로. 바로가기는 그대로 유지
- 식단 탭 화면은 아직 예전 모양(다음 작업 후보)

### 3. 기타
- 화면 우측 상단 **'프로토타입' 도장 제거** (학교 공식 서비스 아님 안내는 MY 화면 문구로 유지)
- 시간표 사진 올리기 기능은 **보류** (보관함: docs/PROGRESS.md)

### 4. 운영 메모 (꼭 읽기)
- **Render 환경변수 `TAGO_SERVICE_KEY` 필요** (공공데이터포털 Decoding 키). 없으면 버스 화면은 '설정 필요' 안내만 나옴.
  키는 Git·코드에 넣지 않는다. 키가 채팅에 노출된 적이 있어 **재발급 예정** → 재발급하면 Render 값도 바꿔야 함
- Render **자동 배포가 꺼져 있음** → `main`에 합친 뒤 Render에서 **Manual Deploy → Deploy latest commit**을 눌러야 반영됨
- TAGO는 **초당 호출 한도**가 있다. 여러 노선을 동시에 부르면 같은 키를 쓰는 서버 전체가 잠깐 막힌다(2026-11-07 실제 발생) → 호출은 차례로
- `lolypoly.lolypoly.workers.dev` 주소는 **다른 데스크탑 + Cloudflare 터널**로 돌던 예전 서버. 그 PC가 꺼지면 "서버에 잠시 연결할 수 없어요"가 뜸.
  다시 켤 때는 `git pull` → `python scripts/setup.py --test` → `.env`에 `TAGO_SERVICE_KEY` 추가 → `python manage.py collect_bus` → 앱·터널 실행
- 공개 주소는 Render(`lolypoly-x7a3`)와 workers.dev 두 개가 있는 상태. 학생들에게 알릴 주소를 하나로 정할 필요 있음

### 5. 다음 할 일
1. Render 수동 배포로 새 홈 반영 확인
2. 식단 탭 화면도 홈처럼 맞출지 결정
3. 플래너 3단계(학사일정 달력·시간표)

## 구조 한눈에

```
공식 홈페이지 ──(Playwright, 관리 명령/자동 타이머)──▶ 추출·검증 ──▶ DB(SQLite)
                                                                  │
학생 브라우저 ◀── Django 화면(DB만 조회, 공식 사이트 실시간 접속 없음) ◀┘
      └─ 서비스 워커: 마지막으로 본 화면을 저장해 오프라인에서도 표시
```

| 폴더 | 역할 |
|---|---|
| `config/` | 설정·URL 시작점 |
| `accounts/` | 사용자 모델(로그인 기능은 아직 없음) |
| `campus/collectors/` | 수집기: `meals.py` `events.py` `notices.py`, 공식 URL `sources.py` |
| `campus/data.py` | 화면용 데이터 묶음(Section): 데이터 + 상태(정상/없음/실패/오래됨) |
| `campus/views.py`, `campus/pwa.py` | 화면, PWA(매니페스트·서비스 워커·오프라인) |
| `templates/`, `static/` | 화면 템플릿, CSS·JS·아이콘 |
| `deploy/systemd/` | Ubuntu 자동 수집 타이머 |
| `scripts/setup.py` | 새 컴퓨터 개발 환경 한 번에 준비 |

## 기술과 버전

- Python 3.10 이상 (개발 확인: 3.13), Django 5.2 LTS, Django Template, HTML/CSS, 최소 JavaScript
- 수집: Playwright 1.64.1(브라우저), BeautifulSoup 4.15.0(HTML 해석) — 정확한 버전은 `requirements.txt`
- DB: SQLite (개발·잠정)
- 운영 실행: Gunicorn 26.2.0, 정적 파일 WhiteNoise 6.12.0, Docker 이미지(`Dockerfile`)

## 다른 컴퓨터에서 시작하기 (빠른 설치)

Git에는 코드·문서·설정 예시만 있고 `.env`·DB·가상환경·수집용 브라우저는 들어 있지 않습니다.
아래 스크립트가 이 네 가지를 한 번에 준비합니다(이미 있는 `.env`·DB는 덮어쓰지 않음).

```bash
git clone https://github.com/chanmini584-ux/LOLYPOLY.git
cd Lolypoly
python scripts/setup.py --collect      # macOS/Linux: python3, Windows에 python이 없으면: py
```

| 옵션 | 내용 |
|---|---|
| (없음) | 가상환경 → 패키지 → 수집용 브라우저 → `.env` 복사 → DB 마이그레이션 |
| `--collect` | + 공식 홈페이지에서 실제 데이터 수집 (인터넷 필요, 약 1분) |
| `--test` | + 자동 테스트 (인터넷 불필요) |
| `--no-browser` | 수집용 브라우저 설치 생략 (화면만 볼 때) |

끝나면 가상환경을 켜고(`source .venv/bin/activate`, Windows: `.venv\Scripts\activate`) `python manage.py runserver` →
http://127.0.0.1:8000/ 에서 확인합니다. 필요한 것: Python 3.10 이상, Git, 인터넷.

### 직접 설치 (스크립트와 같은 내용)

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # 수집에 쓰는 브라우저 (Ubuntu 서버: --with-deps 추가)
cp .env.example .env               # Windows: copy .env.example .env
python manage.py migrate
python manage.py collect_all       # 공식 홈페이지에서 실제 데이터 수집 (약 1분)
python manage.py runserver
```

휴대폰 화면은 개발자 도구의 모바일 보기(375~430px)로 확인합니다.
수집 전에는 식단·학사일정·공지가 "정보가 없어요"로 나옵니다(예시 데이터로 채우지 않음).

### 컴퓨터를 오갈 때 주의

- DB(`db.sqlite3`)는 컴퓨터마다 따로입니다. 새 컴퓨터에서는 `collect_all`로 다시 받으면 됩니다(공개정보라 옮길 필요 없음).
- `.env`는 Git에 올리지 않습니다. 운영 비밀키 등은 각 컴퓨터에서 직접 작성합니다.
- 줄바꿈은 `.gitattributes`로 LF 통일 → Windows에서 수정해도 Ubuntu용 스크립트가 깨지지 않습니다.
- 작업 전 `git pull`, 작업 후 커밋·푸시. 요구사항이 바뀌면 `requirements.txt`가 바뀌므로 `python scripts/setup.py`를 다시 실행하면 됩니다(안전하게 반복 실행 가능).

### 같은 Wi-Fi의 휴대폰으로 보기 (개발용)

1. PC의 내부 IP 확인 (Windows `ipconfig`, macOS `ipconfig getifaddr en0`, Linux `hostname -I`)
2. `.env`의 `DJANGO_ALLOWED_HOSTS`에 그 IP 추가 (예: `localhost,127.0.0.1,192.168.0.12`)
3. `python manage.py runserver 0.0.0.0:8000` 후 휴대폰에서 `http://그IP:8000`
4. PC 방화벽에서 8000 포트 허용이 필요할 수 있음. 학교 Wi-Fi는 기기 간 통신이 막혀 있을 수 있음

이 방식은 HTTPS가 아니므로 홈 화면 설치(PWA)·오프라인 기능은 동작하지 않습니다(6단계 HTTPS 배포 후 가능).

## 화면

하단 탭: 홈 · 식단 · 학사일정 · 시간표 · MY (공지는 홈 카드·바로가기·MY 메뉴에서)

| 경로 | 화면 | 데이터 | 파라미터 |
|---|---|---|---|
| `/` | 홈: 오늘 식단, 다가오는 일정 3개, 최신 공지 3개 | 실제 | — |
| `/meals/` | 식단: 주간 날짜 선택, 조식/중식/석식 | 실제 | `?date=YYYY-MM-DD` |
| `/schedule/` | 학사일정: D-day, 월별 목록, 과정 필터 | 실제 | `?month=YYYY-MM` `?course=과정` |
| `/notices/` | 공지: 분류 필터, 고정 표시, 공식 원문 링크 | 실제 | `?category=분류` |
| `/timetable/` | 시간표: 오늘 수업, 주간 그리드 | **Mock** | — |
| `/my/` | 안내·향후 계획 | **Mock** | — |
| `/bus/` | 학교 버스(홈 바로가기): 폴리텍대학·폴리텍입구 정류장 앞 구간 줄그림 + **실시간 버스 위치**(30초 갱신) + 운행 시각 | 실제(TAGO) · 운행 시각은 노선도 PDF 수동 입력 | `?route=노선번호` |
| `/bus/live/<노선번호>/` | 실시간 버스 위치 JSON (서버 캐시 30초, 심야 0~5시 조회 안 함) | 실제(TAGO) | — |
| `/admin/` | 관리자(개발·점검용): 수집 기록·실패 원인 확인 | — | — |

### 화면 상태 미리보기 (개발용)

`DJANGO_DEBUG=True`일 때 홈·식단·학사일정·공지 화면 맨 아래 "개발용 · 화면 상태 미리보기"에서
`?preview=empty`(데이터 없음), `error`(수집 실패·이전 데이터 유지), `error-empty`, `stale`(오래된 데이터) 화면을 볼 수 있습니다.

## 수동 수집 명령

| 명령 | 내용 |
|---|---|
| `python manage.py collect_meals [--weeks 2]` | 식단, 이번 주부터 N주 (1~4) |
| `python manage.py collect_events [--year 2026 ...]` | 학사일정, 기본 올해+내년 (1~2월엔 작년 포함) |
| `python manage.py collect_notices [--pages 2]` | 공지 목록, 앞에서 N쪽 (1~5) |
| `python manage.py collect_bus [--if-empty]` | 버스 노선·정류장 (국토교통부 TAGO API, `TAGO_SERVICE_KEY` 필요). `--if-empty`: 데이터가 있으면 건너뛰고 실패해도 종료 코드 0 (서버 시작용) |
| `python manage.py collect_all [--only meals ...]` | 위 넷을 차례로. 하나가 실패해도 나머지는 계속, 실패가 있으면 종료 코드 1 |

수집 규칙: 같은 데이터는 중복 저장하지 않고, 페이지 구조가 예상과 다르거나 접속에 실패하면 **아무것도 바꾸지 않고**
실패 원인을 기록합니다(관리자 화면 → 수집 기록). 화면에는 "갱신 실패, 이전 정보 표시"로 나옵니다.

## 자동 갱신 (Ubuntu, systemd) — 설정 파일 작성 완료, 실제 서버 등록은 미실행

```bash
sudo ./deploy/systemd/install.sh /앱/경로 실행사용자     # 예: /home/jusang/Lolypoly jusang
systemctl list-timers 'lolypoly-*'                        # 다음 실행 시각
journalctl -u 'lolypoly-collect@*' --since '14 days ago'  # 실행 로그
```

기본: 매주 월요일 06:10 식단 / 06:20 학사일정 / 06:30 공지 (서울 시간). 주기를 바꾸면 `.env`의 `LOLYPOLY_INTERVAL_*`도 맞춥니다.

## PWA (홈 화면 설치)

- 매니페스트 `/manifest.webmanifest`, 서비스 워커 `/sw.js`, 오프라인 안내 `/offline/`
- 설치 조건: HTTPS(또는 localhost). 실제 휴대폰 설치는 6단계 HTTPS 배포 후 확인 예정
- 캐시: 화면은 네트워크 우선(끊기면 마지막 저장 화면 + "저장된 화면" 안내), 관리자 화면·외부 원문 링크는 캐시하지 않음

## 환경변수 (`.env`)

| 이름 | 설명 | 기본 |
|---|---|---|
| `DJANGO_DEBUG` | 디버그 모드 | False (예시 파일은 True) |
| `DJANGO_SECRET_KEY` | 비밀키. DEBUG=False에서 비어 있으면 시작 거부 | — |
| `DJANGO_ALLOWED_HOSTS` | 허용 호스트(쉼표 구분) | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | HTTPS 도메인(쉼표 구분) | — |
| `DJANGO_HTTPS` | HTTPS 프록시 뒤 운영: HTTPS 이동·보안 쿠키·`X-Forwarded-Proto` 신뢰 | False |
| `DJANGO_HSTS_SECONDS` | HSTS 기간(초). 주소 확정 전에는 0 | 0 |
| `DJANGO_SQLITE_PATH` | SQLite 파일 경로 | `db.sqlite3` |
| `LOLYPOLY_STATE_PREVIEW` | 상태 미리보기 사용 | DEBUG와 같음 |
| `LOLYPOLY_INTERVAL_MEALS` / `_EVENTS` / `_NOTICES` | 수집 주기(일), '오래된 데이터' 판단 기준 | 7 |
| `LOLYPOLY_COLLECTOR_TIMEOUT_MS` / `_DELAY_SEC` | 수집 페이지 대기 / 페이지 간 대기 | 30000 / 2 |
| `TAGO_SERVICE_KEY` | 버스 노선·실시간 위치용 공공데이터포털 **Decoding** 키 (TAGO 버스노선·버스위치·버스정류소 정보 활용신청). 비우면 버스 화면은 '설정 필요' 안내. **Git에 넣지 않는다** | — |
| `LOLYPOLY_BUS_LIVE_CACHE_SEC` | 실시간 위치 서버 캐시(초). 짧을수록 TAGO 일일 호출 한도를 빨리 씀 | 30 |
| `TAGO_TIMEOUT_SEC` | TAGO 응답 대기(초) | 6 |
| `LOLYPOLY_FEEDBACK_URL` | 시험 사용 '의견 보내기' 주소(구글 폼 등, `https://`만). 비우면 숨김 | — |
| `LOLYPOLY_CACHE_DIR` | 서버 캐시 폴더(워커끼리 실시간 버스 결과 공유) | 운영체제 임시 폴더/`lolypoly-cache` |
| `GUNICORN_WORKERS` / `GUNICORN_THREADS` | Docker 실행 시 Gunicorn 워커 수 / 워커당 스레드 수 | 2 / 4 |

## 프로토타입 배포 (Docker) — 이미지 준비 완료, 실제 호스팅 등록은 미실행

나중에 상시 서버로 옮기기 전까지 쓰는 임시 공개 방식입니다. 같은 `Dockerfile`을 어느 컴퓨터에서나 실행할 수 있습니다.

```
[빌드 1단계] 브라우저 설치 → migrate → collect_all(공식 홈페이지 약 8페이지) → DB 생성
[빌드 2단계] 브라우저 없이 앱 + DB + 정적 파일 → Gunicorn 실행 (실행 중에는 공식 사이트 접속 없음)
```

- **데이터 갱신 = 이미지를 캐시 없이 다시 빌드.** 갱신하지 않으면 8일 뒤 화면에 '오래된 데이터'가 표시됩니다.
- 수집이 일부 실패해도 빌드는 계속되고, 화면에 '갱신 실패'로 표시됩니다(샘플로 채우지 않음).
- 관리자 계정은 만들지 않으므로 `/admin/`은 로그인 화면만 보입니다.

### 내 컴퓨터에서 확인

```bash
docker build --build-arg COLLECT_STAMP=$(date +%F) -t lolypoly .
docker run --rm -p 8000:8000 -e DJANGO_SECRET_KEY=아무_긴_값 -e DJANGO_ALLOWED_HOSTS=localhost lolypoly
# → http://localhost:8000/   (COLLECT=0 을 build-arg로 주면 수집 생략)
```

### Render 무료 웹 서비스에 올리기 (사용자가 직접: 계정·연결)

1. render.com 가입(무료 Hobby) → **New → Web Service** → GitHub `Lolypoly` 저장소 연결 → 언어 **Docker**, 인스턴스 **Free**
2. 환경변수: `DJANGO_SECRET_KEY`(긴 무작위 값: `python -c "import secrets; print(secrets.token_urlsafe(50))"`), `DJANGO_HTTPS=True` — 공개 주소(`*.onrender.com`)는 `RENDER_EXTERNAL_HOSTNAME`으로 자동 허용
   - 버스: `TAGO_SERVICE_KEY`(공공데이터포털 Decoding 키). 빌드에는 넣지 않고 실행 환경변수로만 쓴다 → 서버가 시작될 때 노선이 비어 있으면 `collect_bus --if-empty`로 한 번 수집(약 30~60초). 수집은 뒤에서 돌고 앱은 바로 뜬다(시작 직후 잠깐 버스 화면 '노선 정보 없음', 실패해도 서버는 뜸)
   - 시험 사용 의견: `LOLYPOLY_FEEDBACK_URL`(구글 폼 주소)을 넣으면 홈·MY에 '의견 보내기'가 나타난다
3. 배포 후 주소 확인. **데이터 갱신**: Deploys → Manual Deploy → **Clear build cache & deploy** (주 1회 권장)

무료 인스턴스 조건(Render 공식 문서, 2026-11-03 확인): 15분 동안 요청이 없으면 잠들고 다시 깨는 데 약 1분, 월 750시간,
파일 시스템은 재시작·재배포 때 초기화(→ DB를 이미지에 넣는 이유), 영구 디스크는 유료.

### 상시 서버로 옮길 때

같은 이미지를 `docker run`으로 실행하거나, 원래 6단계 계획(가상환경 + Gunicorn + Nginx + `deploy/systemd` 타이머 + 영구 SQLite)을 따릅니다.
`DJANGO_HTTPS=True`는 Nginx 등 HTTPS를 처리하는 프록시 뒤에서만 켭니다.

## 검사 명령

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test        # 네트워크 없이 실행 (저장된 실제 공식 페이지 HTML 사용)
```

## 확인된 한계

- 정보는 마지막 수집 시점 기준입니다(기본 주 1회). 화면에 마지막 수집 시각과 '오래된 데이터' 안내가 표시됩니다.
- 공지 분류는 공식 분류 칸이 아니라 제목 머리말([학사] 등)입니다. 수집 범위(기본 2쪽) 밖 공지는 갱신되지 않습니다.
- 공식 사이트 구조가 바뀌면 수집이 실패하며(기존 데이터 유지), 수집기 수정이 필요합니다.
- 로그인·계정, 실제 개인 시간표, 상시 서버 운영, 실제 휴대폰 검증은 아직입니다.
- 버스 실시간 위치는 TAGO가 주는 '버스가 있는 정류장' 단위입니다(정류장 사이 위치는 모름). 마을버스도 실시간 위치가 나오는 것을 2026-11-07에 확인했습니다. TAGO 일일 호출 한도는 공공데이터포털 마이페이지에서 확인하세요(서버 캐시 30초·심야 미조회·10분 뒤 자동 갱신 중지로 줄임).
- 외부 공개는 위 Docker 방식(DEBUG=False·비밀키·HTTPS 설정)으로만 합니다. `runserver`를 공개하지 마세요.
