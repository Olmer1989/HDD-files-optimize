from contextlib import nullcontext, redirect_stdout, closing
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import uuid
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
                # Importing the very same export again changes nothing.
                self.assertEqual(portable.import_result(base / 'usb' / job.name, base / 'imports'), imported)
                self.assertFalse((base / 'imports' / '_Архив').exists())
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

    def make_job(self, results, disk_id, letter_root, files, policy, hashed=()):
        job_id = disk_id + '_' + uuid.uuid4().hex
        job = results / f'{disk_id} - Test - 1 ТБ' / job_id
        job.mkdir(parents=True)
        record = {'volume_serial': 'ABC', 'volume_bytes': shutil.disk_usage(letter_root).total, 'model': 'Test',
                  'physical_bytes': 10**12, 'hardware_serial': 'SER-' + disk_id}
        portable.write_json(job / 'job.json', {'version': portable.VERSION, 'job_id': job_id, 'disk_id': disk_id,
                            'record': record, 'policy': policy, 'inventory_finished': True})
        portable.write_json(job / 'inventory_summary.json', {'errors': 0, 'files': len(files), 'bytes': 1})
        with closing(sqlite3.connect(job / 'inventory.sqlite')) as db:
            db.execute('create table files(path text,size integer,mtime_ns text,file_id text)')
            for name in files:
                st = (letter_root / name).stat()
                db.execute('insert into files values (?,?,?,?)', (name, st.st_size, str(st.st_mtime_ns), str(st.st_ino)))
            db.commit()
        with closing(sqlite3.connect(job / 'hashes.sqlite')) as db:
            db.execute('create table hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,status text,error text,primary key(disk_id,path))')
            for name in hashed:
                st = (letter_root / name).stat()
                db.execute('insert into hashes values (?,?,?,?,?,?,?,?)', (disk_id, name, st.st_size, str(st.st_mtime_ns),
                           str(st.st_ino), 'x' * 64, 'verified', ''))
            db.commit()
        return job

    def patched(self, root):
        from contextlib import ExitStack
        stack = ExitStack()
        for name, value in [('discover_disk', (str(root), {})), ('describe', {'letter': 'Z'}),
                            ('volume', ('ABC', '', '')), ('awake', nullcontext())]:
            stack.enter_context(patch.object(portable, name, return_value=value))
        stack.enter_context(patch.object(portable, 'require_separate_output'))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return stack

    def test_policy_1_job_is_topped_up_not_rescanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'disk'; root.mkdir()
            (root / 'big.jpg').write_bytes(b'b' * 1048576)      # hashed under version 1
            (root / 'old_phone.jpg').write_bytes(b'p' * 60_000)  # new under version 2
            (root / 'icon.png').write_bytes(b'i' * 60_000)       # stays outside (< 150 KB)
            (root / 'clip.3gp').write_bytes(b'v' * 200_000)      # new: any video size
            job = self.make_job(base / 'results', 'HDD04', root, ['big.jpg', 'old_phone.jpg', 'icon.png', 'clip.3gp'],
                                portable.POLICY_V1, hashed=['big.jpg'])
            read = []
            def fake_hash(path, expected, progress):
                read.append(path.name); return 'h' * 64
            with self.patched(root), patch.object(portable, 'hash_one', side_effect=fake_hash):
                self.assertEqual(portable.process(job), 0)
            self.assertEqual(sorted(read), ['clip.3gp', 'old_phone.jpg'])  # big.jpg reused, icon.png not selected
            manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
            self.assertEqual((manifest['policy'], manifest['policy_history'][0]['from']), (portable.POLICY_V2, 1))
            result = json.loads((job / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual((result['selected_files'], result['cached_files'], result['hashed_files']), (3, 1, 2))
            self.assertIn('policy_upgrade', (job / 'runs.jsonl').read_text(encoding='utf-8'))
            self.assertIn('| v2 |', (base / 'results' / 'Реестр дисков.md').read_text(encoding='utf-8'))

    def test_unknown_policy_refused_and_logged_in_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'disk'; root.mkdir()
            job = self.make_job(base / 'r', 'HDD05', root, [], {'algorithm': 'md5'})
            with patch.object(portable, 'JOB_LOG', None):
                with self.assertRaisesRegex(RuntimeError, 'policy'):
                    portable.process(job)
                self.assertEqual(portable.JOB_LOG, job / 'log.txt')  # main() writes the STOP line there

    def test_export_all_and_import_whole_stick(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'disk'; root.mkdir()
            (root / 'a.jpg').write_bytes(b'a' * 1048576)
            results = base / 'other_pc'
            jobs = [self.make_job(results, d, root, ['a.jpg'], portable.POLICY_V2, hashed=['a.jpg']) for d in ('HDD06', 'HDD07')]
            unfinished = self.make_job(results, 'HDD08', root, ['a.jpg'], portable.POLICY_V2)
            for job in jobs:
                portable.write_json(job / 'result.json', {'status': 'complete'})
            portable.write_json(unfinished / 'result.json', {'status': 'interrupted'})
            stick, main = base / 'usb', base / 'main'
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(portable.export_all(results, stick), 0)
                self.assertEqual(portable.export_all(results, stick), 0)  # nothing changed: skipped
            self.assertEqual(sorted(p.name for p in stick.iterdir()), sorted(j.name for j in jobs))
            self.assertIn('без изменений', out.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(portable.import_any(stick, main), 0)
                self.assertEqual(portable.import_any(stick, main), 0)  # repeated import is harmless
            self.assertEqual(len(portable.find_jobs(main)), 2)
            # A newer export of the same job (one more hash) replaces the old import, which is archived.
            with closing(sqlite3.connect(jobs[0] / 'hashes.sqlite')) as db:
                db.execute("insert into hashes values ('HDD06','b.jpg',1,'1','1','y','verified','')"); db.commit()
            with redirect_stdout(io.StringIO()):
                portable.export_all(results, stick)
                portable.import_any(stick, main)
            self.assertEqual(portable.verified_count(portable.find_jobs(main)[0]), 2)
            self.assertEqual(len(list((main / '_Архив' / 'Заменённые задания').iterdir())), 1)
            # An older export never replaces a newer import.
            with self.assertRaisesRegex(ValueError, 'старее'):
                portable.import_result(stick / jobs[0].name, main)

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
