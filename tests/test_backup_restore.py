import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from tools.backup_restore import backup,restore
from services.jobs import JobQueue


class BackupRestoreTests(unittest.TestCase):
    def test_restore_database_and_artifact_and_reject_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'data';source.mkdir()
            (source/'index').mkdir();(source/'index'/'generation').write_text('version one')
            with closing(sqlite3.connect(source/'expo.db')) as conn:
                conn.execute('CREATE TABLE evidence(value TEXT)');conn.execute("INSERT INTO evidence VALUES('original')")
                conn.commit()
            snapshot=Path(root)/'snapshot'
            self.assertEqual(backup(source,snapshot),2)
            target=Path(root)/'restored'
            self.assertEqual(restore(snapshot,target),2)
            with closing(sqlite3.connect(target/'expo.db')) as conn:
                self.assertEqual(conn.execute('SELECT value FROM evidence').fetchone()[0],'original')
            (snapshot/'index'/'generation').write_text('corrupted')
            with self.assertRaises(ValueError): restore(snapshot,Path(root)/'bad')
            self.assertFalse(any((Path(root)/'bad').iterdir()))

    def test_active_runner_and_nonempty_destination_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'data';source.mkdir()
            queue=JobQueue(str(source));queue.start()
            try:
                with self.assertRaises(RuntimeError): backup(source,Path(root)/'snapshot')
            finally:queue.stop()
            with self.assertRaises(ValueError): restore(source,source)

if __name__=='__main__':unittest.main()
