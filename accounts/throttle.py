"""로그인 시도·가입 횟수 제한 (서버 캐시 사용).

- 기준은 '아이디'다. 같은 학교 Wi-Fi(같은 IP)를 쓰는 다른 학생이 함께 막히지 않게,
  IP 는 훨씬 느슨한 한도의 보조 신호로만 쓴다.
- 접속 주소는 캐시 키에 해시로만 넣는다.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request) -> str:
    ip = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "TRUST_PROXY_IP", False):
        ip = request.META.get("HTTP_CF_CONNECTING_IP") or request.META.get("HTTP_X_REAL_IP", ip)
    return ip


def _h(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{settings.SECRET_KEY}|{kind}|{value}".encode()).hexdigest()[:24]
    return f"lp-thr-{kind}-{digest}"


def _count(key: str) -> int:
    return int(cache.get(key) or 0)


def _bump(key: str, window: int) -> int:
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return 1


def login_locked(request, username: str) -> bool:
    name = (username or "").strip().lower()
    if name and _count(_h("login-user", name)) >= settings.LOGIN_FAIL_LIMIT:
        return True
    return _count(_h("login-ip", client_ip(request))) >= settings.LOGIN_FAIL_IP_LIMIT


def login_failed(request, username: str) -> None:
    name = (username or "").strip().lower()
    if name:
        _bump(_h("login-user", name), settings.LOGIN_FAIL_WINDOW_SEC)
    _bump(_h("login-ip", client_ip(request)), settings.LOGIN_FAIL_WINDOW_SEC)


def login_succeeded(request, username: str) -> None:
    cache.delete(_h("login-user", (username or "").strip().lower()))


def signup_limited(request) -> bool:
    return _count(_h("signup-ip", client_ip(request))) >= settings.SIGNUP_IP_HOURLY_LIMIT


def signup_done(request) -> None:
    _bump(_h("signup-ip", client_ip(request)), 3600)
