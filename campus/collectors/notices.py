"""공지사항 수집.

공식 페이지 구조 (2026-11-02 확인)
- table.tbl_list 머리글 [번호, 제목, 작성자, 작성일]
- 행: 첫 칸 td.notice("공지" = 상단 고정) 또는 td.num(번호)
       제목 링크 onclick="fn_board_detail('게시글번호')"
- 상세 원문: board.do?menu=4827&mode=view&post=게시글번호 (주소로 바로 열림 확인)
- 쪽 이동: fn_board_pageMove(n). 상단 고정 공지는 1쪽에만 나온다.
- 공식 '분류' 칸은 없다 → 제목 맨 앞 머리말 "[학사]" 등을 분류로 사용 (없으면 빈 값)
"""

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from ..models import CollectionRun, Notice
from .base import ParseError, browser_page, polite_pause, run_collection
from .sources import BASE, NOTICES_URL

EXPECTED_HEADERS = ["번호", "제목", "작성자", "작성일"]
POST_RE = re.compile(r"fn_board_detail\('(\d+)'")
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
CATEGORY_RE = re.compile(r"^\s*\[([^\]]{1,20})\]")
MAX_PAGES = 5


def detail_url(post_id: str) -> str:
    return f"{BASE}/chuncheon/board.do?menu=4827&mode=view&post={post_id}"


@dataclass
class ParsedNotice:
    post_id: str
    title: str
    category: str
    author: str
    posted_on: date
    is_pinned: bool


def parse_notice_page(html: str) -> list[ParsedNotice]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.tbl_list")
    if table is None:
        raise ParseError("공지 목록 표(table.tbl_list)를 찾지 못했습니다.")
    headers = [th.get_text(strip=True) for th in table.select("thead th")]
    if headers != EXPECTED_HEADERS:
        raise ParseError(f"공지 표 머리글이 예상과 다릅니다: {headers}")

    items = []
    for tr in table.select("tbody > tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) == 1:  # '등록된 게시물이 없습니다' 같은 안내 행
            continue
        if len(cells) != 4:
            raise ParseError(f"공지 행의 칸 수가 4가 아닙니다: {len(cells)}")
        link = cells[1].find("a")
        m_post = POST_RE.search(str(link)) if link else None
        m_date = DATE_RE.search(cells[3].get_text())
        if not m_post or not m_date:
            raise ParseError("공지 행에서 게시글 번호나 작성일을 찾지 못했습니다.")
        title = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        if not title:
            raise ParseError("공지 제목이 비어 있습니다.")
        m_cat = CATEGORY_RE.match(title)
        items.append(ParsedNotice(
            post_id=m_post.group(1),
            title=title,
            category=m_cat.group(1).strip() if m_cat else "",
            author=cells[2].get_text(strip=True),
            posted_on=date(*map(int, m_date.groups())),
            is_pinned="notice" in (cells[0].get("class") or []),
        ))
    return items


def fetch_notice_pages(pages: int) -> list[str]:
    result = []
    with browser_page() as page:
        page.goto(NOTICES_URL)
        result.append(page.content())
        for n in range(2, pages + 1):
            polite_pause()
            with page.expect_navigation():
                page.evaluate("n => fn_board_pageMove(n)", n)  # 사이트의 쪽 이동 함수 (쪽 번호 링크와 동일)
            result.append(page.content())
    return result


def save_notices(pages: list[list[ParsedNotice]], collected_at=None) -> tuple[int, str]:
    """게시글 번호 기준으로 추가/갱신. 수집 범위 밖의 오래된 공지는 지우지 않는다.

    상단 고정 여부는 1쪽 결과가 근거: 이번 1쪽에서 고정이 아닌 글은 고정 해제.
    """
    collected_at = collected_at or timezone.now()
    seen: dict[str, ParsedNotice] = {}
    for page in pages:
        for n in page:
            seen.setdefault(n.post_id, n)
    pinned_now = {n.post_id for n in pages[0] if n.is_pinned}
    with transaction.atomic():
        Notice.objects.filter(is_pinned=True).exclude(post_id__in=pinned_now).update(is_pinned=False)
        for n in seen.values():
            Notice.objects.update_or_create(
                post_id=n.post_id,
                defaults={
                    "title": n.title, "category": n.category, "author": n.author,
                    "posted_on": n.posted_on, "is_pinned": n.post_id in pinned_now,
                    "source_url": detail_url(n.post_id), "collected_at": collected_at,
                },
            )
    return len(seen), f"공지 {len(seen)}건 (상단 고정 {len(pinned_now)}건)"


def collect_notices(pages: int = 2, fetcher=fetch_notice_pages) -> CollectionRun:
    pages = max(1, min(pages, MAX_PAGES))

    def job():
        htmls = fetcher(pages)
        parsed = [parse_notice_page(h) for h in htmls]
        if not parsed[0]:
            # 게시글이 1,000건 넘는 게시판의 1쪽이 비어 있으면 추출 오류로 본다
            raise ParseError("공지 1쪽 결과가 비어 있습니다 (추출 오류 가능성).")
        return save_notices(parsed)

    return run_collection(CollectionRun.Source.NOTICES, job)
