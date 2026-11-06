from django.core.management.base import BaseCommand, CommandError

from campus.collectors.bus import collect_bus
from campus.models import BusRoute


class Command(BaseCommand):
    help = "TAGO(국토교통부)에서 학교 정류장을 지나는 버스 노선과 정류장 목록을 수집합니다. (TAGO_SERVICE_KEY 필요)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-empty", action="store_true",
            help="노선 데이터가 이미 있으면 건너뜀. 실패해도 오류 코드 없이 끝냄(서버 시작 시 사용).",
        )

    def handle(self, *args, if_empty, **options):
        if if_empty and BusRoute.objects.exists():
            self.stdout.write("버스 노선 데이터가 이미 있어 건너뜁니다.")
            return
        run = collect_bus()
        if run.status == run.Status.SUCCESS:
            self.stdout.write(self.style.SUCCESS(f"버스 노선 수집 성공: {run.message}"))
        elif if_empty:
            self.stderr.write(f"버스 노선 수집 실패(계속 진행): {run.message}")
        else:
            raise CommandError(f"버스 노선 수집 실패: {run.message}")
