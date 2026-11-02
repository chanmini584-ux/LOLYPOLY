from django.core.management.base import BaseCommand, CommandError

from campus.collectors.notices import MAX_PAGES, collect_notices


class Command(BaseCommand):
    help = "공식 홈페이지에서 공지사항 목록을 수집해 DB에 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--pages", type=int, default=2, help=f"앞에서부터 몇 쪽을 수집할지 (1~{MAX_PAGES}, 기본 2)")

    def handle(self, *args, pages, **options):
        run = collect_notices(pages=pages)
        if run.status != run.Status.SUCCESS:
            raise CommandError(f"공지 수집 실패: {run.message}")
        self.stdout.write(self.style.SUCCESS(f"공지 수집 성공: {run.message}"))
