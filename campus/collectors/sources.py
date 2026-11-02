"""공식 페이지 주소.

2026-11-02 춘천캠퍼스 홈페이지(https://www.kopo.ac.kr/chuncheon/index.do) 주메뉴에서 확인:
- 학교식당 > 식단 정보  → content.do?menu=4819
- 학사안내 > 학사일정  → content.do?menu=4797
- 공지사항             → board.do?menu=4827
robots.txt(2026-11-02 확인)는 다운로드·뷰어·검색 경로만 막고 위 경로는 막지 않는다.
"""

BASE = "https://www.kopo.ac.kr"
MEALS_URL = f"{BASE}/chuncheon/content.do?menu=4819"
EVENTS_URL = f"{BASE}/chuncheon/content.do?menu=4797"
NOTICES_URL = f"{BASE}/chuncheon/board.do?menu=4827"
