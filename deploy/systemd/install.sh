#!/usr/bin/env bash
# Lolypoly 자동 수집 타이머 설치 (Ubuntu, systemd)
#
# 사용법:  sudo ./deploy/systemd/install.sh <앱 경로> <실행 사용자>
#   예)    sudo ./deploy/systemd/install.sh /home/jusang/Lolypoly jusang
#
# 하는 일: 이 폴더의 서비스/타이머 파일에서 __APP_DIR__, __APP_USER__ 를 바꿔
#          /etc/systemd/system/ 에 복사하고 3개 타이머를 켠다.
# 미리 필요한 것: <앱 경로>/.venv 에 requirements 설치, .env 작성, migrate,
#                 그 사용자로 'python -m playwright install --with-deps chromium' 실행
set -euo pipefail

APP_DIR="${1:?사용법: sudo $0 <앱 경로> <실행 사용자>}"
APP_USER="${2:?사용법: sudo $0 <앱 경로> <실행 사용자>}"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/etc/systemd/system

[ -x "$APP_DIR/.venv/bin/python" ] || { echo "오류: $APP_DIR/.venv/bin/python 이 없습니다." >&2; exit 1; }
[ -f "$APP_DIR/manage.py" ] || { echo "오류: $APP_DIR/manage.py 가 없습니다." >&2; exit 1; }
id "$APP_USER" >/dev/null 2>&1 || { echo "오류: 사용자 $APP_USER 가 없습니다." >&2; exit 1; }

for f in "$SRC"/lolypoly-collect@.service "$SRC"/lolypoly-collect-*.timer; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" "$f" > "$DEST/$(basename "$f")"
  echo "설치: $DEST/$(basename "$f")"
done

systemctl daemon-reload
for t in meals events notices; do
  systemctl enable --now "lolypoly-collect-$t.timer"
done
systemctl list-timers 'lolypoly-*' --no-pager
echo
echo "지금 한 번 실행해 보기:  sudo systemctl start lolypoly-collect@meals.service"
echo "결과 로그 보기:          journalctl -u 'lolypoly-collect@*' --since today --no-pager"
