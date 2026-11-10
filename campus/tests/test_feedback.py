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

    def test_rate_limit_per_browser(self):
        self.client.get(self.url)                      # 폼을 열면 브라우저별 도배 제한용 쿠키를 받는다
        self.assertIn("lp_fb", self.client.cookies)
        for _ in range(5):
            self.client.post(self.url, {"useful": "a"})
        r = self.client.post(self.url, {"useful": "6번째"})
        self.assertContains(r, "잠시 쉬어 가요")
        self.assertEqual(Feedback.objects.count(), 5)

    def test_same_ip_other_browsers_are_not_blocked(self):
        """학교 Wi-Fi: 같은 접속 주소의 다른 학생(다른 브라우저)은 한 사람이 한도를 채워도 보낼 수 있다(D-061)."""
        from django.test import Client
        first = Client()
        first.get(self.url)
        for _ in range(6):
            first.post(self.url, {"useful": "a"})
        self.assertEqual(Feedback.objects.count(), 5)
        for i in range(8):                             # 같은 IP(테스트 클라이언트는 모두 127.0.0.1)의 다른 학생 8명
            other = Client()
            other.get(self.url)
            self.assertRedirects(other.post(self.url, {"useful": f"학생 {i}"}), self.url + "?sent=1")
        self.assertEqual(Feedback.objects.count(), 13)

    def test_ip_limit_is_a_loose_backstop(self):
        """쿠키를 버리며 보내는 도배는 접속 주소 기준 한도에서 멈춘다."""
        from django.test import Client, override_settings
        with override_settings(FEEDBACK_IP_HOURLY_LIMIT=7):
            for _ in range(10):
                Client().post(self.url, {"useful": "a"})
        self.assertEqual(Feedback.objects.count(), 7)

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
        self.client.get("/feedback/")
        with override_settings(FEEDBACK_HOURLY_LIMIT=2):
            for _ in range(3):
                self.client.post("/feedback/", {"useful": "a"})
        self.assertEqual(Feedback.objects.count(), 2)
