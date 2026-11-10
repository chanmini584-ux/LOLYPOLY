"""손글씨 제목용 글꼴(개구체 Bold) 부분 글꼴 만들기 — 개발용 도구, 앱 실행에는 필요 없음.

왜 필요한가
  개구체 전체(한글 약 1만 1천 자)는 파일이 커서, 제목·날짜에 쓰는 글자만 남겨 파일 하나로 만든다.
  글자 목록 = ASCII + 아래 EXTRA + templates/ 안의 한글. 목록에 없는 글자는 브라우저가
  본문 글꼴로 자동 대체하므로 화면이 깨지지는 않는다(손글씨만 아닐 뿐).
  손글씨로 보여 줄 새 문구를 추가했다면 EXTRA에 넣고 이 스크립트를 다시 실행한다.

준비 (작업 컴퓨터에서 한 번)
  pip install fonttools==4.68.0 brotli==1.2.1   # 개발 도구. requirements.txt(앱 의존성)에는 넣지 않는다
  원본 글꼴: Google Fonts의 Gaegu-Bold.ttf 한 개,
             또는 npm 패키지 @fontsource/gaegu@5.3.0 의 files/ 폴더(700 굵기 woff2 조각들)

실행
  python scripts/build_hand_font.py <원본 글꼴 파일 또는 폴더>

결과
  static/fonts/lolypoly-hand.woff2  (라이선스: static/fonts/OFL-Gaegu.txt, SIL OFL 1.1)
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "fonts" / "lolypoly-hand.woff2"

# 템플릿 본문에는 없지만 손글씨로 그릴 수 있는 글자: 날짜·요일·끼니·제목 후보
EXTRA = (
    "0123456789 월화수목금토일 요일 년월일 주 첫째 둘째 셋째 넷째 다섯째 이번 지난 다음 "
    "오늘 내일 어제 주말 아침 점심 저녁 조식 중식 석식 밥 지금 까지 분 뒤 시작 끝 남은 날 "
    "수업 공강 점심시간 로그인 로그아웃 회원가입 내 정보 탈퇴 계정 설정 구글 이메일 "
    # 커뮤니티·계정 화면 제목(뷰의 page_title)과 학과 이름(accounts 0003 마이그레이션). 학과를 새로 추가했다면 여기에도 넣는다.
    "커뮤니티 가입 비밀번호 변경 완료 검색 글쓰기 글 수정 볼 수 없는 신고 관리 처리 알림 차단 목록 "
    "내가 쓴 댓글 스크랩 이용 규칙 너무 큰 요청 전체 게시판 융합 미디어크리에이터 바이오의약공정 에너지설비 전기자동차"
)


def needed_chars() -> set[str]:
    chars = {chr(c) for c in range(0x20, 0x7F)} | set("–…") | set(EXTRA)
    for path in sorted((ROOT / "templates").rglob("*.html")):
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        chars |= set(re.findall(r"[가-힣]", text))
    return chars


def source_files(src: Path) -> list[Path]:
    if src.is_file():
        return [src]
    # @fontsource 폴더: 굵기 700 조각만 사용
    files = sorted(src.glob("*-700-normal.woff2")) or sorted(src.glob("*.ttf"))
    if not files:
        sys.exit(f"원본 글꼴을 찾지 못했습니다: {src}")
    return files


def main() -> None:
    try:
        from fontTools import subset
        from fontTools.merge import Merger
        from fontTools.ttLib import TTFont
    except ImportError:
        sys.exit("fonttools가 필요합니다: pip install fonttools==4.68.0 brotli==1.2.1")

    parser = argparse.ArgumentParser(description="손글씨 제목용 부분 글꼴 만들기")
    parser.add_argument("source", type=Path, help="Gaegu-Bold.ttf 또는 @fontsource/gaegu 의 files 폴더")
    args = parser.parse_args()

    wanted = {ord(c) for c in needed_chars()}
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, path in enumerate(source_files(args.source)):
            font = TTFont(path)
            keep = wanted & set(font.getBestCmap())
            if not keep:
                continue
            options = subset.Options()
            options.notdef_outline = True
            subsetter = subset.Subsetter(options)
            subsetter.populate(unicodes=keep)
            subsetter.subset(font)
            font.flavor = None
            part = Path(tmp) / f"part{i}.ttf"
            font.save(part)
            parts.append(part)
        if not parts:
            sys.exit("필요한 글자가 원본 글꼴에 없습니다.")
        merged = Merger().merge(parts) if len(parts) > 1 else TTFont(parts[0])
        merged.flavor = "woff2"
        OUT.parent.mkdir(parents=True, exist_ok=True)
        merged.save(OUT)

    covered = wanted & set(TTFont(OUT).getBestCmap())
    missing = sorted(chr(c) for c in wanted - covered if c > 0x20)
    print(f"저장: {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KB), 글자 {len(covered)}개")
    if missing:
        print("원본에 없는 글자(기본 글꼴로 표시):", "".join(missing))


if __name__ == "__main__":
    main()
