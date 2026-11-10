"""개인 화면 캐시 차단과 서비스 워커 정책(서버가 내보내는 헤더·SW 스크립트 내용 기준)."""

from django.test import TestCase
from django.urls import reverse

from community.models import Post
from community.tests.helpers import CommunityTestCase


class PrivateCacheTests(CommunityTestCase):
    def test_private_pages_are_no_store_for_everyone(self):
        post = Post.objects.create(board=self.board_a, author=self.alice, title="t", body="b")
        urls = ["/my/", "/accounts/login/", "/accounts/signup/", "/community/", "/community/rules/",
                f"/community/b/{self.board_a.slug}/", f"/community/p/{post.pk}/", "/community/notifications/",
                "/community/me/posts/", "/admin/login/"]
        for logged_in in (False, True):
            if logged_in:
                self.login(self.alice)
            for url in urls:
                cc = self.client.get(url)["Cache-Control"]
                self.assertIn("no-store", cc, url)
                self.assertIn("private", cc, url)

    def test_public_pages_are_identical_for_members_and_visitors(self):
        """공개 화면은 로그인해도 내용이 같아야 서비스 워커가 저장해도 개인 정보가 섞이지 않는다."""
        import re

        def clean(html):
            html = re.sub(r'name="lolypoly-rendered-at" content="\d+"', "", html)
            return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", html)

        for name in ["home", "meals", "schedule", "notices", "bus"]:
            url = reverse(f"campus:{name}")
            anonymous = clean(self.client.get(url).content.decode())
            self.login(self.alice)
            member = clean(self.client.get(url).content.decode())
            self.client.logout()
            self.assertEqual(anonymous, member, name)
            self.assertNotIn("alice_a", member)

    def test_after_logout_private_urls_redirect_instead_of_serving_content(self):
        post = Post.objects.create(board=self.board_a, author=self.alice, title="로그아웃 뒤 안 보일 글", body="b")
        self.login(self.alice)
        self.assertContains(self.client.get(f"/community/p/{post.pk}/"), "로그아웃 뒤 안 보일 글")
        self.client.post("/accounts/logout/")
        for url in [f"/community/p/{post.pk}/", "/community/", "/community/notifications/"]:
            res = self.client.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertNotIn("로그아웃 뒤 안 보일 글", res.content.decode())
        self.assertNotContains(self.client.get("/my/"), "alice_a")


class ServiceWorkerPolicyTests(TestCase):
    def setUp(self):
        self.body = self.client.get("/sw.js").content.decode()
        self.pages = self.body.split("CACHEABLE_PAGES = ")[1].split(";")[0]

    def test_only_public_pages_are_cacheable(self):
        for path in ['"/"', '"/meals/"', '"/schedule/"', '"/notices/"', '"/bus/"']:
            self.assertIn(path, self.pages)
        for private in ["/my/", "/community", "/accounts", "/admin", "/feedback", "/timetable"]:
            self.assertNotIn(private, self.pages)

    def test_server_down_falls_back_but_access_errors_do_not(self):
        self.assertIn("const SERVER_DOWN = [502, 503, 504];", self.body)
        for status in ("401", "403", "404"):
            self.assertNotIn(status, self.body.split("const SERVER_DOWN")[1].split(";")[0])
        self.assertIn("if (!isCacheablePage(url)) return null;", self.body)      # 개인 화면은 저장본을 찾지도 않는다
        self.assertIn('response.status !== 200', self.body)
        self.assertIn('cc.includes("no-store")', self.body)
        self.assertIn('cc.includes("private")', self.body)

    def test_cache_version_changes_so_old_my_page_cache_is_dropped(self):
        self.assertIn('k.startsWith("lolypoly-") && ![STATIC_CACHE, PAGE_CACHE].includes(k)', self.body)
        self.assertRegex(self.body, r'const CACHE_VERSION = "[0-9a-f]{12}"')

    def test_every_app_response_carries_marker_header(self):
        for url in ["/", "/my/", "/community/", "/no-such-page/"]:
            self.assertEqual(self.client.get(url)["X-Lolypoly"], "1", url)

    def test_manifest_identity_is_unchanged(self):
        import json
        data = json.loads(self.client.get("/manifest.webmanifest").content)
        self.assertEqual((data["id"], data["start_url"], data["scope"]), ("/", "/", "/"))


class ExtremeDateTests(TestCase):
    """아주 먼 날짜를 넣어도 500 이 나지 않고 오늘 기준 화면과 안내가 나온다(D-062)."""

    def test_meals_and_home_with_extreme_dates(self):
        for value in ["9999-12-31", "0001-01-01", "9999-12-25", "2026-02-30", "abc", "1e9", "", "2026-13-01"]:
            for url in [f"/meals/?date={value}", f"/?day={value}"]:
                self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get("/meals/?date=9999-12-31"), "오늘 기준으로 보여 드려요")
        self.assertNotContains(self.client.get("/meals/"), "오늘 기준으로 보여 드려요")

    def test_schedule_with_extreme_months(self):
        for value in ["9999-12", "0001-01", "0000-00", "99999-01", "2026-00", "2026-13", "-1--1", "abc", "2026"]:
            self.assertEqual(self.client.get(f"/schedule/?month={value}").status_code, 200, value)
        self.assertContains(self.client.get("/schedule/?month=9999-12"), "오늘 기준으로 보여 드려요")

    def test_normal_dates_still_work(self):
        from django.utils import timezone
        today = timezone.localdate()
        res = self.client.get(f"/meals/?date={today.replace(day=1).isoformat()}")
        self.assertEqual(res.context["selected"], today.replace(day=1))
        res = self.client.get(f"/schedule/?month={today.year + 1}-03")
        self.assertEqual((res.context["month"].year, res.context["month"].month), (today.year + 1, 3))
