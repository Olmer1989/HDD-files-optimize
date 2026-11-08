from contextlib import nullcontext, redirect_stdout, closing
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import portable

class PortableTests(unittest.TestCase):
    def test_resume_export_import_and_transfer_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'source'; root.mkdir()
            job = base / 'HDD03_job'; job.mkdir()
            photo = root / 'photo.jpg'; photo.write_bytes(b'a' * 1048576)
            st = photo.stat()
            record = {'volume_serial': 'ABC', 'volume_bytes': shutil.disk_usage(root).total}
            portable.write_json(job / 'job.json', {'version': portable.VERSION, 'disk_id': 'HDD03', 'record': record,
                'policy': portable.POLICY, 'inventory_finished': True})
            portable.write_json(job / 'inventory_summary.json', {'errors': 0})
            with closing(sqlite3.connect(job / 'inventory.sqlite')) as db:
                db.execute('create table files(path text,size integer,mtime_ns text,file_id text)')
                db.execute('insert into files values (?,?,?,?)', ('photo.jpg', st.st_size, str(st.st_mtime_ns), str(st.st_ino)))
                db.commit()
            with patch.object(portable, 'discover_disk', return_value=(str(root), {})), \
                 patch.object(portable, 'volume', return_value=('ABC', '', '')), \
                 patch.object(portable, 'require_separate_output'), \
                 patch.object(portable, 'awake', return_value=nullcontext()), redirect_stdout(io.StringIO()):
                self.assertEqual(portable.process(job), 0)
                self.assertEqual(json.loads((job / 'result.json').read_text())['hashed_files'], 1)
                with patch.object(portable, 'hash_one', side_effect=AssertionError('Must reuse')):
                    self.assertEqual(portable.process(job), 0)
                self.assertEqual(json.loads((job / 'result.json').read_text())['cached_files'], 1)
                portable.export(job, base / 'usb')
                portable.import_result(base / 'usb' / job.name, base / 'imports')
                self.assertEqual(len(list((base / 'imports').iterdir())), 1)
                (base / 'usb' / job.name / 'hashes.sqlite').write_bytes(b'damaged')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    portable.import_result(base / 'usb' / job.name, base / 'imports')
                photo.write_bytes(b'b' * 1048576)
                self.assertEqual(portable.process(job), 2)
                self.assertEqual(json.loads((job / 'result.json').read_text())['status'], 'error')

    def test_unfinished_export_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            portable.write_json(folder / 'result.json', {'status': 'interrupted'})
            with self.assertRaisesRegex(RuntimeError, 'completed'):
                portable.export(folder, folder / 'usb')

    def test_unsafe_paths_refused(self):
        for rel in ['..\\x.jpg', 'C:\\x.jpg', '\\\\server\\share\\x.jpg', 'x.jpg:stream']:
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                portable.safe_relative(rel)

    def test_source_volume_output_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'source volume'):
            portable.require_separate_output(Path.cwd(), Path.cwd().anchor)

if __name__ == '__main__':
    unittest.main()
