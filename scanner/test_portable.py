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
            job_id = 'HDD03_' + 'a' * 32
            results = base / 'results'
            job = results / 'HDD03 - Test disk - 2 ТБ - Фото' / job_id; job.mkdir(parents=True)
            photo = root / 'photo.jpg'; photo.write_bytes(b'a' * 1048576)
            st = photo.stat()
            record = {'volume_serial': 'ABC', 'volume_bytes': shutil.disk_usage(root).total, 'model': 'Test disk',
                      'physical_bytes': 2 * 10**12, 'label_at_registration': 'Фото', 'hardware_serial': 'SER'}
            portable.write_json(job / 'job.json', {'version': portable.VERSION, 'job_id': job_id, 'disk_id': 'HDD03', 'record': record,
                'policy': portable.POLICY, 'inventory_finished': True})
            portable.write_json(job / 'inventory_summary.json', {'errors': 0})
            with closing(sqlite3.connect(job / 'inventory.sqlite')) as db:
                db.execute('create table files(path text,size integer,mtime_ns text,file_id text)')
                db.execute('insert into files values (?,?,?,?)', ('photo.jpg', st.st_size, str(st.st_mtime_ns), str(st.st_ino)))
                db.commit()
            progress_file = base / 'progress.json'
            with patch.object(portable, 'discover_disk', return_value=(str(root), {})), \
                 patch.object(portable, 'describe', return_value={'letter': 'Z', 'model': 'Test disk', 'hardware_serial': 'SER'}), \
                 patch.object(portable, 'PROGRESS_FILE', progress_file), \
                 patch.object(portable, 'volume', return_value=('ABC', '', '')), \
                 patch.object(portable, 'require_separate_output'), \
                 patch.object(portable, 'awake', return_value=nullcontext()), redirect_stdout(io.StringIO()):
                stop = base / 'stop'
                def cancel(path, expected, callback):
                    stop.write_text('stop')
                    callback(0)
                with patch.object(portable, 'STOP_FILE', stop), patch.object(portable, 'hash_one', side_effect=cancel):
                    self.assertEqual(portable.process(job), 2)
                    self.assertEqual(json.loads((job / 'result.json').read_text())['status'], 'interrupted')
                stop.unlink()
                self.assertEqual(portable.process(job), 0)
                self.assertEqual(json.loads((job / 'result.json').read_text())['hashed_files'], 1)
                with patch.object(portable, 'hash_one', side_effect=AssertionError('Must reuse')):
                    self.assertEqual(portable.process(job), 0)
                self.assertEqual(json.loads((job / 'result.json').read_text())['cached_files'], 1)
                final = json.loads(progress_file.read_text(encoding='utf-8'))
                self.assertEqual((final['phase'], final['percent'], final['eta_seconds']), ('done', 100.0, 0))
                self.assertEqual((final['files_done'], final['files_total'], final['letter']), (1, 1, str(root)[0]))
                runs = [json.loads(x) for x in (job / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual([r['event'] for r in runs], ['start', 'finish'] * 3)
                self.assertEqual(runs[0]['identity']['hardware_serial'], 'SER')
                self.assertIn('Носитель HDD03: Test disk', (job / 'log.txt').read_text(encoding='utf-8'))
                portable.export(job, base / 'usb')
                self.assertTrue((base / 'usb' / job.name / 'runs.jsonl').exists())
                index = (results / 'Реестр дисков.md').read_text(encoding='utf-8')
                self.assertIn('| HDD03 | Test disk | 2 ТБ | Фото |', index)
                portable.import_result(base / 'usb' / job.name, base / 'imports')
                imported = base / 'imports' / 'HDD03 - Test disk - 2 ТБ - Фото' / job_id
                self.assertTrue((imported / 'hashes.sqlite').exists())
                self.assertIn('HDD03', (base / 'imports' / 'Реестр дисков.csv').read_text(encoding='utf-8-sig'))
                with self.assertRaisesRegex(ValueError, 'already been imported'):
                    portable.import_result(base / 'usb' / job.name, base / 'imports')
                # Exports from 1.0.x have no runs.jsonl/log.txt and must still import.
                old = base / 'old_usb' / job.name
                old.mkdir(parents=True)
                for name in portable.REQUIRED_EXPORTS:
                    shutil.copy2(job / name, old / name)
                manifest = json.loads((old / 'job.json').read_text(encoding='utf-8'))
                portable.write_json(old / 'job.json', {**manifest, 'job_id': 'HDD03_' + 'b' * 32})
                portable.write_json(old / 'checksums.json', {n: portable.checksum(old / n) for n in portable.REQUIRED_EXPORTS})
                portable.import_result(old, base / 'imports')
                self.assertEqual(len(list((base / 'imports' / 'HDD03 - Test disk - 2 ТБ - Фото').iterdir())), 2)
                (base / 'usb' / job.name / 'hashes.sqlite').write_bytes(b'damaged')
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    portable.import_result(base / 'usb' / job.name, base / 'imports')
                photo.write_bytes(b'b' * 1048576)
                self.assertEqual(portable.process(job), 2)
                self.assertEqual(json.loads((job / 'result.json').read_text())['status'], 'error')

    def test_forecast_and_duration(self):
        rate = portable.Rate(window=600, minimum=30)
        rate.add(0, 0)
        rate.add(10, 10**9)
        self.assertIsNone(rate.value())  # too early for a forecast
        rate.add(100, 10**10)
        self.assertAlmostEqual(rate.value(), 10**8)
        rate.add(1000, 10**11)  # old samples leave the window
        self.assertAlmostEqual(rate.value(), (10**11 - 10**10) / 900)
        self.assertEqual(portable.duration(None), 'оценивается…')
        self.assertEqual(portable.duration(30), 'меньше минуты')
        self.assertEqual(portable.duration(5400), '1 ч 30 мин')
        self.assertEqual(portable.duration(600), '10 мин')

    def test_identity_text_keeps_on_disk_markers(self):
        lines = '\n'.join(portable.identity_text('HDD05', {'model': 'WD Red', 'hardware_serial': 'WD-1', 'physical_bytes': 3e12,
            'media_type': 'HDD', 'bus_type': 'SATA', 'volume_label': 'Фото', 'volume_serial': 'AB12CD34', 'filesystem': 'NTFS',
            'volume_bytes': 3e12, 'letter': 'K', 'partition_style': 'MBR', 'mbr_signature': 305419896, 'computer': 'PC2'}))
        for text in ['WD Red', 'WD-1', 'HDD', 'SATA', 'AB12CD34', 'буква K:', '12345678', 'PC2', '«Фото»']:
            self.assertIn(text, lines)

    def test_disk_folder_names(self):
        self.assertEqual(portable.capacity(2000398933504), '2 ТБ')
        self.assertEqual(portable.capacity(18 * 10**12), '18 ТБ')
        self.assertEqual(portable.capacity(1.5 * 10**12), '1,5 ТБ')
        self.assertEqual(portable.capacity(500074283008), '500 ГБ')
        self.assertEqual(portable.disk_folder_name('HDD07', {'model': 'WD: Red?', 'physical_bytes': 3 * 10**12,
                         'label_at_registration': 'Фото/2010'}), 'HDD07 - WD_ Red_ - 3 ТБ - Фото_2010')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'HDD07 - старое имя').mkdir()
            self.assertEqual(portable.disk_folder(root, 'HDD07', {'model': 'новое'}).name, 'HDD07 - старое имя')
            self.assertEqual(portable.results_root(root / 'HDD07 - старое имя' / ('HDD07_' + 'c' * 32)), root)
            self.assertEqual(portable.results_root(root / ('HDD07_' + 'c' * 32)), root)

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
