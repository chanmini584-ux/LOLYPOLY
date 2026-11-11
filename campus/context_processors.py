"""모든 템플릿에서 쓰는 공통 값 (하단 내비게이션, 공식 출처 URL)."""

from django.conf import settings

from . import release_notes

# 하단 내비게이션: 5개 (D-006). 공지는 홈·MY 에서 바로 가고 주소(/notices/)는 그대로다(D-059).
NAV_ITEMS = [
    {"name": "home", "url": "campus:home", "label": "홈"},
    {"name": "meals", "url": "campus:meals", "label": "식단"},
    {"name": "schedule", "url": "campus:schedule", "label": "학사일정"},
    {"name": "community", "url": "community:home", "label": "커뮤니티"},
    {"name": "my", "url": "campus:my", "label": "MY"},
]

# 상태 미리보기 바를 보여줄 화면 (실제 데이터가 들어갈 화면)
PREVIEW_PAGES = {"home", "meals", "schedule", "notices", "bus"}


def site(request):
    match = getattr(request, "resolver_match", None)
    current = match.url_name if match else ""
    namespace = match.namespace if match else ""
    # 하단 탭 강조: 커뮤니티 화면 전체는 '커뮤니티', 계정 화면은 'MY'
    nav = {"community": "community", "accounts": "my"}.get(namespace, current)
    return {
        "nav_items": NAV_ITEMS,
        "current_nav": nav,
        "official_url": settings.LOLYPOLY_OFFICIAL_URL,
        # 업데이트 안내 창(D-069): 모든 화면에 같은 내용으로 들어가고, 보여 줄지는 app.js 가 이 기기의 기록으로 정한다
        "app_version": release_notes.current_version(),
        "update_releases": release_notes.releases()[:release_notes.SHEET_MAX],
        "feedback_url": settings.LOLYPOLY_FEEDBACK_URL,
        "show_state_preview": settings.LOLYPOLY_STATE_PREVIEW and namespace == "campus" and current in PREVIEW_PAGES,
        # 로그인 여부에 따라 달라지는 화면(저장 금지 화면)에서만 알림 문구를 그린다.
        # 공개 화면은 누구에게나 같은 내용이어야 서비스 워커가 저장해도 안전하다.
        "private_page": namespace in {"community", "accounts"} or (namespace == "campus" and current == "my"),
    }
