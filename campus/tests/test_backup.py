import gzip
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TransactionTestCase, override_settings



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
                    call_command("backup_db", dir=str(out), keep=2)
                    import time; time.sleep(1.1)
                files = sorted(out.glob("*.gz"))
                self.assertEqual(len(files), 2)  # 오래된 것 정리
                self.assertEqual(oct(files[-1].stat().st_mode)[-3:], "600")
                call_command("backup_db", verify=str(files[-1]))
                self.assertTrue(gzip.open(files[-1]).read(16).startswith(b"SQLite format 3"))
