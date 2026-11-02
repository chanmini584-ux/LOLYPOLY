"""학사일정 수집.

공식 페이지 구조 (2026-11-02 확인)
- 같은 주소에 searchYear / searchMonth POST. searchMonth=0 이면 '전체'(1년치, 월별 12블록)
- 블록: div.calendar_box > .calendar_date .kr("1월") + .cl_ev li
- li: span.date 안 getDay('YYYY-MM-DD','YYYY-MM-DD') 스크립트(시작·종료) + span.event "[과정]일정명"
- 일정이 없는 달: li 안에 span.date "등록된 일정이 없습니다." 만 있음 → 정상적인 '정보 없음'
- 같은 일정이 여러 번(같은 달 안 반복, 월을 걸친 일정) 나올 수 있다 → (과정, 제목, 시작, 종료)로 중복 제거
"""

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from ..models import AcademicEvent, CollectionRun
from .base import ParseError, browser_page, polite_pause, run_collection
from .sources import EVENTS_URL

DATE_PAIR_RE = re.compile(r"getDay\('(\d{4}-\d{2}-\d{2})'\s*,\s*'(\d{4}-\d{2}-\d{2})'\)")
COURSE_RE = re.compile(r"^\s*\[([^\]]+)\]\s*")
NO_EVENT_TEXT = "등록된 일정이 없습니다"


@dataclass(frozen=True)
class ParsedEvent:
    course: str
    title: str
    start: date
    end: date

    @property
    def key(self):
        return (self.course, self.title, self.start, self.end)


def split_course(raw: str) -> tuple[str, str]:
    """'[공통]신정' → ('공통', '신정'). 머리말이 없으면 ('', 원문)."""
    raw = re.sub(r"\s+", " ", raw).strip()
    m = COURSE_RE.match(raw)
    return (m.group(1).strip(), raw[m.end():].strip()) if m else ("", raw)


def parse_year_events(html: str, year: int) -> list[ParsedEvent]:
    """'전체' 보기 HTML → 그 해의 일정 목록(중복 제거). 구조가 다르면 ParseError."""
    soup = BeautifulSoup(html, "html.parser")
    year_input = soup.select_one('input[name="searchYear"]')
    month_input = soup.select_one('input[name="searchMonth"]')
    if not year_input or year_input.get("value") != str(year) or not month_input or month_input.get("value") != "0":
        raise ParseError(f"{year}년 '전체' 학사일정 페이지가 아닙니다.")

    blocks = soup.select("div.calendar_box")
    months = [b.select_one(".calendar_date .kr").get_text(strip=True) if b.select_one(".calendar_date .kr") else "" for b in blocks]
    if months != [f"{m}월" for m in range(1, 13)]:
        raise ParseError(f"학사일정 월 블록이 1~12월이 아닙니다: {months}")

    events: dict = {}
    for block in blocks:
        for li in block.select(".cl_ev li"):
            date_span, title_span = li.select_one("span.date"), li.select_one("span.event")
            if date_span and not title_span and NO_EVENT_TEXT in date_span.get_text():
                continue  # 공식 안내 행: 그 달은 실제로 일정이 없음 (추출 오류 아님)
            if not date_span or not title_span:
                raise ParseError("학사일정 항목에서 날짜/제목 칸을 찾지 못했습니다.")
            m = DATE_PAIR_RE.search(str(date_span))
            if not m:
                raise ParseError(f"학사일정 날짜 형식이 다릅니다: {date_span}")
            start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
            if end < start or abs(start.year - year) > 1:
                raise ParseError(f"학사일정 날짜가 비정상입니다: {start}~{end}")
            course, title = split_course(title_span.get_text(" ", strip=True))
            if not title:
                raise ParseError("학사일정 제목이 비어 있습니다.")
            ev = ParsedEvent(course, title, start, end)
            events.setdefault(ev.key, ev)
    return sorted(events.values(), key=lambda e: (e.start, e.end, e.title))


def years_to_collect(today: date) -> list[int]:
    """올해 + 내년. 1~2월에는 지난해 겨울 일정도 보이도록 작년도 포함."""
    years = [today.year, today.year + 1]
    if today.month <= 2:
        years.insert(0, today.year - 1)
    return years


def fetch_year_pages(years: list[int]) -> list[str]:
    """각 연도의 '전체' 보기. 사이트의 연·월 이동 함수(fn_schdul_change)를 그대로 호출한다."""
    pages = []
    with browser_page() as page:
        page.goto(EVENTS_URL)
        for y in years:
            polite_pause()
            with page.expect_navigation():
                page.evaluate("y => fn_schdul_change('0', String(y))", y)
            pages.append(page.content())
    return pages


def save_year_events(year: int, events: list[ParsedEvent], collected_at=None) -> tuple[int, str]:
    """한 연도 페이지의 결과를 원자적으로 반영한다.

    - 새 목록에 있는 일정: 추가 또는 갱신
    - 이 연도 페이지에서 왔던 일정 중 새 목록에서 사라진 것: 삭제 (공식에서 제거된 것으로 판단)
    - 새 목록이 통째로 비었는데 기존 일정이 있으면: 아무것도 바꾸지 않음
    """
    collected_at = collected_at or timezone.now()
    with transaction.atomic():
        existing = AcademicEvent.objects.filter(source_year=year)
        if not events and existing.exists():
            return 0, f"{year}년: 새 결과가 비어 있어 기존 {existing.count()}건 유지"
        keys = {e.key for e in events}
        removed = [ev.pk for ev in existing if (ev.course, ev.title, ev.start_date, ev.end_date) not in keys]
        AcademicEvent.objects.filter(pk__in=removed).delete()
        for e in events:
            AcademicEvent.objects.update_or_create(
                course=e.course, title=e.title, start_date=e.start, end_date=e.end,
                defaults={"source_year": year, "source_url": EVENTS_URL, "collected_at": collected_at},
            )
    return len(events), f"{year}년: {len(events)}건 (삭제 {len(removed)})"


def collect_events(years: list[int] | None = None, fetcher=fetch_year_pages) -> CollectionRun:
    years = years or years_to_collect(timezone.localdate())

    def job():
        pages = fetcher(years)
        parsed = [parse_year_events(html, y) for html, y in zip(pages, years, strict=True)]
        if not any(parsed):
            raise ParseError("모든 연도의 학사일정이 비어 있습니다 (추출 오류 가능성).")
        total, notes = 0, []
        with transaction.atomic():  # 여러 연도도 한 번에 반영
            for y, events in zip(years, parsed):
                n, note = save_year_events(y, events)
                total += n
                notes.append(note)
        return total, " / ".join(notes)

    return run_collection(CollectionRun.Source.EVENTS, job)
