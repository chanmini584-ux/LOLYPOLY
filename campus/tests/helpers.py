from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fake_fetcher(*pages):
    """collect_* 에 넘길 가짜 fetcher: 네트워크 없이 저장된 HTML을 돌려준다."""
    def fetch(_weeks=None):
        return list(pages)
    return fetch


def failing_fetcher(exc=None):
    def fetch(_weeks=None):
        raise exc or TimeoutError("공식 홈페이지 응답 없음 (테스트)")
    return fetch
