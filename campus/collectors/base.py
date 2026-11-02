"""수집 공통 기능."""

import logging
import time
from contextlib import contextmanager

from django.conf import settings
from django.utils import timezone

from ..models import CollectionRun

logger = logging.getLogger("campus.collectors")


class ParseError(Exception):
    """페이지 구조가 예상과 다름 → 이번 수집 결과를 저장하지 않는다."""


@contextmanager
def browser_page():
    """Playwright 크롬(헤드리스) 페이지 하나를 연다.

    Playwright 는 수집할 때만 필요하므로 여기서 import 한다(웹 화면 실행에는 불필요).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=settings.LOLYPOLY_COLLECTOR_USER_AGENT, locale="ko-KR")
            page = context.new_page()
            page.set_default_timeout(settings.LOLYPOLY_COLLECTOR_TIMEOUT_MS)
            yield page
        finally:
            browser.close()


def polite_pause():
    """연속 요청 사이 대기 (공식 사이트 부담 최소화)."""
    time.sleep(settings.LOLYPOLY_COLLECTOR_DELAY_SEC)


def run_collection(source: str, job) -> CollectionRun:
    """job() 을 실행하고 결과를 CollectionRun 으로 남긴다.

    job 은 (저장 건수, 요약 메시지)를 돌려준다. 예외가 나면 실패로 기록하고
    예외를 밖으로 던지지 않는다 → 한 종류의 실패가 다른 수집을 멈추지 않는다.
    job 안에서 저장은 검증이 끝난 뒤 transaction.atomic 으로만 하므로,
    실패한 수집은 기존 데이터를 바꾸지 않는다.
    """
    run = CollectionRun.objects.create(source=source)
    try:
        count, message = job()
        run.status = CollectionRun.Status.SUCCESS
        run.item_count = count
        run.message = message
    except Exception as exc:  # 네트워크·구조 변경 등 모든 실패를 기록
        logger.exception("collection failed: %s", source)
        run.status = CollectionRun.Status.FAILED
        run.message = f"{type(exc).__name__}: {exc}"[:2000]
    run.finished_at = timezone.now()
    run.save()
    return run
