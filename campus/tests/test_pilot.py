"""시험 사용(파일럿) 전 개선 테스트 (D-043~D-046).

- 모든 응답의 앱 표시 헤더(서비스 워커가 호스팅 대기 화면과 구분하는 데 사용)
- 홈 '최신 공지'에서 행정 공지 제외(공지사항 화면은 그대로)
- '의견 보내기' 링크: 설정이 있을 때만
- 실시간 버스: 캐시가 빈 순간 TAGO 호출은 한 요청만
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from campus import bus
from campus.middleware import APP_HEADER

from .test_bus import DAYTIME, seed
from .test_views import MONDAY, at, seed_all


class AppHeaderTests(TestCase):
    def test_html_json_and_404_are_marked(self):
        for url in [reverse("campus:home"), reverse("campus:service_worker"), reverse("campus:bus_nearest"),
                    "/없는-주소/"]:
            res = self.client.get(url)
            self.assertEqual(res[APP_HEADER], "1", url)


class HomeNoticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_all()

    def setUp(self):
        p = at(MONDAY)
        p.start()
        self.addCleanup(p.stop)

    def test_home_skips_admin_notices_but_list_keeps_them(self):
        home = self.client.get(reverse("campus:home"))
        latest = home.context["latest_notices"]
        self.assertTrue(latest)
        self.assertTrue(all(n["category"] != "행정" for n in latest))
        listing = self.client.get(reverse("campus:notices"))
        self.assertTrue(any(n["category"] == "행정" for n in listing.context["items"]),
                        "fixture 에 행정 공지가 있어야 이 테스트가 의미 있음")


class FeedbackLinkTests(TestCase):
    @override_settings(LOLYPOLY_FEEDBACK_URL="")
    def test_hidden_without_setting(self):
        for name in ["home", "my"]:
            self.assertNotContains(self.client.get(reverse(f"campus:{name}")), "의견 보내기")

    @override_settings(LOLYPOLY_FEEDBACK_URL="https://forms.example.com/lolypoly")
    def test_shown_on_home_and_my(self):
        for name in ["home", "my"]:
            res = self.client.get(reverse(f"campus:{name}"))
            self.assertContains(res, 'href="https://forms.example.com/lolypoly"')
            self.assertContains(res, "의견 보내기")


@override_settings(TAGO_SERVICE_KEY="test-key", LOLYPOLY_BUS_LIVE_CACHE_SEC=30)
class SingleFetchTests(TestCase):
    def setUp(self):
        cache.clear()
        seed()
        p = patch.object(bus, "FETCH_WAIT_SEC", 0.5)   # 기다리는 시간을 줄여 테스트를 빠르게
        p.start()
        self.addCleanup(p.stop)

    def test_other_request_waits_instead_of_calling_tago(self):
        cache.add("bus-live:901:lock", 1, 30)            # 다른 요청이 이미 TAGO 를 부르는 중
        with patch("campus.tago.call") as m:
            data = bus.live("901", now=DAYTIME)
        m.assert_not_called()
        self.assertFalse(data["ok"])
        self.assertEqual(data["reason"], "busy")

    def test_waiting_request_shows_last_good(self):
        with patch("campus.tago.call", return_value=[]):
            bus.live("901", now=DAYTIME)                 # 정상 결과 → :last 저장
        cache.delete("bus-live:901")
        cache.add("bus-live:901:lock", 1, 30)
        with patch("campus.tago.call") as m:
            data = bus.live("901", now=DAYTIME)
        m.assert_not_called()
        self.assertTrue(data["ok"])
        self.assertTrue(data["delayed"])

    def test_lock_released_after_fetch(self):
        with patch("campus.tago.call", return_value=[]):
            bus.live("901", now=DAYTIME)
            bus.nearest(now=DAYTIME)
        self.assertIsNone(cache.get("bus-live:901:lock"))
        self.assertIsNone(cache.get("bus-nearest:lock"))

    def test_nearest_waits_too(self):
        cache.add("bus-nearest:lock", 1, 30)
        with patch("campus.tago.call") as m:
            data = bus.nearest(now=DAYTIME)
        m.assert_not_called()
        self.assertEqual(data["reason"], "busy")
