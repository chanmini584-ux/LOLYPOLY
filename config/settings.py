"""
Lolypoly Django 설정.

환경변수(.env)에서 민감 정보와 환경별 값을 읽는다.
- 개발: .env.example 을 .env 로 복사해 사용
- 운영: DJANGO_DEBUG=False, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS 를 반드시 지정
"""

import os
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
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
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


STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"  # collectstatic 결과 (운영용, Git 제외)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# 공식 출처 (확인된 URL만 기록한다. 세부 페이지 URL은 수집 단계에서 직접 조사 후 추가)
LOLYPOLY_OFFICIAL_URL = "https://www.kopo.ac.kr/chuncheon/index.do"

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
}

# 수집기 동작
LOLYPOLY_COLLECTOR_TIMEOUT_MS = env_int("LOLYPOLY_COLLECTOR_TIMEOUT_MS", 30000)
LOLYPOLY_COLLECTOR_DELAY_SEC = env_int("LOLYPOLY_COLLECTOR_DELAY_SEC", 2)
LOLYPOLY_COLLECTOR_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome Safari/537.36 "
    "LolypolyCollector/0.1 (+https://github.com/lovesome0405/Lolypoly)"
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"campus.collectors": {"handlers": ["console"], "level": "INFO"}},
}
