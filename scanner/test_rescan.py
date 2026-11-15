"""Пересканирование выбранных папок (1.4.0) на временных папках: что читается заново, что берётся из прежней описи.

Запуск из папки scanner:  py -m unittest test_rescan
"""
from argparse import Namespace
from contextlib import closing, nullcontext, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

import portable
import rescan

SERIAL = 'ABCD1234'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_full_job(results, disk, root, created=None, skip=()):
    """Полная опись носителя, как от сканера: опись всех файлов root и SHA-256 по содержимому."""
    job = results / f'{disk} - Test disk - 2 ТБ' / f'{disk}_{uuid.uuid4().hex}'
    job.mkdir(parents=True)
    record = {'volume_serial': SERIAL, 'volume_bytes': 1, 'hardware_serial': 'SER', 'physical_bytes': 2, 'model': 'Test disk',
              'filesystem': 'NTFS'}
    created = created or portable.utc()
    portable.write_json(job / 'job.json', {'version': portable.VERSION, 'job_id': job.name, 'disk_id': disk,
                                           'record': record, 'policy': portable.POLICY, 'created_utc': created,
                                           'inventory_finished': True})
    portable.write_json(job / 'result.json', {'disk_id': disk, 'status': 'complete'})
    with closing(sqlite3.connect(job / 'inventory.sqlite')) as inv, closing(sqlite3.connect(job / 'hashes.sqlite')) as h:
        inv.execute('create table files(path text primary key,size integer,mtime_ns text,ctime_ns text,file_id text,'
                    'attributes integer,category text)')
        h.execute('create table hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,'
                  'status text,error text,primary key(disk_id,path))')
        for dirpath, _, names in os.walk(root):
            for n in names:
                p = Path(dirpath) / n
                st = p.stat()
                rel = str(p.relative_to(root))
                inv.execute('insert into files values (?,?,?,?,?,?,?)', (rel, st.st_size, str(st.st_mtime_ns),
                                                                         str(st.st_ctime_ns), str(st.st_ino), 32, 'other'))
                if rel not in skip:
                    h.execute('insert into hashes values (?,?,?,?,?,?,?,?)', (disk, rel, st.st_size, str(st.st_mtime_ns),
                                                                             str(st.st_ino), sha(p.read_bytes()), 'verified', ''))
        inv.commit(); h.commit()
    return job, record


def rewrite_same(path, data):
    """Подмена содержимого с тем же размером и прежним mtime - так, как может сделать программа копирования."""
    st = path.stat()
    with open(path, 'r+b') as f:
        f.write(data)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))


def scanner_patches(root, record, reads):
    """Сканер на временной папке вместо диска: опознание носителя и тома подменены, чтение файлов - настоящее,
    каждый прочитанный файл записывается в reads."""
    real = portable.hash_one

    def counting(path, expected, progress=None):
        reads.append(str(Path(path).relative_to(root)))
        return real(path, expected, progress)
    return [patch.object(portable, 'discover_disk', return_value=(str(root), {})),
            patch.object(portable, 'describe', return_value={'letter': 'Z', 'model': 'Test disk'}),
            patch.object(portable, 'inspect', return_value=dict(record)),
            patch.object(portable, 'volume', return_value=(SERIAL, '', 'NTFS')),
            patch.object(portable, 'source_root', return_value=str(root)),
            patch.object(portable, 'require_separate_output'),
            patch.object(portable, 'awake', return_value=nullcontext()),
            patch.object(portable, 'hash_one', side_effect=counting),
            patch.object(portable.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(1, 0, 1))]


class RescanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='rescan_test_'))
        self.root = self.tmp / 'source'
        (self.root / 'Котуй 2026' / 'день 1').mkdir(parents=True)
        (self.root / 'Другое').mkdir()
        self.files = {'Котуй 2026\\a.jpg': b'a' * 300, 'Котуй 2026\\b.jpg': b'b' * 200, 'Котуй 2026\\день 1\\c.mp4': b'c' * 500,
                      'Котуй 2026\\заметки.txt': b'note', 'Котуй 2026\\old.mov': b'm' * 50, 'Другое\\x.jpg': b'x' * 100}
        for rel, data in self.files.items():
            (self.root / rel).write_bytes(data)
        time.sleep(0.05)
        self.results = self.tmp / 'results'
        self.full, self.record = make_full_job(self.results, 'HDD03', self.root, skip=('Котуй 2026\\old.mov',))
        time.sleep(0.05)
        # после описи: b.jpg подменён (размер и mtime те же), c.mp4 удалён, e.jpg добавлен
        rewrite_same(self.root / 'Котуй 2026\\b.jpg', b'B' * 200)
        (self.root / 'Котуй 2026\\день 1\\c.mp4').unlink()
        (self.root / 'Котуй 2026\\e.jpg').write_bytes(b'e' * 70)
        self.out = self.results / rescan.PARTIAL_DIR
        self.reads = []
        self.patches = scanner_patches(self.root, self.record, self.reads)
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        portable.JOB_LOG = None
        shutil.rmtree(self.tmp, ignore_errors=True)

    def start(self, folders=('котуй 2026',), rehash_all=False, hash_all_types=False):
        args = Namespace(disk='HDD03', letter='Z', folder=list(folders), rehash_all=rehash_all, prior_root=None, yes=True,
                         hash_all_types=hash_all_types)
        with redirect_stdout(io.StringIO()):
            code = portable.start_partial(args, dict(self.record), self.out.resolve())
        job = max((p for p in self.out.glob('*/*') if p.is_dir()), key=lambda p: (p / 'job.json').stat().st_mtime_ns)
        return code, job, json.loads((job / 'result.json').read_text(encoding='utf-8'))

    def hashes(self, job):
        with closing(sqlite3.connect(job / 'hashes.sqlite')) as h:
            return {p: (s, st) for p, s, st in h.execute('select path, sha256, status from hashes')}

    def test_only_new_and_changed_are_read(self):
        code, job, res = self.start()
        self.assertEqual(code, 0)
        self.assertEqual(res['status'], 'complete')
        self.assertEqual((res['scan_scope'], res['hash_scope'], res['folders']), ('partial', 'all_regular_files', ['Котуй 2026']))
        # a.jpg и заметки.txt не читаются; b.jpg (подмена с тем же mtime - видна по ChangeTime), e.jpg (новый),
        # old.mov (в описи без хеша) - читаются
        self.assertEqual(sorted(self.reads), ['Котуй 2026\\b.jpg', 'Котуй 2026\\e.jpg', 'Котуй 2026\\old.mov'])
        self.assertEqual((res['reused_files'], res['hashed_files'], res['gone_files']), (2, 3, 1))
        self.assertEqual(res['read_reasons'], {'change_time': [1, 200], 'new': [1, 70], 'nohash': [1, 50]})
        self.assertEqual(res['gone_examples'], ['Котуй 2026\\день 1\\c.mp4'])
        self.assertIn('ChangeTime', res['reuse_basis'])
        self.assertEqual(res['reuse_sources'][0]['job'], self.full.name)
        h = self.hashes(job)
        self.assertEqual(h['Котуй 2026\\a.jpg'], (sha(b'a' * 300), 'verified'))
        self.assertEqual(h['Котуй 2026\\b.jpg'], (sha(b'B' * 200), 'verified'))      # новый хеш, не прежний
        self.assertNotIn('Другое\\x.jpg', h)                                         # вне папки - не описан
        with closing(sqlite3.connect(job / 'hashes.sqlite')) as c:
            info = {p: (how, fj) for p, how, fj in c.execute('select path, how, from_job from hash_info')}
        self.assertEqual(info['Котуй 2026\\a.jpg'], ('reused', self.full.name))
        self.assertEqual(info['Котуй 2026\\e.jpg'], ('read', job.name))
        runs = [json.loads(x) for x in (job / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(runs[-1]['reused_files'], 2)
        manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['version'], portable.VERSION_PARTIAL)          # старый сканер его не продолжит
        # продолжение задания: опись заново, все хеши - из этого же задания, ничего не читается
        self.reads.clear()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(portable.process(job), 0)
        self.assertEqual(self.reads, [])
        res = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual((res['cached_files'], res['reused_files'], res['hashed_files']), (5, 0, 0))
        # повторный скан папки после первого: прежний хеш - из частичного скана, граница - исходная (полная опись)
        self.reads.clear()
        code, job2, res2 = self.start()
        self.assertEqual(self.reads, [])
        self.assertEqual(res2['reused_files'], 5)
        with closing(sqlite3.connect(job2 / 'hashes.sqlite')) as c:
            info = {p: fj for p, fj in c.execute('select path, from_job from hash_info')}
        self.assertEqual(info['Котуй 2026\\a.jpg'], self.full.name)
        self.assertEqual(info['Котуй 2026\\e.jpg'], job.name)

    def test_summary_for_owner_and_hash_types(self):
        code, job, res = self.start(hash_all_types=True)
        self.assertEqual(res['hash_types'], 'all')
        manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual((manifest['hash_types'], manifest['hash_all_types_flag']), ('all', True))
        text = rescan.summary_text(res)
        # прочитано 3 = новые 1 + изменились 1 (ChangeTime) + прежде без хеша 1; взято 2 - с даты прежней описи
        self.assertTrue(text.startswith('Прочитано заново: 3 (новые 1, изменились 1, в прежней описи без хеша'), text)
        day = rescan.date_ru(res['reused_measured_utc'][0])
        self.assertIn(f'файлы не менялись с {day}): 2.', text)
        self.assertIn(rescan.summary_text(res), (job / 'log.txt').read_text(encoding='utf-8'))
        self.assertIn('Перечитано всё', rescan.summary_text({**res, 'rehash_all': True}))

    def test_m2t_and_dv_are_video(self):
        import build_selection
        for name in ('a.m2t', 'b.DV'):
            self.assertTrue(build_selection.select('x\\' + name, 1, build_selection.THRESHOLDS_V2))
        self.assertEqual(portable.policy_version(portable.POLICY_V2), 2)        # старые задания узнаются
        self.assertNotIn('.m2t', portable.POLICY_V2['video_extensions'])
        self.assertIn('.m2t', portable.POLICY_V3['video_extensions'])

    def test_rehash_all_reads_everything(self):
        code, job, res = self.start(rehash_all=True)
        self.assertEqual(len(self.reads), 5)
        self.assertEqual((res['reused_files'], res['read_reasons']), (0, {'rehash_all': [5, 624]}))
        self.assertEqual(res['reuse_sources'], [])

    def test_stop_and_resume(self):
        stop = self.tmp / 'stop'

        def cancel(path, expected, progress):
            stop.write_text('1')
            progress(0)
        with patch.object(portable, 'STOP_FILE', stop), patch.object(portable, 'hash_one', side_effect=cancel):
            code, job, res = self.start()
        self.assertEqual((code, res['status']), (2, 'interrupted'))
        stop.unlink()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(portable.process(job), 0)
        res = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual((res['status'], res['reused_files'], res['cached_files'], res['hashed_files']), ('complete', 1, 1, 3))

    def test_refusals(self):
        with self.assertRaises(ValueError):
            rescan.normalize_folders(str(self.root), ['Котуй 2026', 'Котуй 2026\\день 1'])        # вложенные
        with self.assertRaises(ValueError):
            rescan.normalize_folders(str(self.root), ['..\\x'])
        with self.assertRaises(ValueError):
            rescan.normalize_folders(str(self.root), ['Нет такой'])
        self.assertEqual(rescan.normalize_folders(str(self.root), ['КОТУЙ 2026\\ДЕНЬ 1']), ['Котуй 2026\\день 1'])
        other = dict(self.record, volume_serial='FFFF0000')
        args = Namespace(disk='HDD03', letter='Z', folder=['Котуй 2026'], rehash_all=False, prior_root=None, yes=True)
        with self.assertRaises(RuntimeError), redirect_stdout(io.StringIO()):
            portable.start_partial(args, other, self.out.resolve())                  # другой носитель
        with self.assertRaises(RuntimeError), redirect_stdout(io.StringIO()):
            portable.start_partial(Namespace(**{**vars(args), 'disk': 'HDD04'}), dict(self.record), self.out.resolve())

    def test_unreadable_folder_is_not_accepted(self):
        real = os.scandir

        def broken(path):
            if str(path).endswith('день 1'):
                raise PermissionError(5, 'Отказано в доступе')
            return real(path)
        with patch('inventory.os.scandir', side_effect=broken):
            code, job, res = self.start()
        self.assertEqual((code, res['status']), (2, 'inventory_incomplete'))       # база принимает только complete*

    def test_plan_matches_scan(self):
        p = rescan.plan(str(self.root), 'HDD03', ['Котуй 2026'], [self.results])
        self.assertEqual((p['files'], p['reuse'][0], p['read'][0], p['gone']), (5, 2, 3, 1))
        self.assertEqual(set(p['reasons']), {'change_time', 'new', 'nohash'})
        text = '\n'.join(rescan.plan_text(p))
        self.assertIn('Прочитать с диска: 3 файлов', text)
        self.assertIn('Взять хеш из прежней описи (без чтения): 2', text)
        self.assertEqual(p['read_nonmedia'], [2, 270])     # b.jpg, e.jpg меньше 50 КБ: полная опись их не хешировала бы
        self.assertEqual(self.reads, [])                                               # содержимое не читалось
        # переименование: тот же номер файла - помечается, но хеш не наследуется
        os.rename(self.root / 'Котуй 2026\\a.jpg', self.root / 'Котуй 2026\\a2.jpg')
        p = rescan.plan(str(self.root), 'HDD03', ['Котуй 2026'], [self.results])
        self.assertEqual(p['reasons']['renamed'][0], 1)
        self.assertEqual(p['reuse'][0], 1)

    def test_decide_rules(self):
        now = time.time_ns()
        prior = dict(size=10, mtime_ns='5', file_id='7', ctime_ns='3', sha='x', status='verified', job='j', bound_ns=now - 100)
        cur = dict(size=10, mtime_ns=5, file_id='7', ctime_ns=3, change_ns=now - 200)
        self.assertEqual(rescan.decide(cur, prior, now_ns=now), ('reuse', None))
        self.assertEqual(rescan.decide({**cur, 'change_ns': now - 50}, prior, now_ns=now)[1], 'change_time')
        self.assertEqual(rescan.decide({**cur, 'file_id': '8'}, prior, now_ns=now)[1], 'changed')
        self.assertEqual(rescan.decide({**cur, 'ctime_ns': 4}, prior, now_ns=now)[1], 'changed')
        self.assertEqual(rescan.decide(cur, {**prior, 'bound_ns': now + 10**12}, now_ns=now)[1], 'clock')
        self.assertEqual(rescan.decide(cur, prior, ntfs=False, now_ns=now)[1], 'not_ntfs')
        self.assertEqual(rescan.decide(cur, {**prior, 'sha': None, 'status': 'damaged'}, now_ns=now)[1], 'unread_before')


if __name__ == '__main__':
    unittest.main()
