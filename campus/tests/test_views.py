"""화면 동작 테스트. 데이터는 저장된 실제 공식 HTML(fixtures)을 수집기로 넣어 사용한다."""

import logging
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from campus.collectors.events import collect_events
from campus.collectors.meals import collect_meals
from campus.collectors.notices import collect_notices
from campus.views import _add_months, _parse_month

from .helpers import failing_fetcher, fake_fetcher, fixture

PAGES = ["home", "meals", "schedule", "notices", "timetable", "my"]
MONDAY = date(2026, 11, 2)  # fixtures 를 저장한 날(월요일)


def at(day):
    """뷰의 '오늘'을 고정한다."""
    return patch("campus.views.timezone.localdate", return_value=day)


def seed_all():
    collect_meals(weeks=2, fetcher=fake_fetcher(fixture("meals_2026-11-02.html"), fixture("meals_2026-11-09.html")))
    collect_events(years=[2026], fetcher=fake_fetcher(fixture("events_2026_all.html")))
    collect_notices(pages=2, fetcher=fake_fetcher(fixture("notices_p1.html"), fixture("notices_p2.html")))


class EmptyDatabaseTests(TestCase):
    """수집 전: 모든 화면이 열리고, 실제 데이터 화면에는 예시 데이터가 없다."""

    def test_all_pages_return_200_with_layout(self):
        for name in PAGES:
            with self.subTest(page=name):
                res = self.client.get(reverse(f"campus:{name}"))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'class="bottom-nav"')

    def test_real_data_pages_have_no_mock(self):
        for name in ["home", "meals", "schedule", "notices"]:
            with self.subTest(page=name):
                res = self.client.get(reverse(f"campus:{name}"))
                self.assertNotContains(res, "badge--mock")
                self.assertNotContains(res, "[예시]")

    def test_mock_pages_are_labeled(self):
        # 시간표는 예시(Mock) 데이터라 학생 메뉴에서 숨겼지만, 주소로 열면 여전히 '예시'라고 표시한다(D-048)
        self.assertContains(self.client.get(reverse("campus:timetable")), "badge--mock")

    @override_settings(DEBUG=False, LOLYPOLY_STATE_PREVIEW=False)  # 운영과 같은 조건(개발용 미리보기 꺼짐)
    def test_student_pages_have_no_dev_wording(self):
        for name in ["home", "meals", "schedule", "notices", "my", "feedback"]:
            with self.subTest(page=name):
                html = self.client.get(reverse(f"campus:{name}")).content.decode()
                for word in ["프로토타입", "Prototype", "시범", "Mock", "미구현", "(예정)", "개발용"]:
                    self.assertNotIn(word, html)
                self.assertNotIn(f'href="{reverse("campus:timetable")}"', html)  # 숨긴 시간표로 가는 링크 없음

    def test_unofficial_notice_kept(self):
        self.assertContains(self.client.get(reverse("campus:my")), "학교 공식 서비스가 아니에요")


class NavigationTests(TestCase):
    def test_bottom_nav_is_home_meals_schedule_community_my(self):
        """하단 탭 5개: 홈·식단·학사일정·커뮤니티·MY (D-059). 공지는 홈·MY 에서 가고 주소는 그대로다."""
        html = self.client.get(reverse("campus:meals")).content.decode()
        nav = html.split('class="bottom-nav"')[1]
        for name in ["campus:home", "campus:meals", "campus:schedule", "community:home", "campus:my"]:
            self.assertIn(f'href="{reverse(name)}"', nav)
        self.assertEqual(nav.count("bottom-nav__link"), 5)
        self.assertNotIn(f'href="{reverse("campus:timetable")}"', nav)
        self.assertEqual(self.client.get(reverse("campus:notices")).status_code, 200)
        self.assertContains(self.client.get(reverse("campus:my")), f'href="{reverse("campus:notices")}"')
        self.assertEqual(html.count('aria-current="page"'), 1)

    def test_notices_reachable_from_home(self):
        self.assertContains(self.client.get(reverse("campus:home")), f'href="{reverse("campus:notices")}"')


class WithDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_all()

    def setUp(self):
        p = at(MONDAY)
        p.start()
        self.addCleanup(p.stop)

    def test_home_shows_real_meal_event_notice(self):
        res = self.client.get(reverse("campus:home"))
        self.assertContains(res, "쇠고기미역국")
        self.assertEqual(len(res.context["upcoming"]), 3)
        self.assertEqual(len(res.context["latest_notices"]), 3)
        self.assertEqual(res.context["latest_notices"][0]["posted_on"], date(2026, 10, 28))

    def test_home_week_meal_dots(self):
        res = self.client.get(reverse("campus:home"))
        week = res.context["week"]
        self.assertEqual([d["date"].weekday() for d in week], list(range(7)))
        self.assertTrue(week[0]["is_today"] and week[0]["is_selected"])
        self.assertContains(res, 'data-day-panel="2026-11-02"')
        self.assertContains(res, 'data-day-panel="2026-11-03" hidden')
        # JS 없이 ?day= 로 다른 날 고르기. 이번 주 밖의 날짜는 오늘로
        res = self.client.get(reverse("campus:home"), {"day": "2026-11-03"})
        self.assertTrue(res.context["week"][1]["is_selected"])
        res = self.client.get(reverse("campus:home"), {"day": "2026-12-25"})
        self.assertTrue(res.context["week"][0]["is_selected"])

    def test_home_dday_stickers(self):
        res = self.client.get(reverse("campus:home"))
        self.assertContains(res, "dday-sticker--pink")
        self.assertContains(res, "남은 날")

    def test_schedule_upcoming_and_month(self):
        res = self.client.get(reverse("campus:schedule"))
        self.assertTrue(all(e["end"] >= MONDAY for e in res.context["upcoming"]))
        titles = [e["title"] for e in res.context["month_events"]]
        self.assertIn("기능사 4회 실기시험", titles)
        self.assertContains(res, "menu=4797")

    def test_schedule_course_filter_keeps_common(self):
        res = self.client.get(reverse("campus:schedule"), {"month": "2026-11", "course": "2년제학위과정"})
        courses = {e["course"] for e in res.context["month_events"]}
        self.assertTrue(courses <= {"2년제학위과정", "공통"})
        self.assertIn("2년제학위과정", courses)

    def test_schedule_unknown_course_and_bad_month(self):
        res = self.client.get(reverse("campus:schedule"), {"month": "bad", "course": "없음"})
        self.assertEqual(res.context["selected_course"], "")
        self.assertEqual(res.context["month"], date(2026, 11, 1))

    def test_notices_sorted_with_official_links(self):
        res = self.client.get(reverse("campus:notices"))
        dates = [n["posted_on"] for n in res.context["items"]]
        self.assertEqual(dates, sorted(dates, reverse=True))
        self.assertContains(res, "mode=view&amp;post=788409")
        self.assertContains(res, "tag--pin")
        self.assertContains(res, 'rel="noopener noreferrer"')

    def test_notice_category_filter(self):
        res = self.client.get(reverse("campus:notices"), {"category": "학사"})
        self.assertTrue(res.context["items"])
        self.assertTrue(all(n["category"] == "학사" for n in res.context["items"]))
        res = self.client.get(reverse("campus:notices"), {"category": "없는분류"})
        self.assertEqual(res.context["selected_category"], "")

    def test_meal_date_param(self):
        res = self.client.get(reverse("campus:meals"), {"date": "2026-11-04"})
        self.assertEqual(res.context["selected"], date(2026, 11, 4))
        self.assertEqual(res.context["week_start"], MONDAY)
        self.assertContains(res, "짜장면/미니밥")
        res = self.client.get(reverse("campus:meals"), {"date": "2026-13-99"})
        self.assertEqual(res.context["selected"], MONDAY)

    def test_one_failure_isolated(self):
        logging.disable(logging.CRITICAL)
        collect_notices(fetcher=failing_fetcher())
        logging.disable(logging.NOTSET)
        res = self.client.get(reverse("campus:home"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["notices"].status, "error")
        self.assertEqual(res.context["events"].status, "ok")
        self.assertEqual(res.context["meals"].status, "ok")
        self.assertTrue(res.context["latest_notices"])  # 이전 공지는 계속 보임


class HelperTests(TestCase):
    def test_month_helpers(self):
        self.assertEqual(_add_months(date(2026, 12, 1), 1), date(2027, 1, 1))
        self.assertEqual(_add_months(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(_parse_month("2026-13", MONDAY), date(2026, 11, 1))


class TimetableViewTests(TestCase):
    def test_grid_positions(self):
        with at(MONDAY):
            res = self.client.get(reverse("campus:timetable"))
        first = res.context["classes"][0]  # 월 09:00–10:50
        self.assertEqual((first["col"], first["row"], first["span"]), (2, 2, 4))
        self.assertEqual(len(res.context["today_classes"]), 2)

    def test_weekend_message(self):
        with at(date(2026, 11, 8)):
            self.assertContains(self.client.get(reverse("campus:timetable")), "주말에는 수업이 없어요")


class StatePreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_all()

    @override_settings(LOLYPOLY_STATE_PREVIEW=True)
    def test_preview_states(self):
        url = reverse("campus:notices")
        self.assertContains(self.client.get(url, {"preview": "empty"}), "공지가 아직 없어요")
        err = self.client.get(url, {"preview": "error"})
        self.assertContains(err, "이전에 받아온 정보")
        self.assertTrue(err.context["items"])
        self.assertContains(self.client.get(url, {"preview": "error-empty"}), "표시할 정보가 없어요")
        self.assertContains(self.client.get(url, {"preview": "stale"}), "일이 지났어요")

    @override_settings(LOLYPOLY_STATE_PREVIEW=True)
    def test_home_survives_each_state(self):
        for state in ["empty", "error", "error-empty", "stale"]:
            with self.subTest(state=state):
                self.assertEqual(self.client.get(reverse("campus:home"), {"preview": state}).status_code, 200)

    @override_settings(LOLYPOLY_STATE_PREVIEW=False)
    def test_preview_disabled_in_production(self):
        res = self.client.get(reverse("campus:notices"), {"preview": "empty"})
        self.assertTrue(res.context["items"])
        self.assertNotContains(res, "dev-preview")


class CustomUserModelTests(TestCase):
    def test_auth_user_model_is_custom(self):
        self.assertEqual(get_user_model()._meta.label, "accounts.User")


class UpdateNoticeTests(TestCase):
    """업데이트 안내 창과 /updates/ (D-069)."""

    def test_release_notes_match_version_file(self):
        from pathlib import Path

        from django.conf import settings

        from campus import release_notes
        version = (Path(settings.BASE_DIR) / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(release_notes.RELEASES[0]["version"], version)     # 새 버전을 내면 소식도 함께 적어야 한다
        self.assertEqual(release_notes.label("0.3.0-beta"), "beta v0.3")
        self.assertEqual(release_notes.label("0.3.1-beta"), "beta v0.3.1")
        versions = [r["version"] for r in release_notes.RELEASES]
        self.assertEqual(len(versions), len(set(versions)))

    def test_sheet_is_on_every_page_hidden_with_latest_notes(self):
        from campus import release_notes
        latest = release_notes.RELEASES[0]
        for url in [reverse("campus:home"), reverse("campus:my"), reverse("community:rules")]:
            html = self.client.get(url).content.decode()
            self.assertIn(f'id="update-sheet" role="dialog"', html)
            self.assertRegex(html, r'id="update-sheet"[^>]*data-version="%s" hidden' % latest["version"])
            self.assertIn(f'data-update-release="{latest["version"]}"', html)
            self.assertIn(latest["items"][0], html)

    def test_updates_page_lists_all_releases(self):
        from campus import release_notes
        res = self.client.get(reverse("campus:updates"))
        self.assertEqual(res.status_code, 200)
        for r in release_notes.RELEASES:
            self.assertContains(res, r["title"])
        self.assertContains(self.client.get(reverse("campus:my")), reverse("campus:updates"))
