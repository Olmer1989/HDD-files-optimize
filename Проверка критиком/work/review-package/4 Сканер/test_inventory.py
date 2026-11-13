import sqlite3
import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from inventory import inventory, classification, excluded_file, discover_disk

class InventoryTests(unittest.TestCase):
    def test_changed_drive_letter_resolved_by_hardware(self):
        record = dict(hardware_serial='SERIAL', physical_bytes=1000, volume_serial='ABCD1234', volume_bytes=900)
        payload = json.dumps([dict(letter='Z', serial=' SERIAL ', bytes=1000, unique_id='id')])
        with patch('inventory.subprocess.run', return_value=SimpleNamespace(stdout=payload)), \
             patch('inventory.volume', return_value=('ABCD1234', 'renamed label', 'NTFS')), \
             patch('inventory.shutil.disk_usage', return_value=SimpleNamespace(total=900)):
            root, item = discover_disk(record)
        self.assertEqual(root, 'Z:\\')

    def test_wrong_physical_disk_refused(self):
        record = dict(hardware_serial='SERIAL', physical_bytes=1000, volume_serial='ABCD1234', volume_bytes=900)
        payload = json.dumps([dict(letter='G', serial='OTHER', bytes=1000, unique_id='id')])
        with patch('inventory.subprocess.run', return_value=SimpleNamespace(stdout=payload)):
            with self.assertRaises(RuntimeError):
                discover_disk(record)

    def test_selection_and_no_source_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'trip').mkdir()
            (root / 'trip' / 'same.JPG').write_bytes(b'abc')
            (root / 'trip' / 'edit.xmp').write_bytes(b'xmp')
            (root / 'node_modules').mkdir()
            (root / 'node_modules' / 'skip.jpg').write_bytes(b'skip')
            before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
            db = sqlite3.connect(':memory:')
            result = inventory(str(root), db, lambda: None)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['files'], 2)
            self.assertEqual(result['content_bytes_read'], 0)
            self.assertEqual(result['excluded_directories'], 1)
            self.assertEqual(result['excluded_secret_files'], 0)
            self.assertEqual(before, {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()})
            self.assertEqual(classification('a.MP4', 1048576), 'media_ge_1MiB')
            self.assertEqual(classification('a.jpg', 20), 'media_small')
            self.assertTrue(excluded_file('.env.local'))
            self.assertTrue(excluded_file('.env'))

    def test_identity_change_stops_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'a.jpg').write_bytes(b'a')
            db = sqlite3.connect(':memory:')
            def fail():
                raise RuntimeError('disk replaced')
            result = inventory(temp, db, fail)
            self.assertEqual(result['status'], 'interrupted')
            self.assertEqual(result['files'], 0)
            self.assertEqual(db.execute("select value from metadata where key='status'").fetchone()[0], 'interrupted')

    def test_same_names_in_different_folders_are_separate_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder, content in [('a', b'abc'), ('b', b'xyz')]:
                (root / folder).mkdir()
                (root / folder / 'same.jpg').write_bytes(content)
            db = sqlite3.connect(':memory:')
            result = inventory(temp, db, lambda: None)
            self.assertEqual(result['files'], 2)
            self.assertEqual(db.execute('select count(*) from files').fetchone()[0], 2)
            self.assertNotIn('duplicates', result)  # metadata do not prove equality

    def test_volume_disconnect_during_scan_is_interrupted(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / 'a').mkdir()
            calls = 0
            def check():
                nonlocal calls
                calls += 1
                if calls > 2:
                    raise OSError('simulated disconnect')
            result = inventory(temp, sqlite3.connect(':memory:'), check)
            self.assertEqual(result['status'], 'interrupted')
            self.assertEqual(result['errors'], 1)

    def test_root_access_denied_never_reported_complete(self):
        with patch('inventory.os.scandir', side_effect=PermissionError('simulated')):
            result = inventory('test-root', sqlite3.connect(':memory:'), lambda: None)
        self.assertEqual(result['status'], 'interrupted')

    def test_secret_excluded_before_stat(self):
        class Entries:
            def __enter__(self):
                return iter([SimpleNamespace(name='.env', stat=lambda **kw: self.fail())])
            def __exit__(self, *args):
                pass
            def fail(self):
                raise AssertionError('must never stat secret')
        with patch('inventory.os.scandir', return_value=Entries()):
            result = inventory('test-root', sqlite3.connect(':memory:'), lambda: None)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['excluded_secret_files'], 1)

    def test_reparse_point_not_followed_and_extreme_dates_preserved(self):
        class Entries:
            def __enter__(self):
                def entry(name, attrs):
                    return SimpleNamespace(name=name, path='test-root/'+name,
                        stat=lambda **kw: SimpleNamespace(st_file_attributes=attrs,
                        st_mode=0o100644, st_size=3, st_mtime_ns=-11644473600000000000,
                        st_ctime_ns=-11644473600000000000, st_ino=123))
                return iter([entry('link', 0x400), entry('photo.jpg', 0)])
            def __exit__(self, *args):
                pass
        db = sqlite3.connect(':memory:')
        with patch('inventory.os.scandir', return_value=Entries()):
            result = inventory('test-root', db, lambda: None)
        self.assertEqual(result['reparse_skipped'], 1)
        self.assertEqual(result['files'], 1)
        self.assertEqual(db.execute('select mtime_ns from files').fetchone()[0], '-11644473600000000000')

if __name__ == '__main__':
    unittest.main()
