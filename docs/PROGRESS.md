# 진행 상황

마지막 갱신: 2026-11-02 · 현재 단계: **5단계 완료 → 사용자 피드백 대기**

## 단계 현황

| 단계 | 상태 |
|---|---|
| 1. 프로젝트 기반 구축 | ✅ 완료 |
| 2. 모바일 UI Mock | ✅ 완료 |
| 3. 식단 실제 연동 | ✅ 완료 |
| 4. 학사일정·공지·홈 통합 | ✅ 완료 |
| 5. PWA·자동 갱신 | ✅ 완료 — 단, 자동 수집은 **설정 파일 작성·검증까지** (실제 서버 등록·실행은 6단계) |
| 6. Ubuntu 배포 | ⏳ 대기 — 서버 정보 필요 |
| 7. 스마트폰 실사용 검증 | 미착수 |
| 8. 기획서·제안서 | 미착수 (요청 시) |

Git: 1~5단계 작업은 2026-11-02 `main`에 커밋·푸시 완료 (d442723). 이후 커밋은 사용자가 "여기까지"라고 할 때 한다.

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
- 운영 배포(Nginx·Gunicorn·HTTPS·운영 보안 설정), 실제 타이머 등록 → 6단계
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

## 이어서 작업하는 법

```bash
cd Lolypoly
source .venv/bin/activate          # 없으면: python3 -m venv .venv && pip install -r requirements.txt
python -m playwright install chromium
cp -n .env.example .env
python manage.py migrate
python manage.py test
python manage.py collect_all       # 실제 데이터 (네트워크 필요)
python manage.py runserver
```
