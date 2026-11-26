"""식단 수집.

공식 페이지 구조 (2026-11-02 확인)
- table.tbl_table.menu : 머리글 [구분, 조식, 중식, 석식], 본문 7행(월~일)
- 행 첫 칸: getDay2('YYYY-MM-DD 00:00:00.0') 스크립트로 날짜 + 요일
- 끼니 칸: <span> 안에 "메뉴 , 메뉴 , ..." (괄호 안 쉼표는 메뉴 일부. 예: 간편식(컵밥,빵,음료))
- 주 이동: a.next_week (지난주/다음주) → 같은 주소로 day=YYYYMMDD POST
- table.tbl_table.time : caption "식사시간표", 머리글 [빈칸, 아침, 점심, 저녁], 본문 1행(주중) (2026-11-24 확인, ERR-015)
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from ..models import CollectionRun, Meal, MealHours
from .base import ParseError, browser_page, polite_pause, run_collection
from .sources import MEALS_URL

MEAL_COLUMNS = [Meal.MealType.BREAKFAST, Meal.MealType.LUNCH, Meal.MealType.DINNER]
EXPECTED_HEADERS = ["구분", "조식", "중식", "석식"]
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
MAX_WEEKS = 4


@dataclass
class MealDay:
    date: date
    meals: dict = field(default_factory=dict)  # {"breakfast": [...], ...}

    @property
    def is_blank(self) -> bool:
        return not any(self.meals.values())


# ── 파싱 ──────────────────────────────────────────

def split_menu(text: str) -> list[str]:
    """쉼표로 메뉴를 나눈다. 괄호 안의 쉼표는 나누지 않는다."""
    items, buf, depth = [], [], 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    items.append("".join(buf))
    return [re.sub(r"\s+", " ", i).strip() for i in items if i.strip()]


def parse_meal_week(html: str) -> list[MealDay]:
    """식단 페이지 HTML → 7일치 MealDay. 구조가 다르면 ParseError."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tbl_table.menu")
    if table is None:
        raise ParseError("식단 표(table.tbl_table.menu)를 찾지 못했습니다.")

    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    if headers != EXPECTED_HEADERS:
        raise ParseError(f"식단 표 머리글이 예상과 다릅니다: {headers}")

    rows = table.select("tbody > tr")
    if len(rows) != 7:
        raise ParseError(f"식단 표 행 수가 7이 아닙니다: {len(rows)}")

    days = []
    for tr in rows:
        cells = tr.find_all("td", recursive=False)
        if len(cells) != 4:
            raise ParseError(f"식단 행의 칸 수가 4가 아닙니다: {len(cells)}")
        m = DATE_RE.search(str(cells[0]))  # 스크립트 안 날짜도 포함해 찾는다
        if not m:
            raise ParseError("식단 행에서 날짜를 찾지 못했습니다.")
        day = MealDay(date=date(*map(int, m.groups())))
        for meal_type, cell in zip(MEAL_COLUMNS, cells[1:]):
            text = " ".join(
                s.get_text(" ", strip=True) for s in cell.find_all("span") if "kcal" not in (s.get("class") or [])
            )
            day.meals[meal_type] = split_menu(text)
        days.append(day)

    # 검증: 월요일부터 7일 연속
    first = days[0].date
    if first.weekday() != 0:
        raise ParseError(f"식단 주의 첫 날이 월요일이 아닙니다: {first}")
    if [d.date for d in days] != [first + timedelta(days=i) for i in range(7)]:
        raise ParseError("식단 날짜가 7일 연속이 아닙니다.")
    return days


HOURS_KEYS = {"아침", "점심", "저녁"}
HOURS_RE = re.compile(r"^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$")


def parse_meal_hours(html: str) -> dict | None:
    """식사시간표. 표가 없거나 형식이 기대와 다르면 None(저장하지 않음 → 기존 데이터 유지)."""
    table = BeautifulSoup(html, "html.parser").select_one("table.tbl_table.time")
    if table is None:
        return None
    heads = [th.get_text(strip=True) or "구분" for th in table.select("thead th")]
    if heads[:1] != ["구분"] or not HOURS_KEYS & set(heads):
        return None
    rows = []
    for tr in table.select("tbody tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) != len(heads):
            return None
        row = dict(zip(heads, cells))
        if not all(HOURS_RE.match(row[k]) for k in heads[1:] if row[k]):
            return None
        rows.append(row)
    if not rows:
        return None
    cap = table.select_one("caption")
    return {"caption": cap.get_text(strip=True) if cap else "식사시간표", "headers": heads, "rows": rows}


def save_meal_hours(hours: dict | None, collected_at) -> str:
    """같은 트랜잭션 안에서 호출. 바뀐 내용이 없으면 원래 수집 시각을 유지한다."""
    if hours is None:
        return "식사시간표: 찾지 못해 기존 데이터 유지"
    cur = MealHours.objects.first()
    if cur and (cur.caption, cur.headers, cur.rows) == (hours["caption"], hours["headers"], hours["rows"]):
        return "식사시간표: 변경 없음"
    MealHours.objects.all().delete()
    MealHours.objects.create(source_url=MEALS_URL, collected_at=collected_at, **hours)
    return "식사시간표: 갱신"


# ── 가져오기 (Playwright) ──────────────────────────

def fetch_meal_pages(weeks: int) -> list[str]:
    """이번 주부터 weeks 주 분량의 식단 페이지 HTML. '다음주' 링크를 눌러 이동한다."""
    pages = []
    with browser_page() as page:
        page.goto(MEALS_URL)
        pages.append(page.content())
        for _ in range(weeks - 1):
            polite_pause()
            with page.expect_navigation():
                page.click("a.next_week")
            pages.append(page.content())
    return pages


# ── 저장 ──────────────────────────────────────────

def save_meal_weeks(weeks: list[list[MealDay]], collected_at=None) -> tuple[int, list[str]]:
    """검증된 주 단위 식단을 한 트랜잭션으로 저장한다.

    - 주 단위로 기존 행을 교체 → 재수집해도 중복 없음, 메뉴 변경도 반영
    - 새로 받은 주가 통째로 비어 있는데 기존에 메뉴가 있었다면 덮어쓰지 않는다
      (게시 전 공백인지 오류인지 알 수 없으므로 기존 정상 데이터 유지)
    """
    collected_at = collected_at or timezone.now()
    saved, notes = 0, []
    with transaction.atomic():
        for week in weeks:
            dates = [d.date for d in week]
            existing = Meal.objects.filter(date__in=dates)
            if all(d.is_blank for d in week) and any(m.items for m in existing):
                notes.append(f"{dates[0]} 주: 새 결과가 모두 비어 있어 기존 데이터 유지")
                continue
            existing.delete()
            Meal.objects.bulk_create([
                Meal(date=d.date, meal_type=t, items=d.meals.get(t, []),
                     source_url=MEALS_URL, collected_at=collected_at)
                for d in week for t in MEAL_COLUMNS
            ])
            saved += len(week) * len(MEAL_COLUMNS)
            filled = sum(1 for d in week if not d.is_blank)
            notes.append(f"{dates[0]}~{dates[-1]}: 메뉴 있는 날 {filled}일")
    return saved, notes


def collect_meals(weeks: int = 2, fetcher=fetch_meal_pages) -> CollectionRun:
    """식단 수집 1회. fetcher 는 테스트에서 가짜로 바꿔 끼울 수 있다."""
    weeks = max(1, min(weeks, MAX_WEEKS))

    def job():
        pages = fetcher(weeks)
        parsed = [parse_meal_week(html) for html in pages]  # 하나라도 실패하면 저장 없이 종료
        starts = [w[0].date for w in parsed]
        if len(set(starts)) != len(starts):
            raise ParseError(f"같은 주가 중복 수집되었습니다: {starts}")
        hours = parse_meal_hours(pages[0])
        with transaction.atomic():
            count, notes = save_meal_weeks(parsed)
            notes.append(save_meal_hours(hours, timezone.now()))
        return count, " / ".join(notes)

    return run_collection(CollectionRun.Source.MEALS, job)
