import json

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse


class PwaTests(TestCase):
    def test_manifest_is_valid_and_icons_exist(self):
        res = self.client.get(reverse("campus:manifest"))
        self.assertEqual(res["Content-Type"], "application/manifest+json")
        data = json.loads(res.content)
        self.assertEqual(data["display"], "standalone")
        self.assertEqual((data["name"], data["short_name"]), ("Lolypoly", "Lolypoly"))
        self.assertEqual((data["start_url"], data["scope"]), ("/", "/"))
        self.assertTrue(data["theme_color"] and data["background_color"])
        self.assertNotIn("프로토타입", data["description"])
        sizes = {(i["sizes"], i["purpose"]) for i in data["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("192x192", "maskable"), ("512x512", "maskable")} <= sizes)
        for icon in data["icons"]:
            path = icon["src"].replace("/static/", "", 1)
            self.assertIsNotNone(finders.find(path), path)
        # 아이콘 길게 누르기 바로가기: 식단·학사일정·공지 (시간표는 Mock 이라 제외)
        shortcut_paths = {s["url"].split("?")[0] for s in data["shortcuts"]}
        self.assertEqual(shortcut_paths, {reverse("campus:meals"), reverse("campus:schedule"), reverse("campus:notices")})

    def test_service_worker_served_from_root_without_long_cache(self):
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/javascript")
        self.assertIn("no-cache", res["Cache-Control"])
        body = res.content.decode()
        self.assertIn('"/meals/"', body)
        self.assertNotIn('"/admin/', body.split("CACHEABLE_PAGES")[1].split(";")[0])  # 관리자 화면은 캐시 목록에 없음
        self.assertIn("url.origin !== self.location.origin", body)               # 외부(원문) 링크는 건드리지 않음
        self.assertIn("lolypoly-hand.woff2", body.split("PRECACHE =")[1].split(";")[0])  # 오프라인 손글씨

    def test_offline_page_and_head_tags(self):
        self.assertEqual(self.client.get(reverse("campus:offline")).status_code, 200)
        home = self.client.get(reverse("campus:home"))
        self.assertContains(home, 'rel="manifest"')
        self.assertContains(home, 'name="lolypoly-rendered-at"')
        self.assertContains(home, 'id="cached-banner"')

    def test_install_sheet_on_every_page_and_reopen_in_my(self):
        for name in ("home", "meals", "schedule", "notices", "my"):
            with self.subTest(page=name):
                res = self.client.get(reverse(f"campus:{name}"))
                self.assertContains(res, 'id="install-sheet"')
                self.assertContains(res, "홈 화면에 Lolypoly 설치")
                self.assertContains(res, ">설치하기<")
                self.assertContains(res, ">나중에<")
                # 페이지가 열리자마자 무조건 보이지 않도록 기본은 숨김(app.js 가 조건 확인 후 연다)
                self.assertRegex(res.content.decode(), r'id="install-sheet"[^>]*\shidden')
        my = self.client.get(reverse("campus:my"))
        self.assertContains(my, "data-install-open")
        self.assertNotContains(self.client.get(reverse("campus:home")), "data-install-open")

    def test_apple_and_standalone_meta(self):
        home = self.client.get(reverse("campus:home"))
        self.assertContains(home, 'rel="apple-touch-icon"')
        self.assertContains(home, 'name="apple-mobile-web-app-capable" content="yes"')
        self.assertContains(home, "viewport-fit=cover")
        self.assertIsNotNone(finders.find("icons/apple-touch-icon.png"))

    def test_service_worker_does_not_store_private_or_admin(self):
        body = self.client.get("/sw.js").content.decode()
        self.assertIn('cc.includes("no-store")', body)
        self.assertIn('cc.includes("private")', body)
        self.assertIn('url.pathname.startsWith("/admin")', body)
        self.assertNotIn('"/feedback/"', body.split("CACHEABLE_PAGES")[1].split(";")[0])
