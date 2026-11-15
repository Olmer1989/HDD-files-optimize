"""Хеш у всех файлов: сравнение по хешу для всех классов, «сравнение только по имени и размеру» при хеше с одной
стороны, «возможно, переименована», candel для папок с документами, «когда измерены хеши», .m2t как видео, скорость.
Временные данные (15.11.2026, «Проверка Архитектуры сортировки файлов\\Хеш_всех_файлов_v1.md»).

Запуск из корня проекта:  py -m unittest catalog.test_hash_all
"""
import json
import sqlite3
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hashbase as hb         # noqa: E402
import service as sv          # noqa: E402
from test_hashbase import Base, NS, S, make_partial      # noqa: E402

MB = 1048576


def make_disk_mt(scans, disk, serial, hashed, unhashed=()):
    """Опись носителя с датами изменения: hashed (путь, размер, sha, mtime_s), unhashed (путь, размер, mtime_s)."""
    job = scans / f'{disk} - тест' / f'{disk}_job'
    job.mkdir(parents=True)
    (job / 'result.json').write_text(json.dumps({'disk_id': disk, 'status': 'complete'}), encoding='utf-8')
    (job / 'job.json').write_text(json.dumps({'record': {'volume_serial': serial}}), encoding='utf-8')
    with sqlite3.connect(job / 'hashes.sqlite') as h:
        h.execute('create table hashes(disk_id text,path text,size integer,mtime_ns text,file_id text,sha256 text,'
                  'status text,error text,primary key(disk_id,path))')
        h.executemany('insert into hashes values (?,?,?,?,?,?,?,?)',
                      [(disk, p, size, str(mt * 10**9), '', sha, 'verified', '') for p, size, sha, mt in hashed])
    with sqlite3.connect(job / 'inventory.sqlite') as i:
        i.execute('create table files(path text primary key,size integer,mtime_ns text,ctime_ns text,file_id text,'
                  'attributes integer,category text)')
        i.execute('create table errors(path text,operation text,message text)')
        i.executemany('insert into files values (?,?,?,?,?,?,?)',
                      [(p, size, str(mt * 10**9), '0', '', 32, 'x') for p, size, _, mt in hashed]
                      + [(p, size, str(mt * 10**9), '0', '', 32, 'x') for p, size, mt in unhashed])
    return job


class HashAllTest(Base):
    def setUp(self):
        super().setUp()
        # HDD93 - источник: документы с хешем (пересканирование «все файлы») и без; на 45 и 77 - копии без хеша (N)
        make_disk_mt(self.scans, 'HDD93', 'AAAA0093', [], unhashed=[
            ('Док\\отчёт.docx', 1000, 1), ('Док\\смета.xlsx', 2000, 1), ('Док\\видео.m2t', 3 * MB, 5)])
        time.sleep(0.05)
        make_disk_mt(self.scans, 'HDD94', 'AAAA0094', [], unhashed=[('Копия\\отчёт.docx', 1000, 1),
                                                                   ('Копия\\другое имя.m2t', 3 * MB, 5)])
        hb.ensure_tables()

    def scan_source(self, files):
        time.sleep(0.05)
        return make_partial(self.scans, 'HDD93', 'AAAA0093', ['Док'], files, name='все')

    def test_mixed_hash_and_no_hash_is_name_only(self):
        # источник с хешем, у копий на 45/77 хеш не считался: не «нет», а «сравнение только по имени и размеру»
        self.scan_source([('Док\\отчёт.docx', 1000, S[7]), ('Док\\смета.xlsx', 2000, S[8])])
        time.sleep(0.05)
        make_partial(self.scans, 'HDD45', 'AAAA0045', ['Д'], [], name='пусто')            # (не влияет)
        # копии без хеша: на 45 и 77 той же описью добавляем файлы N через журнал нельзя - кладём частичный скан без хешей
        for disk, serial in (('HDD45', 'AAAA0045'), ('HDD77', 'AAAA0077')):
            job = make_partial(self.scans, disk, serial, ['Д2'], [('Д2\\отчёт.docx', 1000, S[7]),
                                                                ('Д2\\смета.xlsx', 2000, S[8])], name='n' + disk)
            with sqlite3.connect(job / 'hashes.sqlite') as h:          # хеш не прочитан - строка N
                h.execute("update hashes set status='error', sha256=null")
        self.assertEqual(self.row('HDD45', 'Д2\\отчёт.docx')[:2], (None, 'N'))
        self.assertEqual(self.row('HDD93', 'Док\\отчёт.docx')[:2], (S[7], 'S'))
        c = self.db()
        cand = hb.candidates(c, 'HDD93', ['Док\\отчёт.docx', 'Док\\смета.xlsx'], targets=hb.MAIN)
        self.assertEqual(set(cand['Док\\отчёт.docx']), {'HDD45', 'HDD77'})
        out = self.candel('HDD93', 'Док')
        self.assertIn('НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', out)                    # не «НЕТ»: как у того же файла без хеша
        self.assertIn('только вероятная копия', out)
        self.quiet(hb.cmd_missing, NS(disk='HDD93', folder='', depth=1))
        self.assertIn('лежит файл с тем же именем и размером без хеша', self.printed)
        self.assertIn('ИТОГО', self.printed)

    def test_other_hash_is_not_a_candidate(self):
        self.scan_source([('Док\\отчёт.docx', 1000, S[7])])
        time.sleep(0.05)
        make_partial(self.scans, 'HDD45', 'AAAA0045', ['Д2'], [('Д2\\отчёт.docx', 1000, S[9])], name='другой')
        c = self.db()
        self.assertEqual(hb.candidates(c, 'HDD93', ['Док\\отчёт.docx'], targets=['HDD45']), {})   # другое содержимое
        self.assertIn('ОТВЕТ: НЕТ', self.candel('HDD93', 'Док'))

    def test_documents_can_get_yes(self):
        # у всех файлов папки (и документов) подтверждённые копии по SHA-256 на 45 и 77 - «ДА» возможно
        self.scan_source([('Док\\отчёт.docx', 1000, S[7]), ('Док\\смета.xlsx', 2000, S[8]),
                          ('Док\\видео.m2t', 3 * MB, S[9])])
        time.sleep(0.05)
        for disk, serial in (('HDD45', 'AAAA0045'), ('HDD77', 'AAAA0077')):
            make_partial(self.scans, disk, serial, ['Д'], [('Д\\a.docx', 1000, S[7]), ('Д\\b.xlsx', 2000, S[8]),
                                                         ('Д\\c.m2t', 3 * MB, S[9])], name='d' + disk)
        self.assertIn('ОТВЕТ: ДА', self.candel('HDD93', 'Док'))
        # удаление на самом 45: копия внутри удаляемой папки не считается
        self.assertIn('ОТВЕТ: НЕТ', self.candel('HDD45', 'Д'))

    def test_renamed_hint(self):
        self.db()
        c = self.db()
        hint = hb.renamed(c, 'HDD93', ['Док\\видео.m2t', 'Док\\отчёт.docx'])
        self.assertEqual(hint, {'Док\\видео.m2t': {'HDD94': 'Копия\\другое имя.m2t'}})   # docx < 1 МБ - без подсказки
        self.quiet(hb.cmd_missing, NS(disk='HDD93', folder='', depth=1, cmd='only'), True)
        self.assertIn('возможно, переименована', self.printed)
        out = self.candel('HDD93', 'Док')
        self.assertIn('НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ', out)                    # подсказка вердикт не меняет

    def test_cmp_pairs_hash_with_no_hash(self):
        self.scan_source([('Док\\отчёт.docx', 1000, S[7])])
        self.quiet(hb.cmd_cmp, NS(disk_a='HDD93', folder_a='Док', disk_b='HDD94', folder_b='Копия'))
        self.assertIn('С хешем с одной стороны и без хеша с другой (сравнение только по имени и размеру): совпали 1',
                      self.printed)
        self.assertNotIn('одинаковы по содержимому', self.printed)

    def test_m2t_is_video(self):
        self.assertEqual(hb.class_of('x\\a.m2t', 'a.m2t', 3 * MB), hb.C_BIGMEDIA)
        c = self.db()
        n_video = c.execute("select n1 from folders where disk='HDD93' and folder='Док'").fetchone()[0]
        self.assertEqual(n_video, 1)                                          # столбец «видео», а не «прочие»

    def test_hash_dates(self):
        job = self.scan_source([('Док\\отчёт.docx', 1000, S[7]), ('Док\\смета.xlsx', 2000, S[8])])
        with sqlite3.connect(job / 'hashes.sqlite') as h:
            h.execute('create table hash_info(path text primary key,how text,from_job text,bound_ns integer,'
                      'change_ns integer,reason text)')
            h.execute("insert into hash_info values ('Док\\отчёт.docx','reused','old',?,0,'')",
                      (int(time.mktime((2026, 11, 8, 12, 0, 0, 0, 0, -1)) * 1e9),))
            h.execute("insert into hash_info values ('Док\\смета.xlsx','read','все',?,0,'new')", (time.time_ns(),))
        self.db()
        r = sv.hash_dates('HDD93', 'Док')
        self.assertIn('пересканирование (2 файлов, из них взято из прежнего скана 1 (измерены не раньше 08.11.2026))',
                      r['text'])
        self.assertIn('Перечитать всё', r['hint'])
        r = sv.hash_dates('HDD90', 'A')
        self.assertTrue(r['text'].startswith('Хеши измерены: ') and 'полная опись (3 файлов)' in r['text'], r['text'])
        self.assertIn('Без хеша: 1 файлов', r['text'])                      # заметки.doc

    def test_rebuild_selfcheck(self):
        self.scan_source([('Док\\отчёт.docx', 1000, S[7])])
        self.db()
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)


class RestartTest(Base):
    def test_already_there_after_q_restart_keeps_c(self):
        # копирование остановили клавишей Q и запустили снова: «уже есть» в журнале повторного запуска не понижает C до Z
        from test_hashbase import LOG_HEAD
        dst = 'S:\\ПЕРЕНОС\\HDD90\\A\\2.jpg'
        self.task('T1', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-00-00.tsv',
                  LOG_HEAD, [('1', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', S[2], 'K:\\A\\2.jpg', dst)])
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС\\HDD90\\A\\2.jpg')[:2], (S[2], hb.EV_COPY))
        time.sleep(0.05)
        self.task('T1', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-10-00.tsv',
                  LOG_HEAD, [('1', 'HDD77', 'уже есть', '200', '', 'K:\\A\\2.jpg', dst),
                             ('2', 'HDD77', 'уже есть', '500', '', 'K:\\B\\5.jpg', 'S:\\ПЕРЕНОС\\HDD90\\B\\5.jpg')])
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС\\HDD90\\A\\2.jpg')[:2], (S[2], hb.EV_COPY))   # осталось C
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС\\HDD90\\B\\5.jpg')[1], hb.EV_SIZE)            # нового - Z, как было
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)
        self.assertEqual(self.row('HDD77', 'ПЕРЕНОС\\HDD90\\A\\2.jpg')[:2], (S[2], hb.EV_COPY))


class SpeedTest(Base):
    def test_many_namesakes_are_fast(self):
        # диск с тысячами одинаковых служебных файлов (кэш монтажа): прежний подзапрос на каждый файл - квадрат
        n = 6000
        make_disk_mt(self.scans, 'HDD95', 'AAAA0095', [('V\\big.mov', 2 * MB, S[9], 7)],
                     unhashed=[(f'Cache\\{i}\\info.xml', 100, 1) for i in range(n)])
        time.sleep(0.05)
        make_disk_mt(self.scans, 'HDD96', 'AAAA0096', [], unhashed=[(f'C\\{i}\\info.xml', 100, 1) for i in range(n)]
                     + [('V\\big renamed.mov', 2 * MB, 7)])
        c = self.db()
        t = time.time()
        rows = hb.unhashed(c, 'HDD95', '')
        self.assertEqual(len(rows), n)
        self.assertEqual({r[4:] for r in rows}, {(1, True)})                  # есть на 1 другом диске; тёзки тут же
        self.assertEqual(hb.renamed(c, 'HDD95', ['V\\big.mov']), {'V\\big.mov': {'HDD96': 'V\\big renamed.mov'}})
        self.quiet(hb.cmd_where, NS(disk='HDD95', path='Cache'))
        self.assertIn('HDD96', self.printed)
        self.assertLess(time.time() - t, 10)


if __name__ == '__main__':
    unittest.main()
