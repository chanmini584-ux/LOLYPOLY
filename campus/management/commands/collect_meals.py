from django.core.management.base import BaseCommand, CommandError

from campus.collectors.meals import MAX_WEEKS, collect_meals


class Command(BaseCommand):
    help = "공식 홈페이지에서 식단을 수집해 DB에 저장합니다 (Playwright 필요)."

    def add_arguments(self, parser):
        parser.add_argument("--weeks", type=int, default=2, help=f"이번 주부터 몇 주를 수집할지 (1~{MAX_WEEKS}, 기본 2)")

    def handle(self, *args, weeks, **options):
        run = collect_meals(weeks=weeks)
        if run.status != run.Status.SUCCESS:
            # 0이 아닌 종료 코드 → 자동 실행 로그에서 실패를 알 수 있다
            raise CommandError(f"식단 수집 실패: {run.message}")
        self.stdout.write(self.style.SUCCESS(f"식단 수집 성공: {run.item_count}건 저장 — {run.message}"))
