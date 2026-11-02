"""화면에 보여줄 데이터를 '섹션' 단위로 돌려주는 계층.

뷰는 이 모듈만 호출한다. 데이터 출처가 바뀌어도 뷰·템플릿은 그대로다.
- 식단·학사일정·공지: DB(수집 결과)만 조회한다. 수집 전이면 '데이터 없음'이며 예시 데이터로 채우지 않는다.
- 시간표 Mock 은 views.py 가 mock_data 에서 직접 가져온다.

Section.status
- "ok"    : 정상
- "empty" : 보여줄 데이터 없음 (수집 전 포함)
- "error" : 마지막 수집 실패 (items 가 있으면 '이전 정상 데이터'를 계속 보여줌)
- "stale" : 마지막 성공 수집이 '수집 주기 + 1일'보다 오래됨
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .collectors.sources import EVENTS_URL, MEALS_URL, NOTICES_URL
from .models import AcademicEvent, CollectionRun, Meal, Notice

PREVIEW_STATES = ("empty", "error", "error-empty", "stale")
PREVIEW_STALE_DAYS = 10


@dataclass
class Section:
    items: list
    is_mock: bool = False
    status: str = "ok"
    last_success_at: datetime | None = None
    stale_days: int | None = None
    source_url: str = ""
    interval_days: int | None = None


def preview_state(request) -> str:
    """?preview= 값. 설정으로 켜져 있을 때만(기본: DEBUG) 인정한다."""
    if not settings.LOLYPOLY_STATE_PREVIEW:
        return ""
    value = request.GET.get("preview", "")
    return value if value in PREVIEW_STATES else ""


def _apply_preview(section: Section, preview: str) -> Section:
    now = timezone.now()
    if preview == "empty":
        section.items, section.status = [], "empty"
    elif preview == "error":
        section.status = "error"
        section.last_success_at = section.last_success_at or now - timedelta(days=3)
    elif preview == "error-empty":
        section.items, section.status = [], "error"
    elif preview == "stale":
        section.status = "stale"
        section.last_success_at = now - timedelta(days=PREVIEW_STALE_DAYS)
        section.stale_days = PREVIEW_STALE_DAYS
    return section


def _finish(section: Section, preview: str) -> Section:
    section = _apply_preview(section, preview)
    if not section.items and section.status == "ok":
        section.status = "empty"
    return section


def collection_state(source: str) -> dict:
    """수집 기록으로 상태를 정한다: 마지막 실행 실패 → error, 오래됨 → stale."""
    runs = CollectionRun.objects.filter(source=source).exclude(status=CollectionRun.Status.RUNNING)
    last = runs.first()
    last_success = runs.filter(status=CollectionRun.Status.SUCCESS).first()
    interval = settings.LOLYPOLY_COLLECT_INTERVAL_DAYS.get(source, 7)
    state = {
        "status": "ok",
        "last_success_at": last_success.finished_at if last_success else None,
        "stale_days": None,
        "interval_days": interval,
    }
    if last and last.status == CollectionRun.Status.FAILED:
        state["status"] = "error"
    elif last_success:
        age = (timezone.now() - last_success.finished_at).days
        if age > interval:  # 주기 + 1일 이상 지남
            state["status"], state["stale_days"] = "stale", age
    return state


# ── 식단 (실제 데이터) ───────────────────────────────

def week_start(d: date) -> date:
    """d가 속한 주의 월요일."""
    return d - timedelta(days=d.weekday())


MEAL_ORDER = [Meal.MealType.BREAKFAST, Meal.MealType.LUNCH, Meal.MealType.DINNER]


def meals_week(start: date, today: date | None = None, preview: str = "") -> Section:
    """start(월요일)부터 7일의 식단. 수집된 날만 items 에 들어간다."""
    rows = Meal.objects.filter(date__gte=start, date__lt=start + timedelta(days=7))
    by_date: dict = {}
    for m in rows:
        by_date.setdefault(m.date, {t: [] for t in MEAL_ORDER})[m.meal_type] = list(m.items)
    items = [
        {"date": d, "breakfast": v[Meal.MealType.BREAKFAST], "lunch": v[Meal.MealType.LUNCH],
         "dinner": v[Meal.MealType.DINNER]}
        for d, v in sorted(by_date.items())
    ]
    section = Section(items=items, source_url=MEALS_URL, **collection_state(CollectionRun.Source.MEALS))
    return _finish(section, preview)


# ── 학사일정 ─────────────────────────────────────

def events(today: date | None = None, preview: str = "") -> Section:
    """수집된 학사일정 전체(시작일 순). 화면에서 다가오는 일정·월별로 다시 거른다."""
    items = [
        {"title": e.title, "course": e.course, "start": e.start_date, "end": e.end_date}
        for e in AcademicEvent.objects.all()
    ]
    section = Section(items=items, source_url=EVENTS_URL, **collection_state(CollectionRun.Source.EVENTS))
    return _finish(section, preview)


# ── 공지 ────────────────────────────────────────

NOTICE_LIMIT = 100


def notices(today: date | None = None, preview: str = "") -> Section:
    """최신 게시일 순 공지(최대 100건)."""
    items = []
    for n in Notice.objects.all()[:NOTICE_LIMIT]:
        prefix = f"[{n.category}]" if n.category else ""
        display = n.title[len(prefix):].strip() if prefix and n.title.startswith(prefix) else n.title
        items.append({
            "title": n.title, "display_title": display or n.title, "category": n.category,
            "author": n.author, "posted_on": n.posted_on, "is_pinned": n.is_pinned, "url": n.source_url,
        })
    section = Section(items=items, source_url=NOTICES_URL, **collection_state(CollectionRun.Source.NOTICES))
    return _finish(section, preview)
