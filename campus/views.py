"""Lolypoly 화면 뷰.

흐름: URL → 뷰(여기) → campus/data.py 에서 Section 받기 → 템플릿 렌더링.
뷰는 요청마다 공식 홈페이지에 접속하지 않는다. 예외: bus_live 는 TAGO 버스 API 를 서버 캐시를 거쳐 부른다(D-053).

데이터 상태: 식단·학사일정·공지·버스 노선은 수집된 실제 데이터(DB), 시간표·MY는 Mock 화면.
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

# 날짜·월 선택 허용 범위: 오늘 기준 앞뒤 3년. 0001·9999년 같은 값은 날짜 계산이 넘쳐 500 오류가 났었다(D-062).
DATE_RANGE_DAYS = 366 * 3


def _in_range(value: date, today: date) -> bool:
    return abs((value - today).days) <= DATE_RANGE_DAYS


def _parse_date(value: str | None, default: date) -> date:
    """'YYYY-MM-DD' → 날짜. 형식이 틀리거나 허용 범위를 벗어나면 default."""
    try:
        parsed = date.fromisoformat(value) if value else default
    except (ValueError, TypeError):
        return default
    return parsed if _in_range(parsed, default) else default


def _parse_month(value: str | None, default: date) -> date:
    """'YYYY-MM' → 그 달 1일. 잘못된 값이거나 허용 범위를 벗어나면 default가 속한 달."""
    try:
        y, m = (int(x) for x in (value or "").split("-"))
        parsed = date(y, m, 1)
    except (ValueError, TypeError, OverflowError):
        return default.replace(day=1)
    return parsed if _in_range(parsed, default) else default.replace(day=1)


def _date_notice(raw: str | None, used: date, kind: str) -> str:
    """주소에 넣은 날짜를 쓰지 못했을 때 화면에 보여 줄 안내."""
    if not raw:
        return ""
    shown = used.strftime("%Y-%m-%d" if kind == "date" else "%Y-%m")
    return "" if raw == shown else "고른 날짜를 볼 수 없어서 오늘 기준으로 보여 드려요."


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
# 홈 '최신 공지'에서 빼는 분류 (D-058): 시설대여·구매 평가·업무추진비처럼 학생 생활과 먼 공지가 맨 위를 차지해서.
# 공지사항 화면(전체 보기)에는 그대로 모두 나온다.
HOME_NOTICE_EXCLUDE = {"행정"}


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
        "latest_notices": [n for n in notices.items if n["category"] not in HOME_NOTICE_EXCLUDE][:3],
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
        "date_notice": _date_notice(request.GET.get("date"), selected, "date"),
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
        "date_notice": _date_notice(request.GET.get("month"), month, "month"),
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
    """MY: 로그인 전에는 가입·로그인 안내, 로그인 뒤에는 내 학과·내 활동·계정 메뉴.

    로그인 여부에 따라 내용이 달라지므로 저장 금지(no-store) 화면이다(PrivateCacheMiddleware).
    """
    context = {"page_title": "MY"}
    if request.user.is_authenticated:
        from community.models import Notification
        from community.policy import is_moderator

        context.update({
            "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count(),
            "is_moderator": is_moderator(request.user),
        })
    return render(request, "campus/my.html", context)


FEEDBACK_COOKIE = "lp_fb"


def feedback(request):
    """시범 운영 의견 보내기. 로그인 없이 쓸 수 있다. 개인정보를 받지 않는다."""
    import secrets

    from django.shortcuts import redirect

    from .feedback import FeedbackForm, browser_hash, client_hash, rate_limited, save_feedback

    if request.GET.get("sent") == "1":
        return render(request, "campus/feedback_done.html", {"page_title": "의견 보내기"})
    limited = False
    token = request.COOKIES.get(FEEDBACK_COOKIE, "")
    if request.method == "POST":
        form = FeedbackForm(request.POST)
        chash, bhash = client_hash(request), browser_hash(token)
        if rate_limited(chash, bhash):
            limited = True
        elif form.is_valid():
            save_feedback(form, chash, bhash)
            return redirect(f"{request.path}?sent=1")
    else:
        form = FeedbackForm()
    response = render(request, "campus/feedback.html", {"page_title": "의견 보내기", "form": form, "limited": limited})
    if not token:
        # 도배 제한용 무작위 값(개인 식별 정보 아님). 같은 Wi-Fi 의 다른 학생과 한도를 나눠 쓰지 않게 브라우저별로 센다.
        response.set_cookie(FEEDBACK_COOKIE, secrets.token_urlsafe(16), max_age=60 * 60 * 24 * 30, httponly=True,
                            samesite="Lax", secure=request.is_secure())
    return response


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
