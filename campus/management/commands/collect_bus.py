import time

from django.core.management.base import BaseCommand, CommandError

from campus import tago
from campus.collectors.bus import collect_bus
from campus.models import BusRoute

RETRY_WAIT_SEC = 5


class Command(BaseCommand):
    help = "TAGO(국토교통부)에서 학교 정류장을 지나는 버스 노선과 정류장 목록을 수집합니다. (TAGO_SERVICE_KEY 필요)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--if-empty", action="store_true",
            help="노선 데이터가 이미 있으면 건너뜀. 실패해도 오류 코드 없이 끝냄(서버 시작 시 사용).",
        )
        parser.add_argument(
            "--attempts", type=int, default=3,
            help="실패하면 5초 뒤 다시 시도하는 최대 횟수(기본 3). TAGO 는 연결이 가끔 끊겨 한 번만 시도하면 노선이 빈 채로 남는다(ERR-016).",
        )

    def handle(self, *args, if_empty, attempts, **options):
        if if_empty and BusRoute.objects.exists():
            self.stdout.write("버스 노선 데이터가 이미 있어 건너뜁니다.")
            return
        # 키가 없으면 다시 해도 같은 결과라 한 번만 시도한다
        attempts = max(1, attempts) if tago.has_key() else 1
        for n in range(1, attempts + 1):
            run = collect_bus()
            if run.status == run.Status.SUCCESS or n == attempts:
                break
            self.stderr.write(f"버스 노선 수집 {n}/{attempts}번째 실패: {run.message} — {RETRY_WAIT_SEC}초 뒤 다시 시도")
            time.sleep(RETRY_WAIT_SEC)
        if run.status == run.Status.SUCCESS:
            self.stdout.write(self.style.SUCCESS(f"버스 노선 수집 성공: {run.message}"))
        elif if_empty:
            self.stderr.write(f"버스 노선 수집 실패(계속 진행): {run.message}")
        else:
            raise CommandError(f"버스 노선 수집 실패: {run.message}")
