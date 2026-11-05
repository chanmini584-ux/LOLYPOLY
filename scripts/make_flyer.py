"""학생 배포 안내지 2장(앞: 소개+QR, 뒤: 설치 방법+자주 묻는 질문) 만들기 + QR 디코딩 검증.

개발 도구(앱 의존성 아님). 준비: pip install qrcode==8.2 playwright==1.64.1 opencv-python-headless==4.12.0.88 pillow
  손글씨 글꼴 Gaegu-Bold.ttf(OFL) — --hand-font, Playwright Chromium — PLAYWRIGHT_BROWSERS_PATH
사용: python scripts/make_flyer.py https://<고정 주소>/
결과: docs/distribution/lolypoly-flyer-1.png, lolypoly-flyer-2.png (A4 약 300dpi), lolypoly-flyer.pdf
휴대폰 화면은 지금 실제 서비스 주소에서 찍어 넣는다(가짜 화면 아님).
"""
import argparse
import base64
import io
import sys
from pathlib import Path

import cv2
import numpy as np
import qrcode
import qrcode.image.svg
from playwright.sync_api import sync_playwright
from qrcode.constants import ERROR_CORRECT_Q

ROOT = Path(__file__).resolve().parent.parent
TEMP_HOSTS = ("trycloudflare.com", "localhost", "127.0.0.1")


def qr_svg(url):
    img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, error_correction=ERROR_CORRECT_Q, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode().split("?>", 1)[-1]


def b64(png_bytes):
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode()


def shots(browser, url):
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, locale="ko-KR",
                              user_agent="Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/141 Mobile Safari/537.36")
    page = ctx.new_page()
    out = {}
    for name, path in (("meals", "meals/"), ("schedule", "schedule/"), ("notices", "notices/")):
        page.goto(url + path, wait_until="networkidle")
        page.add_style_tag(content=".bottom-nav,#install-sheet,#cached-banner{display:none!important}")
        page.wait_for_timeout(300)
        out[name] = b64(page.screenshot(clip={"x": 0, "y": 0, "width": 390, "height": 760}))
    ctx.close()
    return out


CSS = """
@font-face { font-family: Hand; src: url('__HAND__') format('truetype'); }
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body { font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; color: #1e1e1e; }
.page { width: 794px; height: 1123px; position: relative; overflow: hidden; padding: 46px 52px 0;
  background-color: #fff; background-image: linear-gradient(#e4eaf1 1px, transparent 1px), linear-gradient(90deg, #e4eaf1 1px, transparent 1px);
  background-size: 18px 18px; page-break-after: always; }
.hand { font-family: Hand, sans-serif; font-weight: 700; letter-spacing: -0.03em; }
.brand { font-size: 22px; margin: 0; }
.stamp { position: absolute; top: 46px; right: 52px; border: 2.5px solid #c2352a; color: #c2352a; font-weight: 800; font-size: 15px;
  padding: 7px 12px; border-radius: 4px; transform: rotate(2deg); background: rgba(255,255,255,.9); }
h1 { margin: 14px 0 0; font-size: 64px; line-height: 1.12; }
.hl { background: linear-gradient(transparent 55%, #ffe45e 55%); padding: 0 4px; }
.lead { font-size: 17px; line-height: 1.6; margin: 18px 0 0; color: #333; }
.lead b { color: #1e1e1e; }
.tape { position: absolute; width: 74px; height: 22px; background: rgba(236,211,150,.85); top: -11px; left: 50%; transform: translateX(-50%) rotate(-2deg); }
.phones { position: relative; height: 400px; margin-top: 14px; }
.phone { position: absolute; top: 18px; width: 190px; height: 330px; border: 3px solid #1e1e1e; border-radius: 26px; background: #fff;
  box-shadow: 6px 8px 0 rgba(30,30,30,.12); }
.phone img { position: absolute; inset: 8px; width: calc(100% - 16px); height: calc(100% - 16px); object-fit: cover; object-position: top; border-radius: 18px; }
.p1 { left: 8px; transform: rotate(-4deg); } .p2 { left: 268px; top: 4px; } .p3 { left: 530px; transform: rotate(3deg); }
.pill { position: absolute; top: 358px; font-size: 20px; padding: 7px 18px; white-space: nowrap; border: 2.5px solid #1e1e1e; border-radius: 12px; }
.l1 { left: 44px; background: #ddf1e1; transform: rotate(-3deg); } .l2 { left: 284px; background: #ece5f8; } .l3 { left: 548px; background: #fce7cf; transform: rotate(2deg); }
.bottom { display: flex; gap: 36px; margin-top: 14px; align-items: flex-start; }
.qrcard { position: relative; flex: none; width: 236px; padding: 18px 18px 10px; background: #fbdfe3; border: 2px dashed #1e1e1e; transform: rotate(-1.5deg); text-align: center; }
.qrcard .qr { background: #fff; border: 2px solid #1e1e1e; padding: 10px; }
.qrcard .qr svg { width: 100%; height: auto; display: block; }
.qrcard .cap { font-size: 20px; margin: 8px 0 2px; }
.qrcard .url { font-size: 12.5px; color: #333; word-break: break-all; }
.steps h2 { font-size: 32px; margin: 4px 0 12px; }
.step { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 16px; }
.num { flex: none; width: 34px; height: 34px; border-radius: 50%; background: #2a46b8; color: #fff; display: flex; align-items: center; justify-content: center; font-weight: 800; }
.steps .step b { display: block; font-size: 19px; } .steps .step span { color: #59636b; font-size: 14.5px; }
.card .step span { color: #59636b; font-size: 13px; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
.chip { border: 2.5px solid #1e1e1e; border-radius: 999px; padding: 5px 14px; font-weight: 800; font-size: 14px; background: #ddf1e1; }
.foot { position: absolute; left: 52px; right: 52px; bottom: 26px; display: flex; justify-content: space-between; font-size: 12px; color: #59636b; }
/* 2쪽 */
.mini { position: absolute; top: 30px; right: 52px; width: 104px; padding: 8px 8px 4px; background: #fbdfe3; border: 2px dashed #1e1e1e; transform: rotate(3deg); text-align: center; }
.mini .qr { background: #fff; border: 1.5px solid #1e1e1e; padding: 4px; } .mini svg { width: 100%; height: auto; display: block; }
.mini div.cap { font-size: 13px; margin-top: 3px; }
h1.t2 { font-size: 44px; margin-top: 8px; }
.cards { display: flex; gap: 20px; margin-top: 22px; }
.card { position: relative; flex: 1; border: 2.5px solid #1e1e1e; border-radius: 14px; background: #fff; padding: 18px 16px 12px; box-shadow: 4px 5px 0 rgba(30,30,30,.1); }
.card h3 { font-size: 28px; margin: 2px 0 0; } .card .sub { color: #59636b; font-size: 13px; margin: 0 0 10px; }
.card .step { margin-bottom: 8px; gap: 10px; } .card .num { width: 26px; height: 26px; font-size: 13px; }
.card .step p { margin: 2px 0 0; font-size: 14px; line-height: 1.45; }
mark { background: #ffe45e; font-weight: 800; padding: 0 3px; }
.note { background: #ece5f8; border-radius: 10px; padding: 9px 12px; font-size: 12.5px; line-height: 1.5; margin-top: 6px; }
.callout { margin-top: 16px; background: #fce7cf; border: 2px dashed #1e1e1e; border-radius: 10px; padding: 10px 14px; font-size: 13.5px; line-height: 1.55; }
.faq h2 { font-size: 28px; margin: 14px 0 2px; }
.row { display: flex; gap: 18px; padding: 8px 0; border-bottom: 2px dashed #c3cdd7; font-size: 13.5px; line-height: 1.55; }
.row b { flex: 0 0 200px; font-size: 14px; }
.boxes { display: flex; gap: 16px; margin-top: 14px; }
.box { flex: 1; border: 2.5px solid #1e1e1e; border-radius: 14px; padding: 10px 14px; font-size: 13.5px; line-height: 1.55; }
.box h4 { font-size: 20px; margin: 0 0 6px; } .now { background: #ddf1e1; } .soon { border-style: dashed; background: #fff; }
"""


def page1(url, host, qr, s):
    return f"""<section class="page">
<p class="brand hand">Lolypoly</p>
<div class="stamp">학생이 만든 비공식 앱</div>
<h1 class="hand">오늘 학식 뭐지?<br><span class="hl">폰에서 한 번에</span></h1>
<p class="lead">한국폴리텍대학 춘천캠퍼스의 <b>식단 · 학사일정 · 공지</b>를<br>홈페이지 대신 <b>앱 아이콘 한 번</b>으로 보는 학생용 앱이에요.</p>
<div class="phones">
  <div class="phone p1"><i class="tape"></i><img src="{s['meals']}" alt=""></div>
  <div class="phone p2"><i class="tape"></i><img src="{s['schedule']}" alt=""></div>
  <div class="phone p3"><i class="tape"></i><img src="{s['notices']}" alt=""></div>
  <div class="pill l1 hand">오늘의 식단</div><div class="pill l2 hand">학사일정 · D-day</div><div class="pill l3 hand">공지 모아보기</div>
</div>
<div class="bottom">
  <div class="qrcard"><i class="tape"></i><div class="qr">{qr}</div><div class="cap hand">카메라로 찍어보세요</div><div class="url">{host}</div></div>
  <div class="steps">
    <h2 class="hand">3초 만에 내 폰에</h2>
    <div class="step"><div class="num">1</div><div><b>QR을 찍으면 바로 열려요</b><span>설치 파일·앱스토어 필요 없음</span></div></div>
    <div class="step"><div class="num">2</div><div><b>'설치하기' 또는 '홈 화면에 추가'</b><span>자세한 방법은 뒷장에</span></div></div>
    <div class="step"><div class="num">3</div><div><b>홈 화면 아이콘으로 열기</b><span>연결이 끊겨도 마지막으로 본 화면은 보여요</span></div></div>
    <div class="chips"><span class="chip">무료</span><span class="chip">회원가입 없음</span><span class="chip">개인정보 입력 없음</span></div>
  </div>
</div>
<div class="foot"><span>정보 출처: 한국폴리텍대학 춘천캠퍼스 홈페이지(공개 정보) · 학교 공식 앱이 아닙니다</span><span>1 / 2</span></div>
</section>"""


def page2(qr):
    return f"""<section class="page">
<p class="brand hand">Lolypoly</p>
<div class="mini"><div class="qr">{qr}</div><div class="cap hand">찍어보기</div></div>
<h1 class="hand t2">홈 화면에 <span class="hl">앱처럼</span> 설치하기</h1>
<div class="cards">
  <div class="card"><i class="tape"></i><h3 class="hand">iPhone</h3><p class="sub">Safari로 열어 주세요</p>
    <div class="step"><div class="num">1</div><p>QR을 찍어 <mark>Safari</mark>에서 열기</p></div>
    <div class="step"><div class="num">2</div><p>주소창 옆 <mark>⋯</mark> 버튼 누르기<br><span>(iOS 18 이하는 아래쪽 <b>공유</b> 버튼)</span></p></div>
    <div class="step"><div class="num">3</div><p><mark>공유</mark> → <mark>홈 화면에 추가</mark> 누르기<br><span>(안 보이면 아래로 내리거나 '더 보기')</span></p></div>
    <div class="step"><div class="num">4</div><p><b>웹 앱으로 열기</b> 켜고 <mark>추가</mark> → 홈 화면에 Lolypoly 아이콘</p></div>
    <div class="note">카카오톡 같은 앱 안에서 열렸다면 오른쪽 위 ⋯ → <b>Safari로 열기</b>를 눌러 주세요.</div>
  </div>
  <div class="card"><i class="tape"></i><h3 class="hand">Android</h3><p class="sub">Chrome으로 열어 주세요</p>
    <div class="step"><div class="num">1</div><p>QR을 찍어 <mark>Chrome</mark>에서 열기</p></div>
    <div class="step"><div class="num">2</div><p>화면 아래 뜨는 <mark>설치하기</mark> 버튼 누르기</p></div>
    <div class="step"><div class="num">3</div><p>버튼이 안 보이면 오른쪽 위 <mark>⋮ 메뉴</mark> → <mark>앱 설치</mark><br><span>(또는 홈 화면에 추가)</span></p></div>
    <div class="step"><div class="num">4</div><p><mark>설치</mark> 누르면 홈 화면·앱 서랍에 Lolypoly 아이콘</p></div>
    <div class="note">설치하지 않아도 QR로 열어 그냥 써도 돼요. 앱 안 <b>MY → 앱 설치 방법 보기</b>에서도 다시 볼 수 있어요.</div>
  </div>
</div>
<div class="callout"><b>인터넷이 약해도 괜찮아요.</b> 한 번 본 화면은 폰에 저장돼서, 연결이 끊기면 마지막으로 본 식단·공지를 보여 줘요. 이때는 "○분 전에 저장된 화면"이라고 함께 알려 줘요.</div>
<div class="faq"><h2 class="hand">자주 묻는 질문</h2>
  <div class="row"><b>학교 공식 앱인가요?</b><span>아니요. 학생이 만든 비공식 앱이에요. 학교 홈페이지에 공개된 식단·일정·공지를 모아서 보여 주고, 정확한 내용은 공식 홈페이지 원문이 기준이에요.</span></div>
  <div class="row"><b>돈이 드나요? 가입해야 하나요?</b><span>무료이고 가입이 필요 없어요. 이름·학번 같은 개인정보를 입력받지 않고, 방문 통계 도구도 쓰지 않아요.</span></div>
  <div class="row"><b>식단·공지는 얼마나 최신인가요?</b><span>학교 홈페이지에서 매일 자동으로 가져와요(공지는 하루 3번). 가져온 시각이 화면 아래에 표시돼요. 급한 일정은 공식 홈페이지도 함께 확인해 주세요.</span></div>
</div>
<div class="boxes">
  <div class="box now"><h4 class="hand">지금 쓸 수 있어요</h4>오늘 식단(조·중·석) · 학사일정과 D-day · 공지 분류·원문 링크 · 의견 보내기</div>
  <div class="box soon"><h4 class="hand">만드는 중이에요</h4>개인 시간표 저장 · 로그인 · 공모전·팀원 모집 커뮤니티</div>
</div>
<div class="foot"><span>의견이나 고장 제보는 앱의 MY → 의견 보내기로 알려 주세요 — 더 좋게 고칠게요</span><span>2 / 2</span></div>
</section>"""


def decode(path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = cv2.QRCodeDetector()
    for f in (1.0, 0.5, 0.3):
        im = img if f == 1.0 else cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        text, _, _ = det.detectAndDecode(im)
        if text:
            return text
    return ""


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--out", default=str(ROOT / "docs" / "distribution"))
    p.add_argument("--hand-font", default="D:/lolypoly/tools/gaegu-src/Gaegu-Bold.ttf")
    a = p.parse_args()
    url = a.url if a.url.endswith("/") else a.url + "/"
    if not url.startswith("https://") or any(h in url for h in TEMP_HOSTS):
        sys.exit("고정 https 주소만 쓸 수 있어요.")
    host = url.split("://", 1)[1].rstrip("/")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    qr = qr_svg(url)
    hand = Path(a.hand_font).resolve().as_uri()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        s = shots(browser, url)
        html = (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>{CSS.replace('__HAND__', hand)}</style></head>"
                f"<body>{page1(url, host, qr, s)}{page2(qr)}</body></html>")
        tmp = out / "_flyer.html"
        tmp.write_text(html, encoding="utf-8")
        page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=3.125)
        page.goto(tmp.resolve().as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        for i, el in enumerate(page.query_selector_all("section.page"), 1):
            el.screenshot(path=str(out / f"lolypoly-flyer-{i}.png"))
        page.pdf(path=str(out / "lolypoly-flyer.pdf"), format="A4", print_background=True, prefer_css_page_size=True)
        browser.close()
        tmp.unlink()
    ok = True
    for i in (1, 2):
        got = decode(out / f"lolypoly-flyer-{i}.png")
        print(f"lolypoly-flyer-{i}.png 디코딩 = {got!r}")
        ok &= got == url
    if not ok:
        sys.exit("실패: QR 주소 불일치")
    print("검증 통과 →", out)


if __name__ == "__main__":
    main()
