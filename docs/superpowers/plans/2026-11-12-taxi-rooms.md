# 번개 택시방 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인한 학생이 택시 합승 방을 만들고, 선착순으로 들어온 학생과 익명으로 대화하다가 방이 닫히면 사라지는 기능.

**Architecture:** community 앱 안에 모델 4개(TaxiRoom·TaxiMember·TaxiMessage·TaxiReport)와 서비스 모듈 `community/taxi.py`, 뷰 모듈 `community/taxi_views.py`를 둔다. 화면은 Django 템플릿, 실시간은 `static/js/taxi.js`가 3초마다 JSON을 묻는 폴링. 정원 경쟁은 트랜잭션 첫 줄에서 방 행을 UPDATE 해 SQLite 쓰기 잠금을 먼저 잡아 직렬화한다.

**Tech Stack:** Django 5.2.19, SQLite, Django Template, 바닐라 JS.

**Spec:** `docs/superpowers/specs/2026-11-11-taxi-rooms-design.md`

## Global Constraints

- 정원 2·3·4명(방장 포함). 방장인 열린 방 ≤ 1, 참여 중 열린 방 ≤ 2. 출발 시각 = 지금 ~ 지금+24시간(Asia/Seoul 입력, UTC 저장).
- 열림 = status=open 그리고 now < departs_at + 1시간. 닫힘 사유: host / expired / moderator.
- 표시 이름: 번호 0 = "방장", n = f"익명{n}". 재입장은 같은 번호.
- 메시지 글자만 200자, 도배 제한 10초에 5개. 출발지·도착지 30자, 한마디 40자.
- 닫힌(숨김 포함) 지 7일 지난 방 삭제. 처리 전 신고가 있거나 마지막 신고 처리 후 7일 안이면 보관.
- 비로그인 = 로그인 화면. 닫힌 방·비참여자 메시지 조회 = 404/403. 개인 화면 no-store(기존 PrivateCacheMiddleware 가 /community/ 처리).
- 학생 화면·주소에 계정 ID·아이디 없음.

## Review Focus

- 두 사람이 마지막 한 자리에 동시에 입장 → 한 명만 성공 (Task 2 동시성 테스트)
- 출발 1시간이 지났는데 아무도 손대지 않은 방 → 목록·입장·메시지 모두 닫힘 처리 (Task 2)
- 나간 사람이 메시지 JSON 주소를 계속 부름 → 403 (Task 3)
- 내가 차단한 사람이 방장인 방 → 목록에 안 보이고 입장 거절 (Task 2)
- 출발 시각을 과거·24시간 넘게 입력 → 폼 오류, 방 안 만들어짐 (Task 3)

---

### Task 1: 모델·마이그레이션

**Files:** Modify `community/models.py`, `community/admin.py`; Create `community/migrations/0003_taxi.py` (makemigrations)

**Produces:** `TaxiRoom(host, origin, destination, departs_at, capacity, note, status[open/closed/hidden], close_reason, created_at, closed_at, touched_at)`, `TaxiRoom.closes_at` property(departs_at+1h), `TaxiMember(room, user, number, joined_at, left_at)` unique(room,user), `TaxiMessage(room, member null, kind[text/system], body, created_at)`, `TaxiReport(reporter, room, message null, reason(Report.REASONS), detail, status(Report.STATUSES), created_at, handled_at, handled_by)` + 중복 방지 조건부 유일 제약 2개, `ModerationLog.taxi_room` FK(SET_NULL).

- [ ] makemigrations → 표 추가 + 칸 추가만인지 확인, `check` 통과, 커밋

### Task 2: 서비스 `community/taxi.py`

**Produces:**
`label(number)->str`, `close_expired(now=None)->int`, `open_rooms(user, now=None)->QuerySet`(차단한 방장 제외, 출발 순),
`active_member(room, user)->TaxiMember|None`, `create_room(user, *, origin, destination, departs_at, capacity, note)->TaxiRoom`,
`join(room, user)->TaxiMember`, `leave(room, user)`, `pop(room, user)`, `send(room, user, body)->TaxiMessage`,
`messages_after(room, after_id)->list`, `report(user, room, message=None, *, reason, detail)->bool`,
`moderate_hide(moderator, room, reason)`, `purge_closed(now=None)->int`. 거절은 기존 `services.Rejected`.

- [ ] `community/tests/test_taxi.py`: 만들기 제한(열린 방장 방 1개, 참여 2개, 이용 제한 거절) / 입장 번호 1·2, 재입장 같은 번호 / 정원 초과 거절 / 방장 leave 거절, pop 후 open_rooms 에서 제외 / 출발+1h 지나면 close_expired 가 closed·expired / 차단한 방장 방 목록 제외·입장 거절 / send 도배(10초 6번째 거절) / 비참여 send 거절 / purge: 닫힌 지 8일 삭제, 6일 보존, 처리 전 신고 있으면 보존 / 동시 입장 스레드 5개·남은 자리 1 → 성공 1
- [ ] 실패 확인 → 구현 → 통과 → 커밋

### Task 3: 화면·주소·JS

**Files:** Create `community/taxi_views.py`, `templates/community/taxi/{list,new,room,report,manage}.html`, `static/js/taxi.js`; Modify `community/forms.py`(TaxiRoomForm: day today/tomorrow, time, origin, destination, capacity, note → `clean()`이 aware departs_at 계산·범위 검사; TaxiMessageForm), `community/urls.py`, `static/css/app.css`, `templates/community/home.html`(택시 카드), `templates/community/rules.html`(택시 안내), `community/views.py manage_reports`(택시 신고 목록)

**주소(name):** `taxi/`(taxi_list) `taxi/new/`(taxi_new) `taxi/<pk>/`(taxi_room) `taxi/<pk>/join|leave|pop|send/`(POST) `taxi/<pk>/messages/`(JSON, `?after=`) `taxi/<pk>/report/` `taxi/m/<pk>/report/` `manage/taxi/<pk>/`

- [ ] 뷰 테스트: 비로그인 → 로그인 화면 / 만들기 폼 과거·25시간 뒤 오류 / 방 만들기 → 방 화면 이동 / 비참여자 방 화면 = 입장 버튼, 대화 없음 / messages JSON 비참여·나간 사람 403, 참여자 200·after 이후만 / 닫힌 방 학생 404, 운영자 manage 200 / 신고 중복 / no-store
- [ ] 구현 → 통과 → 브라우저 375·430px(두 계정 대화·정원 마감·터뜨리기) → 커밋

### Task 4: 정리 명령·문서·릴리스 기록

**Files:** Modify `community/management/commands/purge_community.py`(taxi.purge_closed 호출·출력), `AGENTS.md`(범위: 택시 합승 임시 채팅 D-070), `docs/DECISIONS.md`(D-070, D-071), `README.md`(Unreleased), `docs/PROGRESS.md`, spec(신고 표 분리 반영)

- [ ] purge 명령 테스트 → 전체 `check`·`makemigrations --check`·`test` → 커밋·푸시. 버전(v0.4.0-beta)·태그·main 반영은 사용자 승인 후.
