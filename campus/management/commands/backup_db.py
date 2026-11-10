"""SQLite + 커뮤니티 사진 백업·검증 (실행 중에도 안전한 SQLite 백업 API 사용).

  python manage.py backup_db [--dir 경로] [--keep 7]      DB 백업 1개 + 사진 사본 갱신, 오래된 것 정리
  python manage.py backup_db --verify 백업파일            무결성·건수·사진 파일 확인(임시 위치에 풀어 확인, 원본은 건드리지 않음)
  python manage.py backup_db --no-media                   DB 만

DB: gzip 으로 줄이고 파일 권한은 소유자만 읽도록(0600) 한다. 최근 --keep 개를 남긴다.
사진(MEDIA_ROOT): 백업 폴더의 media/ 에 같은 경로로 복사해 둔다(이미 있는 파일은 건너뜀 = 바뀐 것만).
  원본에서 지워진 사진은 바로 없애지 않고 media-removed/<날짜>/ 로 옮겨 --keep 일 동안 둔다.
  → 최근 --keep 일의 어느 DB 백업으로 되돌려도 그 DB 가 가리키는 사진을 media/ 나 media-removed/ 에서 찾을 수 있다.
같은 디스크의 사본은 외부 백업이 아니다. 디스크가 고장 나면 함께 잃는다.
"""

import gzip
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFIX = "lolypoly-"
MEDIA_DIR = "media"
REMOVED_DIR = "media-removed"


class Command(BaseCommand):
    help = "SQLite DB 백업(기본) 또는 백업 파일 검증(--verify)"

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=None, help="백업 폴더 (기본: DB 파일 옆 backups/)")
        parser.add_argument("--keep", type=int, default=7, help="보관할 최근 백업 개수 (기본 7)")
        parser.add_argument("--verify", metavar="FILE", help="이 백업 파일을 풀어 무결성·건수·사진 파일을 확인")
        parser.add_argument("--no-media", action="store_true", help="사진 사본은 갱신하지 않음")

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
        if not opts["no_media"]:
            self.backup_media(out_dir, max(opts["keep"], 1))

    def backup_media(self, out_dir: Path, keep_days: int) -> None:
        source = Path(settings.MEDIA_ROOT)
        mirror, removed_root = out_dir / MEDIA_DIR, out_dir / REMOVED_DIR
        mirror.mkdir(parents=True, exist_ok=True)
        live = {p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file()} if source.exists() else set()
        copied = 0
        for rel in sorted(live):
            dst = mirror / rel
            if not dst.exists() or dst.stat().st_size != (source / rel).stat().st_size:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, dst)
                copied += 1
        # 원본에서 사라진 사진: 보관 폴더로 옮겨 keep_days 일 뒤에 지운다
        today = datetime.now().strftime("%Y%m%d")
        moved = 0
        for path in [p for p in mirror.rglob("*") if p.is_file()]:
            rel = path.relative_to(mirror).as_posix()
            if rel not in live:
                dst = removed_root / today / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), dst)
                moved += 1
        purged = 0
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y%m%d")
        if removed_root.exists():
            for day_dir in sorted(p for p in removed_root.iterdir() if p.is_dir()):
                if day_dir.name < cutoff:
                    purged += sum(1 for p in day_dir.rglob("*") if p.is_file())
                    shutil.rmtree(day_dir)
        self.stdout.write(self.style.SUCCESS(
            f"사진 사본: 전체 {len(live)}개, 새로 복사 {copied}개, 지워진 사진 보관으로 이동 {moved}개, 보관 기간 지난 것 삭제 {purged}개 ({mirror})"))

    def _check(self, path: Path) -> dict:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CommandError("무결성 검사 실패")
            counts = {}
            for t in ("campus_meal", "campus_academicevent", "campus_notice", "campus_feedback",
                      "accounts_user", "community_post", "community_comment", "community_attachment"):
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
            missing, total = self._missing_photos(restored, backup.parent)
        self.stdout.write(self.style.SUCCESS(f"검증 통과(임시 위치에 풀어 확인): {counts}"))
        if total is None:
            self.stdout.write("사진: 이 백업에는 커뮤니티 사진 표가 없어요(커뮤니티 도입 전 백업).")
        elif missing:
            raise CommandError(f"사진 사본에 없는 파일 {len(missing)}/{total}개: {missing[:5]} — 사진 백업을 먼저 확인하세요")
        else:
            self.stdout.write(self.style.SUCCESS(f"사진 검증 통과: 이 DB 가 가리키는 사진 파일 {total}개가 사본(media·media-removed)에 모두 있음"))

    def _missing_photos(self, db_path: Path, backup_dir: Path):
        """백업 DB 가 가리키는 사진 파일이 사본 폴더에 있는지. (없는 파일 목록, 전체 수) — 표가 없으면 (.., None)."""
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute("SELECT path, thumb_path FROM community_attachment").fetchall()
        except sqlite3.OperationalError:
            return [], None
        finally:
            con.close()
        removed = [d for d in (backup_dir / REMOVED_DIR).iterdir() if d.is_dir()] if (backup_dir / REMOVED_DIR).exists() else []
        missing = []
        paths = [p for row in rows for p in row]
        for rel in paths:
            if not (backup_dir / MEDIA_DIR / rel).is_file() and not any((d / rel).is_file() for d in removed):
                missing.append(rel)
        return missing, len(paths)
