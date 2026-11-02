"""학사일정·공지 수집 테스트 (2026-11-02 저장한 실제 공식 HTML 사용)."""

import logging
import re
from datetime import date

from django.test import TestCase

from campus.collectors.base import ParseError
from campus.collectors.events import collect_events, parse_year_events, split_course, years_to_collect
from campus.collectors.notices import collect_notices, parse_notice_page
from campus.models import AcademicEvent, CollectionRun, Notice

from .helpers import failing_fetcher, fake_fetcher, fixture

EVENTS = "events_2026_all.html"


class Quiet(TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)


class EventParseTests(TestCase):
    def test_parse_real_year(self):
        events = parse_year_events(fixture(EVENTS), 2026)
        raw_count = fixture(EVENTS).count("<li><div><span class=\"date\">")
        self.assertLess(len(events), raw_count)  # 공식 목록의 중복이 제거됨
        keys = [e.key for e in events]
        self.assertEqual(len(keys), len(set(keys)))
        exam = [e for e in events if e.title == "기능사 4회 실기시험"][0]
        self.assertEqual((exam.course, exam.start, exam.end), ("공통", date(2026, 11, 14), date(2026, 12, 2)))
        self.assertEqual(sum(1 for e in events if e.title == "학위수여식 및 수료식"), 1)

    def test_months_without_events_are_real_empty(self):
        """2027년 페이지: 빈 달에 '등록된 일정이 없습니다.' 안내 행 (Playwright 렌더링 결과)."""
        events = parse_year_events(fixture("events_2027_all.html"), 2027)
        self.assertEqual(len(events), 8)  # 유효 항목 10개 중 공식 목록 내 중복 2개 제거
        self.assertTrue(all(e.title for e in events))

    def test_split_course(self):
        self.assertEqual(split_course("[공통]신정"), ("공통", "신정"))
        self.assertEqual(split_course("머리말 없음"), ("", "머리말 없음"))

    def test_structure_errors(self):
        html = fixture(EVENTS)
        cases = {
            "wrong year": (html, 2025),
            "not whole-year view": (html.replace('name="searchMonth" value="0"', 'name="searchMonth" value="11"'), 2026),
            "missing month": (html.replace('<span class="kr">7월</span>', '<span class="kr">?</span>'), 2026),
            "date format": (re.sub(r"getDay\('2026-01-01','2026-01-01'\)", "getDay('1/1')", html), 2026),
        }
        for name, (broken, year) in cases.items():
            with self.subTest(name), self.assertRaises(ParseError):
                parse_year_events(broken, year)

    def test_years_to_collect(self):
        self.assertEqual(years_to_collect(date(2026, 11, 2)), [2026, 2027])
        self.assertEqual(years_to_collect(date(2027, 1, 5)), [2026, 2027, 2028])


class EventCollectTests(Quiet):
    def test_collect_and_recollect_without_duplicates(self):
        run = collect_events(years=[2026], fetcher=fake_fetcher(fixture(EVENTS)))
        self.assertEqual(run.status, CollectionRun.Status.SUCCESS, run.message)
        n = AcademicEvent.objects.count()
        self.assertGreater(n, 50)
        collect_events(years=[2026], fetcher=fake_fetcher(fixture(EVENTS)))
        self.assertEqual(AcademicEvent.objects.count(), n)

    def test_removed_event_is_deleted_only_from_same_year(self):
        collect_events(years=[2026], fetcher=fake_fetcher(fixture(EVENTS)))
        n = AcademicEvent.objects.count()
        removed = fixture(EVENTS).replace("[공통]신정", "")
        removed = re.sub(r"<li><div><span class=\"date\"><script>document.write\(getDay\('2026-01-01','2026-01-01'\)\);</script></span><span class=\"event\"></span></div></li>", "", removed)
        collect_events(years=[2026], fetcher=fake_fetcher(removed))
        self.assertEqual(AcademicEvent.objects.count(), n - 1)
        self.assertFalse(AcademicEvent.objects.filter(title="신정").exists())

    def test_empty_next_year_is_fine_but_all_empty_is_error(self):
        empty_2027 = re.sub(r"<li>.*?</li>", "", fixture(EVENTS), flags=re.S).replace('value="2026"', 'value="2027"')
        run = collect_events(years=[2026, 2027], fetcher=fake_fetcher(fixture(EVENTS), empty_2027))
        self.assertEqual(run.status, CollectionRun.Status.SUCCESS)
        before = AcademicEvent.objects.count()
        empty_2026 = re.sub(r"<li>.*?</li>", "", fixture(EVENTS), flags=re.S)
        run = collect_events(years=[2026], fetcher=fake_fetcher(empty_2026))
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertEqual(AcademicEvent.objects.count(), before)

    def test_failure_keeps_data(self):
        collect_events(years=[2026], fetcher=fake_fetcher(fixture(EVENTS)))
        n = AcademicEvent.objects.count()
        run = collect_events(years=[2026], fetcher=failing_fetcher())
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertEqual(AcademicEvent.objects.count(), n)


class NoticeParseTests(TestCase):
    def test_parse_real_pages(self):
        p1 = parse_notice_page(fixture("notices_p1.html"))
        p2 = parse_notice_page(fixture("notices_p2.html"))
        self.assertEqual(len(p1), 20)
        self.assertEqual(sum(n.is_pinned for n in p1), 17)
        self.assertFalse(any(n.is_pinned for n in p2))
        first = p1[0]
        self.assertEqual(first.post_id, "788409")
        self.assertEqual(first.category, "입시")
        self.assertEqual(first.posted_on, date(2026, 10, 28))
        no_prefix = [n for n in p1 if n.post_id == "786749"][0]
        self.assertEqual(no_prefix.category, "")

    def test_structure_errors(self):
        html = fixture("notices_p1.html")
        for name, broken in {
            "no table": html.replace("tbl_list", "tbl_other"),
            "headers": html.replace(">작성일<", ">등록일<"),
            "post id": html.replace("fn_board_detail(", "fn_detail("),
        }.items():
            with self.subTest(name), self.assertRaises(ParseError):
                parse_notice_page(broken)


class NoticeCollectTests(Quiet):
    def pages(self):
        return fake_fetcher(fixture("notices_p1.html"), fixture("notices_p2.html"))

    def test_collect_recollect_no_duplicates(self):
        run = collect_notices(pages=2, fetcher=self.pages())
        self.assertEqual(run.status, CollectionRun.Status.SUCCESS, run.message)
        n = Notice.objects.count()
        self.assertEqual(n, 40)
        collect_notices(pages=2, fetcher=self.pages())
        self.assertEqual(Notice.objects.count(), n)
        self.assertTrue(Notice.objects.get(post_id="788409").source_url.endswith("mode=view&post=788409"))

    def test_unpinned_on_official_page_is_unpinned(self):
        collect_notices(pages=2, fetcher=self.pages())
        p1 = fixture("notices_p1.html").replace('<td class="notice">공지</td>', '<td class="num">9999</td>', 1)
        collect_notices(pages=1, fetcher=fake_fetcher(p1))
        self.assertFalse(Notice.objects.get(post_id="788409").is_pinned)
        self.assertTrue(Notice.objects.get(post_id="787646").is_pinned)

    def test_empty_first_page_is_error_and_keeps_data(self):
        collect_notices(pages=2, fetcher=self.pages())
        empty = re.sub(r"<tbody>.*</tbody>", "<tbody></tbody>", fixture("notices_p1.html"), flags=re.S)
        run = collect_notices(pages=1, fetcher=fake_fetcher(empty))
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertEqual(Notice.objects.count(), 40)
