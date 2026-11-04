#!/usr/bin/env bash
# Lolypoly 운영 서비스 설치 (Ubuntu, systemd): 웹앱 + 자동 수집 타이머 3개 + 백업 타이머
#
# 사용법:  sudo ./deploy/systemd/install.sh <앱 경로> <실행 사용자> [데이터 폴더]
#   예)    sudo ./deploy/systemd/install.sh /srv/lolypoly lolypoly /var/lib/lolypoly
#
# 하는 일: 이 폴더의 파일에서 __APP_DIR__ __APP_USER__ __DATA_DIR__ 를 바꿔 /etc/systemd/system/ 에 복사하고
#          웹앱·수집·백업을 켠다. 데이터 폴더(DB·백업·락)를 만들고 실행 사용자 소유로 둔다.
# 미리 필요한 것: <앱 경로>/.venv 에 requirements 설치, .env 작성(DJANGO_SQLITE_PATH=<데이터 폴더>/db.sqlite3 포함),
#                 migrate, collectstatic, 그 사용자로 'python -m playwright install --with-deps chromium'
# 기존 DB 는 건드리지 않는다. 같은 이름 서비스가 있으면 파일만 교체하고 데이터는 유지한다.
set -euo pipefail

APP_DIR="${1:?사용법: sudo $0 <앱 경로> <실행 사용자> [데이터 폴더]}"
APP_USER="${2:?사용법: sudo $0 <앱 경로> <실행 사용자> [데이터 폴더]}"
DATA_DIR="${3:-/var/lib/lolypoly}"
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST=/etc/systemd/system

[ "$(id -u)" -eq 0 ] || { echo "오류: sudo 로 실행하세요." >&2; exit 1; }
[ -x "$APP_DIR/.venv/bin/python" ] || { echo "오류: $APP_DIR/.venv/bin/python 이 없습니다." >&2; exit 1; }
[ -x "$APP_DIR/.venv/bin/gunicorn" ] || { echo "오류: gunicorn 이 없습니다 (requirements 설치 확인)." >&2; exit 1; }
[ -f "$APP_DIR/manage.py" ] || { echo "오류: $APP_DIR/manage.py 가 없습니다." >&2; exit 1; }
[ -f "$APP_DIR/.env" ] || { echo "오류: $APP_DIR/.env 가 없습니다 (docs/OPERATIONS.md 참고)." >&2; exit 1; }
id "$APP_USER" >/dev/null 2>&1 || { echo "오류: 사용자 $APP_USER 가 없습니다." >&2; exit 1; }
command -v flock >/dev/null || { echo "오류: flock 이 없습니다 (util-linux)." >&2; exit 1; }

install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR" "$DATA_DIR/backups"

for f in "$SRC"/lolypoly-collect@.service "$SRC"/lolypoly-collect-*.timer \
         "$SRC"/lolypoly-web.service "$SRC"/lolypoly-backup.service "$SRC"/lolypoly-backup.timer; do
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__APP_USER__|$APP_USER|g" -e "s|__DATA_DIR__|$DATA_DIR|g" \
      "$f" > "$DEST/$(basename "$f")"
  echo "설치: $DEST/$(basename "$f")"
done

systemctl daemon-reload
systemctl enable --now lolypoly-web.service
for t in meals events notices; do
  systemctl enable --now "lolypoly-collect-$t.timer"
done
systemctl enable --now lolypoly-backup.timer
systemctl list-timers 'lolypoly-*' --no-pager
echo
echo "웹앱 상태:               systemctl status lolypoly-web --no-pager"
echo "지금 한 번 수집해 보기:  sudo systemctl start lolypoly-collect@meals.service"
echo "수집 결과 로그:          journalctl -u 'lolypoly-collect@*' --since today --no-pager"
echo "지금 백업해 보기:        sudo systemctl start lolypoly-backup.service"
