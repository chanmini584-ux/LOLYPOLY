from django.core.management.base import BaseCommand, CommandError

from campus.collectors.bus import collect_bus
from campus.collectors.events import collect_events
from campus.collectors.meals import collect_meals
from campus.collectors.notices import collect_notices

JOBS = {
    "meals": ("식단", collect_meals),
    "events": ("학사일정", collect_events),
    "notices": ("공지", collect_notices),
    "bus": ("버스 노선", collect_bus),
}


class Command(BaseCommand):
    help = "식단·학사일정·공지·버스 노선을 차례로 수집합니다. 하나가 실패해도 나머지는 계속 실행합니다."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=list(JOBS), action="append",
                            help="일부만 실행 (여러 번 지정 가능). 예: --only meals --only notices")

    def handle(self, *args, only, **options):
        failed = []
        for key in only or list(JOBS):
            label, job = JOBS[key]
            run = job()
            if run.status == run.Status.SUCCESS:
                self.stdout.write(self.style.SUCCESS(f"[성공] {label}: {run.message}"))
            else:
                failed.append(label)
                self.stderr.write(self.style.ERROR(f"[실패] {label}: {run.message}"))
        if failed:
            # 0이 아닌 종료 코드 → 스케줄러 로그에서 실패 확인 가능
            raise CommandError(f"실패한 수집: {', '.join(failed)}")
