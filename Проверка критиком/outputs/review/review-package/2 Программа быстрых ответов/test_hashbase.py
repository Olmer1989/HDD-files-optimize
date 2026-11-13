"""Автотест общей базы хешей на временных данных. Архивные диски и настоящие описи не используются.

Запуск:  py -m unittest catalog\\test_hashbase.py      (или из папки catalog: py -m unittest test_hashbase)
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot as bp      # noqa: E402
import hashbase as hb         # noqa: E402

S = {i: f'{i:064x}' for i in range(1, 10)}      # условные SHA-256


def make_disk(scans, disk, serial, hashed, unhashed=()):
    job = scans / f'{disk} - тест' / f'{disk}_job'
    job.mkdir(parents=True)
    (job / 'result.json').write_text(json.dumps({'disk_id': disk, 'status': 'complete'}), encoding='utf-8')
    (job / 'job.json').write_text(json.dumps({'record': {'volume_serial': serial}}), encoding='utf-8')
    h = sqlite3.connect(job / 'hashes.sqlite')
    h.execute('create table hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,'
              'status text,error text,primary key(disk_id,path))')
    h.executemany('insert into hashes values (?,?,?,?,?,?,?,?)',
                  [(disk, p, size, '0', '', sha, 'verified', '') for p, size, sha in hashed])
    h.commit(); h.close()
    i = sqlite3.connect(job / 'inventory.sqlite')
    i.execute('create table files(path text primary key,size integer,mtime_ns text,ctime_ns text,file_id text,'
              'attributes integer,category text)')
    i.executemany('insert into files values (?,?,?,?,?,?,?)',
                  [(p, size, '0', '0', '', 32, 'media_small') for p, size, _ in hashed]
                  + [(p, size, '0', '0', '', 32, 'other') for p, size in unhashed])
    i.commit(); i.close()


class HashBaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='hashbase_test_'))
        self.scans, self.out = self.tmp / 'scans', self.tmp / 'Каталог дисков'
        self.scans.mkdir(); self.out.mkdir()
        self.saved = (bp.SCAN_ROOTS, bp.OUT_DIR)
        bp.SCAN_ROOTS, bp.OUT_DIR = [self.scans], self.out
        hb.set_root(self.out)
        make_disk(self.scans, 'HDD90', 'AAAA0090', [
            ('A\\1.jpg', 100, S[1]), ('A\\2.jpg', 200, S[2]), ('A\\sub\\3.mp4', 300, S[3]),
            ('B\\4.jpg', 400, S[4]), ('B\\5.jpg', 500, S[5])], unhashed=[('A\\заметки.doc', 10)])
        make_disk(self.scans, 'HDD45', 'AAAA0045', [('X\\1.jpg', 100, S[1]), ('X\\2.jpg', 200, S[2])])
        make_disk(self.scans, 'HDD77', 'AAAA0077', [('Y\\1.jpg', 100, S[1])])
        make_disk(self.scans, 'HDD91', 'AAAA0091', [('Z\\4.jpg', 400, S[4])])
        tpl = self.out / '_ШАБЛОН копирования'
        tpl.mkdir()
        (tpl / 'Копировать.ps1').write_text('# шаблон', encoding='utf-8')
        (tpl / 'Запустить.cmd').write_text('rem', encoding='utf-8')

    def tearDown(self):
        bp.SCAN_ROOTS, bp.OUT_DIR = self.saved
        hb.set_root(bp.OUT_DIR)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- помощники ---
    def state(self, disk='HDD90', prefix=''):
        c, _ = self.quiet(hb.connect)
        try:
            return {p: (bool(a), bool(b), n) for p, size, sha, a, b, n in hb.presence(c, disk, prefix)}
        finally:
            c.close()

    def quiet(self, fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = fn(*a)
        self.printed = buf.getvalue()
        return res

    def task(self, name, toma, log_name, head, rows):
        t = self.out / name
        t.mkdir(exist_ok=True)
        (t / 'тома.tsv').write_text('\n'.join('\t'.join(x) for x in toma) + '\n', encoding='utf-8')
        (t / log_name).write_text('\n'.join('\t'.join(x) for x in [head] + rows) + '\n', encoding='utf-8-sig')

    # --- тесты ---
    def test_scans_only(self):
        st = self.state()
        self.assertEqual(st['A\\1.jpg'], (True, True, 3))
        self.assertEqual(st['A\\2.jpg'], (True, False, 2))
        self.assertEqual(st['A\\sub\\3.mp4'], (False, False, 1))
        self.assertEqual(st['B\\4.jpg'], (False, False, 2))       # есть на HDD91, но не на 45/77
        self.assertEqual(st['B\\5.jpg'], (False, False, 1))
        self.assertEqual(set(self.state(prefix='A')), {'A\\1.jpg', 'A\\2.jpg', 'A\\sub\\3.mp4'})
        self.assertEqual(self.state('HDD45')['X\\1.jpg'][:2], (True, True))    # диск «есть сам на себе»

    def test_template_log_with_sha_and_custom_target(self):
        # цель «HDD77» по тома.tsv указывает на серийный номер HDD91 - файл должен числиться на HDD91, не на HDD77
        self.task('T1', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077'), ('HDD45', 'AAAA0091', 'на диск 45')],
                  'Журнал копирования 2026-01-01 00-00-00.tsv',
                  ('время', 'цель', 'результат', 'размер', 'SHA-256 прочитанного', 'источник', 'куда'),
                  [('00:00:01', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', S[2].upper(), 'K:\\A\\2.jpg',
                    'S:\\ПЕРЕНОС с других дисков\\HDD90\\A\\2.jpg'),
                   ('00:00:02', 'HDD45', 'скопирован, размер и SHA-256 совпали', '300', S[3].upper(), 'K:\\A\\sub\\3.mp4',
                    'F:\\на диск 45\\HDD90\\A\\sub\\3.mp4'),
                   ('00:00:03', 'HDD77', 'ОШИБКА: что-то', '500', '', 'K:\\B\\5.jpg', 'S:\\x\\B\\5.jpg'),
                   ('00:00:04', 'HDD77', 'нет источника', '400', '', 'K:\\B\\4.jpg', 'S:\\x\\B\\4.jpg')])
        st = self.state()
        self.assertEqual(st['A\\2.jpg'][:2], (True, True))
        self.assertEqual(st['A\\sub\\3.mp4'], (False, False, 2))  # лежит на HDD91 (временное место), на 45 его нет
        self.assertEqual(st['B\\5.jpg'], (False, False, 1))       # ошибка - не учитывается
        self.assertEqual(st['B\\4.jpg'][:2], (False, False))
        self.assertIn('ПЕРЕНОС с других дисков\\HDD90\\A\\2.jpg', self.state('HDD77'))

    def test_old_log_without_sha_takes_hash_from_source(self):
        self.task('T2', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')],
                  'Журнал копирования 2026-01-02 00-00-00.tsv',
                  ('время', 'цель', 'результат', 'размер', 'источник', 'куда'),
                  [('00:00:01', 'HDD77', 'скопирован, размер совпал', '300', 'J:\\A\\sub\\3.mp4',
                    'S:\\ПЕРЕНОС с других дисков\\HDD90\\A\\sub\\3.mp4')])
        self.assertEqual(self.state()['A\\sub\\3.mp4'], (False, True, 2))

    def test_manual_operations_and_rebuild_on_change(self):
        self.assertEqual(self.state()['B\\4.jpg'][:2], (False, False))
        time.sleep(0.05)
        hb.MANUAL.write_text(hb.MANUAL_HEAD + '\n'
                             '01.01.2026\tудалено\tHDD90\tB\\5.jpg\t\t\tв корзину\n'
                             '01.01.2026\tскопировано\tHDD90\tB\tHDD45\tКОПИЯ B\tпроводником\n'
                             '02.01.2026\tперемещено\tHDD90\tA\\1.jpg\tHDD90\tC\\1.jpg\tпроводником\n',
                             encoding='utf-8-sig')
        st = self.state()                      # база должна пересобраться сама
        self.assertIn('пересобираю', self.printed)
        self.assertNotIn('B\\5.jpg', st)
        self.assertEqual(st['B\\4.jpg'][:2], (True, False))
        self.assertNotIn('A\\1.jpg', st)
        self.assertIn('C\\1.jpg', st)
        self.assertIn('КОПИЯ B\\4.jpg', self.state('HDD45'))
        self.state()
        self.assertNotIn('пересобираю', self.printed)       # без изменений база не пересобирается

    def test_commands_and_decisions(self):
        hb.ensure_tables()
        hb.DECISIONS.write_text(hb.DECISION_HEAD + '\nHDD90\tA\\sub\tне нужно\tпроба\n', encoding='utf-8-sig')
        ns = argparse.Namespace
        self.quiet(hb.cmd_missing, ns(disk='HDD90', folder='', depth=1))
        self.assertIn('Не показано по решению «не нужно»', self.printed)
        self.assertIn('без SHA-256', self.printed)
        self.quiet(hb.cmd_candel, ns(disk='HDD90', folder='A'))
        self.assertIn('ОТВЕТ: НЕТ', self.printed)                 # 2.jpg нет на HDD77
        self.quiet(hb.cmd_candel, ns(disk='HDD90', folder='A\\1.jpg'))
        self.assertIn('ОТВЕТ: ДА', self.printed)
        self.quiet(hb.cmd_cmp, ns(disk_a='HDD90', folder_a='A', disk_b='HDD45', folder_b='X'))
        self.assertIn('в A есть всё из B', self.printed)
        self.quiet(hb.cmd_where, ns(disk='HDD90', path='B'))
        self.assertIn('HDD91', self.printed)
        self.quiet(hb.cmd_mklist, ns(disk='HDD90', to=['HDD45', 'HDD77'], name='Задача', folder=None, dry=False))
        lines = (self.out / 'Задача' / 'список.tsv').read_text(encoding='utf-8').splitlines()
        got = {(x.split('\t')[0], x.split('\t')[1]) for x in lines}
        self.assertEqual(got, {('HDD45', 'B\\4.jpg'), ('HDD45', 'B\\5.jpg'), ('HDD77', 'A\\2.jpg'),
                               ('HDD77', 'B\\4.jpg'), ('HDD77', 'B\\5.jpg')})      # A\sub отложено решением
        self.assertTrue(all(len(x.split('\t')) == 5 and len(x.split('\t')[4]) == 64 for x in lines))
        self.assertEqual((self.out / 'Задача' / 'тома.tsv').read_text(encoding='utf-8').split()[0:2], ['HDD90', 'AAAA0090'])
        self.assertTrue((self.out / 'Задача' / 'Запустить.cmd').exists())
        with self.assertRaises(SystemExit):                          # вторую задачу с тем же именем не создаёт
            self.quiet(hb.cmd_mklist, ns(disk='HDD90', to=['HDD45'], name='Задача', folder=None, dry=False))


class NoHashTest(HashBaseTest):
    """Файлы без хеша: сравнение по имени и размеру, классы, уникальные папки."""

    def setUp(self):
        super().setUp()
        make_disk(self.scans, 'HDD92', 'AAAA0092', [('Фото\\a.jpg', 100, S[9])], unhashed=[
            ('Док\\план.doc', 1000), ('Док\\Смета.XLS', 2000), ('Док\\версия.doc', 500), ('Док\\Thumbs.db', 50),
            ('Док\\пусто.txt', 0), ('Док\\setup.exe', 4000),
            ('Уник\\проект.prproj', 300), ('Уник\\вложенная\\readme.txt', 10)])
        make_disk(self.scans, 'HDD93', 'AAAA0093', [], unhashed=[
            ('Другое\\смета.xls', 2000), ('Другое\\версия.doc', 777), ('Другое\\Thumbs.db', 50), ('Другое\\setup.exe', 4000)])

    def nohash(self, prefix=''):
        c, _ = self.quiet(hb.connect)
        try:
            return {p: (k, others, bool(dup)) for p, s, nm, k, others, dup in hb.unhashed(c, 'HDD92', prefix)}
        finally:
            c.close()

    def test_matching_and_classes(self):
        st = self.nohash()
        self.assertEqual(st['Док\\план.doc'], (hb.C_DOC, 0, False))
        self.assertEqual(st['Док\\Смета.XLS'], (hb.C_DOC, 1, False))            # другой регистр имени - то же имя
        self.assertEqual(st['Док\\версия.doc'][1], 0)                            # тёзка другого размера - не копия
        self.assertEqual(st['Док\\Thumbs.db'][0], hb.C_JUNK)
        self.assertEqual(st['Док\\пусто.txt'][0], hb.C_EMPTY)
        self.assertEqual(st['Док\\setup.exe'][:2], (hb.C_PROG, 1))
        self.assertEqual(st['Уник\\проект.prproj'], (hb.C_PROJ, 0, False))
        self.assertNotIn('Фото\\a.jpg', st)                                       # файл с хешем сюда не попадает
        self.assertEqual(set(self.nohash('Уник')), {'Уник\\проект.prproj', 'Уник\\вложенная\\readme.txt'})

    def test_only_report_finds_unique_folder(self):
        ns = argparse.Namespace
        self.quiet(hb.cmd_missing, ns(disk='HDD92', folder='', depth=1), True)
        text = self.printed
        self.assertIn('ОСТАЛЬНЫЕ ФАЙЛЫ', text)
        whole = text.split('НИ У ОДНОГО')[1].split('Папки, где копия не найдена у части')[0]
        self.assertIn('Уник', whole)
        self.assertNotIn('вложенная', whole)          # показана только верхняя уникальная папка
        self.assertNotIn('Док', whole)                # в «Док» у Сметы есть вероятная копия
        self.assertIn('Док', text.split('Папки, где копия не найдена у части')[1])
        self.assertIn('тёзка другого размера', text)
        lines = (hb.ANSWERS / 'только, без хеша - HDD92.tsv').read_text(encoding='utf-8-sig').splitlines()[1:]
        self.assertEqual({x.split('\t')[0] for x in lines},
                         {'Док\\план.doc', 'Док\\версия.doc', 'Уник\\проект.prproj', 'Уник\\вложенная\\readme.txt'})

    def test_candel_where_cmp_and_log_copy(self):
        ns = argparse.Namespace
        self.quiet(hb.cmd_candel, ns(disk='HDD92', folder='Док'))
        self.assertIn('ОТВЕТ: НЕТ', self.printed)
        self.assertIn('НЕ найдена ни на одном другом диске: 2', self.printed)
        self.quiet(hb.cmd_candel, ns(disk='HDD92', folder='Док\\Смета.XLS'))
        self.assertIn('ОТВЕТ: ДА по фото и видео', self.printed)
        self.quiet(hb.cmd_where, ns(disk='HDD92', path='Док'))
        self.assertIn('HDD93', self.printed)
        self.assertIn('Копия не найдена нигде: 2', self.printed)
        self.quiet(hb.cmd_cmp, ns(disk_a='HDD92', folder_a='Док', disk_b='HDD93', folder_b='Другое'))
        self.assertIn('в обеих 2, только в A 2, только в B 1', self.printed)
        # копирование файла без хеша по журналу: после него копия «план.doc» находится на HDD77
        time.sleep(0.05)
        self.task('T3', [('HDD92', 'AAAA0092'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2026-01-03 00-00-00.tsv',
                  ('время', 'цель', 'результат', 'размер', 'SHA-256 прочитанного', 'источник', 'куда'),
                  [('00:00:01', 'HDD77', 'скопирован, размер совпал', '1000', '', 'K:\\Док\\план.doc',
                    'S:\\ПЕРЕНОС с других дисков\\HDD92\\Док\\план.doc')])
        self.assertEqual(self.nohash()['Док\\план.doc'][1], 1)
        self.assertIn('пересобираю рабочую базу', self.printed)
        self.assertNotIn('собираю снимок', self.printed)      # снимок описей второй раз не собирается


if __name__ == '__main__':
    unittest.main()
