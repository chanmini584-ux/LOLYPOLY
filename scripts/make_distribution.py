"""학생 배포물 만들기: 단독 QR(PNG·SVG) + 배포 안내 이미지(PNG·PDF) + 디코딩 검증.

개발 도구다(앱 의존성 아님). 준비:
  pip install qrcode==8.2 pillow==13.0.0 opencv-python-headless==4.12.0.88
  손글씨 제목 글꼴: Gaegu-Bold.ttf (Google Fonts, SIL OFL 1.1) — --hand-font 로 경로 지정
  본문 글꼴: Windows 맑은 고딕(기본) 또는 Noto Sans CJK — --body-font/--body-bold 로 지정

사용:
  python scripts/make_distribution.py https://<확정 주소>/            # → docs/distribution/
  python scripts/make_distribution.py https://<시험 주소>/ --out <다른 폴더> --draft   # 시험본(“인쇄 금지” 표시)

결과(docs/distribution/):
  lolypoly-qr.png / lolypoly-qr.svg               단독 QR (위에 Lolypoly, 아래 주소)
  lolypoly-poster.png (A4 300dpi) / lolypoly-poster.pdf   학생 배포 안내
만든 PNG 를 실제로 읽어 주소가 같은지 확인하고, 다르면 실패한다.
임시 주소(trycloudflare.com 등)는 --draft 없이는 거부한다(인쇄 사고 방지).
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont
from qrcode.constants import ERROR_CORRECT_Q

ROOT = Path(__file__).resolve().parent.parent
INK, BLUE, GRID, HIGHLIGHT, MUTED, LAVENDER = "#1e1e1e", "#2a46b8", "#e4eaf1", "#ffe45e", "#59636b", "#ece5f8"
TEMP_HOSTS = ("trycloudflare.com", "localhost", "127.0.0.1", "ngrok", "loca.lt")


def qr_matrix(url):
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix(), qr.version  # border 포함 행렬


def qr_image(matrix, px):
    n = len(matrix)
    img = Image.new("L", (n, n), 255)
    img.putdata([0 if c else 255 for row in matrix for c in row])
    return img.resize((px, px), Image.NEAREST).convert("RGB")


def decode(path):
    data = np.fromfile(str(path), dtype=np.uint8)               # 한글 경로에서도 읽히게
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if not text:  # 큰 이미지는 줄여서 한 번 더
        small = cv2.resize(img, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
        text, _, _ = cv2.QRCodeDetector().detectAndDecode(small)
    return text


def font(path, size):
    return ImageFont.truetype(str(path), size)


def centered(draw, y, text, fnt, fill, width):
    w = draw.textlength(text, font=fnt)
    draw.text(((width - w) / 2, y), text, font=fnt, fill=fill)


def grid_paper(w, h, step):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=GRID, width=max(1, step // 18))
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=GRID, width=max(1, step // 18))
    return img


def scribble(draw, x0, x1, y, width):
    pts = [(x0 + (x1 - x0) * t / 40, y + 6 * np.sin(t / 40 * 6.0) * (1 if t % 2 else 0.7)) for t in range(41)]
    draw.line(pts, fill=BLUE, width=width, joint="curve")


def make_standalone(url, matrix, out, hand, body_bold, draft):
    host = url.split("://", 1)[-1].rstrip("/")
    # PNG: 흰 바탕, 위 'Lolypoly', 가운데 QR(여백 4칸 포함), 아래 주소
    W, qpx = 1200, 960
    H = 1440
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    centered(d, 50, "Lolypoly", font(hand, 150), BLUE, W)
    img.paste(qr_image(matrix, qpx), ((W - qpx) // 2, 250))
    size = 56
    while size > 24 and d.textlength(host, font=font(body_bold, size)) > W - 120:
        size -= 2
    centered(d, 250 + qpx + 30, host, font(body_bold, size), INK, W)
    if draft:
        centered(d, H - 70, "시험용 임시 주소 · 인쇄 금지", font(body_bold, 36), "#c2352a", W)
    img.save(out / "lolypoly-qr.png", dpi=(300, 300))

    # SVG: 벡터 QR + 같은 배치의 글자(글꼴은 보는 기기 기본 글꼴로 대체될 수 있음)
    n = len(matrix)
    cell = qpx / n
    rects = "".join(
        f'<rect x="{(W - qpx) / 2 + c * cell:.2f}" y="{250 + r * cell:.2f}" width="{cell + .3:.2f}" height="{cell + .3:.2f}"/>'
        for r in range(n) for c in range(n) if matrix[r][c])
    warn = (f'<text x="{W / 2}" y="{H - 40}" text-anchor="middle" font-size="36" font-weight="700" fill="#c2352a" '
            f'font-family="Malgun Gothic, Noto Sans KR, sans-serif">시험용 임시 주소 · 인쇄 금지</text>') if draft else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
           f'<title>Lolypoly QR — {url}</title><rect width="100%" height="100%" fill="#fff"/>'
           f'<text x="{W / 2}" y="185" text-anchor="middle" font-size="140" font-weight="700" fill="{BLUE}" '
           f'font-family="Gaegu, Lolypoly Hand, sans-serif">Lolypoly</text>'
           f'<g fill="#000">{rects}</g>'
           f'<text x="{W / 2}" y="{250 + qpx + 80}" text-anchor="middle" font-size="48" font-weight="700" fill="{INK}" '
           f'font-family="Malgun Gothic, Apple SD Gothic Neo, Noto Sans KR, sans-serif">{host}</text>{warn}</svg>')
    (out / "lolypoly-qr.svg").write_text(svg, encoding="utf-8")


def make_poster(url, matrix, out, hand, body, body_bold, icon, draft):
    host = url.split("://", 1)[-1].rstrip("/")
    W, H = 2480, 3508                          # A4 300dpi
    img = grid_paper(W, H, 72)
    d = ImageDraw.Draw(img)

    # 앱 아이콘 + 이름
    ic = Image.open(icon).convert("RGBA").resize((300, 300), Image.LANCZOS)
    img.paste(ic, ((W - 300) // 2, 230), ic)
    centered(d, 560, "Lolypoly", font(hand, 300), BLUE, W)
    t = font(body_bold, 112)
    line = "춘천캠퍼스 생활정보를 한곳에서"
    tw = d.textlength(line, font=t)
    scribble(d, (W - tw) / 2, (W + tw) / 2, 1080, 14)
    centered(d, 930, line, t, INK, W)
    # 형광펜 칩: 식단 · 학사일정 · 공지
    chip = font(body_bold, 96)
    label = "식단 · 학사일정 · 공지"
    cw = d.textlength(label, font=chip)
    x0 = (W - cw) / 2
    d.rectangle([x0 - 30, 1210 + 60, x0 + cw + 30, 1210 + 125], fill=HIGHLIGHT)
    d.text((x0, 1200), label, font=chip, fill=INK)

    # QR 카드 (점선 테두리 + 라벤더 바탕 느낌)
    qpx = 1240
    cx, cy = (W - qpx) // 2, 1480
    d.rounded_rectangle([cx - 90, cy - 90, cx + qpx + 90, cy + qpx + 230], radius=60, fill="white", outline=INK, width=8)
    img.paste(qr_image(matrix, qpx), (cx, cy))
    size = 96                                   # 주소가 카드(QR+좌우 여백) 안에 들어갈 때까지 줄인다
    while size > 36 and d.textlength(host, font=font(body_bold, size)) > qpx + 120:
        size -= 4
    centered(d, cy + qpx + 70, host, font(body_bold, size), INK, W)

    # 안내 문구
    centered(d, 3000, "QR코드를 스캔하고 홈 화면에 추가해 보세요.", font(body_bold, 92), INK, W)
    centered(d, 3140, "로그인 없이 바로 써요 · 학생이 만든 비공식 앱이에요", font(body, 62), MUTED, W)
    centered(d, 3240, "정확한 내용은 학교 공식 홈페이지 원문을 기준으로 해 주세요", font(body, 54), MUTED, W)
    if draft:
        d.rectangle([0, 0, W, 150], fill="#c2352a")
        centered(d, 30, "시험용 임시 주소 · 인쇄·배포 금지", font(body_bold, 80), "white", W)
    img.save(out / "lolypoly-poster.png", dpi=(300, 300), optimize=True)
    img.save(out / "lolypoly-poster.pdf", "PDF", resolution=300)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--out", default=str(ROOT / "docs" / "distribution"))
    p.add_argument("--draft", action="store_true", help="시험본: '인쇄 금지' 표시, 임시 주소 허용")
    p.add_argument("--hand-font", default=str(Path("D:/lolypoly/tools/gaegu-src/Gaegu-Bold.ttf")))
    p.add_argument("--body-font", default="C:/Windows/Fonts/malgun.ttf")
    p.add_argument("--body-bold", default="C:/Windows/Fonts/malgunbd.ttf")
    a = p.parse_args()

    url = a.url if a.url.endswith("/") else a.url + "/"
    if not url.startswith("https://"):
        sys.exit("https:// 주소만 쓸 수 있어요.")
    if any(h in url for h in TEMP_HOSTS) and not a.draft:
        sys.exit(f"임시 주소예요: {url}\n배포용 QR은 고정 주소로만 만들어요. 시험본이면 --draft 를 붙이세요.")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    matrix, version = qr_matrix(url)
    icon = ROOT / "static" / "icons" / "icon-512.png"
    make_standalone(url, matrix, out, a.hand_font, a.body_bold, a.draft)
    make_poster(url, matrix, out, a.hand_font, a.body_font, a.body_bold, icon, a.draft)

    ok = True
    for name in ("lolypoly-qr.png", "lolypoly-poster.png"):
        got = decode(out / name)
        print(f"{name}: QR 버전 {version} | 디코딩 = {got!r}")
        ok &= got == url
    if not ok:
        sys.exit(f"실패: QR 주소가 {url} 와 다릅니다.")
    print("검증 통과: 두 파일 모두 같은 주소입니다 →", out)


if __name__ == "__main__":
    main()
