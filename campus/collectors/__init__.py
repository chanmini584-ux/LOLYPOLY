"""공식 홈페이지 공개정보 수집기.

구성
- sources.py : 공식 페이지 URL (홈페이지 메뉴에서 직접 확인한 값만)
- base.py    : Playwright 브라우저 열기, 수집 실행 기록(CollectionRun), 공통 오류
- meals.py   : 식단 (파싱 → 검증 → 원자적 저장)

수집 흐름: fetch(Playwright) → parse(BeautifulSoup) → validate → save(transaction.atomic)
fetch 와 parse 를 분리해, 파서는 저장해 둔 실제 HTML(fixture)로 네트워크 없이 테스트한다.
"""
