"""롤리폴리 안내(D-073) 테스트: 서버 측 엔진 호출·CSRF·상태 전달·장애 구분·내보내기. 실제 엔진은 부르지 않는다(가짜 응답)."""

import io
import json
import logging
import urllib.error
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from campus import rag
from campus.collectors.meals import collect_meals
from campus.collectors.notices import collect_notices
from campus.models import CollectionRun, Meal

from .helpers import failing_fetcher, fake_fetcher, fixture

ON = dict(LOLYPOLY_RAG_API_URL="http://127.0.0.1:8088", LOLYPOLY_RAG_APP_KEY="test-only-key", LOLYPOLY_RAG_TIMEOUT_SEC=5,
          LOLYPOLY_RAG_LIMIT_PER_10MIN=3)
ANSWER = {"status": "answered", "route": "structured", "answer": "2026-11-10(화) 중식 메뉴는 이렇게 나와요: 상하이파스타",
          "citations": [{"source_id": "meal:2026-11-10:lunch", "title": "2026-11-10(화) 중식 식단",
                         "url": "https://www.kopo.ac.kr/chuncheon/content.do?menu=4819", "quote": "상하이파스타",
                         "locator": "식단 > 2026-11-10(화) 중식", "as_of": "LOLYPOLY 수집 DB · 수집 2026-11-09 06:00 KST",
                         "source_type": "repository_data", "note": None},
                        {"source_id": "x", "title": "나쁜 링크", "url": "javascript:alert(1)", "quote": "q", "locator": "",
                         "as_of": None, "source_type": "public_original", "note": None}],
          "as_of": "2026-11-10T12:00:00+09:00", "request_id": "abc123"}


class FakeResp(io.BytesIO):
    headers = {"Server-Timing": "retrieval;dur=3, generation;dur=0, total;dur=4"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def csrf_client(self):
        c = Client(enforce_csrf_checks=True)
        c.get(reverse("campus:meals"))
        return c, c.cookies["csrftoken"].value

    def post(self, c, token, question="오늘 점심 뭐야?"):
        return c.post(reverse("campus:assistant_ask"), data=json.dumps({"question": question}),
                      content_type="application/json", HTTP_X_CSRFTOKEN=token)

    def test_disabled_by_default_hides_ui_and_endpoint(self):
        with override_settings(LOLYPOLY_RAG_API_URL="", LOLYPOLY_RAG_APP_KEY=""):
            page = self.client.get(reverse("campus:meals"))
            self.assertNotContains(page, "data-assistant")
            self.assertEqual(self.client.post(reverse("campus:assistant_ask"), {}).status_code, 404)

    @override_settings(**ON)
    def test_meals_page_shows_assistant_without_key(self):
        page = self.client.get(reverse("campus:meals"))
        self.assertContains(page, "data-assistant")
        self.assertNotContains(page, "test-only-key")
        self.assertNotContains(page, "127.0.0.1:8088")      # 엔진 주소도 화면에 보내지 않음
        self.assertIn("csrftoken", page.cookies)

    @override_settings(**ON)
    def test_csrf_required_and_get_rejected(self):
        c = Client(enforce_csrf_checks=True)
        r = c.post(reverse("campus:assistant_ask"), data='{"question":"점심"}', content_type="application/json")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(reverse("campus:assistant_ask")).status_code, 405)

    @override_settings(**ON)
    def test_forwards_only_question_with_server_key(self):
        c, token = self.csrf_client()
        with patch("campus.rag.urllib.request.urlopen", return_value=FakeResp(json.dumps(ANSWER).encode())) as op:
            r = self.post(c, token)
        self.assertEqual(r.status_code, 200)
        req = op.call_args.args[0]
        self.assertEqual(req.full_url, "http://127.0.0.1:8088/v1/chat")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-only-key")
        self.assertEqual(json.loads(req.data), {"question": "오늘 점심 뭐야?", "language": "ko", "context": {}})
        body = r.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["citations"][0]["source_label"], "앱 수집 자료")
        self.assertIsNone(body["citations"][1]["url"])        # javascript: 링크는 버림
        self.assertIn("no-cache", r["Cache-Control"])

    @override_settings(**ON)
    def test_failures_are_distinct_errors_not_answers(self):
        c, token = self.csrf_client()
        cases = [(TimeoutError(), 504, "timeout"), (urllib.error.URLError("refused"), 503, "network"),
                 (urllib.error.HTTPError("u", 429, "x", {}, None), 429, "rate_limited"),
                 (urllib.error.HTTPError("u", 401, "x", {}, None), 502, "rejected")]
        for exc, code, kind in cases:
            cache.clear()
            with patch("campus.rag.urllib.request.urlopen", side_effect=exc):
                r = self.post(c, token)
            self.assertEqual((r.status_code, r.json()["error"]), (code, kind))
            self.assertNotIn("answer", r.json())

    @override_settings(**ON)
    def test_unknown_status_becomes_unavailable_and_rate_limit(self):
        c, token = self.csrf_client()
        weird = dict(ANSWER, status="hacked")
        with patch("campus.rag.urllib.request.urlopen", side_effect=lambda *a, **k: FakeResp(json.dumps(weird).encode())):
            self.assertEqual(self.post(c, token).json()["status"], "unavailable")
            self.post(c, token)
            self.post(c, token)
            self.assertEqual(self.post(c, token).status_code, 429)   # 10분 3회 제한(테스트 설정)

    @override_settings(**ON)
    def test_bad_question_rejected(self):
        c, token = self.csrf_client()
        self.assertEqual(self.post(c, token, "").status_code, 400)
        self.assertEqual(self.post(c, token, "가" * 501).status_code, 400)


class ExportRagTests(TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_export_has_public_fields_original_dates_and_failed_status(self):
        collect_meals(weeks=1, fetcher=fake_fetcher(fixture("meals_2026-11-02.html")))
        collect_notices(pages=1, fetcher=fake_fetcher(fixture("notices_p1.html")))
        Meal.objects.update(collected_at="2026-11-02T06:00:00+09:00")   # 원래 수집 시각 그대로 내보내는지
        collect_notices(pages=1, fetcher=failing_fetcher())               # 두 번째 공지 수집 실패 → 기존 공지 유지
        with TemporaryDirectory() as d:
            out = Path(d) / "export.json"
            call_command("export_rag", out=str(out), stdout=io.StringIO())
            data = json.loads(out.read_text(encoding="utf-8"))
        prov = data["provenance"]
        self.assertEqual(prov["collections"]["notices"]["last_run_status"], CollectionRun.Status.FAILED)
        self.assertTrue(prov["collections"]["notices"]["last_success_at"])
        self.assertEqual(prov["collections"]["events"]["last_run_status"], "never")
        self.assertTrue(data["notices"])                                 # 실패해도 마지막 성공 공지가 남음
        self.assertEqual(set(data["meals"][0]), {"date", "meal_type", "items", "source_url", "collected_at"})
        self.assertTrue(data["meals"][0]["collected_at"].startswith("2026-11-01T21:00"))  # 06:00 KST = 전날 21:00 UTC
        self.assertNotIn("feedback", data)
        self.assertEqual(date.fromisoformat(data["meals"][0]["date"]).isoformat(), data["meals"][0]["date"])
