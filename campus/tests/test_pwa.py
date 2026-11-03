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
        self.assertEqual(data["start_url"].split("?")[0], "/")
        sizes = {(i["sizes"], i["purpose"]) for i in data["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for icon in data["icons"]:
            path = icon["src"].replace("/static/", "", 1)
            self.assertIsNotNone(finders.find(path), path)
        # 아이콘 길게 누르기 바로가기: 식단·학사일정·시간표
        shortcut_paths = {s["url"].split("?")[0] for s in data["shortcuts"]}
        self.assertEqual(shortcut_paths, {reverse("campus:meals"), reverse("campus:schedule"), reverse("campus:timetable")})

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

    def test_install_card_only_on_home_and_my(self):
        for name in ("home", "my"):
            res = self.client.get(reverse(f"campus:{name}"))
            self.assertContains(res, 'id="install-card"')
            self.assertContains(res, "data-install-btn")
        self.assertContains(self.client.get(reverse("campus:home")), "data-install-close")
        self.assertNotContains(self.client.get(reverse("campus:my")), "data-install-close")
        self.assertNotContains(self.client.get(reverse("campus:meals")), 'id="install-card"')
