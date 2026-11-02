"""식단 수집 테스트. 2026-11-02에 저장한 실제 공식 페이지 HTML(fixtures)로 네트워크 없이 검증한다."""

import logging
import re
from datetime import date, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from campus import data
from campus.collectors.base import ParseError
from campus.collectors.meals import collect_meals, parse_meal_week, split_menu
from campus.models import CollectionRun, Meal

from .helpers import failing_fetcher, fake_fetcher, fixture

WEEK1 = "meals_2026-11-02.html"
WEEK2 = "meals_2026-11-09.html"


class QuietLogs(TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # 일부러 실패시키는 테스트의 로그 숨김

    def tearDown(self):
        logging.disable(logging.NOTSET)


class SplitMenuTests(TestCase):
    def test_split_keeps_commas_inside_parentheses(self):
        self.assertEqual(split_menu("간편식(컵밥,빵,음료)"), ["간편식(컵밥,빵,음료)"])
        self.assertEqual(split_menu("잡곡밥 , 김치/삶은달걀 ,  "), ["잡곡밥", "김치/삶은달걀"])


class ParseMealWeekTests(TestCase):
    def test_parse_real_page(self):
        days = parse_meal_week(fixture(WEEK1))
        self.assertEqual([d.date for d in days], [date(2026, 11, 2) + timedelta(i) for i in range(7)])
        mon = days[0]
        self.assertEqual(mon.meals["breakfast"][0], "잡곡밥")
        self.assertIn("왕만두국", mon.meals["breakfast"])
        self.assertEqual(len(mon.meals["lunch"]), 6)
        self.assertEqual(days[5].meals["breakfast"], [])        # 토 조식 없음
        self.assertEqual(days[5].meals["lunch"], ["간편식"])
        self.assertTrue(days[6].is_blank)                       # 일요일 비어 있음

    def test_parse_next_week_with_parentheses(self):
        days = parse_meal_week(fixture(WEEK2))
        self.assertEqual(days[0].date, date(2026, 11, 9))
        self.assertEqual(days[5].meals["lunch"], ["간편식(컵밥,빵,음료)"])

    def test_structure_errors(self):
        html = fixture(WEEK1)
        cases = {
            "no table": html.replace("tbl_table menu", "tbl_table other"),
            "headers": html.replace(">석식<", ">야식<"),
            "row count": "<tr><td>x</td><td></td><td></td><td></td></tr></tbody>".join(html.rsplit("</tbody>", 1)),
            "dates": html.replace("2026-11-04", "2026-11-14"),
        }
        for name, broken in cases.items():
            with self.subTest(name), self.assertRaises(ParseError):
                parse_meal_week(broken)


class CollectMealsTests(QuietLogs):
    def test_collect_saves_two_weeks(self):
        run = collect_meals(weeks=2, fetcher=fake_fetcher(fixture(WEEK1), fixture(WEEK2)))
        self.assertEqual(run.status, CollectionRun.Status.SUCCESS, run.message)
        self.assertEqual(Meal.objects.count(), 14 * 3)
        self.assertEqual(run.item_count, 42)
        m = Meal.objects.get(date=date(2026, 11, 2), meal_type="lunch")
        self.assertIn("임꺽정떡갈비구이", m.items)
        self.assertTrue(m.source_url.endswith("menu=4819"))

    def test_recollect_has_no_duplicates_and_applies_changes(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        changed = fixture(WEEK1).replace("왕만두국", "떡만두국")
        collect_meals(weeks=1, fetcher=fake_fetcher(changed))
        self.assertEqual(Meal.objects.count(), 21)
        self.assertIn("떡만두국", Meal.objects.get(date=date(2026, 11, 2), meal_type="breakfast").items)

    def test_network_failure_keeps_existing_data(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        before = list(Meal.objects.values_list("date", "meal_type", "items"))
        run = collect_meals(weeks=1, fetcher=failing_fetcher())
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertIn("TimeoutError", run.message)
        self.assertEqual(list(Meal.objects.values_list("date", "meal_type", "items")), before)

    def test_structure_change_keeps_existing_data_even_if_one_week_is_fine(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        broken = fixture(WEEK2).replace("tbl_table menu", "tbl_table new-layout")
        run = collect_meals(weeks=2, fetcher=fake_fetcher(fixture(WEEK1).replace("왕만두국", "변경됨"), broken))
        self.assertEqual(run.status, CollectionRun.Status.FAILED)
        self.assertIn("ParseError", run.message)
        self.assertEqual(Meal.objects.count(), 21)
        self.assertIn("왕만두국", Meal.objects.get(date=date(2026, 11, 2), meal_type="breakfast").items)

    def test_all_blank_week_does_not_overwrite_existing_menu(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        # 같은 주의 모든 메뉴 칸을 비운 HTML (게시 전 공백 또는 오류 상황)
        html = re.sub(r"<span>[^<]*</span>", "<span></span>", fixture(WEEK1))
        run = collect_meals(weeks=1, fetcher=fake_fetcher(html))
        self.assertEqual(run.status, CollectionRun.Status.SUCCESS)
        self.assertIn("기존 데이터 유지", run.message)
        self.assertIn("왕만두국", Meal.objects.get(date=date(2026, 11, 2), meal_type="breakfast").items)


class MealSectionStateTests(QuietLogs):
    MONDAY = date(2026, 11, 2)

    def test_never_collected_is_empty(self):
        section = data.meals_week(self.MONDAY)
        self.assertEqual(section.status, "empty")
        self.assertFalse(section.is_mock)

    def test_failed_last_run_is_error_but_keeps_items(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        collect_meals(weeks=1, fetcher=failing_fetcher())
        section = data.meals_week(self.MONDAY)
        self.assertEqual(section.status, "error")
        self.assertEqual(len(section.items), 7)
        self.assertIsNotNone(section.last_success_at)

    @override_settings(LOLYPOLY_COLLECT_INTERVAL_DAYS={"meals": 7, "events": 7, "notices": 7})
    def test_old_success_is_stale(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture(WEEK1)))
        CollectionRun.objects.update(finished_at=timezone.now() - timedelta(days=9))
        section = data.meals_week(self.MONDAY)
        self.assertEqual(section.status, "stale")
        self.assertEqual(section.stale_days, 9)


class MealPagesWithRealDataTests(QuietLogs):
    def setUp(self):
        super().setUp()
        collect_meals(weeks=2, fetcher=fake_fetcher(fixture(WEEK1), fixture(WEEK2)))
        self.today = patch("campus.views.timezone.localdate", return_value=date(2026, 11, 2))
        self.today.start()

    def tearDown(self):
        self.today.stop()
        super().tearDown()

    def test_meals_page_shows_real_menu_without_mock_badge(self):
        res = self.client.get(reverse("campus:meals"))
        self.assertContains(res, "왕만두국")
        self.assertNotContains(res, "badge--mock")
        self.assertContains(res, "menu=4819")  # 공식 원문 링크

    def test_sunday_shows_official_blank_message(self):
        res = self.client.get(reverse("campus:meals"), {"date": "2026-11-08"})
        self.assertContains(res, "공식 식단표에 이 날 메뉴가 없어요")

    def test_uncollected_week(self):
        res = self.client.get(reverse("campus:meals"), {"date": "2026-11-23"})
        self.assertContains(res, "이 주의 식단 정보가 없어요")

    def test_home_shows_today_meal(self):
        res = self.client.get(reverse("campus:home"))
        self.assertContains(res, "쇠고기미역국")

    def test_one_collector_failure_does_not_break_pages(self):
        collect_meals(weeks=1, fetcher=failing_fetcher())
        for name in ["home", "meals"]:
            res = self.client.get(reverse(f"campus:{name}"))
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, "갱신에 실패")
