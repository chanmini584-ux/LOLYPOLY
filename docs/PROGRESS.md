# 진행 상황

마지막 갱신: 2026-11-03 · 현재 단계: **플래너 UI·회원 기능 추가 작업 1/9단계 완료** (6a 프로토타입 공개 주소: https://lolypoly.onrender.com, 사용자 등록·접속 확인)

## 2026-11-04 강의실 PC 실측 (Windows 11 Home, 로컬 세션에서 직접 실행)

- 사양: i7-10700(8코어/16스레드), RAM 15.9GB, C: 여유 12.4GB / D: 여유 893GB, 유선 1Gbps, 전원 "균형 조정". 복원 소프트웨어(Deep Freeze 등): 서비스·설치 목록에서 **발견 안 됨**(완전 배제는 아님).
- **막힌 곳**: BIOS에서 가상화(VT-x)가 꺼져 있음(`Virtualization Enabled In Firmware: No`), WSL 미설치, 현재 세션은 관리자 권한 상승(UAC) 없음 → WSL2+Ubuntu(OPERATIONS 2절) **미설치**.
- 실행함: Git 2.56 설치, 저장소 클론(브랜치 claude/quirky-euler-j7dwrg), Windows용 venv·migrate·check(이슈 0), 테스트 67개 중 66 통과(실패 1건=`test_backup`의 POSIX 파일권한 600 검사, Windows에선 항상 666 — Linux 문제 아님), **kopo.ac.kr 접속 200, `collect_all` 실수집 성공**(식단 2주, 일정 93건, 공지 40건), 재수집 후 공지 40건 그대로(중복 없음). 개발용 DB/venv는 Git에 안 올라감.
- **lolypoly.com**: 이미 제3자가 2025-10-02 등록(만료 2027-10-02, 등록기관 Strange Domains, 네임서버 Afternic = 매물 대기 페이지). 사용자 소유 아님으로 보임 → 구매는 Afternic 같은 중고 도메인 시장 가격 협상일 수 있음(**가격 미확인, 구매 안 함**).
- 미실행: WSL/Linux 설치, systemd 서비스·타이머, Nginx, 터널, 외부 HTTPS, 재부팅 시험, 실기기.

## 2026-11-04 학교 PC 시범 배포 준비 — 최신 상태 (이 컨테이너 = 클라우드 Linux, **학교 PC 아님**)

결승선: 학생이 QR로 https://lolypoly.com 에 들어와 식단·일정·공지를 보고 의견을 보낼 수 있다.
기준 복구 지점: Git 태그 `backup/pre-ops-2026-11-04`(작업 시작 전 커밋 93f0cce). 기존 코드·DB·Render 배포는 변경·중단하지 않았다.

| 항목 | 코드 작성 | 로컬 시험 | 학교 PC 등록 | 외부 HTTPS | 실기기 | QR 게시 |
|---|---|---|---|---|---|---|
| 의견 보내기(폼·관리자 조회) | ✅ | ✅ 375/430px, 테스트 12개 | ⛔ 미실행 | ⛔ 미확인 | ⛔ 미확인 | — |
| 수집 타이머(식단·일정 1일 1회, 공지 3회, flock·재시도) | ✅ | 🔶 `systemd-analyze verify/calendar`만 (실제 실행 불가: 이 환경 systemd 없음) | ⛔ | — | — | — |
| 웹앱 서비스·Nginx 설정 | ✅ | 🔶 Gunicorn(DEBUG=False)로 부하 시험. Nginx 문법 검사 **미실행**(미설치) | ⛔ | ⛔ | — | — |
| 백업·복원 검증(`backup_db`) | ✅ | ✅ 백업→임시 위치 복원 검증, 7개 보관 정리 | ⛔ | — | — | — |
| lolypoly.com 연결 | 문서·롤백 절차 | — | — | ⛔ 도메인 소유·DNS·학교 허용 미확인 | — | — |
| QR·A4 안내물 | ✅ | ✅ QR PNG·포스터 위 QR 디코딩 = `https://lolypoly.com` | — | — | ⛔ 인쇄본 촬영 미확인 | ⛔ **주소 열림 확인 전 게시 금지** |
| Supabase 연결 | — | ⛔ 보류 | — | — | — | — |
| 회원 기능(가입·로그인·탈퇴) | ⛔ 미구현(D-044) | — | — | — | — | — |

실행한 검증(2026-11-04, Python 3.13.18, Django 5.2.18): `check` 이슈 0, `makemigrations --check` 변경 없음, `test` **67개 통과**, `check --deploy`(DEBUG=False, HTTPS) 경고 1개(HSTS, 의도적 보류).
부하(로컬, Gunicorn 워커 3, 8개 경로 읽기, 요청 사이 0.3초): 동시 10명 400건 p95 12ms·오류 0, 동시 30명 1200건 p95 16ms·오류 0, Gunicorn 메모리 합계 약 169MB. **이 컨테이너 사양(4코어/15GB)이며 학교 PC·Nginx·터널 지연은 포함하지 않음.**
미실행: 학교 PC 설치, 실제 예약 시각 실행, 재부팅 후 자동 시작, 외부망 접속, 실기기 PWA 설치, 실수집(프록시가 kopo.ac.kr 차단), Playwright 브라우저 다운로드(차단 → 사전 설치 Chromium 사용), 수집·Nginx 동시 부하.

변경 파일: `campus/{feedback.py,models.py,views.py,urls.py,admin.py}`, `campus/management/commands/backup_db.py`, 마이그레이션 0003, 템플릿 feedback*.html·home·my, `static/css/app.css`, `deploy/systemd/*`, `deploy/nginx/lolypoly.conf`, `scripts/make_qr.py`, `docs/{OPERATIONS,PILOT}.md`, `docs/handout/*`, 결정 D-040~D-044.

### 사용자 작업 (최대 5개)
1. **도메인**: lolypoly.com 소유·DNS 관리 계정 확인 → 학교 PC 연결(OPERATIONS 3절) → 휴대폰 LTE로 열림 확인. 완료 기준: LTE에서 https://lolypoly.com 이 식단 화면을 보여 줌.
2. **학교 PC**: 관리자 계정으로 OPERATIONS 2절 실행, 학교에 외부 공개/터널 허용 확인.
3. **인쇄 전 확인**: 위가 끝난 뒤 `docs/handout/lolypoly-poster-A4.pdf` 인쇄 → 폰 카메라로 찍어 같은 주소로 열리는지 확인.
4. **Supabase**: 대시보드에서 Restore(현재 INACTIVE) + DB 비밀번호 확인 (회원 기능을 붙일 때 필요, 시범 배부에는 불필요).
5. **관리자 계정**: `createsuperuser` 후 `/admin/` → 학생 의견 확인 방법 익히기.

### 다음 작업 (5분 안에 시작)
`docs/OPERATIONS.md` 2절 1)번 명령(사용자·폴더 생성)을 학교 PC에서 실행.

---

## 단계 현황

| 단계 | 상태 |
|---|---|
| 1. 프로젝트 기반 구축 | ✅ 완료 |
| 2. 모바일 UI Mock | ✅ 완료 |
| 3. 식단 실제 연동 | ✅ 완료 |
| 4. 학사일정·공지·홈 통합 | ✅ 완료 |
| 5. PWA·자동 갱신 | ✅ 완료 — 단, 자동 수집은 **설정 파일 작성·검증까지** (실제 서버 등록·실행은 6단계) |
| 6. 배포 | 🔶 진행 중 — 6a 프로토타입(Docker·무료 호스팅): 이미지·운영 설정 완료, 실제 호스팅 등록 미실행 / 6b 상시 서버(Ubuntu): 서버 정보 필요 |
| 7. 스마트폰 실사용 검증 | 미착수 |
| 8. 기획서·제안서 | 미착수 (요청 시) |

Git: 1~5단계 작업은 2026-11-02 `main`에 커밋·푸시 완료 (d442723). 이후 커밋은 사용자가 "여기까지"라고 할 때 한다.

## 추가 작업: 플래너 UI + 회원 기능 (2026-11-03~)

결승선: 공개 주소에서 플래너 화면으로 식단·일정·공지를 보고, 이메일 가입이나 구글 로그인으로 들어가 MY에서 학과·학년·반을 저장하고 로그아웃·탈퇴까지 할 수 있다.
규칙: 단계마다 승인 후 진행, 코드 변경 5개 파일·약 300줄 이내(문서 제외).

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 디자인 바탕: 모눈종이, 손글씨 제목, 형광펜 탭, 파스텔 색 (D-037) | ✅ 완료 |
| 2 | 홈·식단: 오늘 밥 포스트잇, 남은 날 스티커(파스텔), 요일 동그라미 | 대기 |
| 3 | 학사일정 달력·시간표(Mock 유지) | 대기 |
| 4 | 공지·MY·상태 화면 | 대기 |
| 5 | 회원 DB: Supabase Postgres + 2-DB 라우터 (D-038) | 대기 |
| 6 | 이메일 가입·로그인·로그인 유지 | 대기 |
| 7 | 구글 로그인 | 대기 |
| 8 | 회원 관리: 프로필·만 14세 확인·탈퇴·개인 화면 캐시 금지 | 대기 |
| 9 | 배포·실사용 확인 | 대기 |

### 1단계 (2026-11-03) — 실제 구현
- `static/css/app.css`: 색·글꼴 토큰, 모눈종이 바탕, 손글씨 제목 + 손으로 그은 밑줄, 상자 없는 섹션, 도장 모양 '프로토타입', 형광펜 하단 탭
- `templates/base.html`: 화면 제목을 손글씨 h1로, 하단 탭은 글자만(아이콘 제거), 글꼴 미리 불러오기
- `static/fonts/lolypoly-hand.woff2` + `OFL-Gaegu.txt`, `scripts/build_hand_font.py`
- 검증: `check` 이슈 0, `makemigrations --check` 변경 없음, `test` 54개 통과. 저장된 공식 HTML로 채운 개발 DB에서 375·430px × 7개 화면: 모두 200, 가로 넘침 0, 44px 미만 링크 0, JS 오류 0, 손글씨 글꼴 로드 확인
- 미확인: 실제 휴대폰, 공개 주소 반영(커밋·배포 전)
- 화면별 세부 모양(식단 날짜 선택, D-day, 달력, 시간표, 공지 목록)은 2~4단계에서 바꿈

## 구조와 데이터 흐름

```
[수집] collect_* 명령 / systemd timer
  → campus/collectors/{meals,events,notices}.py
      fetch: Playwright(크롬)로 공식 페이지 열기·주/연도/쪽 이동
      parse: BeautifulSoup 으로 표 해석 → 구조 검증(머리글·행 수·날짜)
      save : transaction.atomic 으로 한 번에 반영 (검증 실패 시 저장 없음)
  → CollectionRun (성공/실패, 건수, 실패 원인)

[화면] URL → views.py → data.py(Section: items + status) → DB 조회 → 템플릿
  status: ok / empty / error(마지막 수집 실패, 이전 데이터 유지) / stale(주기+1일 경과)

[PWA] /manifest.webmanifest, /sw.js(네트워크 우선 + 저장 화면), /offline/
```

## 구현 상태

### 실제 구현
- **식단**: 이번 주+다음 주 수집, (날짜, 끼니) 유일, 주 단위 교체, 주 전체 공백이면 기존 유지
- **학사일정**: 올해+내년 '전체' 보기 수집(1~2월 작년 포함), (과정, 제목, 시작, 종료) 유일, 공식 목록 중복 제거, "등록된 일정이 없습니다" 처리, 과정 필터 화면
- **공지**: 1~2쪽 수집, 게시글 번호 유일, 상단 고정(공식 '공지' 표시) 반영·해제, 제목 머리말 분류, 상세 원문 링크
- **관리 명령**: `collect_meals`, `collect_events`, `collect_notices`, `collect_all`(실패 격리, 실패 시 종료 코드 1)
- **관리자 화면**: 수집 기록(실패 원인·마지막 성공), 식단 조회
- **화면 상태**: 데이터 없음 / 수집 실패(이전 데이터 유지) / 오래된 데이터 / 저장된(오프라인) 화면 안내, 마지막 수집 시각·수집 주기·공식 원문 링크
- **PWA**: 매니페스트, 원본 아이콘 4종, 서비스 워커(화면 네트워크 우선·정적 캐시 우선·버전 자동 갱신·관리자/외부 링크 제외), 오프라인 안내 화면
- **자동 수집 설정**: `deploy/systemd/` (서비스 템플릿 1 + 타이머 3 + install.sh)

### Mock
- 시간표(예시 7개 수업), MY 안내

### 미구현 (예정)
- 실제 호스팅 등록·공개 주소(6a), 상시 서버의 Nginx·systemd·실제 타이머 등록(6b) → 6단계
- 실제 휴대폰 검증, QR → 7단계
- 로그인·계정·개인 시간표 (범위 밖, 방향만 문서화)

## 실행한 검증 (2026-11-02, 클라우드 Linux · Python 3.13.18 · Django 5.2.18 · Playwright 1.64.1)

| 확인 항목 | 방법 | 결과 |
|---|---|---|
| 기본 검사 | `check`, `makemigrations --check --dry-run` | 이슈 0, 변경 없음 |
| 자동 테스트 | `python manage.py test` | **54개 통과** (네트워크 없이, 2026-11-02 저장한 실제 공식 HTML 5개 사용) |
| 식단 실제 수집 | `collect_meals --weeks 2` 2회 | 42건 → 42건 (중복 없음), 1회 약 17초 |
| 식단 실제 실패 | `LOLYPOLY_COLLECTOR_TIMEOUT_MS=1` | 종료 코드 1, 실패 기록, 기존 42건 유지 |
| 학사일정·공지 실제 수집 | `collect_all` 반복 | 학사일정 93건(2026: 86, 2027: 8, 연도 걸친 1건 중복 없음), 공지 40건(고정 17) 재수집 후 동일 |
| 실제 실패 격리 | 첫 실제 수집에서 2027 '일정 없음' 안내 행으로 학사일정 실패 | 공지는 정상 저장, 화면 유지 → 원인 수정 후 해당 페이지를 테스트에 추가 |
| 화면 | Playwright + Chrome 375/430px, 6개 화면 × 상태 5종 | 가로 넘침 0, 44px 미만 링크 0, 주요 조작 정상 |
| PWA 설치 조건 | Chrome CDP `Page.getInstallabilityErrors` (localhost, 일반 프로필) | 오류 0 |
| 매니페스트 | CDP `Page.getAppManifest` | 오류 0, 아이콘 192/512/maskable |
| 오프라인 | Playwright 오프라인 전환 | 저장된 화면 표시, 미방문 화면 → 오프라인 안내, 관리자 화면 캐시 안 됨, 2시간 경과 시 "저장된 화면" 띠 표시 |
| 캐시 갱신 | CSS 변경 후 새로고침 | 새 버전 서비스 워커 활성화, 이전 캐시 삭제 |
| 자동 수집 설정 | `systemd-analyze verify`(경로 치환본), `systemd-analyze calendar`, `bash -n install.sh`, ExecStart 명령 직접 실행 | 경고 0, 다음 실행 2026-11-09 06:10/06:20/06:30 KST, 명령 성공 |

### 미확인 (실행하지 않음)
- 실제 Ubuntu 서버에 타이머 등록·자동 실행 (서버 없음)
- 실제 휴대폰(iOS Safari, Android Chrome)에서 설치·오프라인 동작 (HTTPS 주소 필요)
- Playwright 오프라인 흉내에서는 `navigator.onLine`이 true로 남아 "오프라인이에요" 문구는 미확인 (저장 시각 안내는 확인)
- 스크린리더 실제 낭독, 사용자 PC 실행

## 6a 프로토타입 배포 준비 (2026-11-03)

### 이번에 만든 것 (실제 구현)
- `requirements.txt`: Gunicorn 26.2.0, WhiteNoise 6.12.0 (D-011, D-033)
- `config/settings.py`: WhiteNoise 미들웨어, `DJANGO_HTTPS`(HTTPS 이동·보안 쿠키·프록시 헤더), `DJANGO_HSTS_SECONDS`, Render 공개 주소 자동 허용 (D-034)
- `Dockerfile`(2단계: 수집 → 실행), `.dockerignore` (D-035). 호스팅 선택지·근거는 D-036, 올리는 법은 README

### 실행한 검증 (클라우드 Linux · Docker 29.9.2)
| 확인 항목 | 방법 | 결과 |
|---|---|---|
| 기본 검사 | `check`, `makemigrations --check --dry-run`, `test` | 이슈 0, 변경 없음, **54개 통과** |
| 운영 보안 검사 | `check --deploy` (DEBUG=False, `DJANGO_HTTPS=True`) | 남은 경고 1개: W004 HSTS — 주소 확정 전 의도적 보류(D-034) |
| 이미지 빌드 + 실제 수집 | `docker build` | 식단 2주(메뉴 있는 날 6+6일), 학사일정 94건(2026: 86, 2027: 8), 공지 40건(고정 17) 수집, 수집 단계 약 69초, 이미지 453MB |
| 수집 실패 시 빌드 | 첫 빌드에서 인증서 오류로 3종 모두 실패 | 빌드는 계속, 화면은 "정보가 없어요" + 공식 홈페이지 링크(샘플 없음) |
| 운영 실행 | 컨테이너(DEBUG=False, Gunicorn 워커 2, `PORT=10000`) | 기동 직후 메모리 약 91MB |
| 화면 | Playwright 375/430px × 6개 화면 | 전부 200, 가로 넘침 0, JS 오류 0, 실제 데이터 표시(갱신 실패·오래됨 없음) |
| 정적 파일·PWA | `/static/css/app.css`, `/manifest.webmanifest`, `/sw.js` | 200, 올바른 Content-Type |
| 운영 동작 | 없는 주소, `?preview=error`, `X-Forwarded-Proto: http` | 404(디버그 화면 없음), 미리보기 꺼짐, HTTPS로 301 이동 |

검증 환경 메모: 클라우드 샌드박스의 프록시 때문에 검증 빌드에서만 ①베이스 이미지를 같은 공식 이미지의 AWS 미러(`public.ecr.aws/docker/library/python:3.13-slim-bookworm`)에서 받고 ②프록시 인증서를 이미지에 추가했다. 저장소의 `Dockerfile`에는 이 두 가지가 없다.

### 미확인 (실행하지 않음)
- Render 실제 등록·빌드·공개 HTTPS 주소 접속 (계정 필요 — 사용자 작업)
- Render 무료 인스턴스(512MB)에서의 실제 메모리·잠든 뒤 깨어나는 시간
- 실제 휴대폰에서 PWA 설치·오프라인 (공개 HTTPS 주소 필요 → 7단계)
- 원본 `Dockerfile` 그대로 일반 인터넷 환경에서 빌드 (샌드박스에서는 위 2가지 보정 필요)

### 남은 사용자 작업
1. Render 가입 → GitHub 저장소 연결 → 환경변수 2개 입력 (README "Render 무료 웹 서비스에 올리기")
2. 주 1회 "Clear build cache & deploy"로 데이터 갱신

## 제약·메모
- 공식 사이트 요청: 1회 `collect_all` 기준 약 8페이지(식단 2, 학사일정 1+2, 공지 2 + 이동), 페이지 사이 2초 대기, User-Agent에 프로젝트 표기
- 상태 미리보기의 "마지막 수집" 시각은 시연용 가짜 값 (DEBUG 전용)
- `check --deploy` 경고는 6단계에서 처리
- 공지 화면은 최대 100건을 한 목록으로 표시 (현재 40건) — 페이지 나누기 필요 여부 피드백 대기

## 다음 작업: 6단계 — Ubuntu 배포

필요한 사용자 정보(결정 전 진행 불가)
1. 서버 PC: Ubuntu 설치 여부, 24시간 가동 가능 여부
2. 외부 접속: 공유기 포트포워딩 가능 여부 / 학교망 / 터널(대안 비교 후 선택)
3. 주소: 도메인 구매 여부 또는 무료 대안

할 일
- Gunicorn 버전 확인·추가, systemd 서비스, Nginx(정적 파일·HTTPS), 운영 `.env`(DEBUG=False, 비밀키, ALLOWED_HOSTS, 보안 쿠키)
- `check --deploy` 경고 해결, 로그·백업(SQLite 파일)·재시작 절차
- 자동 수집 타이머 실제 등록·실행 확인

완료 기준
- 실제 서버에서 외부 HTTPS 접속 확인. 서버가 없으면 설정·절차만 만들고 배포는 미완료로 기록

## 이어서 작업하는 법 (어느 컴퓨터든)

```bash
git clone https://github.com/lovesome0405/Lolypoly.git   # 이미 있으면: git pull
cd Lolypoly
python scripts/setup.py --test --collect   # 가상환경·패키지·브라우저·.env·DB·테스트·실제 수집 (기존 .env/DB 보존)
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
python manage.py runserver
```

- 새 컴퓨터 설치 검증(2026-11-02, Linux): GitHub 파일만 있는 빈 폴더에서 `setup.py --test --collect` → 테스트 54개 통과·실제 수집 성공(약 1분 30초), 재실행 시 `.env`·DB 유지 확인. **Windows·macOS에서는 아직 실행해 보지 않음.**
