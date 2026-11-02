# Lolypoly

한국폴리텍대학 춘천캠퍼스 공식 홈페이지의 공개 생활정보(식단·학사일정·공지)를
로그인 없이 모바일에서 쉽게 확인하도록 모으는 **학생 프로토타입** 웹 서비스입니다.
학교 공식 서비스가 아니며, 정보의 기준은 [공식 홈페이지](https://www.kopo.ac.kr/chuncheon/index.do)입니다.

> 현재 상태: **5단계(PWA·자동 갱신 설정) 완료**. 식단·학사일정·공지는 공식 홈페이지에서 수집한 **실제 데이터**,
> 시간표·MY는 Mock입니다. 운영 서버 배포(6단계)는 아직입니다. 자세한 상태는 [docs/PROGRESS.md](docs/PROGRESS.md).

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

## 기술과 버전

- Python 3.10 이상 (개발 확인: 3.13), Django 5.2 LTS, Django Template, HTML/CSS, 최소 JavaScript
- 수집: Playwright 1.64.1(브라우저), BeautifulSoup 4.15.0(HTML 해석) — 정확한 버전은 `requirements.txt`
- DB: SQLite (개발·잠정)

## 설치와 실행 (로컬 개발)

```bash
git clone https://github.com/lovesome0405/Lolypoly.git
cd Lolypoly

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # 수집에 쓰는 브라우저 (Ubuntu 서버: --with-deps 추가)

cp .env.example .env               # Windows: copy .env.example .env
python manage.py migrate
python manage.py collect_all       # 공식 홈페이지에서 실제 데이터 수집 (약 1분)
python manage.py runserver
```

브라우저에서 http://127.0.0.1:8000/ 접속. 휴대폰 화면은 개발자 도구의 모바일 보기(375~430px)로 확인합니다.
수집 전에는 식단·학사일정·공지가 "정보가 없어요"로 나옵니다(예시 데이터로 채우지 않음).

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
| `python manage.py collect_all [--only meals ...]` | 위 셋을 차례로. 하나가 실패해도 나머지는 계속, 실패가 있으면 종료 코드 1 |

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
| `DJANGO_SQLITE_PATH` | SQLite 파일 경로 | `db.sqlite3` |
| `LOLYPOLY_STATE_PREVIEW` | 상태 미리보기 사용 | DEBUG와 같음 |
| `LOLYPOLY_INTERVAL_MEALS` / `_EVENTS` / `_NOTICES` | 수집 주기(일), '오래된 데이터' 판단 기준 | 7 |
| `LOLYPOLY_COLLECTOR_TIMEOUT_MS` / `_DELAY_SEC` | 수집 페이지 대기 / 페이지 간 대기 | 30000 / 2 |

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
- 로그인·계정, 실제 개인 시간표, 운영 배포(HTTPS), 실제 휴대폰 검증은 아직입니다.
- 지금 설정을 그대로 외부에 공개하지 마세요(운영 보안 설정은 6단계).
