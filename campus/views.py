"""Lolypoly 화면 뷰.

흐름: URL → 뷰(여기) → campus/data.py 에서 Section 받기 → 템플릿 렌더링.
뷰는 요청마다 공식 홈페이지에 접속하지 않는다. 예외: bus_live 는 TAGO 버스 API 를 서버 캐시를 거쳐 부른다(D-041).

데이터 상태: 식단은 수집된 실제 데이터(DB), 학사일정·공지는 4단계 전까지 Mock, 시간표·MY는 Mock 화면.
날짜·월·분류 선택은 JavaScript 없이 GET 파라미터(?date= ?month= ?category=)로 처리한다.
"""

from datetime import date, timedelta

from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from . import bus as bus_data
from . import data, mock_data, tago
from .bus_timetable import SOURCE as TIMETABLE_SOURCE
from .bus_timetable import TIMETABLES

MEAL_LABELS = [("breakfast", "조식"), ("lunch", "중식"), ("dinner", "석식")]


# ── 공통 도우미 ─────────────────────────────────────

def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return default


def _parse_month(value: str | None, default: date) -> date:
    """'YYYY-MM' → 그 달 1일. 잘못된 값이면 default가 속한 달."""
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        return date(y, m, 1)
    except ValueError:
        return default.replace(day=1)


def _add_months(first: date, n: int) -> date:
    idx = first.year * 12 + (first.month - 1) + n
    return date(idx // 12, idx % 12 + 1, 1)


def _dday(event: dict, today: date) -> str:
    if event["start"] <= today <= event["end"]:
        return "진행 중" if event["start"] != event["end"] else "오늘"
    return f"D-{(event['start'] - today).days}"


def _meal_rows(day: dict | None) -> list[dict]:
    """하루 식단 → 끼니별 행. 수집 안 된 날이거나 공식 식단표가 통째로 빈 날은 빈 목록."""
    if not day or not any(day[key] for key, _ in MEAL_LABELS):
        return []
    return [{"label": label, "items": day[key]} for key, label in MEAL_LABELS]


def _upcoming(events: list[dict], today: date, limit: int) -> list[dict]:
    items = [e for e in events if e["end"] >= today][:limit]
    return [{**e, "dday": _dday(e, today)} for e in items]


# ── 화면 ────────────────────────────────────────────

STICKER_COLORS = ["pink", "mint", "sky"]


def home(request):
    today = timezone.localdate()
    preview = data.preview_state(request)
    start = data.week_start(today)
    meals = data.meals_week(start, today, preview)
    by_date = {d["date"]: d for d in meals.items}
    # 이번 주 밥: 요일 동그라미 7개 + 날짜별 메모. ?day= 로 고른 날(JS가 있으면 새로고침 없이 바뀜)
    selected_day = _parse_date(request.GET.get("day"), today)
    if not start <= selected_day < start + timedelta(days=7):
        selected_day = today
    week = []
    for d in (start + timedelta(days=i) for i in range(7)):
        rows = _meal_rows(by_date.get(d))
        week.append({"date": d, "rows": rows, "collected": d in by_date, "has_meal": bool(rows),
                     "is_today": d == today, "is_selected": d == selected_day, "is_past": d < today})
    events = data.events(today, preview)
    notices = data.notices(today, preview)
    upcoming = _upcoming(events.items, today, 3)
    for i, e in enumerate(upcoming):
        e["color"] = STICKER_COLORS[i % len(STICKER_COLORS)]
    return render(request, "campus/home.html", {
        "page_title": "홈",
        "today": today,
        "meals": meals,
        "week": week,
        "events": events,
        "upcoming": upcoming,
        "notices": notices,
        "latest_notices": notices.items[:3],
        "has_bus": bool(bus_data.groups()),
    })


def meals(request):
    today = timezone.localdate()
    selected = _parse_date(request.GET.get("date"), today)
    start = data.week_start(selected)
    section = data.meals_week(start, today, data.preview_state(request))
    by_date = {d["date"]: d for d in section.items}
    week_days = [
        {"date": d, "has_meal": bool(_meal_rows(by_date.get(d)))}
        for d in (start + timedelta(days=i) for i in range(7))
    ]
    return render(request, "campus/meals.html", {
        "page_title": "식단",
        "today": today,
        "selected": selected,
        "week_days": week_days,
        "week_start": start,
        "week_end": start + timedelta(days=6),
        "prev_week": start - timedelta(days=7),
        "next_week": start + timedelta(days=7),
        "section": section,
        "meal_rows": _meal_rows(by_date.get(selected)),
        "day_collected": selected in by_date,
    })


def schedule(request):
    today = timezone.localdate()
    month = _parse_month(request.GET.get("month"), today)
    next_month = _add_months(month, 1)
    section = data.events(today, data.preview_state(request))
    courses = sorted({e["course"] for e in section.items if e["course"]}, key=lambda c: (c != "공통", c))
    course = request.GET.get("course", "")
    if course not in courses:
        course = ""
    # 과정 필터: 선택한 과정 + [공통] 일정
    events = [e for e in section.items if not course or e["course"] in (course, "공통")]
    month_events = [
        e for e in events
        if e["start"] < next_month and e["end"] >= month  # 그 달과 기간이 겹치는 일정
    ]
    return render(request, "campus/schedule.html", {
        "page_title": "학사일정",
        "today": today,
        "section": section,
        "upcoming": _upcoming(events, today, 3),
        "courses": [c for c in courses if c != "공통"],
        "selected_course": course,
        "month": month,
        "prev_month": _add_months(month, -1),
        "next_month": next_month,
        "is_this_month": month == today.replace(day=1),
        "month_events": [{**e, "is_past": e["end"] < today} for e in month_events],
    })


def notices(request):
    today = timezone.localdate()
    section = data.notices(today, data.preview_state(request))
    categories = sorted({n["category"] for n in section.items if n["category"]})
    selected = request.GET.get("category", "")
    if selected not in categories:
        selected = ""
    items = [n for n in section.items if not selected or n["category"] == selected]
    return render(request, "campus/notices.html", {
        "page_title": "공지사항",
        "section": section,
        "categories": categories,
        "selected_category": selected,
        "items": items,
    })


# 시간표 그리드: 09:00~18:00, 30분 칸
TT_START_HOUR, TT_END_HOUR = 9, 18
DAY_NAMES = ["월", "화", "수", "목", "금"]


def _slot(t) -> int:
    return (t.hour - TT_START_HOUR) * 2 + t.minute // 30


def timetable(request):
    today = timezone.localdate()
    # 같은 과목은 같은 색 (과목명 등장 순서로 4가지 색 순환)
    colors = {t: i % 4 for i, t in enumerate(dict.fromkeys(row[3] for row in mock_data.TIMETABLE))}
    classes = []
    for day, start, end, title, room in mock_data.TIMETABLE:
        end_slot = _slot(end) + (1 if end.minute % 30 else 0)
        classes.append({
            "day": day, "day_name": DAY_NAMES[day],
            "start": start, "end": end, "title": title, "room": room,
            "col": day + 2,                     # 1열은 시간 표시
            "row": _slot(start) + 2,            # 1행은 요일 표시
            "span": max(end_slot - _slot(start), 1),
            "is_today": day == today.weekday(),
            "color": colors[title],
        })
    return render(request, "campus/timetable.html", {
        "page_title": "시간표",
        "today": today,
        "is_weekend": today.weekday() >= 5,
        "days": [{"name": n, "col": i + 2, "is_today": i == today.weekday()} for i, n in enumerate(DAY_NAMES)],
        "hours": [{"label": h, "row": (h - TT_START_HOUR) * 2 + 2} for h in range(TT_START_HOUR, TT_END_HOUR)],
        "rows": (TT_END_HOUR - TT_START_HOUR) * 2,
        "classes": classes,
        "today_classes": [c for c in classes if c["is_today"]],
    })


def my(request):
    return render(request, "campus/my.html", {"page_title": "MY"})


# ── 버스 ────────────────────────────────────────────

def bus(request):
    """학교 정류장을 지나는 노선의 줄그림. 실시간 위치는 bus.js 가 bus_live 에서 받아 그린다."""
    section = data.bus_routes(data.preview_state(request))
    keys = [g["key"] for g in section.items]
    selected = request.GET.get("route", "")
    if selected not in keys:
        selected = keys[0] if keys else ""
    panels = bus_data.build_panels(bus_data.variants(selected)) if selected else []
    return render(request, "campus/bus.html", {
        "page_title": "버스",
        "section": section,
        "selected": selected,
        "selected_type": next((g["type"] for g in section.items if g["key"] == selected), ""),
        "panels": panels,
        "timetable": TIMETABLES.get(selected),
        "timetable_source": TIMETABLE_SOURCE,
        "live_enabled": tago.has_key(),
    })


@never_cache
def bus_live(request, group):
    """탭 하나의 실시간 버스 위치(JSON). 서버 캐시를 거치므로 자주 불러도 TAGO 호출은 제한된다."""
    if group not in {g["key"] for g in bus_data.groups()}:
        raise Http404("노선 없음")
    return JsonResponse(bus_data.live(group), json_dumps_params={"ensure_ascii": False})


@never_cache
def bus_nearest(request):
    """홈 '학교 가는 버스' 한 줄: 모든 노선 중 학교에 가장 가까운 버스 1대(JSON). 홈을 열 때 한 번만 부른다."""
    return JsonResponse(bus_data.nearest(), json_dumps_params={"ensure_ascii": False})
