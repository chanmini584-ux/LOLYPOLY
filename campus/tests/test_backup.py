import gzip
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, TransactionTestCase, override_settings



class BackupTests(TransactionTestCase):
    def test_backup_verify_and_rotation(self):
        # 테스트는 파일 DB 가 필요하므로 임시 SQLite 로 교체한 설정에서 확인한다.
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "t.sqlite3"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE campus_feedback (id integer)")
            con.execute("INSERT INTO campus_feedback VALUES (1)")
            con.commit(); con.close()
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(db)}}):
                out = Path(tmp) / "b"
                for _ in range(3):
                    call_command("backup_db", dir=str(out), keep=2, no_media=True)
                    import time; time.sleep(1.1)
                files = sorted(out.glob("*.gz"))
                self.assertEqual(len(files), 2)  # 오래된 것 정리
                self.assertEqual(oct(files[-1].stat().st_mode)[-3:], "600")
                call_command("backup_db", verify=str(files[-1]))
                self.assertTrue(gzip.open(files[-1]).read(16).startswith(b"SQLite format 3"))


class MediaBackupTests(TransactionTestCase):
    """DB 백업과 사진 사본으로 임시 위치에 복구할 수 있는지(운영 원본은 건드리지 않는다)."""
    # TransactionTestCase 는 일반 TestCase 가 모두 끝난 뒤 실행되므로, 여기서 DB 를 비워도 다른 테스트에 영향이 없다.

    def test_backup_mirrors_photos_keeps_removed_ones_and_verify_checks_them(self):
        import os
        import time

        from accounts.models import Department
        from community.models import Attachment, Board, Post
        from community.tests.helpers import make_user

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            db, media, out = tmp / "db.sqlite3", tmp / "media", tmp / "backups"
            (media / "community/2026/11").mkdir(parents=True)
            for name in ("a.jpg", "a_t.jpg", "b.jpg", "b_t.jpg"):
                (media / "community/2026/11" / name).write_bytes(b"\xff\xd8 photo " + name.encode())
            with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(db)}},
                                   MEDIA_ROOT=str(media)):
                # 실제 스키마를 가진 파일 DB 를 만들기 위해 테스트 DB 를 그대로 백업한 뒤 필요한 행을 넣는다
                import sqlite3

                from django.db import connection
                dept = Department.objects.create(name="백업테스트과")
                user = make_user("backup_user", dept)
                post = Post.objects.create(board=Board.objects.get(department=dept), author=user, title="t", body="b")
                for stem in ("a", "b"):
                    Attachment.objects.create(post=post, path=f"community/2026/11/{stem}.jpg",
                                              thumb_path=f"community/2026/11/{stem}_t.jpg", width=1, height=1, size=1)
                dst = sqlite3.connect(db)
                connection.connection.backup(dst)
                dst.close()

                call_command("backup_db", "--dir", str(out), "--keep", "7")
                self.assertTrue((out / "media/community/2026/11/a.jpg").is_file())
                first = sorted(out.glob("lolypoly-*.sqlite3.gz"))[-1]
                call_command("backup_db", "--verify", str(first))            # DB 4개 파일 모두 사본에 있음

                # 사진 하나가 지워진 뒤의 백업: 사본에서는 보관 폴더로 옮겨지고, 예전 DB 백업 검증은 여전히 통과
                (media / "community/2026/11/b.jpg").unlink()
                (media / "community/2026/11/b_t.jpg").unlink()
                time.sleep(1.1)
                call_command("backup_db", "--dir", str(out), "--keep", "7")
                self.assertFalse((out / "media/community/2026/11/b.jpg").exists())
                self.assertEqual(len(list((out / "media-removed").rglob("b.jpg"))), 1)
                call_command("backup_db", "--verify", str(first))

                # 보관 기간이 지난 것은 지워지고, 그러면 예전 백업 검증은 '사진 없음'으로 실패해야 한다
                old_dir = next((out / "media-removed").iterdir())
                old_dir.rename(old_dir.with_name("20200101"))
                time.sleep(1.1)
                call_command("backup_db", "--dir", str(out), "--keep", "7")
                self.assertFalse((out / "media-removed/20200101").exists())
                from django.core.management.base import CommandError
                with self.assertRaises(CommandError):
                    call_command("backup_db", "--verify", str(first))
                self.assertTrue(os.path.exists(media / "community/2026/11/a.jpg"))   # 원본은 그대로

class PurgeCommandTests(TestCase):
    def test_purge_command_removes_only_old_orphan_files(self):
        import os
        import time

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "community/2026/11"
            folder.mkdir(parents=True)
            old, fresh = folder / "old.jpg", folder / "fresh.jpg"
            old.write_bytes(b"x")
            fresh.write_bytes(b"x")
            os.utime(old, (time.time() - 3 * 86400,) * 2)
            with override_settings(MEDIA_ROOT=tmp):
                call_command("purge_community", "--dry-run")
                self.assertTrue(old.exists())
                call_command("purge_community")
            self.assertFalse(old.exists())      # DB 에 없는 하루 넘은 파일만 삭제
            self.assertTrue(fresh.exists())     # 방금 올라온(저장 중일 수 있는) 파일은 건드리지 않음
