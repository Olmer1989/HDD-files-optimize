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


if __name__ == '__main__':
    unittest.main()
