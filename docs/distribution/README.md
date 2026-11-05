# 학생 배포물 (QR · 안내 이미지)

**상태: 최종본 생성 (2026-11-05) — `https://lolypoly.lolypoly.workers.dev/`** (D-051). 디코딩 검증 통과, **인쇄본 실기기 스캔은 아직**. (아래 두 문단은 생성 전 기록)

지금 외부 주소는 Cloudflare Quick Tunnel 임시 주소(`*.trycloudflare.com`)라서 터널을 다시 열 때마다 바뀐다.
이 주소로 QR을 인쇄하면 나중에 전부 무효가 되므로 배포용 QR은 만들지 않았다. 생성 스크립트는 임시 주소를 거부한다.

## 2장 안내지
`lolypoly-flyer-1.png`, `lolypoly-flyer-2.png`, `lolypoly-flyer.pdf` — `scripts/make_flyer.py <주소>` 로 생성(QR 디코딩 검증 포함)

## 도메인이 정해지면 (한 줄)
```powershell
cd D:\lolypoly\app
D:\lolypoly\tools\.venv\Scripts\python.exe scripts\make_distribution.py https://<확정 도메인>/
```
결과(이 폴더):

| 파일 | 용도 |
|---|---|
| `lolypoly-qr.png` / `lolypoly-qr.svg` | 단독 QR — 위 `Lolypoly`, 아래 주소. 교수님·학생 전달용 |
| `lolypoly-poster.png` (A4 300dpi) / `lolypoly-poster.pdf` | 학생 배포 안내 — 앱 아이콘, `춘천캠퍼스 생활정보를 한곳에서`, `식단 · 학사일정 · 공지`, QR, 설치 안내 문구 |

스크립트가 만든 PNG를 OpenCV로 다시 읽어 주소가 같은지 검사하고 다르면 실패한다(오류 정정 Q, 여백 4칸, 흑백).
**인쇄 전**: 실제 휴대폰(iPhone 카메라, Android 카메라)으로 인쇄물을 찍어 같은 주소가 열리는지 확인한다.

## 주소가 바뀌어도 QR이 무효가 되지 않게
- QR에는 **최종 도메인의 루트(`https://<도메인>/`)만** 넣는다. 경로·쿼리를 넣지 않는다.
- 도메인을 바꿔야 하면 옛 도메인을 1년 이상 유지하고 새 주소로 301 이동시킨다.

## 시험본
`--draft --out <다른 폴더>` 를 붙이면 임시 주소로도 만들 수 있고, 이미지에 **"시험용 임시 주소 · 인쇄 금지"** 띠가 들어간다. 시험본은 이 폴더에 두지 않는다.
