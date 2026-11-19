"""롤리폴리 안내(RAG) 연결 — 서버 측에서만 공통 RAG 엔진을 부른다 (D-073).

흐름: 브라우저 → 같은 출처 POST /assistant/ask/ (CSRF 검사) → 여기 ask() → RAG 엔진 POST /v1/chat (Bearer 앱 키)
- API 주소·앱 키는 서버 환경변수(LOLYPOLY_RAG_API_URL, LOLYPOLY_RAG_APP_KEY)에만 둔다. 화면·브라우저에 보내지 않는다.
- 둘 중 하나라도 비어 있으면 기능이 꺼진다(화면에 안내 칸을 그리지 않음).
- 지금 질문 한 개만 보낸다. 대화 기록·로그인 정보·커뮤니티·의견 같은 개인 데이터는 보내지 않는다.
- 엔진 응답은 공통 계약(status, route, answer, citations, as_of, request_id)을 그대로 쓰되, 링크는 http(s)만 남긴다.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger("campus.rag")

STATUSES = {"answered", "partial", "insufficient_evidence", "clarification_needed", "unavailable"}
SOURCE_LABELS = {"public_original": "공식 원문", "repository_data": "앱 수집 자료", "synthetic": "합성 테스트 자료"}
MAX_QUESTION = 500


@dataclass
class RagError(Exception):
    """엔진에 닿지 못했거나 엔진이 요청을 거부함. kind: timeout | network | rejected | rate_limited | bad_response"""
    kind: str
    http_status: int | None = None


def is_enabled() -> bool:
    return bool(settings.LOLYPOLY_RAG_API_URL and settings.LOLYPOLY_RAG_APP_KEY)


def _safe_url(url) -> str | None:
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def clean_response(data: dict) -> dict:
    """엔진 응답을 화면용으로 좁힌다. 모르는 상태는 unavailable 로, 링크는 웹 주소만."""
    status = data.get("status") if data.get("status") in STATUSES else "unavailable"
    cites = []
    for c in data.get("citations") or []:
        if not isinstance(c, dict):
            continue
        cites.append({
            "title": str(c.get("title") or ""),
            "url": _safe_url(c.get("url")),
            "quote": str(c.get("quote") or "")[:400],
            "locator": str(c.get("locator") or ""),
            "as_of": str(c.get("as_of") or ""),
            "source_type": str(c.get("source_type") or ""),
            "source_label": SOURCE_LABELS.get(c.get("source_type"), "자료"),
            "note": str(c.get("note") or ""),
        })
    return {"status": status, "route": str(data.get("route") or ""), "answer": str(data.get("answer") or ""),
            "citations": cites, "as_of": str(data.get("as_of") or ""), "request_id": str(data.get("request_id") or "")}


def ask(question: str, language: str = "ko") -> dict:
    """질문 하나를 엔진에 보낸다. 실패는 RagError 로 알린다(장애 문구를 답변처럼 만들지 않는다)."""
    url = settings.LOLYPOLY_RAG_API_URL.rstrip("/") + "/v1/chat"
    body = json.dumps({"question": question[:MAX_QUESTION], "language": language, "context": {}}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {settings.LOLYPOLY_RAG_APP_KEY}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=settings.LOLYPOLY_RAG_TIMEOUT_SEC) as r:
            data = json.loads(r.read().decode("utf-8"))
            timing = r.headers.get("Server-Timing", "")
    except urllib.error.HTTPError as exc:
        kind = "rate_limited" if exc.code == 429 else "rejected"
        logger.warning("rag http %s", exc.code)
        raise RagError(kind, exc.code) from None
    except TimeoutError:
        raise RagError("timeout") from None
    except urllib.error.URLError as exc:
        raise RagError("timeout" if isinstance(exc.reason, TimeoutError) else "network") from None
    except (ValueError, UnicodeDecodeError):
        raise RagError("bad_response") from None
    # 질문 원문은 남기지 않는다. 구간 지연만(엔진 Server-Timing + 앱→엔진 왕복)
    logger.info("rag ok request_id=%s status=%s app_ms=%.0f engine=%s", data.get("request_id"), data.get("status"),
                (time.monotonic() - t0) * 1000, timing)
    return clean_response(data)
