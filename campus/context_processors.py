"""모든 템플릿에서 쓰는 공통 값 (하단 내비게이션, 공식 출처 URL)."""

from django.conf import settings

# 하단 내비게이션: 5개. 시간표는 예시(Mock) 데이터뿐이라 학생 화면에서 숨기고 공지를 넣는다(D-048).
# (원래 결정: docs/DECISIONS.md D-006)
NAV_ITEMS = [
    {"name": "home", "label": "홈", "icon": "home"},
    {"name": "meals", "label": "식단", "icon": "meal"},
    {"name": "schedule", "label": "학사일정", "icon": "calendar"},
    {"name": "notices", "label": "공지", "icon": "notice"},
    {"name": "my", "label": "MY", "icon": "user"},
]

# 상태 미리보기 바를 보여줄 화면 (실제 데이터가 들어갈 화면)
PREVIEW_PAGES = {"home", "meals", "schedule", "notices"}


def site(request):
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    return {
        "nav_items": NAV_ITEMS,
        "current_nav": current,
        "official_url": settings.LOLYPOLY_OFFICIAL_URL,
        "show_state_preview": settings.LOLYPOLY_STATE_PREVIEW and current in PREVIEW_PAGES,
    }
