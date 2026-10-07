import tempfile,unittest
from pathlib import Path
from services.upload_recovery import staging_lease,quarantine_interrupted_uploads

class UploadRecoveryTests(unittest.TestCase):
    def test_child_process_exit_releases_lease_for_safe_quarantine(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'docs';root.mkdir()
            staging=root/('source.pdf.upload-'+'c'*32)
            code="import os,sys; from pathlib import Path; from services.upload_recovery import staging_lease; p=Path(sys.argv[1]); lease=staging_lease(p); lease.__enter__(); p.write_bytes(b'interrupted source'); os._exit(91)"
            result=subprocess.run([sys.executable,'-c',code,str(staging)],timeout=20)
            self.assertEqual(result.returncode,91)
            records=quarantine_interrupted_uploads([root],Path(directory)/'quarantine')
            self.assertEqual(len(records),1)
            self.assertEqual(Path(records[0]['quarantined']).read_bytes(),b'interrupted source')

    def test_active_staging_is_preserved_then_abandoned_bytes_quarantined(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'docs';root.mkdir();dest=Path(directory)/'quarantine'
            staging=root/('source.pdf.upload-'+'a'*32);staging.write_bytes(b'partial bytes')
            original=root/'source.pdf';original.write_bytes(b'original source')
            with staging_lease(staging):
                self.assertEqual(quarantine_interrupted_uploads([root],dest),[])
                self.assertTrue(staging.exists())
            records=quarantine_interrupted_uploads([root],dest)
            self.assertEqual(len(records),1)
            self.assertEqual(Path(records[0]['quarantined']).read_bytes(),b'partial bytes')
            self.assertEqual(original.read_bytes(),b'original source')
            self.assertEqual(records[0]['status'],'REUPLOAD_REQUIRED')

    def test_unleased_and_unrecognized_files_are_not_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'docs';root.mkdir()
            files=[root/('old.pdf.upload-'+'b'*32),root/'source.pdf',root/'source.pdf.upload-not-a-uuid']
            for path in files:path.write_bytes(b'preserve')
            self.assertEqual(quarantine_interrupted_uploads([root],Path(directory)/'quarantine'),[])
            self.assertTrue(all(path.exists() for path in files))
