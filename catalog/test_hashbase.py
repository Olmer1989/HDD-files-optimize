"""Автотест общей базы хешей на временных данных. Архивные диски и настоящие описи не используются.

Запуск из корня проекта:  py -m unittest catalog\\test_hashbase.py

Вторая половина набора (ReviewFixes) - ситуации, которые воспроизвёл независимый критик 13.11.2026:
каждая проверка проходит, только если ошибка исправлена.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_pilot as bp      # noqa: E402
import hashbase as hb         # noqa: E402

S = {i: f'{i:064x}' for i in range(1, 10)}      # условные SHA-256
NS = argparse.Namespace
LOG_HEAD = ('время', 'цель', 'результат', 'размер', 'SHA-256 прочитанного', 'источник', 'куда')
OLD_HEAD = ('время', 'цель', 'результат', 'размер', 'источник', 'куда')


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
    i.execute('create table errors(path text,operation text,message text)')
    i.executemany('insert into files values (?,?,?,?,?,?,?)',
                  [(p, size, '0', '0', '', 32, 'media_small') for p, size, _ in hashed]
                  + [(p, size, '0', '0', '', 32, 'other') for p, size in unhashed])
    i.commit(); i.close()


def make_partial(scans, disk, serial, folders, files, sub='Повторное сканирование', name='part', status='complete'):
    """Частичный скан папок (сканер 1.3.2-partial): хеши у всех файлов этих папок. files: (путь, размер, sha)."""
    job = scans / sub / f'{disk} - тест' / f'{disk}_{name}' if sub else scans / f'{disk} - тест' / f'{disk}_{name}'
    job.mkdir(parents=True)
    (job / 'result.json').write_text(json.dumps({
        'disk_id': disk, 'scan_scope': 'partial', 'folders': folders, 'hash_scope': 'all_regular_files',
        'status': status, 'damaged_files': 0, 'unread_files': 0, 'app_version': '1.3.2-partial-four-folders'},
        ensure_ascii=False), encoding='utf-8')
    (job / 'job.json').write_text(json.dumps({'record': {'volume_serial': serial}}), encoding='utf-8')
    h = sqlite3.connect(job / 'hashes.sqlite')
    h.execute('create table hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,'
              'status text,error text,primary key(disk_id,path))')
    h.executemany('insert into hashes values (?,?,?,?,?,?,?,?)',
                  [(disk, p, size, '0', '', sha, 'verified', '') for p, size, sha in files])
    h.commit(); h.close()
    i = sqlite3.connect(job / 'inventory.sqlite')
    i.execute('create table files(path text primary key,size integer,mtime_ns text,ctime_ns text,file_id text,'
              'attributes integer,category text)')
    i.execute('create table errors(path text,operation text,message text)')
    i.executemany('insert into files values (?,?,?,?,?,?,?)', [(p, size, '0', '0', '', 32, 'other') for p, size, _ in files])
    i.commit(); i.close()
    return job


class Base(unittest.TestCase):
    """Общая обвязка без собственных проверок."""

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
        if hb._last is not None:
            hb._last.close(); hb._last = None
        bp.SCAN_ROOTS, bp.OUT_DIR = self.saved
        hb.set_root(bp.OUT_DIR)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- помощники ---
    def quiet(self, fn, *a):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = fn(*a)
        self.printed = buf.getvalue()
        return res

    def db(self):
        return self.quiet(hb.connect)[0]

    def state(self, disk='HDD90', prefix=''):
        """путь -> (подтверждённая копия на 45, на 77, дисков всего, слабая на 45, слабая на 77)."""
        return {p: (bool(a), bool(b), n, bool(w1), bool(w2))
                for p, size, sha, a, b, n, w1, w2 in hb.presence(self.db(), disk, prefix, weak=True)}

    def row(self, disk, path):
        return self.db().execute('select sha, ev, sha_exp, size from files where disk=? and path=?', (disk, path)).fetchone()

    def candel(self, disk, folder):
        self.quiet(hb.cmd_candel, NS(disk=disk, folder=folder))
        return self.printed

    def job(self, disk):
        return next((self.scans / f'{disk} - тест').iterdir())

    def task(self, name, toma, log_name, head, rows):
        t = self.out / name
        t.mkdir(exist_ok=True)
        (t / 'тома.tsv').write_text('\n'.join('\t'.join(x) for x in toma) + '\n', encoding='utf-8')
        (t / log_name).write_text('\n'.join('\t'.join(x) for x in [head] + rows) + '\n', encoding='utf-8-sig')

    def manual(self, *lines):
        hb.ensure_tables()
        time.sleep(0.02)
        hb.MANUAL.write_text(hb.MANUAL_HEAD + '\n' + ''.join(x + '\n' for x in lines), encoding='utf-8-sig')

    def decide(self, *lines):
        hb.ensure_tables()
        time.sleep(0.02)
        hb.DECISIONS.write_text(hb.DECISION_HEAD + '\n' + ''.join(x + '\n' for x in lines), encoding='utf-8-sig')


class HashBaseTest(Base):
    def test_scans_only(self):
        st = self.state()
        self.assertEqual(st['A\\1.jpg'][:3], (True, True, 3))
        self.assertEqual(st['A\\2.jpg'][:3], (True, False, 2))
        self.assertEqual(st['A\\sub\\3.mp4'][:3], (False, False, 1))
        self.assertEqual(st['B\\4.jpg'][:3], (False, False, 2))       # есть на HDD91, но не на 45/77
        self.assertEqual(st['B\\5.jpg'][:3], (False, False, 1))
        self.assertEqual(set(self.state(prefix='A')), {'A\\1.jpg', 'A\\2.jpg', 'A\\sub\\3.mp4'})
        self.assertEqual(self.state('HDD45')['X\\1.jpg'][:2], (True, True))
        self.assertEqual(self.row('HDD90', 'A\\1.jpg')[1], hb.EV_SCAN)
        self.assertEqual(self.row('HDD90', 'A\\заметки.doc')[:2], (None, hb.EV_NONE))

    def test_copy_with_measured_hash_counts_and_custom_target(self):
        # цель «HDD45» по тома.tsv указывает на серийный номер HDD91 - файл числится на HDD91, не на HDD45
        self.task('T1', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077'), ('HDD45', 'AAAA0091', 'на диск 45')],
                  'Журнал копирования 2099-01-01 00-00-00.tsv', LOG_HEAD,
                  [('00:00:01', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', S[2].upper(), 'K:\\A\\2.jpg',
                    'S:\\ПЕРЕНОС с других дисков\\HDD90\\A\\2.jpg'),
                   ('00:00:02', 'HDD45', 'скопирован, размер и SHA-256 совпали', '300', S[3].upper(), 'K:\\A\\sub\\3.mp4',
                    'F:\\на диск 45\\HDD90\\A\\sub\\3.mp4'),
                   ('00:00:03', 'HDD77', 'ОШИБКА: что-то', '500', '', 'K:\\B\\5.jpg', 'S:\\x\\B\\5.jpg'),
                   ('00:00:04', 'HDD77', 'нет источника', '400', '', 'K:\\B\\4.jpg', 'S:\\x\\B\\4.jpg')])
        st = self.state()
        self.assertEqual(st['A\\2.jpg'][:2], (True, True))
        self.assertEqual(st['A\\sub\\3.mp4'][:3], (False, False, 2))  # лежит на HDD91 (временное место), на 45 его нет
        self.assertEqual(st['B\\5.jpg'][:3], (False, False, 1))       # ошибка - не учитывается
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС с других дисков\\HDD90\\A\\2.jpg')[:2], (S[2], hb.EV_COPY))

    def test_manual_operations_and_rebuild_on_change(self):
        self.assertEqual(self.state()['B\\4.jpg'][:2], (False, False))
        self.manual('01.01.2099\tудалено\tHDD90\tB\\5.jpg\t\t\tв корзину',
                    '01.01.2099\tскопировано\tHDD90\tB\tHDD45\tКОПИЯ B\tпроводником',
                    '02.01.2099\tперемещено\tHDD90\tA\\1.jpg\tHDD90\tC\\1.jpg\tпроводником')
        st = self.state()                      # база должна пересобраться сама
        self.assertIn('пересобираю', self.printed)
        self.assertNotIn('B\\5.jpg', st)
        # копия «со слов пользователя» копией не считается, но видна как неподтверждённая
        self.assertEqual(st['B\\4.jpg'], (False, False, 2, True, False))
        self.assertEqual(self.row('HDD45', 'КОПИЯ B\\4.jpg')[:3], (None, hb.EV_USER, S[4]))
        # перемещение внутри диска - тот же файл, его хеш остаётся подтверждённым
        self.assertNotIn('A\\1.jpg', st)
        self.assertEqual(st['C\\1.jpg'][:2], (True, True))
        self.state()
        self.assertNotIn('пересобираю', self.printed)       # без изменений база не пересобирается

    def test_commands_and_decisions(self):
        self.decide('HDD90\tA\\sub\tне нужно\tпроба')
        self.quiet(hb.cmd_missing, NS(disk='HDD90', folder='', depth=1))
        self.assertIn('По решению «не нужно» не показано: 1', self.printed)
        self.assertIn('без SHA-256', self.printed)
        self.assertIn('ОТВЕТ: НЕТ', self.candel('HDD90', 'A\\2.jpg'))          # 2.jpg нет на HDD77
        self.assertIn('ОТВЕТ: ДА', self.candel('HDD90', 'A\\1.jpg'))
        self.quiet(hb.cmd_where, NS(disk='HDD90', path='B'))
        self.assertIn('HDD91', self.printed)
        self.quiet(hb.cmd_mklist, NS(disk='HDD90', to=['HDD45', 'HDD77'], name='Задача', folder=None, dry=False))
        lines = (self.out / 'Задача' / 'список.tsv').read_text(encoding='utf-8').splitlines()
        got = {(x.split('\t')[0], x.split('\t')[1]) for x in lines}
        self.assertEqual(got, {('HDD45', 'B\\4.jpg'), ('HDD45', 'B\\5.jpg'), ('HDD77', 'A\\2.jpg'),
                               ('HDD77', 'B\\4.jpg'), ('HDD77', 'B\\5.jpg')})      # A\sub - «не нужно»
        self.assertTrue(all(len(x.split('\t')) == 5 and len(x.split('\t')[4]) == 64 for x in lines))
        self.assertEqual((self.out / 'Задача' / 'тома.tsv').read_text(encoding='utf-8').split()[0:2], ['HDD90', 'AAAA0090'])
        self.assertTrue((self.out / 'Задача' / 'Запустить.cmd').exists())
        with self.assertRaises(SystemExit):                          # вторую задачу с тем же именем не создаёт
            self.quiet(hb.cmd_mklist, NS(disk='HDD90', to=['HDD45'], name='Задача', folder=None, dry=False))


class ReviewFixes(Base):
    """Двенадцать ситуаций из проверки критика. Номера - как в его отчёте."""

    def test_01_size_only_copy_is_not_a_confirmed_copy(self):
        # старый скрипт: «скопирован, размер совпал», хеша в журнале нет
        self.task('T2', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')],
                  'Журнал копирования 2099-01-02 00-00-00.tsv', OLD_HEAD,
                  [('00:00:01', 'HDD77', 'скопирован, размер совпал', '300', 'J:\\A\\sub\\3.mp4', 'S:\\П\\HDD90\\A\\sub\\3.mp4')])
        self.assertEqual(self.state()['A\\sub\\3.mp4'], (False, False, 1, False, True))
        self.assertEqual(self.row('HDD77', 'П\\HDD90\\A\\sub\\3.mp4')[:3], (None, hb.EV_SIZE, S[3]))

    def test_01_already_there_does_not_inherit_source_hash(self):
        # шаблон увидел в цели файл того же размера («уже есть») и не читал его
        self.task('T4', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')],
                  'Журнал копирования 2099-01-04 00-00-00.tsv', LOG_HEAD,
                  [('00:00:01', 'HDD77', 'уже есть', '200', '', 'K:\\A\\2.jpg', 'S:\\П\\HDD90\\A\\2.jpg')])
        text = self.candel('HDD90', 'A\\2.jpg')
        self.assertIn('ОТВЕТ: НЕТ', text)
        self.assertIn('не подтверждены', text)
        self.assertEqual(self.row('HDD77', 'П\\HDD90\\A\\2.jpg')[:2], (None, hb.EV_SIZE))

    def test_02_unique_database_blocks_yes_until_owner_decides(self):
        with sqlite3.connect(self.job('HDD90') / 'inventory.sqlite') as c:
            c.execute("delete from files where path not in ('A\\1.jpg')")
            c.execute('insert into files values (?,?,?,?,?,?,?)', ('A\\unique.mdb', 1234, '0', '0', '', 32, 'other'))
        with sqlite3.connect(self.job('HDD90') / 'hashes.sqlite') as c:
            c.execute("delete from hashes where path<>'A\\1.jpg'")
        text = self.candel('HDD90', 'A')
        self.assertIn('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', text)
        self.assertNotIn('ОТВЕТ: ДА', text)
        self.assertIn('программы и системное', text)
        # только явное решение владельца снимает вопрос
        self.decide('*\tкласс: программы и системное\tне нужно\tрешил владелец')
        self.assertIn('ОТВЕТ: ДА', self.candel('HDD90', 'A'))

    def test_03_probable_copy_never_gives_yes(self):
        with sqlite3.connect(self.job('HDD91') / 'inventory.sqlite') as c:
            c.execute('insert into files values (?,?,?,?,?,?,?)', ('Z\\заметки.doc', 10, '0', '0', '', 32, 'other'))
        text = self.candel('HDD90', 'A\\заметки.doc')
        self.assertIn('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', text)
        self.assertNotIn('ОТВЕТ: ДА', text)

    def test_04_incomplete_inventory_blocks_yes(self):
        with sqlite3.connect(self.job('HDD90') / 'inventory.sqlite') as c:
            c.execute("delete from files where path<>'A\\1.jpg'")
            c.execute('insert into errors values (?,?,?)', ('F:\\A\\unreadable', 'scandir', 'Access denied'))
        with sqlite3.connect(self.job('HDD90') / 'hashes.sqlite') as c:
            c.execute("delete from hashes where path<>'A\\1.jpg'")
        text = self.candel('HDD90', 'A')
        self.assertIn('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', text)
        self.assertIn('опись неполная', text)
        # ошибка в другой папке ответу по одному файлу не мешает
        self.assertIn('ОТВЕТ: ДА', self.candel('HDD90', 'A\\1.jpg'))

    def test_04_unfinished_scan_blocks_yes(self):
        (self.job('HDD90') / 'result.json').write_text(json.dumps({'disk_id': 'HDD90', 'status': 'running'}), encoding='utf-8')
        text = self.candel('HDD90', 'A\\1.jpg')
        self.assertIn('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', text)
        self.assertIn('не завершена', text)

    def test_05_stale_hash_is_not_applied_to_changed_file(self):
        with sqlite3.connect(self.job('HDD90') / 'inventory.sqlite') as c:
            c.execute("update files set size=999, mtime_ns='2000000000' where path='A\\1.jpg'")
        text = self.candel('HDD90', 'A\\1.jpg')
        self.assertNotIn('ОТВЕТ: ДА', text)
        self.assertEqual(self.row('HDD90', 'A\\1.jpg'), (None, hb.EV_STALE, S[1], 999))

    def test_06_old_log_does_not_resurrect_absent_copy(self):
        with sqlite3.connect(self.job('HDD77') / 'inventory.sqlite') as c:
            c.execute('delete from files')
        with sqlite3.connect(self.job('HDD77') / 'hashes.sqlite') as c:
            c.execute('delete from hashes')
        self.task('OldCopy', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')],
                  'Журнал копирования 2020-01-01 00-00-00.tsv', LOG_HEAD,
                  [('00:00:01', 'HDD77', 'скопирован, размер и SHA-256 совпали', '100', S[1], 'K:\\A\\1.jpg', 'S:\\old\\1.jpg')])
        self.assertIn('ОТВЕТ: НЕТ', self.candel('HDD90', 'A\\1.jpg'))
        self.assertIsNone(self.row('HDD77', 'old\\1.jpg'))
        self.quiet(hb.cmd_stats, NS())
        self.assertIn('опись новее', self.printed)

    def test_07_deleted_instance_is_not_its_own_backup(self):
        with sqlite3.connect(self.job('HDD90') / 'hashes.sqlite') as c:
            c.execute('delete from hashes where sha256=?', (S[1],))
        with sqlite3.connect(self.job('HDD90') / 'inventory.sqlite') as c:
            c.execute("delete from files where path='A\\1.jpg'")
        # после удаления X\1.jpg с HDD45 на HDD45 не останется ничего: «ДА» быть не может
        self.assertIn('ОТВЕТ: НЕТ', self.candel('HDD45', 'X\\1.jpg'))
        # а второй экземпляр на том же HDD45 вне удаляемой папки засчитывается
        with sqlite3.connect(self.job('HDD45') / 'hashes.sqlite') as c:
            c.execute('insert into hashes values (?,?,?,?,?,?,?,?)', ('HDD45', 'W\\1.jpg', 100, '0', '', S[1], 'verified', ''))
        with sqlite3.connect(self.job('HDD45') / 'inventory.sqlite') as c:
            c.execute('insert into files values (?,?,?,?,?,?,?)', ('W\\1.jpg', 100, '0', '0', '', 32, 'media_small'))
        self.assertIn('ОТВЕТ: ДА', self.candel('HDD45', 'X\\1.jpg'))

    def test_10_two_moves_on_the_same_day_leave_no_phantom(self):
        self.manual('13.11.2099\tперемещено\tHDD90\tB\tHDD90\tC\tпервое',
                    '13.11.2099\tперемещено\tHDD90\tC\tHDD90\tD\tвторое')
        paths = {r[0] for r in self.db().execute("select path from files where disk='HDD90'")}
        self.assertIn('D\\5.jpg', paths)
        self.assertNotIn('C\\5.jpg', paths)
        self.assertNotIn('B\\5.jpg', paths)

    def test_11_section_decision_does_not_silently_drop_files(self):
        self.decide('HDD90\tB\tраздел: Архив\tхранить на своём диске')
        self.quiet(hb.cmd_mklist, NS(disk='HDD90', to=['HDD45', 'HDD77'], name='План', folder=['B'], dry=True))
        self.assertNotIn('Копировать нечего', self.printed)
        self.assertIn('ЖДУТ СВОЕГО ДИСКА', self.printed)
        self.assertIn('раздел: Архив', self.printed)
        # список для диска раздела строится явно
        self.quiet(hb.cmd_mklist, NS(disk='HDD90', to=['HDD91'], name='Архив', folder=None, dry=False, section='раздел: Архив'))
        lines = (self.out / 'Архив' / 'список.tsv').read_text(encoding='utf-8').splitlines()
        self.assertEqual({x.split('\t')[1] for x in lines}, {'B\\5.jpg'})      # B\4.jpg на HDD91 уже есть
        # в missing такие файлы видны отдельной таблицей, а не спрятаны
        self.quiet(hb.cmd_missing, NS(disk='HDD90', folder='', depth=1))
        self.assertIn('По решениям пользователя', self.printed)

    def test_12_cmp_verdict_comes_after_both_parts(self):
        self.quiet(hb.cmd_cmp, NS(disk_a='HDD90', folder_a='A\\заметки.doc', disk_b='HDD91', folder_b='missing'))
        self.assertNotIn('одинаковы по содержимому', self.printed)
        self.assertIn('Папки не одинаковы', self.printed)
        self.quiet(hb.cmd_cmp, NS(disk_a='HDD90', folder_a='A\\1.jpg', disk_b='HDD45', folder_b='X\\1.jpg'))
        self.assertIn('одинаковы по содержимому (SHA-256)', self.printed)


class NoHashTest(Base):
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
        return {p: (k, others, bool(dup)) for p, s, nm, k, others, dup in hb.unhashed(self.db(), 'HDD92', prefix)}

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
        self.quiet(hb.cmd_missing, NS(disk='HDD92', folder='', depth=1), True)
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
        text = self.candel('HDD92', 'Док')
        self.assertIn('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', text)
        self.assertNotIn('ОТВЕТ: ДА', text)
        self.assertNotIn('пустые файлы', text)                 # пустой файл терять нечего
        self.quiet(hb.cmd_where, NS(disk='HDD92', path='Док'))
        self.assertIn('HDD93', self.printed)
        self.assertIn('Копия не найдена нигде: 2', self.printed)
        self.quiet(hb.cmd_cmp, NS(disk_a='HDD92', folder_a='Док', disk_b='HDD93', folder_b='Другое'))
        self.assertIn('в обеих 2, только в A 2, только в B 1', self.printed)
        self.assertIn('Папки не одинаковы', self.printed)
        # копирование файла без хеша по журналу: после него вероятная копия «план.doc» есть на HDD77
        time.sleep(0.05)
        self.task('T3', [('HDD92', 'AAAA0092'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-03 00-00-00.tsv',
                  LOG_HEAD, [('00:00:01', 'HDD77', 'скопирован, размер совпал', '1000', '', 'K:\\Док\\план.doc',
                              'S:\\ПЕРЕНОС с других дисков\\HDD92\\Док\\план.doc')])
        self.assertEqual(self.nohash()['Док\\план.doc'][1], 1)
        self.assertIn('пересобираю рабочую базу', self.printed)
        self.assertNotIn('собираю снимок', self.printed)      # снимок описей второй раз не собирается


class PartialGuardTest(Base):
    """Шаг 1 ТЗ v3: частичный скан никогда не считается полной описью носителя."""

    def test_partial_scan_is_never_a_full_inventory(self):
        time.sleep(0.05)
        # рядом с полной описью (тот же уровень, файл новее) и в «Повторное сканирование» (уровнем глубже)
        make_partial(self.scans, 'HDD45', 'AAAA0045', ['W'], [('W\\9.jpg', 100, S[9])], sub=None, name='p1')
        make_partial(self.scans, 'HDD45', 'AAAA0045', ['W'], [('W\\9.jpg', 100, S[9])], name='p2')
        jobs = bp.find_jobs()
        self.assertEqual(jobs['HDD45']['dir'].name, 'HDD45_job')
        self.assertEqual(set(jobs), {'HDD90', 'HDD45', 'HDD77', 'HDD91'})
        # в базе HDD45 по-прежнему весь: файлы вне папки частичного скана не пропали, сам скан добавил свою папку
        self.assertIsNotNone(self.row('HDD45', 'X\\2.jpg'))
        self.assertEqual(self.row('HDD45', 'W\\9.jpg')[:2], (S[9], hb.EV_SCAN))


T2099_06 = time.mktime((2099, 6, 1, 0, 0, 0, 0, 0, -1))


class PartialSetup(Base):
    """Общие данные для шагов 2 и 3: журналы до и после частичного скана HDD77, исключённая папка."""

    def setUp(self):
        super().setUp()
        # журнал ДО скана: «уже есть» (Z), копия с хешем (C), копия во временную папку владельца
        self.task('До скана', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-00-00.tsv',
                  LOG_HEAD, [('1', 'HDD77', 'уже есть', '200', '', 'K:\\A\\2.jpg', 'S:\\П\\HDD90\\A\\2.jpg'),
                             ('2', 'HDD77', 'скопирован, размер и SHA-256 совпали', '300', S[3], 'K:\\A\\sub\\3.mp4',
                              'S:\\П\\HDD90\\A\\sub\\3.mp4'),
                             ('3', 'HDD77', 'скопирован, размер и SHA-256 совпали', '400', S[4], 'K:\\B\\4.jpg',
                              'S:\\П\\temp\\4.jpg')])
        # журнал ПОСЛЕ скана
        self.task('После скана', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2100-01-01 00-00-00.tsv',
                  LOG_HEAD, [('1', 'HDD77', 'скопирован, размер и SHA-256 совпали', '500', S[5], 'K:\\B\\5.jpg',
                              'S:\\П\\HDD90\\B\\5.jpg'),
                             ('2', 'HDD77', 'скопирован, размер и SHA-256 совпали', '100', S[1], 'K:\\A\\1.jpg',
                              'S:\\П\\temp\\1.jpg')])
        job = make_partial(self.scans, 'HDD77', 'AAAA0077', ['П'], [
            ('П\\HDD90\\A\\2.jpg', 200, S[2]), ('П\\HDD90\\new.jpg', 600, S[6]), ('П\\doc.txt', 10, S[7]),
            ('П\\temp\\t.jpg', 700, S[8]), ('П\\temp\\dup.jpg', 100, S[1])])
        os.utime(job / 'inventory.sqlite', (T2099_06, T2099_06))
        hb.ensure_tables()
        hb.EXCLUSIONS.write_text(hb.EXCLUSION_HEAD + '\nHDD77\tП\\temp\tвременная копия владельца\n', encoding='utf-8-sig')

    def paths(self, disk='HDD77'):
        return {r[0]: r[1] for r in self.db().execute('select path, ev from files where disk=?', (disk,))}



class PartialScanTest(PartialSetup):
    """Шаг 2 ТЗ v3: частичный скан папок и исключения."""

    def test_partial_scan_changes_only_its_folders(self):
        got = self.paths()
        self.assertEqual(got['Y\\1.jpg'], hb.EV_SCAN)                      # вне папки скана - не тронуто
        self.assertEqual(got['П\\HDD90\\A\\2.jpg'], hb.EV_SCAN)            # было Z - стало S
        self.assertEqual(got['П\\HDD90\\new.jpg'], hb.EV_SCAN)             # найден впервые
        self.assertEqual(self.row('HDD77', 'П\\doc.txt')[:2], (S[7], hb.EV_SCAN))   # хеш прочих файлов сохраняется
        self.assertNotIn('П\\HDD90\\A\\sub\\3.mp4', got)                   # в скане нет - исчез
        self.assertEqual(len(self.paths('HDD90')), 6)                       # другие носители не тронуты
        rep = json.loads(self.db().execute("select value from meta where key='report'").fetchone()[0])
        line = rep['partial'][0]
        self.assertIn('стало S: Z 1', line)
        self.assertIn('новые 2', line)
        self.assertIn('исчезли из базы 1', line)
        self.assertIn('хеш не совпал 0', line)
        self.assertIn('пропущено по исключениям 2', line)

    def test_old_log_does_not_change_folders_after_newer_partial_scan(self):
        got = self.paths()
        self.assertNotIn('П\\HDD90\\A\\sub\\3.mp4', got)                   # старый журнал не воскрешает
        self.assertEqual(got['П\\HDD90\\B\\5.jpg'], hb.EV_COPY)             # новый журнал действует
        self.quiet(hb.cmd_stats, NS())
        self.assertIn('Частичные сканы папок', self.printed)
        # ручная операция старше скана в его папке не действует, новее - действует
        self.manual('01.03.2099\tскопировано\tHDD90\tB\tHDD77\tП\\вручную\tдо скана',
                    '01.01.2101\tудалено\tHDD77\tП\\doc.txt\t\t\tпосле скана')
        got = self.paths()
        self.assertFalse(any(p.startswith('П\\вручную') for p in got))
        self.assertNotIn('П\\doc.txt', got)

    def test_exclusions(self):
        got = self.paths()
        self.assertFalse(any(p.startswith('П\\temp') for p in got))         # ни из скана, ни из журналов
        # фото и видео из исключённой папки, которых больше нигде нет, - в отдельном списке
        lines = (hb.ANSWERS / 'исключения - больше нигде нет - HDD77.tsv').read_text(encoding='utf-8-sig').splitlines()[1:]
        self.assertEqual([x.split('\t')[0] for x in lines], ['П\\temp\\t.jpg'])
        self.quiet(hb.cmd_stats, NS())
        self.assertIn('нет больше ни на одном носителе', self.printed)
        # без исключения временные файлы попадают в базу
        hb.EXCLUSIONS.write_text(hb.EXCLUSION_HEAD + '\n', encoding='utf-8-sig')
        self.assertIn('П\\temp\\t.jpg', self.paths())

    def test_partial_scan_older_than_full_inventory_is_ignored(self):
        job = next((self.scans / 'Повторное сканирование' / 'HDD77 - тест').iterdir())
        os.utime(job / 'inventory.sqlite', (1, 1))
        got = self.paths()
        self.assertNotIn('П\\HDD90\\new.jpg', got)
        self.quiet(hb.cmd_stats, NS())
        self.assertIn('опись новее', self.printed)
        self.assertIn('полная опись носителя новее', (hb.ANSWERS / 'сборка - подробно.txt').read_text(encoding='utf-8-sig'))


T2102 = time.mktime((2102, 1, 1, 0, 0, 0, 0, 0, -1))
T2103 = time.mktime((2103, 1, 1, 0, 0, 0, 0, 0, -1))


class IncrementalTest(PartialSetup):
    """Шаг 3 ТЗ v3: сборщик применяет только новые модули; rebuild даёт ту же базу."""

    def rebuild_matches(self):
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed, self.printed)

    def append_log(self, task, name, *rows):
        with open(self.out / task / name, 'a', encoding='utf-8') as f:
            for r in rows:
                f.write('\t'.join(r) + '\n')

    def test_steps_equal_full_rebuild(self):
        self.db()                                                    # первая сборка - целиком
        self.assertIn('целиком', self.printed)
        # 1) новый журнал
        self.task('Ещё', [('HDD90', 'AAAA0090'), ('HDD45', 'AAAA0045')], 'Журнал копирования 2100-02-01 00-00-00.tsv',
                  LOG_HEAD, [('1', 'HDD45', 'скопирован, размер и SHA-256 совпали', '300', S[3], 'K:\\A\\sub\\3.mp4',
                              'G:\\П\\HDD90\\A\\sub\\3.mp4')])
        self.assertEqual(self.row('HDD45', 'П\\HDD90\\A\\sub\\3.mp4')[:2], (S[3], hb.EV_COPY))
        self.assertIn('частично', self.printed)
        self.assertNotIn('целиком', self.printed)
        # 2) журнал дописан, последняя строка ещё не закончена - она не учитывается
        self.append_log('Ещё', 'Журнал копирования 2100-02-01 00-00-00.tsv',
                        ('2', 'HDD45', 'скопирован, размер и SHA-256 совпали', '400', S[4], 'K:\\B\\4.jpg', 'G:\\П\\HDD90\\B\\4.jpg'))
        with open(self.out / 'Ещё' / 'Журнал копирования 2100-02-01 00-00-00.tsv', 'a', encoding='utf-8') as f:
            f.write('3\tHDD45\tскопирован, размер и SHA-256 совпали\t500\t' + S[5])          # без конца строки
        self.assertEqual(self.row('HDD45', 'П\\HDD90\\B\\4.jpg')[:2], (S[4], hb.EV_COPY))
        self.assertNotIn('целиком', self.printed)
        with open(self.out / 'Ещё' / 'Журнал копирования 2100-02-01 00-00-00.tsv', 'a', encoding='utf-8') as f:
            f.write('\tK:\\B\\5.jpg\tG:\\П\\HDD90\\B\\5.jpg\n')                                   # строка дописана
        self.assertEqual(self.row('HDD45', 'П\\HDD90\\B\\5.jpg')[:2], (S[5], hb.EV_COPY))
        # 3) новая ручная операция и новое исключение
        self.manual('01.01.2101\tперемещено\tHDD90\tB\tHDD90\tB2\tпосле скана')
        self.assertIn('B2\\5.jpg', self.paths('HDD90'))
        with open(hb.EXCLUSIONS, 'a', encoding='utf-8') as f:
            f.write('HDD45\tП\\HDD90\\B\tпроба\n')
        self.assertNotIn('П\\HDD90\\B\\4.jpg', self.paths('HDD45'))
        # 4) новый частичный скан и новая полная опись носителя
        job = make_partial(self.scans, 'HDD45', 'AAAA0045', ['X'], [('X\\1.jpg', 100, S[1]), ('X\\7.jpg', 700, S[7])], name='p45')
        os.utime(job / 'inventory.sqlite', (T2102, T2102))
        self.assertEqual(set(p for p in self.paths('HDD45') if p.startswith('X')), {'X\\1.jpg', 'X\\7.jpg'})
        self.assertNotIn('целиком', self.printed)
        with sqlite3.connect(self.job('HDD91') / 'inventory.sqlite') as c:
            c.execute('insert into files values (?,?,?,?,?,?,?)', ('Z\\new.doc', 5, '0', '0', '', 32, 'other'))
        c.close()
        os.utime(self.job('HDD91') / 'inventory.sqlite', (T2103, T2103))
        self.assertIn('Z\\new.doc', self.paths('HDD91'))
        self.assertNotIn('целиком', self.printed)
        kinds = {r[0] for r in self.db().execute('select kind from applied')}
        self.assertEqual(kinds, {'опись', 'журнал', 'частичный скан', 'ручная операция', 'исключение'})
        self.rebuild_matches()

    def test_changed_module_forces_full_rebuild(self):
        self.db()
        p = self.out / 'После скана' / 'Журнал копирования 2100-01-01 00-00-00.tsv'
        p.write_text(p.read_text(encoding='utf-8-sig').replace('скопирован, размер и SHA-256 совпали', 'ОШИБКА', 1),
                     encoding='utf-8-sig')
        got = self.paths()
        self.assertIn('изменился уже учтённый журнал', self.printed)
        self.assertIn('целиком', self.printed)
        self.assertNotIn('П\\HDD90\\B\\5.jpg', got)                 # исправленная строка больше не действует
        self.rebuild_matches()


LEGACY_PRESENCE = '''select f.path, exists(select 1 from files g where g.sha=f.sha and g.disk='HDD45'),
       exists(select 1 from files g where g.sha=f.sha and g.disk='HDD77'),
       (select count(distinct g.disk) from files g where g.sha=f.sha),
       exists(select 1 from files g where g.sha_exp=f.sha and g.disk='HDD45'),
       exists(select 1 from files g where g.sha_exp=f.sha and g.disk='HDD77')
       from files f where f.disk=? and f.sha is not null'''


class DerivedTablesTest(PartialSetup):
    """Шаг 4 ТЗ v3: готовые таблицы presence и folders, команды на них."""

    def check_presence(self):
        c = self.db()
        for disk in ('HDD90', 'HDD45', 'HDD77', 'HDD91'):
            old = {p: (bool(a), bool(b), n, bool(w1) and not a, bool(w2) and not b)
                   for p, a, b, n, w1, w2 in c.execute(LEGACY_PRESENCE, (disk,))}
            new = {p: (bool(a), bool(b), n, bool(w1), bool(w2))
                   for p, size, sha, a, b, n, w1, w2 in hb.presence(c, disk, '', weak=True)}
            self.assertEqual(old, new, disk)

    def folder(self, disk, folder):
        return self.db().execute('select files, bytes, n0, n1, n2, n3, n4 from folders where disk=? and folder=?',
                                 (disk, folder)).fetchone()

    def test_presence_table_matches_direct_query(self):
        self.check_presence()
        self.manual('01.01.2101\tскопировано\tHDD90\tB\tHDD45\tКОПИЯ\tсо слов',
                    '01.01.2101\tудалено\tHDD77\tY\t\t\tпроба')
        self.check_presence()                                           # после сборки по шагам - тоже

    def test_folder_sums_and_search(self):
        self.assertEqual(self.folder('HDD90', ''), (6, 1510, 4, 1, 1, 0, 0))
        self.assertEqual(self.folder('HDD90', 'A'), (4, 610, 2, 1, 1, 0, 0))     # вместе с подпапкой sub
        self.assertEqual(self.folder('HDD90', 'A\\sub'), (1, 300, 0, 1, 0, 0, 0))
        self.manual('01.01.2101\tперемещено\tHDD90\tB\tHDD90\tНовая B\tпроба')
        self.assertIsNone(self.folder('HDD90', 'B'))
        self.assertEqual(self.folder('HDD90', 'Новая B'), (2, 900, 2, 0, 0, 0, 0))
        self.assertEqual(self.folder('HDD90', '')[:2], (6, 1510))
        self.quiet(hb.cmd_find, NS(words=['нОвая'], disk=None))
        self.assertIn('Новая B', self.printed)
        self.assertIn('Папки со словами', self.printed)
        self.quiet(hb.cmd_folders, NS(disk='HDD90', folder='A', depth=1))
        self.assertIn('sub', self.printed)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)


class ShortAnswerTest(PartialSetup):
    """Шаг 5 ТЗ v3: ни одна команда не выводит на экран больше 20 строк."""

    def run_main(self, *argv):
        buf = io.StringIO()
        saved = sys.argv
        sys.argv = ['hashbase.py', *argv]
        try:
            with contextlib.redirect_stdout(buf):
                hb.main()
        finally:
            sys.argv = saved
            hb.close_last()
        return buf.getvalue().splitlines()

    def test_long_answer_is_cut_to_20_lines(self):
        buf = io.StringIO()
        path = self.tmp / 'ответ.txt'
        ans = hb.ShortAnswer(buf, path)
        for i in range(50):
            ans.write(f'строка {i}\n')
        ans.close_answer()
        shown = buf.getvalue().splitlines()
        self.assertEqual(len(shown), 20)
        self.assertEqual(shown[-1], 'строка 49')                     # итог в конце ответа виден
        self.assertIn('полный ответ', shown[13])
        self.assertEqual(len(path.read_text(encoding='utf-8-sig').splitlines()), 50)

    def test_every_command_fits_20_lines(self):
        for i in range(40):                                           # много папок и решений - длинные таблицы
            make_partial(self.scans, 'HDD90', 'AAAA0090', [f'Много{i}'], [(f'Много{i}\\f.jpg', 1000 + i, f'{100 + i:064x}')],
                         name=f'm{i}')
        hb.ensure_tables()
        self.decide(*[f'HDD90\tМного{i}\tраздел: Р{i}\tпроба' for i in range(0, 40, 2)])
        for argv in (['build'], ['stats'], ['missing', 'HDD90'], ['only', 'HDD90'], ['where', 'HDD90', 'A'],
                     ['cmp', 'HDD90', 'A', 'HDD45', 'X'], ['candel', 'HDD90', 'A'], ['folders', 'HDD90'],
                     ['find', 'много'], ['mklist', 'HDD90', '--name', 'Длинная', '--dry'], ['rebuild']):
            lines = self.run_main(*argv)
            self.assertLessEqual(len(lines), 20, f'{argv}: {len(lines)} строк\n' + '\n'.join(lines))
            self.assertTrue(lines, argv)


class MoveOnSourceTest(Base):
    """Шаблон «Переместить на источнике» и учёт его журнала (логика v2, раздел 5)."""

    def setUp(self):
        super().setUp()
        for job in self.scans.glob('*/*'):                     # описи - 2020 год, журналы копирования - 2025
            for fn in ('inventory.sqlite', 'hashes.sqlite'):
                os.utime(job / fn, (1580000000, 1580000000))
        tpl = self.out / '_ШАБЛОН перемещения'
        tpl.mkdir()
        real = Path(__file__).resolve().parents[1] / 'Каталог дисков' / '_ШАБЛОН перемещения'
        for name in ('Переместить.ps1', 'Запустить.cmd'):
            shutil.copy2(real / name, tpl / name)
        ok = 'скопирован, размер и SHA-256 совпали'
        self.task('Копия HDD90', [('HDD90', 'AAAA0090'), ('HDD45', 'AAAA0045'), ('HDD77', 'AAAA0077')],
                  'Журнал копирования 2025-01-01 00-00-00.tsv', LOG_HEAD,
                  [('1', 'HDD77', ok, '200', S[2], 'K:\\A\\2.jpg', 'S:\\П\\HDD90\\A\\2.jpg'),
                   ('2', 'HDD45', ok, '300', S[3], 'K:\\A\\sub\\3.mp4', 'G:\\П\\HDD90\\A\\sub\\3.mp4'),
                   ('3', 'HDD77', ok, '300', S[3], 'K:\\A\\sub\\3.mp4', 'S:\\П\\HDD90\\A\\sub\\3.mp4'),
                   ('4', 'HDD45', ok, '400', S[4], 'K:\\B\\4.jpg', 'G:\\П\\HDD90\\B\\4.jpg'),
                   ('5', 'HDD77', 'уже есть', '400', '', 'K:\\B\\4.jpg', 'S:\\П\\HDD90\\B\\4.jpg')])

    def run_move(self, task, root):
        proc = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(task / 'Переместить.ps1'), '-TestRoots', f'HDD90={root}'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode('utf-8', errors='replace'))

    def test_move_after_confirmed_copy(self):
        self.quiet(hb.cmd_mvlist, NS(disk='HDD90', name='Переложить HDD90', folder=None, dry=False))
        self.assertIn('Ждут: копия ещё не подтверждена - 1 файлов', self.printed)       # B\4.jpg: на 77 только «уже есть»
        self.assertIn('Остаются на месте (на 45 и 77 уже были): 1 файлов', self.printed)  # A\1.jpg
        task = self.out / 'Переложить HDD90'
        rows = [x.split('\t') for x in (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertEqual({(r[0], r[3]) for r in rows}, {('A\\2.jpg', 'ПЕРЕНЕСЕНО → только 77'),
                                                        ('A\\sub\\3.mp4', 'ПЕРЕНЕСЕНО → 45 и 77')})
        # настоящий шаблон на временной папке вместо диска
        disk = self.tmp / 'диск HDD90'
        for rel, size in (('A\\2.jpg', 200), ('A\\sub\\3.mp4', 300), ('A\\1.jpg', 100)):
            p = disk / rel.replace('\\', '/')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * size)
            os.utime(p, (0, 0))
        self.run_move(task, disk)
        self.assertTrue((disk / 'ПЕРЕНЕСЕНО → только 77' / 'A' / '2.jpg').exists())
        self.assertTrue((disk / 'ПЕРЕНЕСЕНО → 45 и 77' / 'A' / 'sub' / '3.mp4').exists())
        self.assertFalse((disk / 'A' / '2.jpg').exists())
        self.assertTrue((disk / 'A' / '1.jpg').exists())                                 # не в списке - на месте
        self.run_move(task, disk)                                                        # повтор: «уже перемещён»
        # база приняла журнал: новый путь, тот же хеш и степень; решение по старому пути действует
        paths = {r[0]: r[1] for r in self.db().execute("select path, ev from files where disk='HDD90'")}
        self.assertEqual(paths.get('ПЕРЕНЕСЕНО → только 77\\A\\2.jpg'), hb.EV_SCAN)
        self.assertNotIn('A\\2.jpg', paths)
        self.decide('HDD90\tA\tраздел: Проба\tрешение по исходному пути')
        self.assertEqual(hb.decision_of('ПЕРЕНЕСЕНО → только 77\\A\\2.jpg', hb.decisions_for('HDD90')), 'раздел: Проба')
        self.quiet(hb.cmd_mvlist, NS(disk='HDD90', name='Ещё раз', folder=None, dry=True))
        self.assertIn('перемещать нечего', self.printed)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)

    def test_copy_from_folder_of_another_disk(self):
        # исходный носитель уже очищен; его копия лежит на HDD45 в папке X - копируем оттуда под именем HDD90
        self.quiet(hb.cmd_mklist, NS(disk='HDD45', to=['HDD91'], name='Из копии', folder=None, dry=False,
                                     source_folder='X', as_name='HDD90'))
        task = self.out / 'Из копии'
        self.assertEqual((task / 'тома.tsv').read_text(encoding='utf-8').splitlines(), ['HDD90\tAAAA0045\tX', 'HDD91\tAAAA0091'])
        self.assertEqual({x.split('\t')[1] for x in (task / 'список.tsv').read_text(encoding='utf-8').splitlines()},
                         {'1.jpg', '2.jpg'})
        (task / 'Журнал копирования 2025-02-01 00-00-00.tsv').write_text(
            '\t'.join(LOG_HEAD) + '\n1\tHDD91\tскопирован, размер и SHA-256 совпали\t200\t' + S[2] +
            '\tG:\\X\\2.jpg\tZ:\\ПЕРЕНОС с других дисков\\HDD90\\2.jpg\n', encoding='utf-8-sig')
        self.assertEqual(self.row('HDD91', 'ПЕРЕНОС с других дисков\\HDD90\\2.jpg')[:2], (S[2], hb.EV_COPY))

    def test_template_refuses_foreign_destination(self):
        task = self.out / 'Плохой список'
        task.mkdir()
        for name in ('Переместить.ps1', 'Запустить.cmd'):
            shutil.copy2(self.out / '_ШАБЛОН перемещения' / name, task / name)
        (task / 'тома.tsv').write_text('HDD90\tAAAA0090\n', encoding='utf-8')
        (task / 'перемещение.tsv').write_text('A\\1.jpg\t100\t\tДругая папка\t\tпроба\n', encoding='utf-8')
        disk = self.tmp / 'диск'
        (disk / 'A').mkdir(parents=True)
        (disk / 'A' / '1.jpg').write_bytes(b'x' * 100)
        proc = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                               str(task / 'Переместить.ps1'), '-TestRoots', f'HDD90={disk}'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue((disk / 'A' / '1.jpg').exists())                                 # ничего не тронуто


if __name__ == '__main__':
    unittest.main()
