"""SQLite 백업·검증 (실행 중에도 안전한 SQLite 백업 API 사용).

  python manage.py backup_db [--dir 경로] [--keep 7]      백업 1개 만들고 오래된 것 정리
  python manage.py backup_db --verify 백업파일            무결성·건수 확인(복원 시험용, 원본은 건드리지 않음)

백업은 gzip 으로 줄이고 파일 권한은 소유자만 읽도록(0600) 한다. 같은 디스크의 사본은 외부 백업이 아니다.
"""

import gzip
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFIX = "lolypoly-"


class Command(BaseCommand):
    help = "SQLite DB 백업(기본) 또는 백업 파일 검증(--verify)"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="백업 폴더 (기본: DB 파일 옆 backups/)")
        parser.add_argument("--keep", type=int, default=7, help="보관할 최근 백업 개수 (기본 7)")
        parser.add_argument("--verify", metavar="FILE", help="이 백업 파일을 풀어 무결성·건수를 확인")

    def handle(self, *args, **opts):
        if opts["verify"]:
            return self.verify(Path(opts["verify"]))
        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not db_path.exists():
            raise CommandError(f"DB 파일이 없습니다: {db_path}")
        out_dir = Path(opts["dir"]) if opts["dir"] else db_path.parent / "backups"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = out_dir / f"{PREFIX}{stamp}.sqlite3.gz"
        with tempfile.TemporaryDirectory(dir=out_dir) as tmp:
            snap = Path(tmp) / "snap.sqlite3"
            src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            dst = sqlite3.connect(snap)
            with dst:
                src.backup(dst)  # 쓰기 중에도 일관된 사본
            src.close()
            dst.close()
            self._check(snap)
            with open(snap, "rb") as f_in, gzip.open(target, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        target.chmod(0o600)
        old = sorted(out_dir.glob(f"{PREFIX}*.sqlite3.gz"))[: -max(opts["keep"], 1)]
        for p in old:
            p.unlink()
        self.stdout.write(self.style.SUCCESS(f"백업 완료: {target} ({target.stat().st_size} bytes), 정리한 오래된 백업 {len(old)}개"))

    def _check(self, path: Path) -> dict:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CommandError("무결성 검사 실패")
            counts = {}
            for t in ("campus_meal", "campus_academicevent", "campus_notice", "campus_feedback"):
                try:
                    counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]  # noqa: S608 (고정 이름)
                except sqlite3.OperationalError:
                    counts[t] = None
            return counts
        finally:
            con.close()

    def verify(self, backup: Path):
        if not backup.exists():
            raise CommandError(f"파일이 없습니다: {backup}")
        with tempfile.TemporaryDirectory() as tmp:
            restored = Path(tmp) / "restored.sqlite3"
            with gzip.open(backup, "rb") as f_in, open(restored, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            counts = self._check(restored)
        self.stdout.write(self.style.SUCCESS(f"검증 통과(임시 위치에 풀어 확인): {counts}"))
