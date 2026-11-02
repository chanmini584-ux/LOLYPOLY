"""Lolypoly 화면 뷰.

흐름: URL → 뷰(여기) → campus/data.py 에서 Section 받기 → 템플릿 렌더링.
뷰는 요청마다 공식 홈페이지에 접속하지 않는다.

데이터 상태: 식단은 수집된 실제 데이터(DB), 학사일정·공지는 4단계 전까지 Mock, 시간표·MY는 Mock 화면.
날짜·월·분류 선택은 JavaScript 없이 GET 파라미터(?date= ?month= ?category=)로 처리한다.
"""

from datetime import date, timedelta

from django.shortcuts import render
from django.utils import timezone

from . import data, mock_data

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

def home(request):
    today = timezone.localdate()
    preview = data.preview_state(request)
    meals = data.meals_week(data.week_start(today), today, preview)
    today_meal = next((d for d in meals.items if d["date"] == today), None)
    today_collected = today_meal is not None
    events = data.events(today, preview)
    notices = data.notices(today, preview)
    return render(request, "campus/home.html", {
        "page_title": "홈",
        "today": today,
        "meals": meals,
        "today_meals": _meal_rows(today_meal),
        "today_collected": today_collected,
        "events": events,
        "upcoming": _upcoming(events.items, today, 3),
        "notices": notices,
        "latest_notices": notices.items[:3],
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
