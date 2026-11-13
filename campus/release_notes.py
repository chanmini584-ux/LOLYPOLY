"""버전별 업데이트 소식 — 앱 화면의 '업데이트 안내' 창과 /updates/ 화면이 이 목록을 그대로 보여 준다.

새 버전을 낼 때
  1. 루트 VERSION 을 올린다(AGENTS.md 8장).
  2. 이 목록 **맨 위**에 항목을 추가한다. version 은 VERSION 과 같아야 한다(테스트가 확인).
  3. 학생이 읽는 글이다: 무엇이 생겼고 어디서 쓰는지를 짧게. 내부 용어·오류 번호는 쓰지 않는다.
README 의 버전별 기능 이력(개발자용 상세 기록)과는 별개다.
"""

from pathlib import Path

from django.conf import settings

RELEASES = [
    {
        "version": "0.4.0-beta",
        "date": "2026-11-13",
        "title": "택시 같이 탈 사람을 구해요",
        "items": [
            "커뮤니티 탭의 택시 같이 타기에서 출발 시각·장소·정원(2~4명)을 정해 방을 만들 수 있어요.",
            "먼저 들어온 순서대로 자리가 차고, 방 안에서는 '방장'·'익명1'처럼 익명으로 대화해요.",
            "방장이 방을 터뜨리거나 출발 1시간이 지나면 방과 대화가 사라져요.",
            "연락처·학번은 적지 말고, 사람 많은 곳에서 만나요.",
        ],
    },
    {
        "version": "0.3.0-beta",
        "date": "2026-11-11",
        "title": "업데이트 소식을 알려 드려요",
        "items": [
            "새 버전이 나오면 처음 열 때 무엇이 바뀌었는지 이 창으로 알려 드려요.",
            "지난 소식은 MY → '업데이트 소식'에서 다시 볼 수 있어요.",
        ],
    },
    {
        "version": "0.2.0-beta",
        "date": "2026-11-10",
        "title": "학과 커뮤니티가 생겼어요",
        "items": [
            "가입하면 전체 게시판과 학과별 익명 게시판을 쓸 수 있어요. 아래 '커뮤니티' 탭에서 시작해요.",
            "모든 학과 게시판을 읽을 수 있고, 글·댓글은 전체 게시판과 내 학과에 쓸 수 있어요.",
            "글에 사진을 5장까지 올릴 수 있어요.",
            "내 글에 댓글이 달리면 MY의 알림에서 확인해요.",
            "공지사항은 홈과 MY에서 열 수 있어요.",
        ],
    },
    {
        "version": "0.1.0-beta",
        "date": "2026-11-10",
        "title": "첫 베타",
        "items": [
            "식단·학사일정·공지를 한곳에서 볼 수 있어요.",
            "학교 버스가 지금 어디쯤 오는지 볼 수 있어요.",
            "홈 화면에 앱으로 설치할 수 있어요.",
        ],
    },
]

SHEET_MAX = 2      # 안내 창에 한 번에 보여 줄 최대 버전 수(더 오래된 것은 /updates/ 에서)


def current_version() -> str:
    try:
        return (Path(settings.BASE_DIR) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return RELEASES[0]["version"]


def label(version: str) -> str:
    """'0.3.0-beta' → 'beta v0.3' (PATCH 가 0 이 아니면 'beta v0.3.1')."""
    number, _, stage = version.partition("-")
    parts = number.split(".")
    short = ".".join(parts[:2]) if parts[2:] == ["0"] else number
    return f"{stage} v{short}" if stage else f"v{short}"


def releases() -> list[dict]:
    return [{**r, "label": label(r["version"])} for r in RELEASES]
