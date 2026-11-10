"""
Lolypoly Django 설정.

환경변수(.env)에서 민감 정보와 환경별 값을 읽는다.
- 개발: .env.example 을 .env 로 복사해 사용
- 운영: DJANGO_DEBUG=False, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS 를 반드시 지정
"""

import os
import sys
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# 프로젝트 루트의 .env 를 읽는다. 이미 설정된 OS 환경변수가 우선한다.
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():  # 비어 있으면 기본값
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# 안전한 기본값: DEBUG 는 명시적으로 켜야 한다.
DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # 로컬 개발 전용 키. 운영에서는 절대 사용되지 않는다(DEBUG=False면 아래 예외).
        SECRET_KEY = "django-insecure-local-dev-only-change-me"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY 가 없습니다. 개발 환경이라면 .env.example 을 .env 로 복사하세요."
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

# 프로토타입 호스팅(Render)이 자동으로 넣어 주는 공개 주소. 다른 서버에서는 없으므로 영향 없음.
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if _render_host:
    ALLOWED_HOSTS.append(_render_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_render_host}")

# Nginx 가 X-Real-IP 를 덮어써 주는 구조에서만 True (도배 제한의 접속 주소 판별용)
TRUST_PROXY_IP = env_bool("LOLYPOLY_TRUST_PROXY_IP", default=False)

# 의견 폼 도배 제한 (D-061): 기준은 '브라우저'(쿠키), 접속 주소(IP)는 느슨한 보조 한도.
# 학교 Wi-Fi 는 여러 학생이 같은 주소로 보이므로 주소만으로 막으면 정상 이용자가 함께 막힌다.
FEEDBACK_HOURLY_LIMIT = int(os.environ.get("LOLYPOLY_FEEDBACK_HOURLY_LIMIT", "5").strip() or 5)
FEEDBACK_IP_HOURLY_LIMIT = int(os.environ.get("LOLYPOLY_FEEDBACK_IP_HOURLY_LIMIT", "120").strip() or 120)

# HTTPS 운영 설정. Nginx·호스팅이 HTTPS를 처리하고 앱에는 HTTP로 넘겨 주는 구조를 가정한다.
# DJANGO_HTTPS=True: HTTP→HTTPS 이동, 쿠키 HTTPS 전용, 프록시의 X-Forwarded-Proto 신뢰.
# (X-Forwarded-Proto를 덮어쓰는 프록시 뒤에서만 켠다. 앱 포트를 인터넷에 직접 열면 켜지 않는다.)
if env_bool("DJANGO_HTTPS", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
# HSTS는 한 번 켜면 브라우저가 기간 동안 HTTP 접속을 거부한다. 주소가 확정된 뒤에만 늘린다(기본 0 = 끔).
SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0").strip() or 0)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 프로젝트 앱
    "accounts",
    "campus",
    "community",
]

MIDDLEWARE = [
    "campus.middleware.AppMarkerMiddleware",  # 모든 응답에 X-Lolypoly 표시 (D-055, 서비스 워커가 사용)
    "django.middleware.security.SecurityMiddleware",
    # 운영(DEBUG=False)에서 정적 파일(CSS·JS·아이콘)을 Gunicorn이 직접 제공. Nginx를 쓰면 Nginx가 먼저 처리해도 된다.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "accounts.middleware.AdminLoginThrottleMiddleware",   # 관리자 로그인 실패 횟수 제한
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.PrivateCacheMiddleware",         # 커뮤니티·계정·MY 화면은 어디에도 저장 금지
    "community.middleware.UploadSizeLimitMiddleware",     # 사진 올리기 요청 전체 크기 제한
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "campus.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# 초기 개발 DB: SQLite (잠정). 운영 DB 변경은 docs/DECISIONS.md 의 재검토 조건을 따른다.
_sqlite_path = os.environ.get("DJANGO_SQLITE_PATH", "").strip() or str(BASE_DIR / "db.sqlite3")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _sqlite_path,
        # 글·댓글처럼 쓰기가 생기므로: 잠겨 있으면 20초까지 기다리고, 쓰기 트랜잭션은 시작할 때 잠금을 잡는다
        # (읽다가 쓰기로 바뀌며 생기는 'database is locked' 를 피한다. Django 5.1+ transaction_mode).
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
    }
}

# 처음부터 Custom User Model 을 사용한다 (최초 마이그레이션 전에 지정해야 함).
AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# 한국 학교 정보 기준: 한국어 / Asia/Seoul. DB 에는 UTC 로 저장(USE_TZ=True)하고 표시만 서울 시간.
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True


# ── 계정 ──
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "community:home"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30      # '로그인 유지'를 켠 경우의 최대 기간. 끄면 브라우저를 닫을 때 끝난다(뷰에서 지정)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
# 로그인 실패 제한: 아이디 기준(같은 Wi-Fi 의 다른 학생은 영향 없음). IP 는 훨씬 느슨한 보조 한도.
LOGIN_FAIL_LIMIT = int(os.environ.get("LOLYPOLY_LOGIN_FAIL_LIMIT", "8").strip() or 8)
LOGIN_FAIL_WINDOW_SEC = int(os.environ.get("LOLYPOLY_LOGIN_FAIL_WINDOW_SEC", "600").strip() or 600)
LOGIN_FAIL_IP_LIMIT = int(os.environ.get("LOLYPOLY_LOGIN_FAIL_IP_LIMIT", "200").strip() or 200)
SIGNUP_IP_HOURLY_LIMIT = int(os.environ.get("LOLYPOLY_SIGNUP_IP_HOURLY_LIMIT", "60").strip() or 60)

# ── 커뮤니티 ──
# 사진은 코드 폴더·Git 밖에 둔다. 기본: DB 파일과 같은 폴더의 media/ (학교 PC: D:\lolypoly\data\media).
# 공개 주소(MEDIA_URL)는 만들지 않는다. 사진은 로그인·열람 권한을 확인하는 뷰(community.views.photo)로만 나간다.
MEDIA_ROOT = os.environ.get("LOLYPOLY_MEDIA_ROOT", "").strip() or str(Path(_sqlite_path).resolve().parent / "media")
COMMUNITY_PHOTO_MAX_COUNT = int(os.environ.get("LOLYPOLY_PHOTO_MAX_COUNT", "5").strip() or 5)
COMMUNITY_PHOTO_MAX_BYTES = int(os.environ.get("LOLYPOLY_PHOTO_MAX_MIB", "10").strip() or 10) * 1024 * 1024
COMMUNITY_PHOTO_MAX_EDGE = int(os.environ.get("LOLYPOLY_PHOTO_MAX_EDGE", "1920").strip() or 1920)
# 화소 수 한도: 요즘 휴대폰 기본 사진(12~50MP)은 통과, 200MP 모드 같은 초대형은 거절. 60MP ≈ 풀 때 메모리 약 180MB.
COMMUNITY_PHOTO_MAX_PIXELS = int(os.environ.get("LOLYPOLY_PHOTO_MAX_MEGAPIXELS", "60").strip() or 60) * 1_000_000
# 도배 제한(계정 기준)
COMMUNITY_POST_LIMIT = int(os.environ.get("LOLYPOLY_POST_LIMIT", "5").strip() or 5)
COMMUNITY_POST_WINDOW_SEC = int(os.environ.get("LOLYPOLY_POST_WINDOW_SEC", "600").strip() or 600)
COMMUNITY_COMMENT_LIMIT = int(os.environ.get("LOLYPOLY_COMMENT_LIMIT", "20").strip() or 20)
COMMUNITY_COMMENT_WINDOW_SEC = int(os.environ.get("LOLYPOLY_COMMENT_WINDOW_SEC", "300").strip() or 300)
COMMUNITY_REPORT_LIMIT = int(os.environ.get("LOLYPOLY_REPORT_HOURLY_LIMIT", "20").strip() or 20)
# 서로 다른 계정의 처리 전 신고가 이만큼 모이면 운영자 확인 전까지 '임시' 숨김. 0 이면 자동 숨김 끔.
COMMUNITY_REPORT_AUTOHIDE = int(os.environ.get("LOLYPOLY_REPORT_AUTOHIDE", "5").strip() or 0)
# 작성자가 지웠지만 처리 전 신고가 있는 글·댓글을 운영자 검토용으로 남겨 두는 최대 일수
COMMUNITY_REVIEW_RETENTION_DAYS = int(os.environ.get("LOLYPOLY_REVIEW_RETENTION_DAYS", "30").strip() or 30)
# 요청 하나의 최대 크기: 사진 최대 장수 × 한 장 크기 + 여유 2MiB
COMMUNITY_MAX_REQUEST_BYTES = COMMUNITY_PHOTO_MAX_COUNT * COMMUNITY_PHOTO_MAX_BYTES + 2 * 1024 * 1024

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic 결과 (운영용, Git 제외)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# 공식 출처 (확인된 URL만 기록한다. 세부 페이지 URL은 수집 단계에서 직접 조사 후 추가)
LOLYPOLY_OFFICIAL_URL = "https://www.kopo.ac.kr/chuncheon/index.do"

# 시험 사용 의견 받기 (D-057): 구글 폼 등 https 주소. 비워두면 '의견 보내기'를 숨긴다.
_feedback = os.environ.get("LOLYPOLY_FEEDBACK_URL", "").strip()
LOLYPOLY_FEEDBACK_URL = _feedback if _feedback.startswith("https://") else ""

# 화면 상태 미리보기(?preview=empty|error|error-empty|stale). 개발·시연용이며 기본은 DEBUG일 때만 켠다.
LOLYPOLY_STATE_PREVIEW = env_bool("LOLYPOLY_STATE_PREVIEW", default=DEBUG)


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


# 수집 주기(일). 마지막 성공 후 '주기 + 1일'이 지나면 화면에 '오래된 데이터'로 표시한다.
# 실제 자동 실행 주기는 서버의 스케줄 설정(deploy/)과 맞춰야 한다.
LOLYPOLY_COLLECT_INTERVAL_DAYS = {
    "meals": env_int("LOLYPOLY_INTERVAL_MEALS", 7),
    "events": env_int("LOLYPOLY_INTERVAL_EVENTS", 7),
    "notices": env_int("LOLYPOLY_INTERVAL_NOTICES", 7),
    "bus": env_int("LOLYPOLY_INTERVAL_BUS", 7),
}

# 버스: 국토교통부 TAGO OpenAPI (공공데이터포털). 키가 없으면 버스 화면은 '설정 필요' 안내만 보여 준다.
TAGO_SERVICE_KEY = os.environ.get("TAGO_SERVICE_KEY", "").strip()

# 서버 캐시 (D-056): 실시간 버스 결과를 Gunicorn 워커·스레드가 함께 쓰도록 파일 캐시.
# 기본 위치는 운영체제 임시 폴더(컨테이너에서도 앱 사용자가 쓸 수 있음). 재시작하면 비어도 괜찮은 값만 넣는다.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("LOLYPOLY_CACHE_DIR", "").strip()
        or str(Path(tempfile.gettempdir()) / "lolypoly-cache"),
    }
}
# 테스트는 실행마다 빈 메모리 캐시로 (이전 실행·개발 서버의 캐시 파일이 결과를 바꾸지 않게)
if sys.argv[1:2] == ["test"]:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
TAGO_TIMEOUT_SEC = env_int("TAGO_TIMEOUT_SEC", 6)
# 실시간 위치를 서버에서 묶어 두는 시간(초). 이 시간 안의 요청은 TAGO 를 다시 부르지 않는다(호출 한도 보호).
LOLYPOLY_BUS_LIVE_CACHE_SEC = env_int("LOLYPOLY_BUS_LIVE_CACHE_SEC", 30)

# 수집기 동작
LOLYPOLY_COLLECTOR_TIMEOUT_MS = env_int("LOLYPOLY_COLLECTOR_TIMEOUT_MS", 30000)
LOLYPOLY_COLLECTOR_DELAY_SEC = env_int("LOLYPOLY_COLLECTOR_DELAY_SEC", 2)
LOLYPOLY_COLLECTOR_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36 "
    "LolypolyCollector/0.1 (+https://github.com/chanmini584-ux/LOLYPOLY)"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"campus.collectors": {"handlers": ["console"], "level": "INFO"}},
}
