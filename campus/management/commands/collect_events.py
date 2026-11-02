from django.core.management.base import BaseCommand, CommandError

from campus.collectors.events import collect_events


class Command(BaseCommand):
    help = "공식 홈페이지에서 학사일정(연도별 '전체' 보기)을 수집해 DB에 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, action="append", dest="years",
                            help="수집할 연도 (여러 번 지정 가능). 기본: 올해와 내년 (1~2월엔 작년 포함)")

    def handle(self, *args, years, **options):
        run = collect_events(years=years)
        if run.status != run.Status.SUCCESS:
            raise CommandError(f"학사일정 수집 실패: {run.message}")
        self.stdout.write(self.style.SUCCESS(f"학사일정 수집 성공: {run.message}"))
