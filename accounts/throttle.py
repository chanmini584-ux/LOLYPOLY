"""로그인 시도·가입 횟수 제한 (서버 캐시 사용).

- 기준은 '아이디'다. 같은 학교 Wi-Fi(같은 IP)를 쓰는 다른 학생이 함께 막히지 않게,
  IP 는 훨씬 느슨한 한도의 보조 신호로만 쓴다.
- 접속 주소는 캐시 키에 해시로만 넣는다.
- 횟수는 (횟수, 창이 끝나는 시각)으로 저장한다. cache.incr 는 운영 캐시(파일 캐시)에서 만료 시간을
  기본값 300초로 다시 써서, 설정한 창(로그인 600초·가입 3600초)이 지켜지지 않았다(ERR-012).
"""

import hashlib
import time

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


def _read(key: str) -> tuple[int, float]:
    """(횟수, 창이 끝나는 시각). 없거나 창이 끝났으면 (0, 0)."""
    entry = cache.get(key)
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        count, until = int(entry[0]), float(entry[1])
        return (count, until) if until > time.time() else (0, 0.0)
    if isinstance(entry, int):        # 이전 형식(횟수만 저장). 창 끝을 모르므로 다음 기록 때 새 창을 연다
        return entry, 0.0
    return 0, 0.0


def _count(key: str) -> int:
    return _read(key)[0]


def _bump(key: str, window: int) -> int:
    """횟수를 1 올린다. 창은 첫 기록부터 window 초이며, 그 뒤 기록은 창을 늘리지 않는다."""
    now = time.time()
    count, until = _read(key)
    if until <= now:
        until = now + window
    count += 1
    cache.set(key, (count, until), max(1, int(until - now) + 1))
    return count


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
