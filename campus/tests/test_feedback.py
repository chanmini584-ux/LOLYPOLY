from django.test import TestCase
from django.urls import reverse

from campus.models import Feedback


class FeedbackTests(TestCase):
    url = "/feedback/"

    def test_form_page_loads(self):
        r = self.client.get(self.url)
        self.assertContains(r, "이름·학번·전화번호는 적지 마세요")
        self.assertNotIn(self.url, [reverse(f"campus:{n}") for n in ("home",)])

    def test_submit_saves_and_redirects(self):
        r = self.client.post(self.url, {"useful": "식단", "trouble": "", "wish": ""})
        self.assertRedirects(r, self.url + "?sent=1")
        self.assertEqual(Feedback.objects.get().useful, "식단")

    def test_empty_rejected(self):
        r = self.client.post(self.url, {"useful": " ", "trouble": "", "wish": ""})
        self.assertContains(r, "한 곳 이상")
        self.assertEqual(Feedback.objects.count(), 0)

    def test_too_long_rejected(self):
        r = self.client.post(self.url, {"useful": "가" * 501})
        self.assertEqual(Feedback.objects.count(), 0)
        self.assertEqual(r.status_code, 200)

    def test_html_is_escaped(self):
        Feedback.objects.create(useful="<script>alert(1)</script>")
        self.client.post(self.url, {"useful": "<b>x</b>"})
        self.assertEqual(Feedback.objects.count(), 2)

    def test_bad_code_rejected(self):
        self.client.post(self.url, {"useful": "a", "participant_code": "홍길동 010"})
        self.assertEqual(Feedback.objects.count(), 0)

    def test_honeypot_not_saved(self):
        r = self.client.post(self.url, {"useful": "a", "website": "http://spam"})
        self.assertRedirects(r, self.url + "?sent=1")
        self.assertEqual(Feedback.objects.count(), 0)

    def test_rate_limit(self):
        for _ in range(5):
            self.client.post(self.url, {"useful": "a"})
        r = self.client.post(self.url, {"useful": "6번째"})
        self.assertContains(r, "잠시 뒤에")
        self.assertEqual(Feedback.objects.count(), 5)

    def test_csrf_enforced(self):
        from django.test import Client
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(c.post(self.url, {"useful": "a"}).status_code, 403)

    def test_admin_requires_login(self):
        r = self.client.get("/admin/campus/feedback/")
        self.assertEqual(r.status_code, 302)

    def test_not_cached_by_service_worker(self):
        r = self.client.get("/sw.js")
        self.assertNotIn("/feedback/", r.content.decode().split("CACHEABLE_PAGES = ")[1].split(";")[0])


class FeedbackLimitSettingTests(TestCase):
    def test_limit_is_configurable(self):
        from django.test import override_settings
        with override_settings(FEEDBACK_HOURLY_LIMIT=2):
            for _ in range(3):
                self.client.post("/feedback/", {"useful": "a"})
        self.assertEqual(Feedback.objects.count(), 2)
