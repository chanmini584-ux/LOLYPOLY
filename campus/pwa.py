"""PWA 구성: 웹 앱 매니페스트, 서비스 워커, 오프라인 화면.

서비스 워커는 사이트 전체(scope: /)를 다루려면 루트 경로(/sw.js)에서 제공돼야 해서
정적 파일이 아니라 Django 뷰(템플릿)로 내보낸다. 캐시 버전은 정적 파일 내용의 해시로 정해
CSS·JS·아이콘이 바뀌면 자동으로 새 캐시를 쓴다.
"""

import hashlib
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control

PRECACHE_ASSETS = ["css/app.css", "js/app.js", "icons/icon-192.png", "icons/apple-touch-icon.png"]
CACHEABLE_PAGE_NAMES = ["home", "meals", "schedule", "notices", "timetable", "my"]


@lru_cache(maxsize=1)
def cache_version() -> str:
    digest = hashlib.sha256()
    for directory in settings.STATICFILES_DIRS:
        for path in sorted(Path(directory).rglob("*")):
            if path.is_file():
                digest.update(path.name.encode())
                digest.update(path.read_bytes())
    digest.update((Path(settings.BASE_DIR) / "templates/pwa/sw.js").read_bytes())
    return digest.hexdigest()[:12]


@cache_control(no_cache=True)
def manifest(request):
    return render(request, "pwa/manifest.webmanifest", content_type="application/manifest+json")


@cache_control(no_cache=True)  # 브라우저가 항상 새 서비스 워커가 있는지 확인하도록
def service_worker(request):
    return render(request, "pwa/sw.js", {
        "cache_version": cache_version(),
        "cacheable_pages": [reverse(f"campus:{n}") for n in CACHEABLE_PAGE_NAMES],
        "precache_assets": [static(a) for a in PRECACHE_ASSETS],
        "static_url": settings.STATIC_URL if settings.STATIC_URL.startswith("/") else "/" + settings.STATIC_URL,
    }, content_type="application/javascript")


def offline(request):
    return render(request, "campus/offline.html", {"page_title": "오프라인", "hide_cached_banner": True})
