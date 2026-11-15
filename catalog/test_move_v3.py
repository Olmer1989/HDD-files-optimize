"""Логика v3, этап 3 (15.11.2026): перенос папки разбора на носителе в «Скопировано на <направление> (<диски>)»
и раздел окна «Задания» (заголовок в столбик, названия дисков, «Можно переместить на носителе», «Готово»).

Запуск из корня проекта:  py -m unittest catalog.test_move_v3
Временные данные; настоящие диски, таблицы и задания не используются. Шаблон перемещения запускается настоящий
(Windows PowerShell 5.1) на временной папке вместо диска. Снимок «Заданий»: переменная MOVE_V3_SHOT=<папка>.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication                  # noqa: E402

import hashbase as hb                                       # noqa: E402
import service as sv                                        # noqa: E402
import tasks_page as tp                                     # noqa: E402
from hb_cmd import mvlist as mv                             # noqa: E402
from test_hashbase import LOG_HEAD, NS, S                   # noqa: E402
from test_logic_v3 import H, SRC, V3Base                    # noqa: E402
from test_tasks_move import FakeWin                         # noqa: E402

QAPP = QApplication.instance() or QApplication([])
OK = 'скопирован, размер и SHA-256 совпали'
OK_NOHASH = 'скопирован, размер совпал'
DOC1, DOC2 = 'd1' * 32, 'd2' * 32                           # хеш прочитанного у документов без хеша в описи
WORK = 'HDD60 — Работа — Работа'
HIKE = 'HDD60 — Поход 2010 — Семейный архив'
WORK_ROOT = 'Скопировано на Работа (91)'
FAMILY_ROOT = 'Скопировано на Семейный архив (45 и 77)'
REAL_TPL = Path(__file__).resolve().parents[1] / 'Каталог дисков' / '_ШАБЛОН перемещения'


def args(**kw):
    a = dict(disk=None, name=None, folder=None, dry=False, task=None, allow_main=False, recheck=None, task_root='scripts',
             razbor=None, razbor_manifest=None, group=None)
    a.update(kw)
    return NS(**a)


def run_ps(task, root, extra=()):
    p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(Path(task) / 'Переместить.ps1'),
                        '-TestRoots', f'{SRC}={root}', *extra], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
    try:                                         # кодировка консоли PowerShell 5.1: OEM (866) или UTF-8 - смотря кто запустил
        return p.returncode, p.stdout.decode('utf-8')
    except UnicodeDecodeError:
        return p.returncode, p.stdout.decode('cp866', errors='replace')


def journal(task):
    rows = []
    for log in sorted(Path(task).glob('Журнал перемещения *.tsv')):
        rows += [x.split('\t') for x in log.read_text(encoding='utf-8-sig').splitlines()[1:] if x.strip()]
    return rows


class MoveBase(V3Base):
    def setUp(self):
        super().setUp()
        for job in self.scans.glob('*/*'):                     # описи - 2020 год, журналы копирования - 2025
            for fn in ('inventory.sqlite', 'hashes.sqlite'):
                os.utime(job / fn, (1580000000, 1580000000))
        tpl = self.out / '_ШАБЛОН перемещения'
        tpl.mkdir()
        for name in ('Переместить.ps1', 'Запустить.cmd'):
            shutil.copy2(REAL_TPL / name, tpl / name)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.disk = self.tmp / 'диск HDD60'

    def copy_log(self, task, stamp, lines):
        """lines: (цель, результат, размер, sha, путь от корня носителя)."""
        rows = [('10:00:0%d' % (i % 10), t, res, str(size), sha, 'K:\\' + p, f'X:\\ПЕРЕНОС с других дисков\\{SRC}\\' + p)
                for i, (t, res, size, sha, p) in enumerate(lines)]
        (hb.TASKS / task / f'Журнал копирования {stamp}.tsv').write_text(
            '\t'.join(LOG_HEAD) + '\n' + ''.join('\t'.join(x) + '\n' for x in rows), encoding='utf-8-sig')
        hb.close_last()

    def files(self, *items):
        """Файлы на «диске» (временная папка): (путь, размер); дата изменения = как в описи (0)."""
        for rel, size in items:
            p = self.disk / rel.replace('\\', '/')
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'x' * size)
            os.utime(p, (0, 0))

    def mv(self, **kw):
        self.quiet(mv.cmd_mvlist, args(**kw))
        return self.printed

    def append_decision(self, line):
        with open(hb.DECISIONS, 'a', encoding='utf-8') as f:
            f.write(line + '\n')

    def work_task(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        sv.razbor_tasks(SRC, dry=False)
        self.copy_log(WORK, '2025-01-01 10-00-00', [('HDD91', OK, 70, H[21], 'Работа\\схема.jpg'),
                                                    ('HDD91', OK_NOHASH, 20, DOC1, 'Работа\\отчёт.doc')])


class NameTest(unittest.TestCase):
    def test_folder_names(self):
        self.assertEqual(hb.copied_folder('Семейный архив', ['HDD77', 'HDD45']), FAMILY_ROOT)
        self.assertEqual(hb.copied_folder('Работа и Сафари', ['HDD78']), 'Скопировано на Работа и Сафари (78)')
        # исходный путь: «Скопировано на …» снимается только для папок из журнала перемещения (moved_roots)
        p = WORK_ROOT + '\\Работа\\a.jpg'
        self.assertEqual(hb.original_path(p), p)
        self.assertEqual(hb.original_path(p, frozenset([WORK_ROOT])), 'Работа\\a.jpg')
        self.assertEqual(hb.original_path('ПЕРЕНЕСЕНО → 78\\A\\1.jpg'), 'A\\1.jpg')            # старые - по имени
        d = hb.Decisions([('Работа', 'раздел: Работа')])
        self.assertIsNone(hb.decision_of(p, d))
        d.roots = frozenset([WORK_ROOT])
        self.assertEqual(hb.decision_of(p, d), 'раздел: Работа')


class WholeFolderTest(MoveBase):
    def test_whole_folder_one_rename_and_base_knows_original_path(self):
        self.work_task()
        text = self.mv(razbor=WORK, dry=True)
        self.assertIn(f'«{WORK_ROOT}»', text)
        self.assertIn('папкой целиком, одним переименованием', text)
        self.assertIn('Можно перенести: 2 файлов', text)
        self.assertFalse((hb.TASKS / (WORK + mv.V3_SUFFIX)).exists())                       # --dry ничего не создаёт
        self.mv(razbor=WORK)
        task = hb.TASKS / (WORK + mv.V3_SUFFIX)
        self.assertEqual((task / 'папки целиком.tsv').read_text(encoding='utf-8').split('\t')[:3], ['Работа', WORK_ROOT, '2'])
        self.assertEqual((task / 'корни.tsv').read_text(encoding='utf-8'), f'{WORK_ROOT}\tновый\n')
        meta = json.loads((task / 'перемещение.json').read_text(encoding='utf-8'))
        self.assertTrue(meta['целиком'])
        self.assertEqual(meta['задание копирования'], WORK)
        rows = [x.split('\t') for x in (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertEqual({r[0]: r[4] for r in rows}, {'Работа\\отчёт.doc': DOC1.upper(), 'Работа\\схема.jpg': H[21].upper()})
        # шаблон на временной папке: одно переименование, подпапки сохраняются (пустая тоже)
        self.files(('Работа\\схема.jpg', 70), ('Работа\\отчёт.doc', 20))
        (self.disk / 'Работа' / 'Пустая').mkdir()
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertIn('перенесена целиком', outp)
        self.assertFalse((self.disk / 'Работа').exists())
        self.assertTrue((self.disk / WORK_ROOT / 'Работа' / 'схема.jpg').exists())
        self.assertTrue((self.disk / WORK_ROOT / 'Работа' / 'Пустая').is_dir())
        intent = (task / 'Намерение перемещения.tsv').read_text(encoding='utf-8')
        self.assertIn('\tпапка\tнамерение\tРабота\t', intent)
        self.assertIn('\tпапка\tвыполнено\tРабота\t', intent)
        self.assertEqual(sorted(r[1] for r in journal(task)), ['перемещён', 'перемещён'])
        # база: новый путь, служебная папка - из журнала; решение по исходному пути действует
        c = self.db()
        self.assertEqual(c.execute('select folder from moved_roots where disk=?', (SRC,)).fetchall(), [(WORK_ROOT,)])
        self.assertTrue(c.execute('select 1 from files where disk=? and path=?', (SRC, WORK_ROOT + '\\Работа\\схема.jpg')).fetchone())
        # старый расчёт v2 и повторный v3 перенесённое не берут
        self.assertNotIn(WORK_ROOT, self.mv(disk=SRC, dry=True))
        self.assertIn('Можно перенести: 0 файлов', self.mv(razbor=WORK, dry=True))   # второй раз - нечего
        self.append_decision(f'{SRC}\tРабота\tраздел: Работа\tпо исходному пути')
        self.assertEqual(hb.decision_of(WORK_ROOT + '\\Работа\\схема.jpg', hb.decisions_for(SRC)), 'раздел: Работа')
        # повторный запуск шаблона ничего не трогает: «уже перемещён» по строкам журнала
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertEqual([r[1] for r in journal(task)].count('уже перемещён'), 2)
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)

    def test_mark_changed_and_foreign_root_refused(self):
        self.work_task()
        self.mark(('Работа', 'Н1'))
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=WORK, dry=True)
        self.assertIn('Отметка папки «Работа» изменилась', str(e.exception))

    def test_folder_named_by_owner_is_not_used(self):
        from test_hashbase import make_disk
        make_disk(self.scans, 'HDD62', 'AAAA0062', [('Работа\\a.jpg', 10, H[31]), (WORK_ROOT + '\\b.jpg', 10, H[32])])
        hb.close_last()
        self.quiet(hb.connect)
        self.mark(('Работа', 'Н2'), disk='HDD62')
        res = sv.razbor_tasks('HDD62', dry=False)
        name = res['specs'][0]['name']
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=name, dry=True)
        self.assertIn('создала не программа', str(e.exception))
        self.assertEqual(hb.decision_of(WORK_ROOT + '\\b.jpg', [('', 'не нужно')] and hb.decisions_for('HDD62')), None)


class PartialCopyTest(MoveBase):
    def hike(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        sv.razbor_tasks(SRC, dry=False)
        lst = (hb.TASKS / HIKE / 'список.tsv').read_text(encoding='utf-8')
        self.assertIn('Поход 2010\\Монтаж\\clip копия.mp4', lst)
        self.copy_log(HIKE, '2025-01-01 10-00-00', [
            ('HDD45', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc'),
            ('HDD45', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4'),
            ('HDD77', OK, 200, S[2], 'Поход 2010\\Фото\\2.jpg'),
            ('HDD77', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4'),
            ('HDD77', 'ОШИБКА: устройство не готово', 10, '', 'Поход 2010\\описание.doc')])

    def test_move_copied_then_retry_rest(self):
        self.hike()
        text = self.mv(razbor=HIKE, dry=True)
        self.assertIn('по файлам', text)
        self.assertIn(f'Остаются на месте - {mv.R_ERR}: 1 файлов', text)                    # описание.doc на 77
        self.assertIn(f'Остаются на месте - {mv.R_NOHASH}: 1 файлов', text)                 # проект монтажа - не копировался
        self.assertIn('Можно перенести: 5 файлов', text)        # 1.jpg и 2.jpg (уже были / докопирован), 2 клипа, Thumbs.db
        self.mv(razbor=HIKE)
        task = hb.TASKS / (HIKE + mv.V3_SUFFIX)
        self.assertEqual((task / 'папки целиком.tsv').read_text(encoding='utf-8'), '')
        self.files(('Поход 2010\\Фото\\1.jpg', 100), ('Поход 2010\\Фото\\2.jpg', 200), ('Поход 2010\\Фото\\Thumbs.db', 5),
                   ('Поход 2010\\описание.doc', 10), ('Поход 2010\\Монтаж\\проект.prproj', 50),
                   ('Поход 2010\\Монтаж\\clip.mp4', 600), ('Поход 2010\\Монтаж\\clip копия.mp4', 600))
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        new = self.disk / FAMILY_ROOT / 'Поход 2010'
        for rel in ('Фото/1.jpg', 'Фото/2.jpg', 'Фото/Thumbs.db', 'Монтаж/clip.mp4', 'Монтаж/clip копия.mp4'):
            self.assertTrue((new / rel).exists(), rel)
        self.assertTrue((self.disk / 'Поход 2010' / 'описание.doc').exists())                # ошибка копирования - на месте
        self.assertTrue((self.disk / 'Поход 2010' / 'Монтаж' / 'проект.prproj').exists())
        self.assertEqual([r[1] for r in journal(task)].count('начато'), 5)                  # намерение перед каждым файлом
        # «Задания»: скопированное перенесено, осталось повторить копирование
        rows = self.page_rows()
        offers, done = tp.move_items(rows)
        mine = [o for o in offers if o.get('copy_task') == HIKE]
        self.assertEqual([o['buttons'] for o in mine], [['Повторить копирование']])
        self.assertTrue(any('перенесена в «' + FAMILY_ROOT in d['text'] and 'осталось 2 файлов' in d['text'] for d in done))
        # повтор: новое задание только из того, что не скопировано
        res = sv.retry_copy_task(HIKE)
        self.assertEqual(res['task'].name, HIKE + ' — повтор 1')
        self.assertEqual([x.split('\t')[:2] for x in (res['task'] / 'список.tsv').read_text(encoding='utf-8').splitlines()],
                         [['HDD77', 'Поход 2010\\описание.doc']])
        self.assertEqual(json.loads((res['task'] / 'разбор.json').read_text(encoding='utf-8'))['повтор'], HIKE)
        with self.assertRaises(SystemExit):
            self.mv(razbor=res['task'].name, dry=True)         # повтор переносится по исходному заданию
        self.copy_log(res['task'].name, '2025-01-02 10-00-00', [('HDD77', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc')])
        with self.assertRaises(sv.Refused):
            sv.retry_copy_task(HIKE)                           # всё скопировано
        rows = self.page_rows()
        offers, _done = tp.move_items(rows)
        self.assertEqual([o['buttons'] for o in offers if o.get('copy_task') == HIKE], [['Переместить']])
        text = self.mv(razbor=HIKE, dry=True)
        self.assertIn('Можно перенести: 1 файлов', text)                                     # описание.doc
        self.mv(razbor=HIKE)
        self.assertTrue((hb.TASKS / (HIKE + mv.V3_SUFFIX + ' 2')).exists())

    def test_unfinished_copy_refused(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        sv.razbor_tasks(SRC, dry=False)
        self.copy_log(WORK, '2025-01-01 10-00-00', [('HDD91', OK, 70, H[21], 'Работа\\схема.jpg')])
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=WORK, dry=True)
        self.assertIn('обработано 1 из 2', str(e.exception))

    def page_rows(self):
        with mock.patch.object(sv, 'running_scripts', return_value=[]), \
                mock.patch.object(sv, 'volumes', return_value={}), \
                mock.patch.object(tp, 'serial_names', return_value={'AAAA0060': SRC, 'AAAA0045': 'HDD45',
                                                                    'AAAA0077': 'HDD77', 'AAAA0091': 'HDD91'}), \
                mock.patch.object(tp, 'disk_labels', return_value={'HDD45': 'Бэкап фото и видео', 'HDD77': 'Путешествия'}):
            return tp.load(hb.TASKS)


class DirectionDiskTest(MoveBase):
    def test_source_is_direction_disk(self):
        self.mark(('', 'Н1'), disk='HDD91')                    # HDD91 - сам диск «Работы»: копировать можно
        res = sv.razbor_tasks('HDD91', dry=False)
        name = res['specs'][0]['name']
        meta = json.loads((hb.TASKS / name / 'разбор.json').read_text(encoding='utf-8'))
        self.assertFalse(meta['перемещать на носителе'])
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=name, dry=True)
        self.assertIn('перемещать на нём ничего нельзя', str(e.exception))
        row = dict(task=name, kind='копирование', state='готово', meta=meta, labels={}, errors=0, skipped=0)
        offers, done = tp.move_items([row])
        self.assertEqual(offers, [])
        self.assertIn('диск направления, на нём ничего не перемещается', done[0]['text'])


class TemplateRecoveryTest(unittest.TestCase):
    """Шаблон 1.1 без базы: намерения, восстановление, чужая папка, оглавление не сходится."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='move_v3_ps_'))
        self.task = self.tmp / 'Запускаемые скрипты' / 'Перенос'
        self.task.mkdir(parents=True)
        for name in ('Переместить.ps1', 'Запустить.cmd'):
            shutil.copy2(REAL_TPL / name, self.task / name)
        (self.task / 'тома.tsv').write_text(f'{SRC}\tAAAA0060\n', encoding='utf-8')
        self.disk = self.tmp / 'диск'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def put(self, rel, size, base=None):
        p = (base or self.disk) / rel.replace('\\', '/')
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'y' * size)
        os.utime(p, (0, 0))

    def plan(self, items, whole=(), roots='новый'):
        (self.task / 'перемещение.tsv').write_text(''.join(f'{r}\t{s}\t0\t{FAMILY_ROOT}\t{"AB" * 32}\tпроверка\n'
                                                           for r, s in items), encoding='utf-8')
        (self.task / 'папки целиком.tsv').write_text(''.join(f'{w}\t{FAMILY_ROOT}\t{n}\t0\n' for w, n in whole),
                                                     encoding='utf-8')
        (self.task / 'корни.tsv').write_text(f'{FAMILY_ROOT}\t{roots}\n', encoding='utf-8')

    def test_crash_after_rename_is_recovered_only_with_intent(self):
        items = [('A\\1.jpg', 10), ('A\\Фото\\2.jpg', 20)]
        self.plan(items, whole=[('A', 2)])
        # «сбой»: папка уже переименована, журнала нет, но есть запись намерения
        for rel, size in items:
            self.put(rel, size, self.disk / FAMILY_ROOT)
        (self.task / 'Намерение перемещения.tsv').write_text(
            'время\tоперация\tвид\tсостояние\tоткуда\tкуда\tфайлов\n'
            f'2026-11-15 10:00:00\tx-корень\tкорень\tсоздан\t\t{FAMILY_ROOT}\t\n'
            f'2026-11-15 10:00:01\tx-1\tпапка\tнамерение\tA\t{FAMILY_ROOT}\\A\t2\n', encoding='utf-8')
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertEqual(sorted(r[1] for r in journal(self.task)), ['уже перемещён', 'уже перемещён'])
        self.assertIn('\tx-1\tпапка\tвыполнено\t', (self.task / 'Намерение перемещения.tsv').read_text(encoding='utf-8'))

    def test_without_intent_manual_check(self):
        items = [('A\\1.jpg', 10)]
        self.plan(items)
        self.put('A\\1.jpg', 10, self.disk / FAMILY_ROOT)          # назначение есть, источника нет, записей нет
        (self.task / 'Намерение перемещения.tsv').write_text(
            f'время\tоперация\tвид\tсостояние\tоткуда\tкуда\tфайлов\n2026-11-15 10:00:00\tx\tкорень\tсоздан\t\t{FAMILY_ROOT}\t\n',
            encoding='utf-8')
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 1, outp)
        self.assertTrue(journal(self.task)[-1][1].startswith('нужна ручная проверка'))

    def test_foreign_root_and_listing_mismatch(self):
        items = [('A\\1.jpg', 10), ('A\\2.jpg', 20)]
        self.plan(items, whole=[('A', 2)])
        for rel, size in items:
            self.put(rel, size)
        (self.disk / FAMILY_ROOT).mkdir(parents=True)               # папку создал не скрипт и не журнал
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 1, outp)
        self.assertIn('программа её не создавала', outp)
        self.assertTrue((self.disk / 'A' / '1.jpg').exists())
        (self.disk / FAMILY_ROOT).rmdir()
        self.put('A\\лишний.txt', 3)                                # на диске файл, которого нет в описи
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertIn('пойдёт по файлам', outp)
        self.assertTrue((self.disk / 'A' / 'лишний.txt').exists())                   # остался на месте
        self.assertTrue((self.disk / FAMILY_ROOT / 'A' / '2.jpg').exists())
        self.assertNotIn('папка\tнамерение', (self.task / 'Намерение перемещения.tsv').read_text(encoding='utf-8'))


class TasksPageV3Test(unittest.TestCase):
    """Экран offscreen на подставленных строках: заголовок в столбик, названия дисков, блоки под таблицей."""

    LABELS = {'HDD17': 'Samsung 750', 'HDD45': 'Бэкап фото и видео', 'HDD77': 'Путешествия 2018–2025',
              'HDD78': 'Работа Сафари 6ТБ'}

    def rows(self):
        gib = 1024 ** 3
        base = dict(labels=self.LABELS, errors=0, skipped=0, examples=[], journal='', mark=None, move_task=None,
                    serials=set(), src_serial='S17', log_ts=0)
        run = dict(base, task='HDD17 — Поход 2010 — Семейный архив', kind='копирование', state='идёт', done=1234,
                   total=5678, good=1234, done_b=12.3 * gib, total_b=45.6 * gib, speed=85 * 1024 ** 2, eta=420,
                   eta_text='~7 мин', ago=5, disks='HDD17 (K:) → HDD45 (G:), HDD77 (S:)',
                   disks_long='HDD17 «Samsung 750» (K:) → HDD45 «Бэкап фото и видео» (G:), HDD77 «Путешествия 2018–2025» (S:)',
                   src_long='HDD17 «Samsung 750» (K:)',
                   dst_long=['HDD45 «Бэкап фото и видео» (G:)', 'HDD77 «Путешествия 2018–2025» (S:)'],
                   meta={'носитель': 'HDD17', 'папка': 'Поход 2010', 'обязательные диски': ['HDD45', 'HDD77'],
                         'имя направления': 'Семейный архив'})
        meta = {'носитель': 'HDD17', 'папка': 'Работа 2019', 'обязательные диски': ['HDD78'], 'имя направления': 'Работа и Сафари'}
        copied = dict(base, task='HDD17 — Работа 2019 — Работа и Сафари', kind='копирование', state='готово', done=40,
                      total=40, good=40, done_b=3 * gib, total_b=3 * gib, disks='HDD17 → HDD78',
                      disks_long='HDD17 «Samsung 750» → HDD78 «Работа Сафари 6ТБ»', meta=meta, left=0)
        meta2 = dict(meta, папка='Свадьба 2015', **{'обязательные диски': ['HDD45', 'HDD77'], 'имя направления': 'Семейный архив'})
        errs = dict(copied, task='HDD17 — Свадьба 2015 — Семейный архив', state='готово с ошибками', errors=3, left=3,
                    meta=meta2, disks_long='HDD17 «Samsung 750» → HDD45 «Бэкап фото и видео», HDD77 «Путешествия 2018–2025»')
        meta3 = dict(meta, папка='Котуй 2026', **{'обязательные диски': ['HDD45', 'HDD77'], 'имя направления': 'Семейный архив'})
        dcopy = dict(copied, task='HDD17 — Котуй 2026 — Семейный архив', meta=meta3,
                     disks_long='HDD17 «Samsung 750» → HDD45 «Бэкап фото и видео», HDD77 «Путешествия 2018–2025»')
        dmove = dict(base, task='HDD17 — Котуй 2026 — Семейный архив — перемещение', kind='перемещение', state='готово',
                     done=812, total=812, good=812, done_b=0, total_b=0, disks='HDD17 (внутри диска)',
                     disks_long='HDD17 «Samsung 750» (K:) (внутри диска)',
                     move_meta={'задание копирования': dcopy['task'], 'куда': FAMILY_ROOT, 'папка': 'Котуй 2026',
                                'всего в папке': [815, 0], 'остаток': {'копии на диске нет': [3, 1024]}, 'создано_ts': 1})
        return [run, copied, errs, dcopy, dmove]

    def test_page(self):
        rows = self.rows()
        text = tp.headline_text(rows, queue=())
        for line in ('Идёт копирование', 'Задание: HDD17 — Поход 2010 — Семейный архив', 'Откуда: HDD17 «Samsung 750» (K:)',
                     'Куда: HDD45 «Бэкап фото и видео» (G:), HDD77 «Путешествия 2018–2025» (S:)',
                     'Сделано: 1 234 из 5 678 файлов · 12.3 из 45.6 ГБ', 'Скорость: 85 МБ/с', 'Осталось: около 7 мин'):
            self.assertIn(line, text.splitlines())
        page = tp.TasksPage(FakeWin())
        page.resize(1500, 900)
        page.render(rows, groups=[])
        QAPP.processEvents()
        self.assertIn('Samsung 750', page.t.item(0, 7).text())
        self.assertIn('<table', page.head.text())
        texts = [o['text'] for o in page.offers]
        self.assertTrue(any('Работа 2019' in t and 'Скопировано на Работа и Сафари (78)' in t for t in texts))
        sw = next(o for o in page.offers if 'Свадьба' in o['text'])
        self.assertEqual(sw['buttons'], ['Переместить скопированное', 'Повторить копирование'])     # порядок владельца
        self.assertTrue(any('Котуй 2026' in d['text'] and 'осталось 3 файлов' in d['text'] for d in page.done_items))
        calls = []
        page.move_v3 = lambda it: calls.append(('move', it['copy_task']))
        page.retry_copy = lambda it: calls.append(('retry', it['copy_task']))
        page.on_offer(sw, 'Переместить скопированное')
        page.on_offer(sw, 'Повторить копирование')
        self.assertEqual(calls, [('move', sw['copy_task']), ('retry', sw['copy_task'])])
        shot = os.environ.get('MOVE_V3_SHOT')
        if shot:
            Path(shot).mkdir(parents=True, exist_ok=True)
            page.grab().save(str(Path(shot) / 'Задания.png'))

    def test_move_blocks_other_folder_allowed(self):
        cp = dict(task='К', kind='копирование', state='идёт', src_serial='S17', meta={'папка': 'Поход 2010'})
        mvr = dict(task='П', kind='перемещение', state='не запускалось', src_serial='S17', move_meta={'папка': 'Работа'})
        self.assertFalse(tp.move_blocks([mvr], [cp, mvr]))                       # другая папка того же носителя
        self.assertTrue(tp.move_blocks([dict(mvr, move_meta={'папка': 'поход 2010\\Фото'})], [cp]))   # пересекаются

    def test_offer_creates_and_runs_move(self):
        rows = self.rows()[1:2]
        page = tp.TasksPage(FakeWin())
        page.render(rows, groups=[])
        calls, shown = [], []

        def fake_run(*a, timeout=0):
            calls.append(a)
            if '--dry' in a:
                return 0, 'Можно перенести: 40 файлов, 3.00 ГБ.'
            if '--recheck' in a:
                return 0, 'Проверено'
            return 0, 'Папка задания: C:\\x\\HDD17 — Работа 2019 — Работа и Сафари — перемещение'
        page.show_text = lambda title, text, ok=None: shown.append(ok) or True
        page.start_file = calls.append
        with mock.patch.object(tp, 'run_hb', fake_run), mock.patch.object(tp, 'load_all', lambda *a, **k: (rows, [])):
            page.on_offer(page.offers[0], 'Переместить')
        self.assertEqual(calls[0], ('mvlist', '--razbor', 'HDD17 — Работа 2019 — Работа и Сафари', '--dry'))
        self.assertEqual(shown[0], 'Создать и запустить (40 файлов)')
        self.assertEqual(calls[1], ('mvlist', '--razbor', 'HDD17 — Работа 2019 — Работа и Сафари'))
        self.assertEqual(calls[2][:2], ('mvlist', '--recheck'))
        self.assertTrue(str(calls[3]).endswith('HDD17 — Работа 2019 — Работа и Сафари — перемещение\\Запустить.cmd'))


if __name__ == '__main__':
    unittest.main()
