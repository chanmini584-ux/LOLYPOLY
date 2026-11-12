"""커뮤니티 보관 기간 정리 (하루 한 번, 백업 작업과 함께 실행).

- 작성자가 지웠지만 처리 전 신고 때문에 남겨 둔 글·댓글 → COMMUNITY_REVIEW_RETENTION_DAYS 일이 지나면 내용·사진 삭제
- DB 에 기록이 없는 사진 파일(업로드 도중 서버가 꺼진 경우 등) → 하루 넘게 지난 것만 삭제
- 읽은 지 90일 넘은 알림, 끝난 로그인 세션 정리
- 닫힌 지 7일 지난 번개 택시방(대화 포함) 삭제. 처리 전 신고가 있으면 처리 후 7일까지 보관(D-070)
"""

import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from community import services, taxi
from community.models import Attachment, Notification


class Command(BaseCommand):
    help = "보관 기간이 지난 커뮤니티 내용·주인 없는 사진·오래된 알림·끝난 세션 정리"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="지우지 않고 대상 수만 출력(주인 없는 사진만 해당)")

    def handle(self, *args, **opts):
        posts = comments = rooms = 0
        if not opts["dry_run"]:
            posts, comments = services.purge_expired()
            rooms = taxi.purge_closed()
        root = Path(settings.MEDIA_ROOT)
        known = set()
        for main, thumb in Attachment.objects.values_list("path", "thumb_path"):
            known.update((main, thumb))
        orphans = []
        if (root / "community").exists():
            day_ago = time.time() - 86400
            for path in (root / "community").rglob("*.jpg"):
                if path.relative_to(root).as_posix() not in known and path.stat().st_mtime < day_ago:
                    orphans.append(path)
        if not opts["dry_run"]:
            for path in orphans:
                path.unlink(missing_ok=True)
            old = Notification.objects.filter(read_at__lt=timezone.now() - timedelta(days=90)).delete()[0]
            call_command("clearsessions")
        else:
            old = 0
        self.stdout.write(self.style.SUCCESS(
            f"정리{'(미리보기)' if opts['dry_run'] else ''}: 글 {posts}개, 댓글 {comments}개, 택시방 {rooms}개, 주인 없는 사진 {len(orphans)}개, 오래된 알림 {old}개"))
