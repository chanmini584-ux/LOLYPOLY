"""공개 수집 결과(식단·식사시간표·학사일정·공지)를 공통 RAG 엔진 적재용 JSON 으로 내보낸다 (D-073).

    python manage.py export_rag --out /경로/lolypoly-rag-export.json

- 허용 필드만 내보낸다. 계정·커뮤니티·택시방·의견·사진·버스는 내보내지 않는다.
- 각 행의 collected_at(실제 수집 시각)을 그대로 쓴다. 날짜를 오늘로 바꾸지 않는다.
- 수집 종류별 마지막 실행 결과(success/failed)와 마지막 성공 시각을 함께 적는다. 엔진은 failed 인 종류의 삭제를 반영하지 않아
  마지막 성공 데이터가 유지된다(DB 도 실패한 수집으로 기존 행을 바꾸지 않는다).
- 파일은 임시 파일에 쓴 뒤 바꿔 넣는다(엔진이 반쯤 쓴 파일을 읽지 않게).
엔진 쪽 적재: RAG_LOLYPOLY_EXPORT=<이 파일> python -m ragcore.cli ingest --project lolypoly
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from campus.models import AcademicEvent, CollectionRun, Meal, MealHours, Notice

PUBLIC_FIELDS = {
    "meals": ["date", "meal_type", "items", "source_url", "collected_at"],
    "events": ["title", "course", "start_date", "end_date", "source_year", "source_url", "collected_at"],
    "notices": ["post_id", "title", "category", "author", "posted_on", "is_pinned", "source_url", "collected_at"],
    "meal_hours": ["caption", "headers", "rows", "source_url", "collected_at"],   # ERR-015
}
MODELS = {"meals": Meal, "events": AcademicEvent, "notices": Notice, "meal_hours": MealHours}
RUN_SOURCE = {"meal_hours": "meals"}   # 식사시간표는 식단 수집과 같은 실행에서 모은다
EXCLUDED = ["accounts", "community", "taxi", "feedback", "bus", "photos"]


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(settings.BASE_DIR), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "VERSION-" + (Path(settings.BASE_DIR) / "VERSION").read_text(encoding="utf-8").strip()


def collection_status(source: str) -> dict:
    runs = CollectionRun.objects.filter(source=source).exclude(status=CollectionRun.Status.RUNNING)
    last = runs.first()
    ok = runs.filter(status=CollectionRun.Status.SUCCESS).first()
    return {
        "last_run_status": last.status if last else "never",
        "last_run_at": _iso(last.finished_at) if last else None,
        "last_success_at": _iso(ok.finished_at) if ok else None,
    }


def build_export(source_label: str = "lolypoly-db") -> dict:
    out = {
        "provenance": {
            "kind": "repository_data",
            "source": source_label,
            "format": 2,
            "description": "LOLYPOLY 수집 DB의 공개 필드(식단·식사시간표·학사일정·공지). 각 행의 collected_at 은 실제 수집 시각",
            "lolypoly_commit": _commit(),
            "exported_at": _iso(timezone.now()),
            "schema": PUBLIC_FIELDS,
            "excluded": EXCLUDED,
            "collections": {k: collection_status(RUN_SOURCE.get(k, k)) for k in MODELS},
        }
    }
    for key, model in MODELS.items():
        out[key] = [{f: _iso(getattr(obj, f)) for f in PUBLIC_FIELDS[key]} for obj in model.objects.all()]
    return out


def write_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rag-export-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class Command(BaseCommand):
    help = "공개 수집 결과(식단·식사시간표·학사일정·공지)를 RAG 엔진 적재용 JSON 으로 내보냅니다."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="내보낼 JSON 파일 경로")
        parser.add_argument("--source-label", default="lolypoly-db", help="provenance.source 값(재현 도구는 fixture)")

    def handle(self, *args, out, source_label, **options):
        data = build_export(source_label)
        write_atomic(Path(out), data)
        counts = {k: len(data[k]) for k in MODELS}
        status = {k: v["last_run_status"] for k, v in data["provenance"]["collections"].items()}
        self.stdout.write(self.style.SUCCESS(f"[내보냄] {out} {counts} 수집 상태 {status}"))
