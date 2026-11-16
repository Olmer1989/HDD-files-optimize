"""Сканер 1.6.0: хеш только у выбранных типов файлов при пересканировании папок (временные папки).

Запуск из папки scanner:  py -m unittest test_hash_types
"""
from argparse import Namespace
from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
import unittest
from unittest.mock import patch

import portable
import rescan
import test_rescan
from test_rescan import sha

ONLY_JPG = dict(hash_ext='.jpg', hash_skip_names='thumbs.db,~$*', hash_skip_path_re='proxy media|render cache')


class HashTypesTests(unittest.TestCase):
    """Папка «Котуй 2026» (см. RescanTests.setUp): a.jpg (не менялся), b.jpg (подменён), e.jpg (новый), заметки.txt
    (не менялся), old.mov (в прежней описи без хеша); c.mp4 исчез. Здесь добавлены новые не-jpg и служебные файлы."""

    tearDown = test_rescan.RescanTests.tearDown
    hashes = test_rescan.RescanTests.hashes

    def setUp(self):
        test_rescan.RescanTests.setUp(self)
        k = self.root / 'Котуй 2026'
        (k / 'отчёт.docx').write_bytes(b'd' * 40)                 # новый документ
        (k / '~$отчёт.jpg').write_bytes(b'~' * 10)                # служебный по имени
        (k / 'Proxy Media').mkdir()
        (k / 'Proxy Media' / 'p.jpg').write_bytes(b'p' * 30)      # кэш монтажа по пути
        (k / 'без расширения').write_bytes(b'z' * 5)

    def start_types(self, rehash_all=False, **types):
        args = Namespace(disk='HDD03', letter='Z', folder=['Котуй 2026'], rehash_all=rehash_all, prior_root=None,
                         yes=True, hash_all_types=False, **types)
        with redirect_stdout(io.StringIO()):
            code = portable.start_partial(args, dict(self.record), self.out.resolve())
        job = max((p for p in self.out.glob('*/*') if p.is_dir()), key=lambda p: (p / 'job.json').stat().st_mtime_ns)
        return code, job, json.loads((job / 'result.json').read_text(encoding='utf-8'))

    def test_only_selected_types_are_read(self):
        code, job, res = self.start_types(**ONLY_JPG)
        self.assertEqual((code, res['status']), (0, 'complete'))
        # читаются только jpg без годного прежнего хеша; служебные jpg - нет
        self.assertEqual(sorted(self.reads), ['Котуй 2026\\b.jpg', 'Котуй 2026\\e.jpg'])
        h = self.hashes(job)
        self.assertEqual(h['Котуй 2026\\заметки.txt'], (sha(b'note'), 'verified'))   # не выбран, прежний хеш годен
        self.assertEqual(h['Котуй 2026\\a.jpg'], (sha(b'a' * 300), 'verified'))
        for p in ('отчёт.docx', 'old.mov', '~$отчёт.jpg', 'Proxy Media\\p.jpg', 'без расширения'):
            self.assertNotIn('Котуй 2026\\' + p, h)              # строки нет: не «не прочитан», а тип не выбран
        self.assertEqual((res['skipped_files'], res['hashed_files'], res['reused_files']), (5, 2, 2))
        self.assertEqual(res['hash_scope'], 'selected_types')
        self.assertEqual((res['hash_types']['mode'], res['hash_types']['ext']), ('only', ['.jpg']))
        manifest = json.loads((job / 'job.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['hash_types'], res['hash_types'])
        with closing(sqlite3.connect(job / 'inventory.sqlite')) as c:                # опись - все файлы, как раньше
            self.assertEqual(c.execute('select count(*) from files').fetchone()[0], 9)
        self.assertIn('без хеша (тип не выбран) 5', (job / 'log.txt').read_text(encoding='utf-8'))
        # продолжение задания - по правилу из задания: ничего не читается, без хеша - те же
        self.reads.clear()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(portable.process(job), 0)
        self.assertEqual(self.reads, [])
        res = json.loads((job / 'result.json').read_text(encoding='utf-8'))
        self.assertEqual((res['skipped_files'], res['cached_files']), (5, 4))

    def test_skip_mode_hashes_the_rest(self):
        # «Другие» выбраны: всё, кроме перечисленных расширений и служебных
        code, job, res = self.start_types(hash_skip_ext='.docx,.mov', hash_skip_names='~$*',
                                          hash_skip_path_re='proxy media')
        self.assertEqual(sorted(self.reads), ['Котуй 2026\\b.jpg', 'Котуй 2026\\e.jpg', 'Котуй 2026\\без расширения'])
        self.assertEqual(res['hash_types']['mode'], 'skip')
        self.assertEqual(res['skipped_files'], 4)

    def test_rehash_all_rereads_only_selected(self):
        code, job, res = self.start_types(rehash_all=True, **ONLY_JPG)
        self.assertEqual(sorted(self.reads), ['Котуй 2026\\a.jpg', 'Котуй 2026\\b.jpg', 'Котуй 2026\\e.jpg'])
        self.assertEqual(self.hashes(job)['Котуй 2026\\заметки.txt'], (sha(b'note'), 'verified'))   # S не потерян
        self.assertEqual(res['read_reasons']['rehash_all'][0], 3)
        self.assertTrue(res['reuse_sources'])
        self.assertIn('у невыбранных', res['reuse_basis'])

    def test_rehash_all_resume_does_not_reread_own(self):
        """Продолжение «перечитать всё»: прочитанное уже в этом задании не читается и не входит в оценку чтения."""
        for types in ({}, ONLY_JPG):
            self.reads.clear()
            code, job, res = self.start_types(rehash_all=True, **types)
            self.assertTrue(self.reads)
            self.reads.clear()
            published = []
            with patch.object(portable, 'publish', side_effect=published.append), redirect_stdout(io.StringIO()):
                self.assertEqual(portable.process(job), 0)
            self.assertEqual(self.reads, [], types)
            self.assertEqual(published[-1]['to_read_bytes'], 0, types)
            res = json.loads((job / 'result.json').read_text(encoding='utf-8'))
            self.assertEqual(res['hashed_files'], 0)

    def test_all_types_is_the_old_behaviour(self):
        code, job, res = self.start_types(hash_ext=None, hash_skip_ext=None)       # без ключей выбора
        self.assertEqual(res['hash_types'], 'all')
        self.assertEqual(res['hash_scope'], 'all_regular_files')
        self.assertEqual(res['skipped_files'], 0)
        self.assertEqual(len(self.reads), 7)            # b, e, old.mov + 4 новых файла - как до 1.6.0
        self.reads.clear()
        code, job, res = self.start_types(hash_skip_ext='')                         # пустой пропуск = все типы
        self.assertEqual(res['hash_types'], 'all')

    def test_plan_estimate_matches_scan(self):
        rule = rescan.hash_rule({'hash_types': {'mode': 'only', 'ext': ['.jpg'], 'junk_names': ['thumbs.db', '~$*'],
                                                'junk_path_re': 'proxy media|render cache'}})
        p = rescan.plan(str(self.root), 'HDD03', ['Котуй 2026'], [self.results])
        e = rescan.by_types(p, rule)
        self.assertEqual((e['read'][0], e['reuse'][0], e['skip'][0]), (2, 2, 5))
        self.assertIn('Котуй 2026\\отчёт.docx', e['skip_paths'])
        self.assertEqual(rescan.by_types(p, None)['read'], p['read'])               # все типы = прежняя оценка
        pr = rescan.plan(str(self.root), 'HDD03', ['Котуй 2026'], [self.results], rehash_all=True)
        e = rescan.by_types(pr, rule)
        self.assertEqual((e['read'][0], e['reuse'][0], e['skip'][0]), (3, 1, 5))
        code, job, res = self.start_types(**ONLY_JPG)
        self.assertEqual((res['hashed_files'], res['reused_files'], res['skipped_files']), (2, 2, 5))


class RuleAndKeysTests(unittest.TestCase):
    def test_wants_hash(self):
        r = rescan.hash_rule({'hash_types': {'mode': 'only', 'ext': ['.jpg', '.DOCX'], 'junk_names': ['Thumbs.db', '~$*'],
                                             'junk_path_re': 'proxy media'}})
        self.assertTrue(rescan.wants_hash('A\\b.JPG', r))
        self.assertTrue(rescan.wants_hash('A\\b.docx', r, 5))
        self.assertFalse(rescan.wants_hash('A\\b.jpg.exe', r))                     # последнее расширение
        self.assertFalse(rescan.wants_hash('A\\~$b.docx', r))
        self.assertFalse(rescan.wants_hash('A\\Proxy Media\\b.jpg', r))
        self.assertFalse(rescan.wants_hash('A\\noext', r))
        self.assertFalse(rescan.wants_hash('A\\b.jpg', r, 0))                       # пустой - «Другие», не выбраны
        s = rescan.hash_rule({'hash_types': {'mode': 'skip', 'ext': ['.zip']}})
        self.assertTrue(rescan.wants_hash('A\\noext', s) and rescan.wants_hash('A\\x.zip', s, 0))
        self.assertFalse(rescan.wants_hash('A\\x.ZIP', s))
        self.assertIsNone(rescan.hash_rule({'hash_types': 'all'}))
        self.assertIsNone(rescan.hash_rule({}))                                     # задания до 1.6.0
        self.assertTrue(rescan.wants_hash('A\\x.exe', None, 0))

    def test_keys(self):
        def run(*argv):
            err = io.StringIO()
            with patch.object(sys, 'argv', ['portable.py', 'start', '--disk', 'HDD03', '--letter', 'Z', *argv]), \
                    redirect_stderr(err), self.assertRaises(SystemExit):
                portable.main()
            return err.getvalue()
        self.assertIn('choose one', run('--folder', 'A', '--hash-all-types', '--hash-ext', '.jpg'))
        self.assertIn('choose one', run('--folder', 'A', '--hash-ext', '.jpg', '--hash-skip-ext', '.zip'))
        self.assertIn('only with --folder', run('--hash-ext', '.jpg'))
        self.assertIn('empty list', run('--folder', 'A', '--hash-ext', ' , '))
        self.assertIn('only with --hash-ext', run('--folder', 'A', '--hash-skip-names', 'thumbs.db'))
        self.assertIn('--hash-skip-path-re', run('--folder', 'A', '--hash-ext', '.jpg', '--hash-skip-path-re', '('))
        self.assertEqual(portable.APP_VERSION, '1.6.1')
        ns = Namespace(hash_ext='JPG, .Mp4', hash_skip_ext=None, hash_skip_names='~$*', hash_skip_path_re='')
        self.assertEqual(portable.hash_types_of(ns), {'mode': 'only', 'ext': ['.jpg', '.mp4'], 'junk_names': ['~$*'],
                                                       'junk_path_re': ''})
        self.assertEqual(portable.hash_types_of(Namespace(hash_all_types=True)), 'all')     # старый вызов


if __name__ == '__main__':
    unittest.main()
