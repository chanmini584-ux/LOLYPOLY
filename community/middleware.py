"""사진 올리기 요청의 전체 크기 제한. 본문을 읽기 전에 Content-Length 로 먼저 거절한다."""

from django.conf import settings
from django.shortcuts import render


class UploadSizeLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST":
            try:
                length = int(request.META.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            limit = settings.COMMUNITY_MAX_REQUEST_BYTES if request.path.startswith("/community/") else 2 * 1024 * 1024
            if length > limit and not request.path.startswith("/admin/"):
                return render(request, "community/too_large.html", {
                    "page_title": "너무 큰 요청",
                    "max_count": settings.COMMUNITY_PHOTO_MAX_COUNT,
                    "max_mb": settings.COMMUNITY_PHOTO_MAX_BYTES // (1024 * 1024),
                }, status=413)
        return self.get_response(request)
