"""Логика v3, этап 3 (15.11.2026): перенос папки разбора на носителе в «Скопировано на <направление> (<диски>)»
и раздел окна «Задания» (заголовок в столбик, названия дисков, «Можно переместить на носителе», «Готово»).

Запуск из корня проекта:  py -m unittest catalog.test_move_v3
Временные данные; настоящие диски, таблицы и задания не используются. Шаблон перемещения запускается настоящий
(Windows PowerShell 5.1) на временной папке вместо диска. Снимок «Заданий»: переменная MOVE_V3_SHOT=<папка>.
"""
import hashlib
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
from tests.sv_patch import sv, sv_patch                    # noqa: E402 - service и подмена его имён (все подмодули)
import tasks_page as tp                                     # noqa: E402
from hb_cmd import mvlist as mv                             # noqa: E402
from hb_core import razbor as rz                            # noqa: E402
from test_hashbase import LOG_HEAD, NS, S, make_disk        # noqa: E402
from test_logic_v3 import H, SRC, V3Base                    # noqa: E402
from test_tasks_move import FakeWin                         # noqa: E402

QAPP = QApplication.instance() or QApplication([])
OK = 'скопирован, размер и SHA-256 совпали'
OK_NOHASH = 'скопирован, размер совпал'
DOC1, DOC2 = 'd1' * 32, 'd2' * 32                           # хеш прочитанного у документов без хеша в описи
WORK = 'HDD60 — Работа — Работа'
HIKE = 'HDD60 — Поход 2010 — Семейный архив'            # группа; задания этапа 5 - отдельно на 45 и на 77
HIKE45, HIKE77 = HIKE + ' — на 45', HIKE + ' — на 77'
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

    def copy_log(self, task, stamp, lines, sub=''):
        """lines: (цель, результат, размер, sha, путь из списка); sub - подпапка источника (этап 14), как пишет
        шаблон: источник - с ней, назначение - без неё."""
        src = 'K:\\' + (sub + '\\' if sub else '')
        rows = [('10:00:0%d' % (i % 10), t, res, str(size), sha, src + p, f'X:\\ПЕРЕНОС с других дисков\\{SRC}\\' + p)
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
        lst = (hb.TASKS / HIKE45 / 'список.tsv').read_text(encoding='utf-8')
        self.assertIn('Поход 2010\\Монтаж\\clip копия.mp4', lst)
        self.assertFalse((hb.TASKS / HIKE).exists())                                        # общего задания нет
        self.copy_log(HIKE45, '2025-01-01 10-00-00', [
            ('HDD45', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc'),
            ('HDD45', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4')])
        self.copy_log(HIKE77, '2025-01-01 11-00-00', [
            ('HDD77', OK, 200, S[2], 'Поход 2010\\Фото\\2.jpg'),
            ('HDD77', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4'),
            ('HDD77', 'ОШИБКА: устройство не готово', 10, '', 'Поход 2010\\описание.doc')])

    def test_move_copied_then_retry_rest(self):
        self.hike()
        text = self.mv(razbor=HIKE45, dry=True)
        self.assertIn('по файлам', text)
        self.assertIn(f'Остаются на месте - {mv.R_ERR}: 1 файлов', text)                    # описание.doc на 77
        self.assertIn(f'Остаются на месте - {mv.R_NOHASH}: 1 файлов', text)                 # проект монтажа - не копировался
        self.assertIn('Можно перенести: 5 файлов', text)        # 1.jpg и 2.jpg (уже были / докопирован), 2 клипа, Thumbs.db
        self.mv(razbor=HIKE45)
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
        mine = [o for o in offers if o.get('copy_task') == HIKE45]
        self.assertEqual([o['buttons'] for o in mine], [['Повторить копирование']])
        self.assertEqual(mine[0]['retry_tasks'], [HIKE77])                                   # повтор - у задания на 77
        self.assertTrue(any('перенесена в «' + FAMILY_ROOT in d['text'] and 'осталось 2 файлов' in d['text'] for d in done))
        # повтор: новое задание только из того, что не скопировано
        res = sv.retry_copy_task(HIKE77)
        self.assertEqual(res['task'].name, HIKE77 + ' — повтор 1')
        self.assertEqual([x.split('\t')[:2] for x in (res['task'] / 'список.tsv').read_text(encoding='utf-8').splitlines()],
                         [['HDD77', 'Поход 2010\\описание.doc']])
        self.assertEqual(json.loads((res['task'] / 'разбор.json').read_text(encoding='utf-8'))['повтор'], HIKE77)
        with self.assertRaises(SystemExit):
            self.mv(razbor=res['task'].name, dry=True)         # повтор переносится по исходному заданию
        self.copy_log(res['task'].name, '2025-01-02 10-00-00', [('HDD77', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc')])
        with self.assertRaises(sv.Refused):
            sv.retry_copy_task(HIKE77)                           # всё скопировано
        rows = self.page_rows()
        offers, _done = tp.move_items(rows)
        self.assertEqual([o['buttons'] for o in offers if o.get('copy_task') == HIKE45], [['Переместить']])
        text = self.mv(razbor=HIKE45, dry=True)
        self.assertIn('Можно перенести: 1 файлов', text)                                     # описание.doc
        self.mv(razbor=HIKE45)
        self.assertTrue((hb.TASKS / (HIKE + mv.V3_SUFFIX + ' 2')).exists())

    def test_two_disks_move_waits_for_both(self):
        """Этап 5: на 45 скопировано, на 77 - нет: перемещение не предлагается, строка «на 45 - скопировано, на 77 -
        ждёт запуска»; mvlist по заданию на 45 отказывает, пока задание на 77 не закончено."""
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        res = sv.razbor_tasks(SRC, dry=False)
        hike = [x for x in res['specs'] if x['group'] == HIKE]
        self.assertEqual([(x['name'], x['targets'], x['disks']) for x in hike],
                         [(HIKE45, ['HDD45'], ['HDD45', 'HDD77']), (HIKE77, ['HDD77'], ['HDD45', 'HDD77'])])
        meta = json.loads((hb.TASKS / HIKE77 / 'разбор.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['цели'], meta['обязательные диски'], meta['группа']), (['HDD77'], ['HDD45', 'HDD77'], HIKE))
        self.assertEqual((hb.TASKS / HIKE77 / 'тома.tsv').read_text(encoding='utf-8').splitlines(),
                         ['HDD60\tAAAA0060', 'HDD77\tAAAA0077'])
        self.copy_log(HIKE45, '2025-01-01 10-00-00', [
            ('HDD45', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc'),
            ('HDD45', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4')])
        offers, _done = tp.move_items(self.page_rows())
        mine = [o for o in offers if 'Поход 2010' in o['text']]
        self.assertEqual(len(mine), 1)
        # этап 9: кнопка «Переместить» есть, но неактивна; строка «На 45 скопировано… · на 77 ждёт запуска»
        self.assertEqual((mine[0]['kind'], mine[0]['buttons'], mine[0]['disabled']), ('wait', ['Переместить'], True))
        self.assertTrue(mine[0]['small'].startswith('На 45 скопировано'), mine[0]['small'])
        self.assertTrue(mine[0]['small'].endswith(' · на 77 ждёт запуска'), mine[0]['small'])
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=HIKE45, dry=True)
        self.assertIn(f'«{HIKE77}» ещё не закончено', str(e.exception))
        again = sv.razbor_tasks(SRC, dry=False)                      # повтор: оба уже подготовлены
        self.assertTrue(all(x.get('exists') for x in again['specs']))
        # замечание 5: перенос создан по ВТОРОМУ заданию группы (из командной строки) - окно его видит
        self.copy_log(HIKE77, '2025-01-01 11-00-00', [
            ('HDD77', OK, 200, S[2], 'Поход 2010\\Фото\\2.jpg'),
            ('HDD77', OK, 600, H[20], 'Поход 2010\\Монтаж\\clip копия.mp4'),
            ('HDD77', OK_NOHASH, 10, DOC1, 'Поход 2010\\описание.doc')])
        offers, _done = tp.move_items(self.page_rows())
        mine = [o for o in offers if 'Поход 2010' in o['text']]
        self.assertEqual([o['buttons'] for o in mine], [['Переместить']])
        self.mv(razbor=HIKE77)
        self.assertTrue((hb.TASKS / (HIKE + mv.V3_SUFFIX)).exists())                 # имя - по группе
        offers, _done = tp.move_items(self.page_rows())
        mine = [o for o in offers if 'Поход 2010' in o['text']]
        self.assertEqual([(o['kind'], o['buttons']) for o in mine], [('run', ['Запустить перемещение'])])
        self.assertEqual(mine[0]['move_task'], HIKE + mv.V3_SUFFIX)

    def test_unfinished_copy_refused(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        sv.razbor_tasks(SRC, dry=False)
        self.copy_log(WORK, '2025-01-01 10-00-00', [('HDD91', OK, 70, H[21], 'Работа\\схема.jpg')])
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=WORK, dry=True)
        self.assertIn('обработано 1 из 2', str(e.exception))

    def page_rows(self):
        with sv_patch('running_scripts', return_value=[]), \
                sv_patch('volumes', return_value={}), \
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


R45 = 'Скопировано на Семейный архив 45'
R4577 = 'Скопировано на Семейный архив 45 и 77'
HIKE_FILES = (('Поход 2010\\Фото\\1.jpg', 100), ('Поход 2010\\Фото\\2.jpg', 200), ('Поход 2010\\Фото\\Thumbs.db', 5),
              ('Поход 2010\\описание.doc', 10), ('Поход 2010\\Монтаж\\проект.prproj', 50),
              ('Поход 2010\\Монтаж\\clip.mp4', 600), ('Поход 2010\\Монтаж\\clip копия.mp4', 600))


class SecondPassTest(MoveBase):
    """Этап 13: 45 и 77 - два направления; вторая копия - вторым проходом по «Скопировано на Семейный архив 45»,
    затем переименование в «Скопировано на Семейный архив 45 и 77» (без вложенности). Шаблон - настоящий, на
    временной папке вместо диска."""

    def setUp(self):
        super().setUp()
        sv.add_direction(num='Н1', name='Семейный архив 45', disks=['HDD45'])
        sv.add_direction(name='Семейный архив 77', disks=['HDD77'], kind=hb.KIND_MEDIA)      # Н4 в тестовых данных
        self.n77 = hb.find_direction(sv.directions(), 'Семейный архив 77').num
        self.files(*HIKE_FILES)

    def log_all(self, task, stamp, fail=()):
        """Журнал копирования по списку задания: всё скопировано (у файлов без хеша - хеш прочитанного DOC1)."""
        lines = []
        for f in (hb.TASKS / task / 'список.tsv').read_text(encoding='utf-8').splitlines():
            t, path, size, kind, *sha = f.split('\t')
            if path in fail:
                lines.append((t, 'ОШИБКА: устройство не готово', int(size), '', path))
            else:
                lines.append((t, OK if sha and sha[0] else OK_NOHASH, int(size), (sha[0].lower() if sha and sha[0] else DOC1), path))
        vol = (hb.TASKS / task / 'тома.tsv').read_text(encoding='utf-8').splitlines()[0].split('\t')
        self.copy_log(task, stamp, lines, sub=vol[2] if len(vol) > 2 else '')

    def first_pass(self, fail=()):
        """Поход 2010 -> Н1 (только 45): копия, проверка, перенос в «Скопировано на Семейный архив 45»."""
        self.mark(('Поход 2010', 'Н1'))
        res = sv.razbor_tasks(SRC, dry=False)
        name = res['specs'][0]['name']
        self.assertEqual(name, 'HDD60 — Поход 2010 — Семейный архив 45')            # один диск - без «— на 45»
        self.assertEqual(res['specs'][0]['disks'], ['HDD45'])
        self.log_all(name, '2025-01-01 10-00-00', fail)
        text = self.mv(razbor=name, dry=True)
        self.assertIn(f'«{R45}»', text)
        self.mv(razbor=name)
        task = hb.TASKS / (name + mv.V3_SUFFIX)
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        # журнал переноса - «в прошлом» (июнь 2025), до журнала второй копии (июль 2025): сборка с нуля применяет журналы
        # по времени, как было бы на самом деле (шаблон ставит в имя текущее время)
        for log in task.glob('Журнал перемещения *.tsv'):
            log.rename(log.with_name('Журнал перемещения 2025-06-01 10-00-00.tsv'))
        hb.close_last()
        return name

    def second_task(self, mark_path):
        self.mark((mark_path, self.n77))
        res = sv.razbor_tasks(SRC, dry=False, only=[self.n77])
        self.assertEqual(len(res['specs']), 1)
        s = res['specs'][0]
        self.assertEqual(s['targets'], ['HDD77'])
        return s

    def test_first_pass_45_only_then_subfolder_to_77(self):
        self.first_pass()
        # первый проход: на 45 скопировано и проверено - папка в «Скопировано на Семейный архив 45» (77 не нужен)
        hike = self.disk / R45 / 'Поход 2010'
        for rel in ('Фото/1.jpg', 'Фото/2.jpg', 'Фото/Thumbs.db', 'описание.doc', 'Монтаж/clip.mp4', 'Монтаж/clip копия.mp4'):
            self.assertTrue((hike / rel).exists(), rel)
        self.assertTrue((self.disk / 'Поход 2010' / 'Монтаж' / 'проект.prproj').exists())   # не подходит по типу - на месте
        c = self.db()
        self.assertIn((R45,), c.execute('select folder from moved_roots where disk=?', (SRC,)).fetchall())
        # в разборе: без своей отметки - «уже перенесено»; исходная отметка Н1 внутрь не проникает
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_MOVED)[0], 6 + 1)                     # + старая «ПЕРЕНЕСЕНО → 45 и 77»
        self.assertEqual(self.a(P, rz.O_COPY, 'Н1'), (0, 0))
        # отметка ВНУТРИ «Скопировано на …» для 77 - по нынешнему пути
        pv = sv.marks_preview(SRC, [(R45 + '\\Поход 2010', self.n77)])
        self.assertEqual(pv['fields'][0][1], R45 + '\\Поход 2010')
        self.assertIn('отметка действует только там', pv['lines'][1])
        s = self.second_task(R45 + '\\Поход 2010')
        self.assertEqual(s['name'], 'HDD60 — Поход 2010 — Семейный архив 77')
        rows = {r[1] for r in s['rows']}
        # 1.jpg уже есть на 77 (по хешу) - не копируется; клип - один раз (дубль в задании)
        # этап 14: пути - от подпапки источника «Скопировано на …» (на 77 ляжет как на 45, без служебной папки)
        self.assertEqual(rows, {'Поход 2010\\Фото\\2.jpg', 'Поход 2010\\Монтаж\\clip копия.mp4',
                                'Поход 2010\\описание.doc'})
        self.assertEqual(s['sub'], R45)
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_HAVE, self.n77), (1, 100))
        self.log_all(s['name'], '2025-07-01 10-00-00')   # после журнала первого переноса
        text = self.mv(razbor=s['name'], dry=True)
        self.assertIn(f'«{R4577}»', text)
        self.assertIn('папкой целиком', text)
        self.mv(razbor=s['name'])
        task = hb.TASKS / (s['name'] + mv.V3_SUFFIX)
        whole = (task / 'папки целиком.tsv').read_text(encoding='utf-8').rstrip('\n').split('\t')
        self.assertEqual(whole[:2] + whole[4:], [R45 + '\\Поход 2010', R4577, R45])
        meta = json.loads((task / 'перемещение.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['куда'], meta['снять'], meta['части']), (R4577, R45, ['Семейный архив 45', 'Семейный архив 77']))
        self.assertEqual((task / 'корни.tsv').read_text(encoding='utf-8'), f'{R45}\tизвестен\n{R4577}\tновый\n')
        rows = [x.split('\t') for x in (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(r[3] == R4577 and r[6] == R45 for r in rows))
        self.assertIn('HDD45', rows[0][5])                                    # обязательные: и 45, и 77
        self.assertIn('HDD77', rows[0][5])
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertIn('перенесена целиком', outp)
        new = self.disk / R4577 / 'Поход 2010'                                 # без вложенности
        self.assertTrue((new / 'Фото' / '1.jpg').exists())
        self.assertFalse((self.disk / R4577 / R45).exists())
        self.assertFalse((self.disk / R45 / 'Поход 2010').exists())
        hb.close_last()
        c = self.db()
        self.assertEqual(sorted(x for (x,) in c.execute('select folder from moved_roots where disk=?', (SRC,))), [R45, R4577])
        self.assertTrue(c.execute('select 1 from files where disk=? and path=?',
                                  (SRC, R4577 + '\\Поход 2010\\Фото\\1.jpg')).fetchone())
        self.assertFalse(c.execute('select 1 from files where disk=? and path like ?', (SRC, R45 + '\\%')).fetchone())
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_MOVED)[0], 6 + 1)                     # всё «уже перенесено»
        self.assertIn('Можно перенести: 0 файлов', self.mv(razbor=s['name'], dry=True))    # второй раз - нечего
        # «Задания»: строка переноса - без вложенности
        self.assertEqual(tp.move_line('F:', SRC, R45 + '\\Поход 2010', R4577), f'F:\\{R45}\\Поход 2010 → F:\\{R4577}\\Поход 2010')
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)                             # сборка по шагам = с нуля

    def test_whole_copied_folder_renamed(self):
        self.first_pass()
        s = self.second_task(R45)                                              # отмечена вся «Скопировано на …»
        self.assertEqual(s['name'], f'HDD60 — {R45} — Семейный архив 77')
        self.log_all(s['name'], '2025-07-01 10-00-00')   # после журнала первого переноса
        self.mv(razbor=s['name'])
        task = hb.TASKS / (s['name'] + mv.V3_SUFFIX)
        whole = (task / 'папки целиком.tsv').read_text(encoding='utf-8').rstrip('\n').split('\t')
        self.assertEqual(whole[:2] + whole[4:], [R45, R4577, R45])
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertFalse((self.disk / R45).exists())                           # одно переименование всей папки
        self.assertTrue((self.disk / R4577 / 'Поход 2010' / 'Монтаж' / 'clip.mp4').exists())
        intent = (task / 'Намерение перемещения.tsv').read_text(encoding='utf-8')
        self.assertIn(f'\tпапка\tнамерение\t{R45}\t{R4577}\t', intent)
        self.assertIn(f'\tкорень\tсоздан\t\t{R4577}\t', intent)                # записано ПОСЛЕ удачного переименования
        self.assertLess(intent.index('\tпапка\tнамерение\t'), intent.index('\tкорень\tсоздан\t'))
        hb.close_last()
        c = self.db()
        self.assertIn((R4577,), c.execute('select folder from moved_roots where disk=?', (SRC,)).fetchall())
        self.assertEqual(c.execute('select count(*) from files where disk=? and path like ?', (SRC, R4577 + '\\%')).fetchone()[0], 6)

    def test_not_confirmed_on_45_stays(self):
        """Гарантия: в «… 45 и 77» переезжает только то, что подтверждено по SHA-256 и на 45, и на 77."""
        self.first_pass()
        # «потеря» копии клипа на 45: журнал первого прохода говорит, что клип на 45 не записан
        first = hb.TASKS / 'HDD60 — Поход 2010 — Семейный архив 45'
        log = next(first.glob('Журнал копирования *.tsv'))
        log.write_text(log.read_text(encoding='utf-8-sig').replace(f'{OK}\t600\t{H[20]}', 'ОШИБКА: устройство не готово\t600\t'),
                       encoding='utf-8-sig')
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        s = self.second_task(R45 + '\\Поход 2010')
        self.log_all(s['name'], '2025-07-01 10-00-00')   # после журнала первого переноса
        text = self.mv(razbor=s['name'], dry=True)
        self.assertIn(f'Остаются на месте - {mv.R_ERR}: 1 файлов', text)        # клип: на 45 ошибка копирования
        self.assertIn(f'Остаются на месте - {mv.R_NONE}: 1 файлов', text)       # его дубль: на 45 копии нет
        self.assertIn('по файлам', text)
        self.mv(razbor=s['name'])
        task = hb.TASKS / (s['name'] + mv.V3_SUFFIX)
        moved = {x.split('\t')[0] for x in (task / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()}
        self.assertNotIn(R45 + '\\Поход 2010\\Монтаж\\clip.mp4', moved)
        code, outp = run_ps(task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertTrue((self.disk / R45 / 'Поход 2010' / 'Монтаж' / 'clip.mp4').exists())    # остался
        self.assertTrue((self.disk / R4577 / 'Поход 2010' / 'Фото' / '2.jpg').exists())

    def test_move_metas_only_own_disk_and_done(self):
        """Проверка ядра, п. 1: записи переносов - только этого носителя и только выполненные (есть журнал)."""
        for name, disk, done in (('A', SRC, True), ('B', 'HDD61', True), ('C', SRC, False)):
            t = hb.TASKS / name
            t.mkdir(parents=True)
            (t / mv.V3_META).write_text(json.dumps({'версия': 3, 'носитель': disk, 'куда': R45}), encoding='utf-8')
            if done:
                (t / 'Журнал перемещения 2025-01-01 10-00-00.tsv').write_text(
                    'время\tрезультат\tразмер\tsha-256\tоткуда\tкуда\n10:00\tперемещён\t1\t\tK:\\a\tK:\\b\n',
                    encoding='utf-8-sig')
        self.assertEqual([m['носитель'] for m in mv.move_metas(SRC)], [SRC])
        self.assertEqual(len(mv.move_metas()), 2)

    def test_no_history_refused(self):
        """П. 2 в работе: запись первого переноса (перемещение.json) потеряна, журнал есть - второй проход не
        предлагается (на какие диски копия уже подтверждена, неизвестно)."""
        name = self.first_pass()
        (hb.TASKS / (name + mv.V3_SUFFIX) / mv.V3_META).unlink()
        s = self.second_task(R45 + '\\Поход 2010')
        self.log_all(s['name'], '2025-07-01 10-00-00')
        with self.assertRaises(SystemExit) as e:
            self.mv(razbor=s['name'], dry=True)
        self.assertIn('не найдена история этой папки', str(e.exception))

    def test_file_in_root_of_copied_folder(self):
        """П. 5: файл прямо в корне «Скопировано на …» - история по его исходному пути («корень.jpg»), обязателен 45."""
        first = hb.TASKS / 'Копия корня на 45'                       # задание копирования первого прохода
        first.mkdir(parents=True)
        (first / 'тома.tsv').write_text(f'{SRC}\tAAAA0060\nHDD45\tAAAA0045\n', encoding='utf-8')
        (first / 'список.tsv').write_text(f'HDD45\tкорень.jpg\t80\tс хешем\t{H[26].upper()}\n', encoding='utf-8')
        self.copy_log('Копия корня на 45', '2025-01-01 10-00-00', [('HDD45', OK, 80, H[26], 'корень.jpg')])
        mvt = hb.TASKS / 'Перенос корня'                              # выполненный перенос в R45
        mvt.mkdir()
        (mvt / 'тома.tsv').write_text(f'{SRC}\tAAAA0060\n', encoding='utf-8')
        (mvt / mv.V3_META).write_text(json.dumps({'версия': 3, 'носитель': SRC, 'куда': R45, 'имя направления':
                                                  'Семейный архив 45', 'обязательные диски': ['HDD45']}), encoding='utf-8')
        (mvt / 'Журнал перемещения 2025-06-01 10-00-00.tsv').write_text(
            'время\tрезультат\tразмер\tsha-256\tоткуда\tкуда\n'
            f'10:00\tперемещён\t80\t{H[26]}\tK:\\корень.jpg\tK:\\{R45}\\корень.jpg\n', encoding='utf-8-sig')
        hb.close_last()
        s = self.second_task(R45)
        self.assertEqual([r[1] for r in s['rows']], ['корень.jpg'])                 # от подпапки источника R45
        self.log_all(s['name'], '2025-07-01 10-00-00')
        self.mv(razbor=s['name'])
        task = hb.TASKS / (s['name'] + mv.V3_SUFFIX)
        row = (task / 'перемещение.tsv').read_text(encoding='utf-8').split('\t')
        self.assertEqual((row[0], row[3], row[5], row[6].strip()),
                         (R45 + '\\корень.jpg', R4577, 'копия подтверждена: HDD45, HDD77', R45))
        self.assertEqual(mv.dest_path(row), R4577 + '\\корень.jpg')
        # без копии на 45 (журнал первого копирования - ошибка) - остаётся на месте
        log = next(first.glob('Журнал копирования *.tsv'))
        log.write_text(log.read_text(encoding='utf-8-sig').replace(OK, 'ОШИБКА: устройство не готово'), encoding='utf-8-sig')
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn(f'Остаются на месте - {mv.R_ERR}: 1 файлов', self.mv(razbor=s['name'], dry=True))

    def test_all_have_manifest_without_tasks(self):
        """Копировать нечего (всё уже есть на диске по хешу): манифест пишется и без новых заданий - перенос
        предлагается «Заданиями» (раньше манифест писался, только если были новые задания); повтор - не дублирует."""
        self.mark(('Поход 2010\\Фото', 'Н1'))                                  # 1.jpg и 2.jpg уже есть на 45
        res = sv.razbor_tasks(SRC, dry=False)
        self.assertEqual(res['specs'], [])
        self.assertIsNotNone(res['manifest'])
        self.assertEqual([g['state'] for g in res['states']], [rz.G_HAVE])
        self.assertIsNone(sv.razbor_tasks(SRC, dry=False)['manifest'])
        groups = tp.latest_manifest_groups()
        self.assertEqual([g['group']['folder'] for g in groups], ['Поход 2010\\Фото'])
        self.assertIn(f'«{R45}»', self.mv(razbor_manifest=res['manifest'].name, group='Поход 2010\\Фото', dry=True))

    def test_names_and_refusals(self):
        self.assertEqual(hb.copied_folder('Семейный архив 45', ['HDD45']), R45)          # без «(45)»
        self.assertEqual(hb.copied_folder('Семейный архив 45', ['HDD80']), R45 + ' (80)')  # диск сменили - видно
        self.assertEqual(hb.copied_folder('Архив 2045', ['HDD45']), 'Скопировано на Архив 2045 (45)')
        self.assertEqual(hb.copied_folder('Семейный архив 45 и 77', ['HDD77']), R4577 + ' (77)')
        self.assertEqual(hb.copied_folder('Фильмы', ['HDD55']), 'Скопировано на Фильмы (55)')
        j = lambda *p: hb.copied_join(list(p))
        self.assertEqual(j('Семейный архив 45', 'Семейный архив 77'), R4577)
        self.assertEqual(j('Семейный архив 77', 'Семейный архив 45'), R4577)            # порядок проходов не важен
        self.assertEqual(j('Семейный архив 45 и 77', 'Семейный архив 77'), R4577)       # повтор - то же имя (отказ)
        self.assertEqual(j('Семейный архив 45 и 77', 'Фильмы (55)'), R4577 + ', Фильмы (55)')
        self.assertEqual(j('Фильмы (55)', 'Работа (78)'), 'Скопировано на Работа (78) и Фильмы (55)')
        self.assertEqual(j('Фильмы (55)', 'Работа (78)', 'Друзья (81)'),
                         'Скопировано на Друзья (81), Работа (78) и Фильмы (55)')
        self.assertEqual(hb.copied_parts(R4577 + ', Фильмы (55)'), ['Семейный архив 45 и 77', 'Фильмы (55)'])
        src = dict(direction='Семейный архив 77', disks=['HDD77'], disk=SRC)
        m45 = {'куда': R45, 'носитель': SRC, 'обязательные диски': ['HDD45'], 'имя направления': 'Семейный архив 45'}
        m4577 = dict(m45, куда=R4577, части=['Семейный архив 45', 'Семейный архив 77'], **{'обязательные диски': ['HDD77']})
        with self.assertRaises(SystemExit):
            mv.second_dest(R4577, src, metas=[m4577])                                # 77 уже в имени
        with self.assertRaises(SystemExit):
            mv.second_dest(R45, dict(direction='x' * 30, disks=['HDD91'], disk=SRC),
                           metas=[dict(m45, части=['y' * 30, 'z' * 30, 'w' * 30])])  # длиннее 120 знаков
        self.assertEqual(mv.second_dest(R45, src, metas=[m45])[:3:2], (R4577, {'HDD45'}))
        # проверка ядра, п. 2: истории папки нет - отказ, а не молчаливая потеря диска 45
        with self.assertRaises(SystemExit) as e:
            mv.second_dest(R45, src, metas=[])
        self.assertIn('не найдена история этой папки', str(e.exception))
        # п. 1: то же имя «Скопировано на …» на другом носителе - не наша история
        other = dict(m45, носитель='HDD61', **{'обязательные диски': ['HDD91']})
        self.assertEqual(mv.second_dest(R45, src, metas=[m45, other])[2], {'HDD45'})
        with self.assertRaises(SystemExit):
            mv.second_dest(R45, src, metas=[other])
        # старая «ПЕРЕНЕСЕНО → …»: как раньше - сама не отмечается, внутри отметка по исходному пути
        with self.assertRaises(sv.Refused):
            sv.marks_preview(SRC, [('ПЕРЕНЕСЕНО → 45 и 77', 'Н2')])


def rz_children(c, disk):
    """Дети папок носителя по таблице folders (как в planner) - для прямого вызова razbor._twins."""
    ch = {}
    for (f,) in c.execute('select folder from folders where disk=?', (disk,)):
        if f:
            ch.setdefault(f.rpartition('\\')[0], []).append(f)
    return ch


COPY_TPL = Path(__file__).resolve().parents[1] / 'Каталог дисков' / '_ШАБЛОН копирования' / 'Копировать.ps1'
DEST = 'ПЕРЕНОС с других дисков'


class CleanDestTest(MoveBase):
    """Этап 14: копия второго прохода ложится на 77 без «Скопировано на …» - как на 45 при первом проходе. Задание
    составляется со служебной папкой как подпапкой источника (третья колонка тома.tsv), шаблон копирования 2.4 не
    менялся и запускается настоящий (Windows PowerShell 5.1, -TestRoots) на временных папках."""
    log_all, first_pass, second_task = SecondPassTest.log_all, SecondPassTest.first_pass, SecondPassTest.second_task

    def setUp(self):
        MoveBase.setUp(self)
        sv.add_direction(num='Н1', name='Семейный архив 45', disks=['HDD45'])
        sv.add_direction(name='Семейный архив 77', disks=['HDD77'], kind=hb.KIND_MEDIA)
        self.n77 = hb.find_direction(sv.directions(), 'Семейный архив 77').num
        self.files(*HIKE_FILES)

    def put_scan(self, disk, rows):
        """Дописать в опись диска файлы (путь, размер, sha) и вернуть описи прежнюю дату (2020 - раньше журналов)."""
        import sqlite3
        job = next(self.scans.glob(f'{disk} - тест/*'))
        for fn, q, args_ in (('hashes.sqlite', "insert into hashes values (?, ?, ?, '0', '', ?, 'verified', '')",
                              [(disk, p, s, h) for p, s, h in rows if h]),             # h=None - файл без хеша
                             ('inventory.sqlite', "insert into files values (?, ?, '0', '0', '', 32, 'media_small')",
                              [(p, s) for p, s, _h in rows])):
            con = sqlite3.connect(job / fn)
            con.executemany(q, args_)
            con.commit(); con.close()
            os.utime(job / fn, (1580000000, 1580000000))
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())

    def run_copy(self, task, t77):
        shutil.copy2(COPY_TPL, hb.TASKS / task / 'Копировать.ps1')
        t77.mkdir(parents=True, exist_ok=True)
        p = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                            str(hb.TASKS / task / 'Копировать.ps1'), '-TestRoots', f'{SRC}={self.disk};HDD77={t77}'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180, stdin=subprocess.DEVNULL)
        logs = sorted((hb.TASKS / task).glob('Журнал копирования *.tsv'))
        rows = [x.split('\t') for x in logs[-1].read_text(encoding='utf-8-sig').splitlines()[1:] if x.strip()]
        return p.returncode, {Path(r[5]).name: r for r in rows}, logs[-1]

    def test_second_copy_same_layout_as_first(self):
        self.first_pass()
        s = self.second_task(R45 + '\\Поход 2010')
        task = hb.TASKS / s['name']
        vol = (task / 'тома.tsv').read_text(encoding='utf-8').splitlines()
        self.assertEqual(vol[0], f'{SRC}\tAAAA0060\t{R45}')                       # подпапка источника - служебная
        self.assertEqual(vol[1], 'HDD77\tAAAA0077')
        meta = json.loads((task / 'разбор.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['папка'], meta['подпапка источника']), (R45 + '\\Поход 2010', R45))
        self.assertEqual(meta['зависимые']['HDD77'][0][0], 'Поход 2010\\Монтаж\\clip.mp4')   # дубль - тоже от подпапки
        # настоящий шаблон 2.4: читает F:\R45\Поход 2010\…, пишет в …\HDD60\Поход 2010\… (на 45 - тот же путь)
        t77 = self.tmp / 'диск HDD77'
        code, got, log = self.run_copy(s['name'], t77)
        self.assertEqual(code, 1)                    # у фото в описи вымышленный SHA-256 - «не совпал», это ожидаемо
        doc = got['описание.doc']
        self.assertEqual(doc[2], OK_NOHASH)
        self.assertEqual(doc[5], str(self.disk / R45 / 'Поход 2010' / 'описание.doc'))
        self.assertEqual(doc[6], str(t77 / DEST / SRC / 'Поход 2010' / 'описание.doc'))
        self.assertTrue((t77 / DEST / SRC / 'Поход 2010' / 'описание.doc').exists())
        self.assertFalse((t77 / DEST / SRC / R45).exists())
        self.assertTrue(all(r[6].startswith(str(t77 / DEST / SRC / 'Поход 2010') + '\\') for r in got.values()))
        self.assertTrue(got['2.jpg'][2].startswith('ОШИБКА: SHA-256'))           # копия не оставлена
        self.assertFalse((t77 / DEST / SRC / 'Поход 2010' / 'Фото' / '2.jpg').exists())
        log.unlink()                                 # дальше - журнал «всё скопировано» (содержимое - как в описи)
        # сборка: копия на 77 - по очищенному пути, связь с файлом носителя - по SHA-256
        self.log_all(s['name'], '2025-07-01 10-00-00')
        hb.close_last()
        c = self.db()
        dst = f'{DEST}\\{SRC}\\Поход 2010\\Фото\\2.jpg'
        self.assertEqual(c.execute('select sha, ev from files where disk=? and path=?', ('HDD77', dst)).fetchone(),
                         (S[2], 'C'))                                                          # C - копия по журналу
        self.assertFalse(c.execute('select 1 from files where disk=? and path like ?', ('HDD77', f'%{R45}%')).fetchone())
        P = self.plan()                       # «уже есть» на 77 - по SHA-256; без хеша в описи - всегда «копировать»
        self.assertEqual(self.a(P, rz.O_COPY, self.n77), (1, 10))
        # переименование в «… 45 и 77» находит подтверждения на обоих дисках
        text = self.mv(razbor=s['name'], dry=True)
        self.assertIn(f'«{R4577}»', text)
        self.assertIn('папкой целиком', text)
        self.mv(razbor=s['name'])
        mvt = hb.TASKS / (s['name'] + mv.V3_SUFFIX)
        rows = [x.split('\t') for x in (mvt / 'перемещение.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(rows and all(r[5] == 'копия подтверждена: HDD45, HDD77' or 'мусор' in r[5] for r in rows))
        code, outp = run_ps(mvt, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertTrue((self.disk / R4577 / 'Поход 2010' / 'Фото' / '2.jpg').exists())
        hb.close_last()
        c = self.db()                                                             # сборка по шагам: журнал переноса
        self.assertIn((R4577,), c.execute('select folder from moved_roots where disk=?', (SRC,)).fetchall())
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)                             # сборка по шагам = с нуля

    def test_conflict_and_have_on_clean_path(self):
        self.first_pass()
        base = f'{DEST}\\{SRC}\\Поход 2010\\'
        self.put_scan('HDD77', [(base + 'Фото\\2.jpg', 200, H[41]),             # другой SHA - конфликт
                                (base + 'Монтаж\\clip.mp4', 600, H[20]),         # тот же SHA - «уже есть»
                                (f'{DEST}\\{SRC}\\{R45}\\Поход 2010\\описание.doc', 10, H[42])])  # старая раскладка
        self.mark((R45 + '\\Поход 2010', self.n77))
        P = self.plan(detail=True)
        self.assertIn((R45 + '\\Поход 2010\\Фото\\2.jpg', 'HDD77', rz.B_CONFLICT, 200), P.blocked)
        self.assertEqual(self.a(P, rz.O_HAVE, self.n77), (3, 1300))              # 1.jpg и оба клипа - по SHA-256
        g = next(k for k in P.groups if k[1] == R45 + '\\Поход 2010')
        # запись по старой раскладке (…\HDD60\Скопировано на …\…) путь назначения больше не занимает
        self.assertEqual({r[1] for r in P.rows[(g, 'HDD77')]}, {R45 + '\\Поход 2010\\описание.doc'})
        self.assertTrue(any('другое подтверждённое содержимое' in x for x in rz.attention_lines(P)))
        # на диске (в обход базы) по очищенному пути другой файл - шаблон: «КОНФЛИКТ», ничего не перезаписано
        s = sv.razbor_tasks(SRC, dry=False, only=[self.n77])['specs'][0]
        t77 = self.tmp / 'диск HDD77'
        busy = t77 / DEST / SRC / 'Поход 2010' / 'описание.doc'
        busy.parent.mkdir(parents=True)
        busy.write_bytes(b'abc')
        code, got, _log = self.run_copy(s['name'], t77)
        self.assertEqual(code, 1)
        self.assertTrue(got['описание.doc'][2].startswith('КОНФЛИКТ'))
        self.assertEqual(busy.read_bytes(), b'abc')
        busy.write_bytes(b'z' * 10)                         # тот же размер, другое содержимое - шаблон 2.5: КОНФЛИКТ
        code, got, _log = self.run_copy(s['name'], t77)
        self.assertEqual((code, got['описание.doc'][2]),
                         (1, 'КОНФЛИКТ: на месте назначения другой файл того же размера (SHA-256 отличается)'))
        self.assertEqual(busy.read_bytes(), b'z' * 10)
        busy.write_bytes(b'x' * 10)                         # то же содержимое (хеша в описи нет - сверка с источником)
        code, got, _log = self.run_copy(s['name'], t77)
        self.assertEqual((code, got['описание.doc'][2]), (0, 'уже есть, SHA-256 совпал'))
        self.assertEqual(got['описание.doc'][4], hashlib.sha256(b'x' * 10).hexdigest().upper())

    def test_duplicate_outside_copied_folder(self):
        """Проверка кода, п. 3: дубль (тот же SHA-256) файла из R в обычной папке носителя - другая группа, в
        «зависимые» задания R не попадает; оба задания составляются (дубли - только внутри группы)."""
        self.first_pass()
        self.put_scan(SRC, [('Новое\\clip.mp4', 600, H[20])])
        self.mark((R45 + '\\Поход 2010', self.n77), ('Новое', self.n77))
        specs = {s['folder']: s for s in sv.razbor_tasks(SRC, dry=False, only=[self.n77])['specs']}
        r, n = specs[R45 + '\\Поход 2010'], specs['Новое']
        self.assertEqual((r['sub'], n['sub']), (R45, ''))
        self.assertEqual([x[1] for x in n['rows']], ['Новое\\clip.mp4'])
        self.assertIn('Поход 2010\\Монтаж\\clip копия.mp4', {x[1] for x in r['rows']})
        self.assertEqual([d[0] for d in r['deps']['HDD77']], ['Поход 2010\\Монтаж\\clip.mp4'])
        self.assertEqual(n['deps']['HDD77'], [])

    def test_owner_folder_not_cleaned(self):
        """Папка владельца «Скопировано на …» (журнала перемещения нет) - обычная: путь на диске - с ней."""
        own = R45 + '\\q.jpg'
        make_disk(self.scans, 'HDD61', 'AAAA0061', [(own, 10, H[30])])
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.mark(('', self.n77), disk='HDD61')
        s = sv.razbor_tasks('HDD61', dry=False)['specs'][0]
        self.assertEqual(([r[1] for r in s['rows']], s['sub']), ([own], ''))
        self.assertEqual((hb.TASKS / s['name'] / 'тома.tsv').read_text(encoding='utf-8').splitlines()[0], 'HDD61\tAAAA0061')
        self.assertEqual(json.loads((hb.TASKS / s['name'] / 'разбор.json').read_text(encoding='utf-8'))['подпапка источника'], '')

    def test_twins_blocked(self):
        """Двойники пути: «корень.jpg» в корне носителя и в корне «Скопировано на …» с разным SHA-256 - оба не
        копируются; файл «фото.jpg» против папки «Скопировано на …\\фото.jpg»; одинаковый SHA-256 - не двойники."""
        self.first_pass()
        self.put_scan(SRC, [(R45 + '\\корень.jpg', 80, H[44]), ('фото.jpg', 60, H[46]), (R45 + '\\фото.jpg\\x.jpg', 70, H[47]),
                            (R45 + '\\Друзья\\a.jpg', 90, H[22])])               # тот же SHA, что у «Друзья\a.jpg»
        self.mark((R45, self.n77), ('корень.jpg', self.n77), ('фото.jpg', self.n77), ('Друзья', self.n77))
        P = self.plan(detail=True)
        blocked = {(p, w) for p, d, w, _s in P.blocked if d == 'HDD77'}
        self.assertIn((R45 + '\\корень.jpg', rz.B_TWIN), blocked)
        self.assertIn(('корень.jpg', rz.B_TWIN), blocked)
        self.assertIn(('фото.jpg', rz.B_TWIN), blocked)                         # файл против папки - файл
        self.assertNotIn((R45 + '\\фото.jpg\\x.jpg', rz.B_TWIN), blocked)
        self.assertNotIn((R45 + '\\Друзья\\a.jpg', rz.B_TWIN), blocked)
        self.assertTrue(any('один путь назначения' in x for x in rz.attention_lines(P)))
        rows = {r[1] for k, v in P.rows.items() for r in v}
        self.assertIn('Друзья\\a.jpg', rows)
        self.assertNotIn(R45 + '\\корень.jpg', rows)
        # проверка кода, п. 4: файл без хеша против папки - тоже двойник (блок обязателен)
        self.put_scan(SRC, [(R45 + '\\корень.txt\\y.jpg', 5, H[48]), (R45 + '\\без хеша.jpg', 7, None),
                            ('без хеша.jpg', 7, None)])
        c = self.db()
        tw = rz._twins(c, SRC, sorted(r[0] for r in c.execute('select folder from folders where disk=?', (SRC,))),
                       rz_children(c, SRC), {R45, R4577} & {r[0] for r in c.execute('select folder from moved_roots')})
        self.assertIn('корень.txt', tw)                                          # без хеша против папки
        self.assertNotIn(R45 + '\\корень.txt\\y.jpg', tw)
        self.assertTrue({'без хеша.jpg', R45 + '\\без хеша.jpg'} <= tw)          # оба без хеша - двойники
        # на обычном носителе (без «Скопировано на …») проверка ничего не находит
        self.assertEqual(rz._twins(None, SRC, ['', 'A'], {'': ['A']}, set()), set())


class TemplateSecondPassTest(unittest.TestCase):
    """Шаблон 1.2 без базы: колонка «снять», сбой после переименования всей «Скопировано на …»."""
    setUp, tearDown, put = TemplateRecoveryTest.setUp, TemplateRecoveryTest.tearDown, TemplateRecoveryTest.put

    def plan2(self, items, whole=(), roots=((R45, 'известен'), (R4577, 'новый')), strip=R45):
        (self.task / 'перемещение.tsv').write_text(''.join(f'{r}\t{s}\t0\t{R4577}\t{"AB" * 32}\tпроверка\t{strip}\n'
                                                           for r, s in items), encoding='utf-8')
        (self.task / 'папки целиком.tsv').write_text(''.join(f'{w}\t{R4577}\t{n}\t0\t{strip}\n' for w, n in whole),
                                                     encoding='utf-8')
        (self.task / 'корни.tsv').write_text(''.join(f'{a}\t{b}\n' for a, b in roots), encoding='utf-8')

    def test_strip_by_files(self):
        items = [(R45 + '\\A\\1.jpg', 10), (R45 + '\\A\\2.jpg', 20)]
        self.plan2(items)
        for rel, size in items:
            self.put(rel, size)
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertTrue((self.disk / R4577 / 'A' / '1.jpg').exists())
        self.assertEqual(sorted(r[5][r[5].index(R4577):] for r in journal(self.task) if r[1] == 'перемещён'),
                         [R4577 + '\\A\\1.jpg', R4577 + '\\A\\2.jpg'])
        self.assertEqual(hb.moved_rel(f'K:\\{R45}\\A\\1.jpg', f'K:\\{R4577}\\A\\1.jpg'),
                         (R45 + '\\A\\1.jpg', R4577 + '\\A\\1.jpg'))

    def test_strip_only_known_program_folder(self):
        items = [(R45 + '\\A\\1.jpg', 10)]
        self.plan2(items, roots=((R45, 'новый'), (R4577, 'новый')))                 # R45 не создана программой
        self.put(items[0][0], 10)
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 1, outp)
        self.assertIn('снять', outp)
        self.assertTrue((self.disk / R45 / 'A' / '1.jpg').exists())
        self.plan2(items, strip='')                                                   # без «снять» - старое правило
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 1, outp)
        self.assertIn('уже лежит в служебной папке', outp)

    def test_crash_after_whole_root_rename(self):
        items = [(R45 + '\\A\\1.jpg', 10), (R45 + '\\Б\\2.jpg', 20)]
        self.plan2(items, whole=[(R45, 2)])
        for rel, size in items:                                                       # «сбой» после переименования
            self.put(rel.replace(R45, R4577), size)
        (self.task / 'Намерение перемещения.tsv').write_text(
            'время\tоперация\tвид\tсостояние\tоткуда\tкуда\tфайлов\n'
            f'2026-11-16 10:00:01\tx-1\tпапка\tнамерение\t{R45}\t{R4577}\t2\n', encoding='utf-8')
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 0, outp)
        self.assertEqual(sorted(r[1] for r in journal(self.task)), ['уже перемещён', 'уже перемещён'])
        intent = (self.task / 'Намерение перемещения.tsv').read_text(encoding='utf-8')
        self.assertIn(f'\tкорень\tсоздан\t\t{R4577}\t', intent)
        self.assertIn('\tx-1\tпапка\tвыполнено\t', intent)

    def test_old_and_empty_strip_column(self):
        """П. 6: задание без 7-й колонки (1.1) и с пустой «снять» - прежнее поведение, шаблон не падает."""
        for tail in ('', '\t'):
            (self.task / 'перемещение.tsv').write_text(f'A\\1.jpg\t10\t0\t{R4577}\t{"AB" * 32}\tпроверка{tail}\n',
                                                     encoding='utf-8')
            (self.task / 'папки целиком.tsv').write_text(f'A\t{R4577}\t1\t0{tail}\n', encoding='utf-8')
            (self.task / 'корни.tsv').write_text(f'{R4577}\tновый\n', encoding='utf-8')
            self.put('A\\1.jpg', 10)
            code, outp = run_ps(self.task, self.disk)
            self.assertEqual(code, 0, outp)
            self.assertTrue((self.disk / R4577 / 'A' / '1.jpg').exists(), tail)
            shutil.rmtree(self.disk)
            for x in self.task.glob('Журнал перемещения *.tsv'):
                x.unlink()
            (self.task / 'Намерение перемещения.tsv').unlink()

    def test_whole_root_rename_foreign_target(self):
        items = [(R45 + '\\A\\1.jpg', 10)]
        self.plan2(items, whole=[(R45, 1)])
        self.put(items[0][0], 10)
        (self.disk / R4577).mkdir()                                                   # чужая папка с тем же именем
        code, outp = run_ps(self.task, self.disk)
        self.assertEqual(code, 1, outp)
        self.assertIn('программа её не создавала', outp)
        self.assertTrue((self.disk / R45 / 'A' / '1.jpg').exists())


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
        self.assertEqual(tp.state_text(rows[0])[0], 'Идёт · 85 МБ/с · осталось 7 мин')       # этап 9: всё в «Состоянии»
        page = tp.TasksPage(FakeWin())
        page.resize(1500, 900)
        page.render(rows, groups=[])
        QAPP.processEvents()
        self.assertIn('Samsung 750', page.t.item(0, 1).toolTip())                # названия дисков - в подсказке
        self.assertEqual(page.t.item(0, 3).text(), '1 234 из 5 678')
        self.assertFalse(page.t.item(0, 0).flags() & tp.Qt.ItemIsUserCheckable)   # у идущего галочки нет
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


class TasksPageMockupTest(unittest.TestCase):
    """Этап 9 (16.11.2026): экран «Задания на копирование» по макету владельца."""

    GIB = 1024 ** 3

    def row(self, task, state, folder='Котуй 2026', direction='Работа и Сафари', disks=('HDD78',), targets=None,
            group=None, total=5947, done=None, hashed=None, errors=0, skipped=0, **kw):
        meta = {'носитель': 'HDD09', 'папка': folder, 'имя направления': direction, 'обязательные диски': list(disks),
                'цели': list(targets or disks)}
        if group:
            meta['группа'] = group
        done = total if done is None else done
        r = dict(task=task, kind='копирование', state=state, total=total, done=done, good=done - errors - skipped,
                 errors=errors, skipped=skipped, examples=[], journal='', labels={}, serials=set(), src_serial='S09',
                 src='HDD09', src_letter='F:', targets=list(targets or disks), done_b=336.6 * self.GIB,
                 total_b=336.6 * self.GIB, hashed=done if hashed is None else hashed, log_ts=0, meta=meta, left=0,
                 disks='HDD09 → ' + ', '.join(targets or disks), last_res='')
        r.update(kw)
        return r

    def family(self, s45, s77):
        g = 'HDD09 — Свадьба — Семейный архив'
        kw = dict(folder='Свадьба', direction='Семейный архив', disks=('HDD45', 'HDD77'), group=g, total=100)
        return [self.row(g + ' — на 45', s45, targets=['HDD45'], **kw),
                self.row(g + ' — на 77', s77, targets=['HDD77'], **dict(kw, done=0 if s77 == 'не запускалось' else None))]

    def test_summary_and_texts(self):
        run = self.row('A', 'идёт', done=4120, speed=410 * 1024 ** 2, eta=720, eta_text='~12 мин', ago=3)
        stop = self.row('B', 'прервано', done=10, last_res='ОШИБКА: диск переполнен')
        rows = [run, stop, self.row('C', 'не запускалось', done=0), self.row('D', 'готово с ошибками', errors=2),
                self.row('E', 'готово'), self.row('F', 'состояние неизвестно', done=3)]
        self.assertEqual(tp.summary(rows, queue=['C']), [('Идёт: 1', '#1565c0'), ('Ждут запуска: 1 (в очереди 1)', None),
                                                          ('Прервано, с ошибками: 2', tp.RED), ('Готово: 1', '#2e7d32'),
                                                          ('Неизвестно: 1', tp.GREY)])
        self.assertEqual(tp.summary([])[2], ('Прервано, с ошибками: 0', None))          # не красная, если 0
        self.assertEqual(tp.what_where(run), ('HDD09 · F:\\Котуй 2026', '→ Работа и Сафари — HDD78'))
        fam = self.family('готово', 'не запускалось')[0]
        self.assertEqual(tp.what_where(fam)[1], '→ Семейный архив — на 45 (HDD45)')
        self.assertEqual(tp.what_where(dict(run, src_letter=''))[0], 'HDD09 · Котуй 2026')   # носитель не подключён
        self.assertEqual(tp.state_text(run)[0], 'Идёт · 410 МБ/с · осталось 12 мин')
        self.assertEqual(tp.state_text(stop)[0], 'Прервано · последняя запись: ОШИБКА: диск переполнен')
        self.assertEqual(tp.state_text(dict(stop, last_res='скопирован, размер и SHA-256 совпали'))[0],
                         'Прервано · повторный запуск продолжит')
        self.assertEqual(tp.state_text(rows[2], queue=['C'])[0], 'В очереди')
        self.assertEqual([tp.checkable(r) for r in rows], [False, True, True, False, True, False])
        self.assertEqual([r['task'] for r in tp.run_all_set(rows)], ['B', 'C'])
        page = tp.TasksPage(FakeWin())
        page.render(rows, groups=[])
        self.assertEqual(page.t.rowCount(), 5)                                     # «готово» - не в таблице
        self.assertEqual(page.t.cellWidget(0, 1).text().split('<br>')[0], 'HDD09 · F:\\Котуй 2026')
        self.assertEqual(page.t.item(0, 3).text(), '4 120 из 5 947')
        self.assertEqual(page.t.item(3, 4).text(), '2')
        self.assertEqual(page.t.item(3, 4).foreground().color().name(), tp.RED)
        red = next(c for c in page.chips if c.text().startswith('Прервано'))
        self.assertIn(tp.RED, red.styleSheet())

    def test_move_block_and_family_branches(self):
        page = tp.TasksPage(FakeWin())
        page.render([self.row('W', 'готово')], groups=[])
        it = page.offers[0]
        self.assertEqual(it['line'], 'F:\\Котуй 2026 → F:\\Скопировано на Работа и Сафари (78)\\Котуй 2026')
        self.assertEqual(it['small'], 'Копии проверены по хешу на диске 78 · 5 947 файлов, 336,6 ГБ')
        btn = next(b for o, b in page.offer_buttons if o is it)
        self.assertEqual(btn.text(), 'Переместить')
        self.assertTrue(btn.isEnabled())
        calls = []
        page.move_v3 = lambda o: calls.append(o['copy_task'])                    # тот же вызов, что раньше
        btn.click()
        self.assertEqual(calls, ['W'])
        # не все строки проверены по хешу - так и написано
        page.render([self.row('W', 'готово', hashed=5000)], groups=[])
        self.assertTrue(page.offers[0]['small'].startswith('Скопировано на диске 78; по журналу копирования SHA-256 сверен у 5 000 из 5 947'))
        # Семейный архив: на 45 готово, на 77 ждёт - кнопка неактивна
        page.render(self.family('готово', 'не запускалось'), groups=[])
        it = page.offers[0]
        self.assertEqual(it['small'], 'На 45 скопировано и проверено · на 77 ждёт запуска')
        self.assertEqual(it['line'], 'F:\\Свадьба → F:\\Скопировано на Семейный архив (45 и 77)\\Свадьба')
        btn = next(b for o, b in page.offer_buttons if o is it)
        self.assertFalse(btn.isEnabled())
        page.on_offer(it, 'Переместить')                                          # и вызов ничего не делает
        self.assertEqual(calls, ['W'])
        # оба диска готовы - обычная строка с активной кнопкой
        page.render(self.family('готово', 'готово'), groups=[])
        it = page.offers[0]
        self.assertEqual(it['small'], 'Копии проверены по хешу на дисках 45 и 77 · 100 файлов, 336,6 ГБ')
        self.assertTrue(next(b for o, b in page.offer_buttons if o is it).isEnabled())
        # созданное, но не запущенное перемещение - «Запустить перемещение» (как раньше)
        mv = dict(self.row('W — перемещение', 'не запускалось', total=3, done=0), kind='перемещение', meta=None,
                  move_meta={'задание копирования': 'W', 'куда': 'Скопировано на Работа и Сафари (78)', 'папка': 'Котуй 2026',
                             'создано_ts': 1})
        page.render([self.row('W', 'готово'), mv], groups=[])
        self.assertEqual(page.offers[0]['buttons'], ['Запустить перемещение'])
        self.assertEqual(tp.what_where(mv)[1], '→ перемещение внутри носителя в «Скопировано на Работа и Сафари (78)»')
        # пусто
        page.render([], groups=[])
        self.assertEqual(page.offers, [])
        self.assertEqual(page.offer_lay.itemAt(0).widget().text(), tp.MOVE_EMPTY)

    def test_code_review_fixes(self):
        # 1. повтор тех же файлов не засчитывается дважды: по уникальному ключу (диск, путь без буквы тома)
        k = lambda p: tp._file_key(('HDD78', p))                                    # noqa: E731
        self.assertEqual(k('F:\\Котуй\\1.jpg'), k('g:\\котуй\\1.JPG'))            # буква носителя сменилась
        orig = self.row('W', 'готово с ошибками', total=3, hashed=2, hashed_keys=frozenset({k('F:\\a'), k('F:\\b')}))
        dup = self.row('W — повтор 1', 'готово', total=1, hashed=1, hashed_keys=frozenset({k('G:\\b')}))
        self.assertTrue(tp.hash_words([orig], [dup]).startswith(
            'Скопировано на диске 78; по журналу копирования SHA-256 сверен у 2 из 3'))   # было бы «проверены» (2+1)
        new = dict(dup, hashed_keys=frozenset({k('F:\\c')}))
        self.assertEqual(tp.hash_words([orig], [new]), 'Копии проверены по хешу на диске 78')
        # 3. «готово с ошибками», источник - диск направления (блока перемещения нет): галочка есть
        r = self.row('X', 'готово с ошибками', errors=1)
        self.assertFalse(tp.checkable(r))                                          # повтор - кнопкой в блоке
        r['meta']['перемещать на носителе'] = False
        self.assertTrue(tp.checkable(r))
        offers, _ = tp.move_items([r])
        self.assertEqual(offers, [])                                               # блока нет - повтор только галочкой
        page = tp.TasksPage(FakeWin())
        page.render([r], groups=[])
        page.t.item(0, 0).setCheckState(tp.Qt.Checked)
        self.assertEqual(page.run_btn.text(), 'Запустить отмеченные (1)')
        # 4. корень носителя: и None, и пустая строка, с буквой и без
        for folder in (None, ''):
            self.assertEqual(tp.what_where(self.row('R', 'готово', folder=folder))[0], 'HDD09 · F:\\ (файлы в корне)')
            self.assertEqual(tp.what_where(self.row('R', 'готово', folder=folder, src_letter=''))[0],
                             'HDD09 · (файлы в корне)')
            self.assertEqual(tp.move_line('F:', 'HDD09', folder, 'Скопировано на Р (78)'),
                             'F:\\ (файлы в корне) → F:\\Скопировано на Р (78)\\')
        # 5. подпись «Готово»
        self.assertEqual(page.done_t.horizontalHeaderItem(3).text(), 'Ошибок и пропусков')
        # 6. «Обновить» много раз - плашки не копятся (4 плашки + растяжка)
        for _ in range(5):
            page.render([r], groups=[])
        self.assertEqual(page.chips_lay.count(), 5)
        self.assertEqual(len(page.chips), 4)

    def test_done_list_collapsed(self):
        page = tp.TasksPage(FakeWin())
        page.show()
        rows = [self.row('Готовое 1', 'готово', log_ts=time.mktime((2026, 11, 16, 12, 0, 0, 0, 0, -1))),
                self.row('Идёт', 'идёт', done=1)]
        page.render(rows, groups=[])
        QAPP.processEvents()
        self.assertEqual(page.done_btn.text(), '▸ Готово (1)')
        self.assertTrue(page.done_t.isHidden())                                   # свёрнуто
        page.done_btn.click()
        self.assertFalse(page.done_t.isHidden())
        self.assertEqual(page.done_btn.text(), '▾ Готово (1)')
        self.assertEqual([page.done_t.item(0, c).text() for c in range(5)],
                         ['Готовое 1', '5 947', '336,6', '0', '16.11.2026'])
        page.done_t.selectRow(0)
        self.assertEqual(page.current()['task'], 'Готовое 1')                     # «Открыть папку задания» - для неё
        page.t.selectRow(0)
        self.assertEqual(page.current()['task'], 'Идёт')                          # выделение - одно на обе таблицы
        self.assertFalse(page.done_t.selectionModel().selectedRows())
        page.done_btn.click()
        self.assertTrue(page.done_t.isHidden())
        page.close()


if __name__ == '__main__':
    unittest.main()
