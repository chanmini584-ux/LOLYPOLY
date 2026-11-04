"""배부용 QR 생성 + 디코딩 검증. 앱 의존성이 아니라 개발 도구다 (qrcode 8.2, pillow, opencv-python-headless).

  python scripts/make_qr.py [주소]    기본 https://lolypoly.com  →  docs/handout/lolypoly-qr.{svg,png}
생성 후 PNG 를 실제로 읽어 주소가 같은지 확인한다. 다르면 실패한다.
여백(quiet zone)은 4칸, 오류 정정 M 이상, 검정/흰색 고대비.
"""
import sys
from pathlib import Path

import cv2
import qrcode
import qrcode.image.svg
from qrcode.constants import ERROR_CORRECT_Q

url = sys.argv[1] if len(sys.argv) > 1 else "https://lolypoly.com"
out = Path(__file__).resolve().parent.parent / "docs" / "handout"
out.mkdir(parents=True, exist_ok=True)

qr = qrcode.QRCode(error_correction=ERROR_CORRECT_Q, box_size=20, border=4)
qr.add_data(url)
qr.make(fit=True)
qr.make_image(fill_color="black", back_color="white").save(out / "lolypoly-qr.png")
qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, error_correction=ERROR_CORRECT_Q, border=4).save(out / "lolypoly-qr.svg")

decoded, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.imread(str(out / "lolypoly-qr.png")))
print("QR 버전", qr.version, "| 디코딩 결과:", decoded)
if decoded != url:
    raise SystemExit(f"실패: 기대 {url} / 실제 {decoded!r}")
print("검증 통과: QR 주소가 일치합니다.")
