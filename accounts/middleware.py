"""계정 관련 미들웨어.

PrivateCacheMiddleware
  로그인해야 보이는 화면(커뮤니티·계정·MY·관리자)은 브라우저·중간 서버·서비스 워커 어디에도 저장되지 않게
  'no-store, private' 를 붙인다. 공개 화면(식단·일정·공지 등)은 로그인 여부와 상관없이 같은 내용이라 그대로 둔다.

AdminLoginThrottleMiddleware
  /admin/login/ 은 누구나 열 수 있는 주소라, 아이디 기준으로 로그인 실패 횟수를 제한한다.
"""

from django.http import HttpResponse
from django.utils.cache import add_never_cache_headers

from . import throttle

PRIVATE_PREFIXES = ("/community/", "/accounts/", "/my/", "/admin/")


class PrivateCacheMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(PRIVATE_PREFIXES):
            add_never_cache_headers(response)
        return response


class AdminLoginThrottleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        watching = request.method == "POST" and request.path == "/admin/login/"
        username = request.POST.get("username", "") if watching else ""
        if watching and throttle.login_locked(request, username):
            return HttpResponse("로그인 시도가 너무 많아요. 잠시 뒤 다시 시도해 주세요.", status=429,
                                content_type="text/plain; charset=utf-8")
        response = self.get_response(request)
        if watching:
            if response.status_code == 200:      # 로그인 폼이 다시 나옴 = 실패
                throttle.login_failed(request, username)
            elif response.status_code in (301, 302):
                throttle.login_succeeded(request, username)
        return response
