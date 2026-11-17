import contextlib
import hashlib
import os
import shutil
import sqlite3
import json
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from inventory import inventory, classification, excluded_file, discover_disk
from winpath import extended, plain, under

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
                    return SimpleNamespace(name=name, path=extended('test-root') + '\\' + name,   # 1.6.2: обход по \\?\
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

    def test_path_longer_than_260_is_listed_and_hashed(self):
        # 17.11.2026: Python longPathAware + LongPathsEnabled=1 - опись и хеш читают пути длиннее 260 знаков без \\?\.
        import os, sys, hashlib
        from hash_files import hash_one
        if sys.platform != 'win32':
            self.skipTest('только Windows')
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem') as k:
                enabled = winreg.QueryValueEx(k, 'LongPathsEnabled')[0] == 1
        except OSError:
            enabled = False
        if not enabled:
            self.skipTest('в Windows не включены длинные пути (LongPathsEnabled) - на этом компьютере пути > 260 не читаются')
        with tempfile.TemporaryDirectory() as temp:
            folder = os.path.join(temp, *(['папка ' + 'п' * 57] * 5))
            os.makedirs(folder)
            path = os.path.join(folder, 'фото.jpg')
            with open(path, 'wb') as f:
                f.write(b'long' * 100)
            self.assertGreater(len(path), 330)
            db = sqlite3.connect(':memory:')
            result = inventory(temp, db, lambda: None)
            self.assertEqual((result['status'], result['files']), ('complete', 1))
            rel, size, mtime, fid = db.execute('select path, size, mtime_ns, file_id from files').fetchone()
            self.assertEqual(hash_one(Path(temp) / rel, (size, mtime, fid)), hashlib.sha256(b'long' * 100).hexdigest())


@contextlib.contextmanager
def special_temp():
    """Временная папка; удаляется по \\\\?\\-пути (обычный путь не удаляет CON.jpg и «a.»)."""
    temp = tempfile.mkdtemp()
    try:
        yield temp
    finally:
        shutil.rmtree(extended(temp))


@unittest.skipUnless(os.name == 'nt', 'только Windows')
class SpecialNamesTests(unittest.TestCase):
    """1.6.2: CON.jpg, NUL, «a.», «b », папка «dir. », путь > 300 - в описи с исходными именами, SHA-256 посчитан."""
    LONG = '\\'.join(['папка ' + 'п' * 57] * 5) + '\\фото.jpg'

    def make(self, temp):
        x = extended(temp)
        files = {'CON.jpg': b'con', 'NUL': b'nul', 'a.': b'dot', 'b ': b'space', 'dir. \\LPT1.png': b'lpt',
                 'com1.txt': b'com', self.LONG: b'long' * 50}
        for rel, data in files.items():
            os.makedirs(os.path.dirname(x + '\\' + rel), exist_ok=True)
            with open(x + '\\' + rel, 'wb') as f:
                f.write(data)
        return files

    def test_reserved_and_trailing_names_listed_and_hashed(self):
        import portable
        from hash_files import hash_one
        with special_temp() as temp:
            files = self.make(temp)
            self.assertGreater(len(os.path.join(temp, self.LONG)), 300)
            db = sqlite3.connect(':memory:')
            result = inventory(temp, db, lambda: None)
            self.assertEqual((result['status'], result['errors'], result['files']), ('complete', 0, len(files)))
            rows = db.execute('select path, size, mtime_ns, file_id from files').fetchall()
            self.assertEqual({r[0] for r in rows}, set(files))            # обычный путь, исходное имя, без \\?\
            for rel, size, mtime, fid in rows:
                self.assertEqual(size, len(files[rel]), rel)
                # как в portable: путь от корня тома строится из описи; CON.jpg - файл, а не консоль
                path = portable.source_path(temp, rel)
                self.assertEqual(path.stat().st_size, len(files[rel]), rel)
                for p in (path, Path(temp) / rel):
                    self.assertEqual(hash_one(p, (size, mtime, fid)), hashlib.sha256(files[rel]).hexdigest(), rel)

    def test_rescan_walk_and_folders(self):
        import rescan
        with special_temp() as temp:
            files = self.make(temp)
            self.assertEqual(rescan.normalize_folders(temp, ['dir. ']), ['dir. '])
            got, errors, _ = rescan.walk(temp, ['dir. ', 'папка ' + 'п' * 57])
            self.assertEqual(errors, [])
            self.assertEqual(set(got), {'dir. \\LPT1.png', self.LONG})
            self.assertEqual(got['dir. \\LPT1.png']['size'], 3)
            self.assertEqual(rescan.file_info(os.path.join(temp, 'CON.jpg'))['size'], len(files['CON.jpg']))

    def test_partial_scan_of_special_folder(self):
        with special_temp() as temp:
            self.make(temp)
            db = sqlite3.connect(':memory:')
            result = inventory(temp, db, lambda: None, folders=['dir. '])
            self.assertEqual((result['status'], result['files']), ('complete', 1))
            self.assertEqual(db.execute('select path from files').fetchone()[0], 'dir. \\LPT1.png')

    def test_error_on_one_file_does_not_stop_scan(self):
        import inventory as inv
        real = inv.classification
        def broken(name, size):
            if name == 'CON.jpg':
                raise ValueError('сбой на одном файле')
            return real(name, size)
        with special_temp() as temp:
            files = self.make(temp)
            db = sqlite3.connect(':memory:')
            with patch('inventory.classification', side_effect=broken):
                result = inventory(temp, db, lambda: None)
            self.assertEqual((result['status'], result['errors'], result['files']), ('complete_with_errors', 1, len(files) - 1))
            path, op, msg = db.execute('select path, operation, message from errors').fetchone()
            self.assertEqual((path, op, msg), (os.path.join(temp, 'CON.jpg'), 'не прочитан', 'сбой на одном файле'))

    def test_database_failure_stops_scan(self):
        with special_temp() as temp:
            self.make(temp)
            db = sqlite3.connect(':memory:')
            with patch('inventory.classification', side_effect=sqlite3.OperationalError('disk I/O error')):
                result = inventory(temp, db, lambda: None)
            self.assertEqual(result['status'], 'interrupted')        # не «файл не прочитан»

    def test_winpath(self):
        self.assertEqual(extended('C:\\'), '\\\\?\\C:\\')
        self.assertEqual(extended(Path('C:/x/../y. /CON.jpg')), '\\\\?\\C:\\y. \\CON.jpg')
        self.assertEqual(extended('\\\\srv\\sh\\a\\..\\b '), '\\\\?\\UNC\\srv\\sh\\b ')
        self.assertEqual(extended('\\\\?\\UNC\\srv\\sh\\b '), '\\\\?\\UNC\\srv\\sh\\b ')
        self.assertEqual(plain('\\\\?\\UNC\\srv\\sh\\b '), '\\\\srv\\sh\\b ')
        self.assertEqual(plain('\\\\?\\C:\\a.'), 'C:\\a.')
        self.assertEqual(under('\\\\?\\C:\\x\\a.', extended('C:\\')), 'x\\a.')
        self.assertEqual(under('\\\\?\\UNC\\srv\\sh\\x', extended('\\\\srv\\sh')), 'x')
        for bad in ('C:x', '\\\\.\\CON', '\\\\srv'):
            self.assertRaises(ValueError, extended, bad)
        self.assertRaises(ValueError, under, '\\\\?\\D:\\x', extended('C:\\'))


if __name__ == '__main__':
    unittest.main()
