"""Логика v3, этап 1 «ядро» (15.11.2026): направления, отметки, маршрут, итог разбора, задания по отметкам.

Запуск из корня проекта:  py -m unittest catalog.test_logic_v3
Временные данные; настоящие диски, таблицы и задания не используются.
"""
import collections
import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hashbase as hb                                        # noqa: E402
import service as sv                                         # noqa: E402
from hb_core import razbor as rz                             # noqa: E402
from hb_core.derived import folder_type                      # noqa: E402
from hb_core.consts import F_JUNK, F_PHOTO, F_TEXT, F_VIDEO  # noqa: E402
from hb_cmd import candel as c_candel, missing as c_missing, mklist as c_mklist, mvlist as c_mvlist  # noqa: E402
from test_hashbase import LOG_HEAD, NS, S, Base, make_disk    # noqa: E402

H = {i: f'{i:064x}' for i in range(1, 60)}
SRC = 'HDD60'
FILES = [                                                    # (путь, размер, sha или None)
    ('Поход 2010\\Фото\\1.jpg', 100, S[1]),                  # есть на 45 и на 77 (обвязка Base)
    ('Поход 2010\\Фото\\2.jpg', 200, S[2]),                  # есть только на 45
    ('Поход 2010\\Фото\\Thumbs.db', 5, None),                # мусор
    ('Поход 2010\\описание.doc', 10, None),                  # документ рядом (фото - в подпапке)
    ('Поход 2010\\Монтаж\\проект.prproj', 50, None),         # не подходит по типу семейному
    ('Поход 2010\\Монтаж\\clip.mp4', 600, H[20]),
    ('Поход 2010\\Монтаж\\clip копия.mp4', 600, H[20]),      # то же содержимое - дубль внутри задания
    ('Работа\\отчёт.doc', 20, None),
    ('Работа\\схема.jpg', 70, H[21]),
    ('Документы\\письмо.doc', 30, None),                     # фото рядом нет - не подходит
    ('Друзья\\a.jpg', 90, H[22]),
    ('Друзья\\Наши\\b.jpg', 95, H[23]),
    ('Смешанная\\заметка.txt', 7, None),                     # основание - только подпапка с другой отметкой
    ('Смешанная\\Чужое\\c.jpg', 40, H[24]),
    ('ПЕРЕНЕСЕНО → 45 и 77\\Старое\\z.jpg', 300, H[25]),     # перенесено раньше (v2)
    ('корень.jpg', 80, H[26]),
    ('корень.txt', 3, None),                                 # документ в корне носителя - не «рядом»
]
DIRS = [dict(name='Семейный архив', disks=['HDD45', 'HDD77'], kind=hb.KIND_MEDIA, note=''),
        dict(name='Работа', disks=['HDD91'], kind=hb.KIND_ALL, former=['Сафари'], note=''),
        dict(name='Без диска', disks=[], kind=hb.KIND_ALL, note='')]


def args(**kw):
    a = dict(disk=None, name=None, folder=None, dry=False, task=None, allow_main=False, recheck=None, task_root='scripts')
    a.update(kw)
    return NS(**a)


class V3Base(Base):
    def setUp(self):
        super().setUp()
        make_disk(self.scans, SRC, 'AAAA0060', [(p, s, h) for p, s, h in FILES if h],
                  unhashed=[(p, s) for p, s, h in FILES if not h])
        self.quiet(hb.connect)
        sv.add_directions_batch(DIRS)

    def mark(self, *rows, disk=SRC):
        return sv.add_marks_batch(disk, list(rows))

    def plan(self, disk=SRC, drafts=(), detail=False):
        P = sv._plan(disk, drafts, detail)
        self.assertEqual(P.errors, [])
        return P

    def a(self, P, outcome, num=None):
        return tuple(P.part_a.get((outcome, num), (0, 0)))


class DirectionsTest(V3Base):
    def test_numbers_rename_former_and_checks(self):
        d = sv.directions()
        self.assertEqual([(x.num, x.name) for x in d.values()], [('Н1', 'Семейный архив'), ('Н2', 'Работа'), ('Н3', 'Без диска')])
        self.assertEqual(d['Н1'].folder(), 'Скопировано на Семейный архив (45 и 77)')
        self.assertEqual(d['Н2'].folder(), 'Скопировано на Работа (91)')
        sv.add_direction(num='Н2', name='Работа и Сафари')
        d = sv.directions()
        self.assertEqual(d['Н2'].name, 'Работа и Сафари')
        self.assertEqual(set(d['Н2'].former), {'Сафари', 'Работа'})
        with self.assertRaises(sv.Refused):                       # прежнее имя другого направления занять нельзя
            sv.direction_preview(num='Н3', name='Работа')
        with self.assertRaises(sv.Refused):                       # один диск - одному направлению
            sv.direction_preview(num='Н3', add_disks=['HDD45'])
        with self.assertRaises(sv.Refused):
            sv.direction_preview(name='Фото: 2010')               # символ, запрещённый в имени папки
        with self.assertRaises(sv.Refused):
            sv.direction_preview(name='x' * 31)
        with self.assertRaises(sv.Refused):
            sv.direction_preview(num='Н1', name='Семейный архив')  # ничего не меняется
        with self.assertRaises(sv.Refused):
            sv.direction_preview(name='Новое', disks=['HDD999'])   # диска нет в базе
        sv.add_direction(num='Н3', add_disks=['HDD90'])
        self.assertEqual(sv.directions()['Н3'].disks, ('HDD90',))
        with self.assertRaises(sv.Refused):                       # повтор пакета по умолчанию - всё уже есть
            sv.add_directions_batch(DIRS[:1])

    def test_default_directions_command(self):
        for d in ('HDD78', 'HDD55'):
            make_disk(self.scans, d, 'AAAA00' + d[3:], [])
        hb.DIRECTIONS.unlink()
        self.quiet(hb.connect)
        pv = sv.directions_batch_preview(sv.DEFAULT_DIRECTIONS)
        self.assertEqual(len(pv['fields']), 6)
        sv.add_directions_batch(sv.DEFAULT_DIRECTIONS)
        d = sv.directions()
        self.assertEqual(d['Н2'].name, 'Работа и Сафари')
        self.assertEqual(d['Н2'].disks, ('HDD78',))
        self.assertEqual(d['Н3'].disks, ('HDD55',))
        self.assertEqual(d['Н5'].name, 'Саша, Таня, Наташа')
        self.assertEqual(d['Н5'].disks, ())
        self.assertIsNotNone(hb.find_direction(d, 'Сафари'))      # старый «раздел: Сафари»


class RouteTest(V3Base):
    def test_all_except_marked_mode(self):
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('Друзья', 'не копировать'), ('Смешанная\\Чужое', 'не копировать'))
        P = self.plan()
        self.assertEqual(P.total, [len(FILES), sum(s for _, s, _ in FILES)])
        self.assertEqual(sum(v[0] for v in P.part_a.values()), len(FILES))
        self.assertEqual(sum(v[1] for v in P.part_a.values()), P.total[1])
        # семейный: 1.jpg есть везде; 2.jpg, clip×2, описание.doc (рядом с фото), корень.jpg - копировать
        self.assertEqual(self.a(P, rz.O_HAVE, 'Н1'), (1, 100))
        self.assertEqual(self.a(P, rz.O_COPY, 'Н1'), (5, 200 + 600 + 600 + 10 + 80))
        # не подходит: проект монтажа, письмо без фото рядом, документ в корне, заметка (фото - только в чужой подпапке)
        self.assertEqual(self.a(P, rz.O_TYPE, 'Н1'), (4, 50 + 30 + 3 + 7))
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (2, 90))     # «все файлы»
        self.assertEqual(self.a(P, rz.O_SKIP), (3, 90 + 95 + 40))  # наследование в подпапку «Друзья\Наши»
        self.assertEqual(self.a(P, rz.O_JUNK), (1, 5))
        self.assertEqual(self.a(P, rz.O_MOVED), (1, 300))         # отметка носителя в «ПЕРЕНЕСЕНО» не наследуется
        # часть Б: на 45 - clip один раз (дубль в задании), корень.jpg, описание.doc; на 77 - ещё 2.jpg
        self.assertEqual(tuple(P.part_b['HDD45']), (3, 600 + 80 + 10))
        self.assertEqual(tuple(P.part_b['HDD77']), (4, 200 + 600 + 80 + 10))
        self.assertEqual(tuple(P.part_b['HDD91']), (2, 90))
        self.assertEqual([x[0] for x in P.docs_near], ['Поход 2010'])
        self.assertIn(P.docs_near[0][3], {'Поход 2010\\Фото', 'Поход 2010\\Монтаж'})   # основание - подпапка с фото
        groups = {g[1]: g for g in rz.group_rows(P)}
        self.assertEqual(set(groups), {'Поход 2010', 'Работа', '(файлы в корне)', 'Документы', 'Смешанная'})
        self.assertEqual(groups['Документы'][2], rz.G_TYPE)

    def test_only_marked_mode_and_case_insensitive(self):
        self.mark(('', 'не копировать'), ('поход 2010\\фото', 'Н1'))   # регистр - как в Windows
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_COPY, 'Н1'), (1, 200))
        self.assertEqual(self.a(P, rz.O_HAVE, 'Н1'), (1, 100))
        self.assertEqual(self.a(P, rz.O_JUNK), (1, 5))
        self.assertEqual(self.a(P, rz.O_SKIP), (len(FILES) - 4, P.total[1] - 305 - 300))
        rows = [r for r in hb.read_table(hb.DECISIONS) if r and r[0] == SRC]
        self.assertEqual(rows[-1][1], 'Поход 2010\\Фото')           # записан путь как в базе

    def test_repeat_last_wins_and_inherit(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        self.mark(('Работа', 'не копировать'))                       # последняя действует
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (0, 0))
        with self.assertRaises(sv.Refused):                           # та же отметка ещё раз - писать нечего
            self.mark(('Работа', 'не копировать'))
        self.mark(('Работа', 'как у родителя'))                       # снять - снова семейный по наследству
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_SKIP), (0, 0))
        with self.assertRaises(sv.Refused):
            self.mark(('Работа', 'как у родителя'))
        with self.assertRaises(sv.Refused):                           # дважды в пакете
            sv.marks_preview(SRC, [('Друзья', 'Н1'), ('друзья', 'Н2')])
        with self.assertRaises(sv.Refused):
            sv.marks_preview(SRC, [('Нет такой', 'Н1')])
        with self.assertRaises(sv.Refused):
            sv.marks_preview(SRC, [('Друзья', 'Н9')])

    def test_drafts_apply_after_saved(self):
        self.mark(('', 'Н1'))
        P = self.plan(drafts=[('Работа', 'Н2'), ('Работа', 'как у родителя'), ('Друзья', 'не копировать')])
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (0, 0))
        self.assertEqual(self.a(P, rz.O_SKIP)[0], 2)
        self.assertEqual(len([r for r in hb.read_table(hb.DECISIONS) if r and r[0] == SRC]), 1)   # черновик не записан

    def test_direction_without_disk_and_file_mark(self):
        self.mark(('', 'Н1'), ('Документы', 'Без диска'), ('Поход 2010\\Монтаж\\проект.prproj', 'Н2'))
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_NODISK, 'Н3'), (1, 30))
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (1, 50))        # файл без хеша со своей отметкой
        self.assertEqual(self.a(P, rz.O_TYPE, 'Н1'), (1, 3))          # проект монтажа ушёл своей отметкой
        res = sv.razbor_tasks(SRC, dry=True)
        self.assertNotIn('Н3', {s['num'] for s in res['specs']})
        self.assertIn(rz.G_NODISK, {g['state'] for g in res['states']})

    def test_moved_folder_explicit_mark_copies(self):
        self.mark(('', 'Н1'), ('Старое', 'Н2'))                      # исходный путь папки в «ПЕРЕНЕСЕНО → …»
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_MOVED), (0, 0))
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (1, 300))
        self.assertEqual(P.moved_copy, [1, 300])
        # отметка папки внутри служебной пишется по исходному пути
        pv = sv.marks_preview(SRC, [('ПЕРЕНЕСЕНО → 45 и 77\\Старое', 'не копировать')])
        self.assertEqual(pv['fields'][0][1], 'Старое')
        with self.assertRaises(sv.Refused):
            sv.marks_preview(SRC, [('ПЕРЕНЕСЕНО → 45 и 77', 'Н1')])

    def test_legacy_rows(self):
        hb.ensure_tables()
        with open(hb.DECISIONS, 'a', encoding='utf-8') as f:
            f.write(f'{SRC}\tРабота\tраздел: Сафари\tстарое\n{SRC}\tДрузья\tраздел: Неизвестный\t\n'
                    f'{SRC}\tДокументы\tне нужно\t\n{SRC}\tСмешанная\tпока не трогаем\t\n')
        self.mark(('', 'Н1'))
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (2, 90))        # «раздел: Сафари» - прежнее имя Н2
        self.assertEqual(self.a(P, rz.O_UNSET), (2, 185))
        self.assertEqual(self.a(P, rz.O_SKIP), (3, 30 + 7 + 40))

    def test_source_is_direction_disk(self):
        self.mark(('', 'Н1'), disk='HDD45')                           # на диске своего направления - можно
        P = self.plan('HDD45')
        self.assertEqual(dict(P.part_b), {'HDD77': [1, 200]})        # X\2.jpg - только на 77
        self.assertEqual(self.a(P, rz.O_HAVE, 'Н1'), (1, 100))
        self.assertEqual(P.info['is_target'], ['Н1'])
        res = sv.razbor_tasks('HDD45', dry=False)
        self.assertEqual([s['targets'] for s in res['specs']], [['HDD77']])
        man = json.loads(res['manifest'].read_text(encoding='utf-8'))
        self.assertFalse(man['перемещать на носителе'])

    def test_already_on_each_disk_separately(self):
        self.mark(('', 'Н1'))
        P = self.plan()
        self.assertNotIn('Поход 2010\\Фото\\2.jpg', {r[1] for r in P.rows.get(((1, 'Поход 2010'), 'HDD45'), [])})
        P = self.plan(detail=True)
        g = next(k for k in P.groups if k[1] == 'Поход 2010')
        self.assertNotIn('Поход 2010\\Фото\\2.jpg', {r[1] for r in P.rows[(g, 'HDD45')]})
        self.assertIn('Поход 2010\\Фото\\2.jpg', {r[1] for r in P.rows[(g, 'HDD77')]})
        self.assertNotIn('Поход 2010\\Фото\\1.jpg', {r[1] for d in ('HDD45', 'HDD77') for r in P.rows[(g, d)]})
        clip = [r for r in P.rows[(g, 'HDD45')] if 'clip' in r[1]]
        self.assertEqual([r[1] for r in clip], ['Поход 2010\\Монтаж\\clip копия.mp4'])   # наименьший путь
        self.assertEqual([d[0] for d in P.deps[(g, 'HDD45')]], ['Поход 2010\\Монтаж\\clip.mp4'])

    def test_aggregate_equals_per_file_reference(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'), ('Смешанная\\Чужое', 'не копировать'),
                  ('Старое', 'Н2'), ('Документы', 'Без диска'))
        P = self.plan()
        dirs = sv.directions()
        ms = hb.MarkSet.build(hb.mark_rows(SRC, hb.table_bytes(hb.DECISIONS)), dirs)
        on = {d: {sha for (sha,) in self.db().execute('select sha from files where disk=? and sha is not null', (d,))}
              for d in ('HDD45', 'HDD77', 'HDD91')}
        ref = collections.Counter()

        def route(path):                     # независимо: самая глубокая отметка над файлом, по частям пути
            parts = path.split('\\')
            moved = parts[0].startswith('ПЕРЕНЕСЕНО')
            if moved:
                parts = parts[1:]
            for i in range(len(parts) - 1, -1 if not moved else 0, -1):
                m = ms.get('\\'.join(parts[:i]))
                if m:
                    return m, moved
            return None, moved

        def media_basis(folder, mrow):
            for p, s, h in FILES:
                if p.startswith(folder + '\\') and folder_type(p, p.rsplit('\\', 1)[-1].lower(), s) in (F_PHOTO, F_VIDEO):
                    m, _ = route(p)
                    if m and m.row == mrow:
                        return True
            return False

        for p, s, h in FILES:
            m, moved = route(p)
            k = folder_type(p, p.rsplit('\\', 1)[-1].lower(), s)
            if moved and not (m and m.kind == hb.R_DIR):
                ref[(rz.O_MOVED, None)] += 1
                continue
            if m.kind == hb.R_SKIP:
                ref[(rz.O_SKIP, None)] += 1
                continue
            d = dirs[m.num]
            if not d.disks:
                ref[(rz.O_NODISK, d.num)] += 1
                continue
            if k == F_JUNK:
                ref[(rz.O_JUNK, None)] += 1
                continue
            folder = p.rsplit('\\', 1)[0] if '\\' in p else ''
            ok = (not d.media_only or k in (F_PHOTO, F_VIDEO)
                  or (k == F_TEXT and folder and media_basis(folder, m.row)))
            if not ok:
                ref[(rz.O_TYPE, d.num)] += 1
            elif h and all(h in on[x] for x in d.disks):
                ref[(rz.O_HAVE, d.num)] += 1
            else:
                ref[(rz.O_COPY, d.num)] += 1
        self.assertEqual({k: v[0] for k, v in P.part_a.items() if v[0]}, dict(ref))


class TasksTest(V3Base):
    def test_dry_then_create_then_repeat(self):
        self.mark(('', 'Н1'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        res = sv.razbor_tasks(SRC, dry=True)
        self.assertFalse(hb.TASKS.exists() and any(hb.TASKS.iterdir()))
        names = {s['name'] for s in res['specs']}
        fam = [f'HDD60 — {x} — Семейный архив — на {d}' for x in ('Поход 2010', '(файлы в корне)', 'Смешанная')
               for d in (45, 77)]
        self.assertEqual(names, set(fam) | {'HDD60 — Работа — Работа'})          # этап 5: на 45 и на 77 - отдельно
        res = sv.razbor_tasks(SRC, dry=False)
        rows = []
        for d in ('45', '77'):
            t = hb.TASKS / f'HDD60 — Поход 2010 — Семейный архив — на {d}'
            got = [x.split('\t') for x in (t / 'список.tsv').read_text(encoding='utf-8').splitlines()]
            self.assertEqual({r[0] for r in got}, {'HDD' + d})                   # в задании - только свой диск
            self.assertEqual((t / 'тома.tsv').read_text(encoding='utf-8').splitlines(),
                             ['HDD60\tAAAA0060', f'HDD{d}\tAAAA00{d}'])
            rows += got
        self.assertEqual(sorted((r[0], r[1]) for r in rows), [
            ('HDD45', 'Поход 2010\\Монтаж\\clip копия.mp4'), ('HDD45', 'Поход 2010\\описание.doc'),
            ('HDD77', 'Поход 2010\\Монтаж\\clip копия.mp4'), ('HDD77', 'Поход 2010\\Фото\\2.jpg'),
            ('HDD77', 'Поход 2010\\описание.doc')])
        meta = json.loads((t / 'разбор.json').read_text(encoding='utf-8'))
        self.assertEqual(meta['обязательные диски'], ['HDD45', 'HDD77'])
        self.assertEqual(meta['что копировать'], hb.KIND_MEDIA)
        self.assertTrue((t / 'Копировать.ps1').exists())
        man = json.loads(res['manifest'].read_text(encoding='utf-8'))
        self.assertEqual(man['статус'], 'готово')
        self.assertTrue(man['перемещать на носителе'])
        self.assertEqual(sv.task_state(t, running=[])['state'], 'не запускалось')
        self.assertFalse(list(hb.RAZBORY.glob('*.tmp')))
        res = sv.razbor_tasks(SRC, dry=False)                        # повтор: всё уже подготовлено
        self.assertTrue(all(s.get('exists') for s in res['specs']))
        self.assertIsNone(res['manifest'])
        self.quiet(lambda: None)

    def test_blocked_destination_paths(self):
        # на 45 по пути назначения лежит другое подтверждённое содержимое - строка не включается («конфликт»)
        make_disk(self.scans, 'HDD92', 'AAAA0092', [])
        hb.close_last()
        job = next(self.scans.glob('HDD45 - тест/*'))
        import sqlite3
        for fn, row in (('hashes.sqlite', ("insert into hashes values ('HDD45', ?, 10, '0', '', ?, 'verified', '')",
                                           ('ПЕРЕНОС с других дисков\\HDD60\\Поход 2010\\описание.doc', H[40]))),
                        ('inventory.sqlite', ("insert into files values (?, 10, '0', '0', '', 32, 'other')",
                                              ('ПЕРЕНОС с других дисков\\HDD60\\Поход 2010\\описание.doc',)))):
            con = sqlite3.connect(job / fn)
            con.execute(row[0], row[1])
            con.commit(); con.close()
        self.quiet(hb.cmd_rebuild, NS())
        self.mark(('', 'Н1'))
        P = self.plan(detail=True)
        # у источника хеша нет - сравнить нельзя: «нужна проверка», а не «конфликт»
        self.assertIn(('Поход 2010\\описание.doc', 'HDD45', rz.B_CHECK, 10), P.blocked)
        g = next(k for k in P.groups if k[1] == 'Поход 2010')
        self.assertNotIn('Поход 2010\\описание.doc', {r[1] for r in P.rows[(g, 'HDD45')]})
        self.assertIn('Поход 2010\\описание.doc', {r[1] for r in P.rows[(g, 'HDD77')]})
        self.assertEqual(P.group_state(g), rz.G_BLOCKED)


class CompatTest(V3Base):
    """Старые команды: ответы до и после добавления отметок v3 одинаковы (в том числе «*», пустой путь, регистр)."""

    def answers(self):
        res = []
        for fn, a in ((c_candel.cmd_candel, NS(disk=SRC, folder='Поход 2010')),
                      (c_candel.cmd_candel, NS(disk=SRC, folder='')),
                      (c_missing.cmd_missing, NS(disk=SRC, folder='', depth=1)),
                      (c_mklist.cmd_mklist, NS(disk=SRC, to=['HDD45', 'HDD77'], name='x', folder=None, dry=True,
                                               section=None, all=False, source_folder=None, as_name=None, whole=False,
                                               task_root='scripts')),
                      (c_mvlist.cmd_mvlist, args(disk=SRC, dry=True))):
            self.quiet(fn, a)
            res.append('\n'.join(x for x in self.printed.splitlines() if 'ответы' not in x))
        return res

    def test_old_commands_unchanged(self):
        hb.ensure_tables()
        with open(hb.DECISIONS, 'a', encoding='utf-8') as f:
            f.write(f'{SRC}\tДрузья\tне нужно\t\n{SRC}\tРабота\tраздел: Работа\t\n*\tкласс: служебные и временные\tне нужно\t\n')
        before = self.answers()
        self.mark(('', 'Н1'), ('Поход 2010', 'не копировать'), ('поход 2010\\фото', 'Н1'), ('Друзья', 'Н2'),
                  ('Работа', 'как у родителя'))
        with open(hb.DECISIONS, 'a', encoding='utf-8') as f:
            f.write('*\tДокументы\tне копировать\t\n')
        self.assertEqual(self.answers(), before)
        self.assertEqual(hb.decisions_for(SRC), [('Друзья', 'не нужно'), ('Работа', 'раздел: Работа')])


class MovedRootsTest(V3Base):
    def test_copied_folder_known_only_from_move_journal(self):
        os.utime(next(self.scans.glob('HDD60 - тест/*')) / 'inventory.sqlite', (1580000000, 1580000000))
        t = self.out / 'Перенос HDD60'
        t.mkdir()
        (t / 'тома.tsv').write_text('HDD60\tAAAA0060\n', encoding='utf-8')
        head = ('время', 'результат', 'размер', 'sha-256', 'откуда', 'куда')
        root = 'Скопировано на Работа (91)'
        (t / 'Журнал перемещения 2025-01-01 00-00-00.tsv').write_text(
            '\t'.join(head) + '\n' + f'10:00\tперемещён\t70\t{H[21]}\tK:\\Работа\\схема.jpg\tK:\\{root}\\Работа\\схема.jpg\n',
            encoding='utf-8-sig')
        c = self.db()
        self.assertEqual(c.execute('select folder from moved_roots where disk=?', (SRC,)).fetchall(), [(root,)])
        self.assertTrue(c.execute('select 1 from files where disk=? and path=?', (SRC, root + '\\Работа\\схема.jpg')).fetchone())
        self.mark(('', 'Н1'), ('Работа', 'Н2'))
        P = self.plan()
        # старая «ПЕРЕНЕСЕНО» (носитель не наследуется) + схема в «Скопировано на …»: этап 13 - исходная отметка
        # «Работа» внутрь «Скопировано на …» не проникает (там действуют только отметки, поставленные внутри)
        self.assertEqual(self.a(P, rz.O_MOVED), (2, 300 + 70))
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (1, 20))        # отчёт.doc, оставшийся на старом месте
        self.assertEqual(P.moved_copy, [0, 0])
        self.mark((root + '\\Работа', 'Н2'))                         # отметка внутри служебной - по нынешнему пути
        P = self.plan()
        self.assertEqual(self.a(P, rz.O_COPY, 'Н2'), (2, 70 + 20))   # схемы нет на 91 - копируется (второй проход)
        self.assertEqual(P.moved_copy, [0, 0])
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn('ИТОГ: совпала', self.printed)                  # сборка по шагам = с нуля (moved_roots тоже)
        self.assertEqual(hb.copied_folder('Работа', ['HDD91']), root)

    def test_owner_named_folder_is_ordinary(self):
        # папка, которую владелец сам назвал «Скопировано на …», служебной не считается (журнала перемещения нет)
        make_disk(self.scans, 'HDD61', 'AAAA0061', [('Скопировано на Семейный архив (45 и 77)\\q.jpg', 10, H[30])])
        self.quiet(hb.connect)
        self.mark(('', 'Н1'), disk='HDD61')
        P = self.plan('HDD61')
        self.assertEqual(self.a(P, rz.O_COPY, 'Н1'), (1, 10))
        self.assertEqual(P.info['roots'], [])
        self.assertEqual(hb.disk_nums(['HDD78', 'HDD77', 'HDD45']), '45, 77 и 78')


class FamilySplitTest(V3Base):
    """Этап 13: переход данных Н1 «Семейный архив» (45 + 77) -> Н1 «Семейный архив 45» (45) + Н7 «Семейный архив 77»."""

    def setUp(self):
        super().setUp()
        for d in ('HDD78', 'HDD55'):
            make_disk(self.scans, d, 'AAAA00' + d[3:], [])
        hb.DIRECTIONS.unlink()
        self.quiet(hb.connect)
        sv.add_directions_batch(sv.DEFAULT_DIRECTIONS)                 # как в настоящих данных: Н1..Н6
        self.mark(('Поход 2010', 'Н1'), ('Работа', 'Н2'))
        hb.ensure_tables()
        with open(hb.DECISIONS, 'a', encoding='utf-8') as f:
            f.write(f'{SRC}\tДрузья\tраздел: Семейный архив\tстарое\n')

    def test_preview_write_and_repeat(self):
        before = hb.DIRECTIONS.read_bytes()
        pv = sv.family_split_preview()
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)            # предпросмотр ничего не пишет
        text = '\n'.join(pv['lines'])
        self.assertIn('«Семейный архив» (HDD45, HDD77) -> «Семейный архив 45» (HDD45)', text)
        self.assertIn('Н7 (новое): «Семейный архив 77» (HDD77)', text)
        self.assertIn('«Скопировано на Семейный архив 45 и 77»', text)
        self.assertIn(f'{SRC}: 2', text)                 # отметки Н1 по носителям (и старый «раздел: Семейный архив»)
        self.assertIn('Заданий на 45 и 77 прежнего вида нет', text)
        self.assertEqual(len(pv['fields']), 2)
        self.quiet(hb.main, ['family-split'])                           # команда без --yes - только предпросмотр
        self.assertIn('Это предпросмотр, ничего не записано', self.printed)
        self.assertEqual(hb.DIRECTIONS.read_bytes(), before)
        self.quiet(hb.main, ['family-split', '--yes'])
        d = sv.directions()
        self.assertEqual((d['Н1'].name, d['Н1'].disks, d['Н1'].kind), ('Семейный архив 45', ('HDD45',), hb.KIND_MEDIA))
        self.assertIn('Семейный архив', d['Н1'].former)
        self.assertEqual((d['Н7'].name, d['Н7'].disks, d['Н7'].kind), ('Семейный архив 77', ('HDD77',), hb.KIND_MEDIA))
        self.assertTrue(hb.DIRECTIONS.read_bytes().startswith(before))   # таблица только дописана
        # отметки Н1 остались за Н1 (только 45); старый «раздел: Семейный архив» - тоже Н1
        P = self.plan()
        self.assertEqual(set(P.part_b), {'HDD45', 'HDD78'})
        self.assertEqual(self.a(P, rz.O_COPY, 'Н7'), (0, 0))
        self.assertEqual({g['folder']: g['num'] for g in rz.group_states(P)}['Друзья'], 'Н1')
        self.assertEqual(d['Н1'].folder(), 'Скопировано на Семейный архив 45')
        self.assertEqual(d['Н7'].folder(), 'Скопировано на Семейный архив 77')
        with self.assertRaises(sv.Refused) as e:                         # повтор - уже сделано
            sv.family_split_preview()
        self.assertIn('Переход уже сделан', str(e.exception))

    def test_continue_after_partial_write(self):
        sv.add_direction(num='Н1', name='Семейный архив 45', disks=['HDD45'])   # «сбой» после первой строки
        pv = sv.family_split_preview()
        self.assertEqual(len(pv['fields']), 1)                          # дописывается только Н7
        sv.family_split()
        self.assertEqual(sv.directions()['Н7'].disks, ('HDD77',))

    def test_unexpected_state_refused(self):
        sv.add_direction(num='Н1', name='Другой архив')                 # диски 45 и 77, но имя не «Семейный архив»
        with self.assertRaises(sv.Refused):
            sv.family_split_preview()
        sv.add_direction(num='Н1', name='Семейный архив')
        dirs = sv.directions()
        before = dict(dirs)
        sv.family_split_preview(dirs)                                    # переданный словарь не меняется
        self.assertEqual(dirs, before)
        sv.add_direction(name='Ещё', disks=[])                          # Н7 занят - новое получило бы Н8
        with self.assertRaises(sv.Refused) as e:
            sv.family_split_preview()
        self.assertIn('Н8, а не Н7', str(e.exception))
        sv.add_direction(num='Н1', disks=['HDD45'])                      # Н1 без 77, но имя прежнее
        with self.assertRaises(sv.Refused):
            sv.family_split_preview()


class ContestedTest(V3Base):
    def test_folders_to_rehash(self):
        res = sv.contested(SRC, 'Поход 2010')
        got = {d: dict(f) for d, _l, f in res}
        self.assertEqual(got[SRC], {'Поход 2010': 3})                 # описание, Thumbs, проект (вложенные свёрнуты)
        self.assertNotIn('HDD45', got)
        res = sv.contested('HDD90', '')                               # обвязка Base: A\заметки.doc без хеша
        self.assertEqual({d: dict(f) for d, _l, f in res}, {'HDD90': {'A': 1}})


class CommandsTest(V3Base):
    """Команды командной строки: предпросмотр без --yes ничего не пишет; ответы понятны."""

    def run_cmd(self, *argv):
        import hb_cli
        import contextlib
        import io
        a = hb_cli.parser().parse_args(list(argv))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                a._run(a)
            except SystemExit:
                pass
        return buf.getvalue()

    def test_commands(self):
        self.assertIn('Семейный архив', self.run_cmd('directions'))
        before = hb.DECISIONS.read_bytes() if hb.DECISIONS.exists() else b''
        self.assertIn('предпросмотр', self.run_cmd('mark', SRC, '--disk-wide', '--where', 'Семейный архив'))
        self.assertEqual(hb.DECISIONS.read_bytes() if hb.DECISIONS.exists() else b'', before)
        self.assertIn('Записано отметок: 2', self.run_cmd('mark', SRC, '--disk-wide', '--folder', 'Работа', '--where',
                                                          'Н1', '--yes'))
        out = self.run_cmd('razbor', SRC)
        self.assertIn('Итого = опись носителя: 17', out)
        self.assertIn('Б. Сколько писать', out)
        out = self.run_cmd('razbor-tasks', SRC, '--dry')
        self.assertIn('Пробный расчёт (--dry)', out)
        self.assertIn('Без диска', self.run_cmd('direction-add', 'Ещё', '--what', 'фото'))  # предпросмотр
        self.assertIn('НЕ ЗАПИСАНО', self.run_cmd('direction-edit', 'Н2', '--add-disk', 'HDD45'))
        self.assertIn('HDD60', self.run_cmd('contested', SRC, 'Поход 2010'))
        self.assertIn('НЕ ЗАПИСАНО', self.run_cmd('decide', SRC, 'Работа', 'направление: Н1'))   # уже так
        self.assertIn('Записано', self.run_cmd('decide', SRC, 'Работа', 'направление: Н2', '--yes'))


class SignatureTest(V3Base):
    def test_signature_follows_tables(self):
        s1 = self.plan().info['signature']
        self.mark(('', 'Н1'))
        s2 = self.plan().info['signature']
        self.assertNotEqual(s1, s2)
        self.assertEqual(s2, self.plan().info['signature'])


CAT_FILES = [                                                # носитель HDD63: все категории «что копировать»
    ('Р\\Фото\\1.jpg', 11, H[41]), ('Р\\clip.MP4', 12, None), ('Р\\отчёт.docx', 13, None), ('Р\\a.zip', 14, None),
    ('Р\\b.mp3', 15, None), ('Р\\c.prproj', 16, None), ('Р\\d.exe', 17, None), ('Р\\e.dll', 18, H[42]),
    ('Р\\f.html', 19, None), ('Р\\g', 20, None), ('Р\\h.jpg.exe', 21, None), ('Р\\i.tmp', 22, None),
    ('Р\\Thumbs.db', 23, None), ('Р\\j.ini', 24, None), ('Р\\k.ZIP', 25, None), ('Р\\пусто.zip', 0, None),
    ('Р\\Без фото\\письмо.doc', 26, None)]


class CategoriesTest(V3Base):
    """Этап 5 (15.11.2026): «что копировать» - набор категорий; программы, системные и временные - никогда."""

    def test_copy_kind_rules(self):
        from hb_core.derived import copy_kind
        from hb_core import consts as K
        cases = {'a.JPG': K.F_PHOTO, 'b.MOV': K.F_VIDEO, 'c.DOCX': K.F_TEXT, 'd.7z': K.F_ARCH, 'e.psd': K.F_PROJ,
                 'f.flac': K.F_MUSIC, 'file.jpg.exe': K.F_NEVER, 'g.DLL': K.F_NEVER, 'h.py': K.F_NEVER,
                 'readme': K.F_OTHER, 'i.html': K.F_OTHER, 'j.sqlite': K.F_OTHER, 'k.qwerty': K.F_OTHER,
                 '.htaccess': K.F_OTHER, 'l.tmp': K.F_JUNK, 'thumbs.db': K.F_JUNK, '~$m.docx': K.F_JUNK}
        ft = rz.fast_folder_type(fine=True)
        for nm, k in cases.items():
            self.assertEqual(copy_kind('П\\' + nm, nm.lower(), 10), k, nm)
            self.assertEqual(ft('П\\' + nm.lower(), nm.lower(), 10), k, nm)          # быстрая - та же логика
            self.assertEqual(folder_type('П\\' + nm, nm.lower(), 10), min(k, K.F_OTHER) if k != K.F_JUNK else k, nm)
        self.assertEqual(copy_kind('П\\x.exe', 'x.exe', 0), K.F_NEVER)               # пустая программа - тоже никогда
        import build_pilot as bp
        never = K.NEVER_COPY_EXT
        self.assertFalse(never & set(bp.EXT_TYPE))                                   # фото и видео - не программы
        self.assertFalse(never & {e for e, c in K.EXT_CLASS.items() if c in (K.C_DOC, K.C_JUNK, K.C_ARCH, K.C_MUSIC,
                                                                             K.C_PROJ)})

    def test_kind_values_compatible(self):
        A, M = hb.ALL_CATS, hb.MEDIA_CATS
        self.assertEqual(hb.parse_kind('все файлы'), (A, False, True))
        self.assertEqual(hb.parse_kind(''), (A, False, True))                         # старая строка без колонки
        self.assertEqual(hb.parse_kind('фото, видео и документы рядом'), (M, True, True))
        self.assertEqual(hb.parse_kind('Фото,  музыка'), (frozenset({hb.CAT_PHOTO, hb.CAT_MUSIC}), False, True))
        self.assertEqual(hb.parse_kind('ерунда'), (frozenset(), False, False))      # неизвестное - НЕ «все файлы»
        self.assertEqual(hb.kind_text(A), hb.KIND_ALL)
        self.assertEqual(hb.kind_text(M, True), hb.KIND_MEDIA)
        self.assertEqual(hb.kind_text(M, False), 'фото, видео, документы')
        self.assertEqual(hb.kind_text({hb.CAT_DOC, hb.CAT_ARCH}, True), 'документы рядом, архивы')
        with open(hb.DIRECTIONS, 'a', encoding='utf-8') as f:
            f.write('Н2\tРабота\tСафари\tHDD91\tчто-то странное\t\n')
        d = sv.directions()['Н2']
        self.assertFalse(d.kind_ok)
        self.assertEqual(d.cats, frozenset())
        for bad in ('', 'ерунда', (frozenset(), False)):
            with self.assertRaises(sv.Refused):
                sv.direction_preview(num='Н2', kind=bad or 'x y')
        self.assertEqual(sv.direction_preview(num='Н2', kind='все')['direction'].kind, hb.KIND_ALL)

    def make_cat_disk(self):
        make_disk(self.scans, 'HDD63', 'AAAA0063', [(p, s_, h) for p, s_, h in CAT_FILES if h],
                  unhashed=[(p, s_) for p, s_, h in CAT_FILES if not h])
        hb.close_last()
        self.quiet(hb.connect)

    def reference(self, d):
        from hb_core.derived import copy_kind
        from hb_core import consts as K
        ref = collections.Counter()
        for p, size, h in CAT_FILES:
            k = copy_kind(p, p.rsplit('\\', 1)[-1].lower(), size)
            if k == K.F_JUNK:
                ref[(rz.O_JUNK, None)] += 1
                continue
            cat = K.CAT_OF_TYPE.get(k)
            near = p.startswith('Р\\') and not p.startswith('Р\\Без фото\\')        # фото - в «Р\Фото», видео - в «Р»
            ok = cat in d.cats and (cat != K.CAT_DOC or not d.docs_near or near)
            ref[(rz.O_COPY if ok else rz.O_TYPE, d.num)] += 1
        return dict(ref)

    def test_planner_follows_set(self):
        self.make_cat_disk()
        c = self.db()
        n = c.execute('select n3, n5, n6, n7, n8 from folders where disk=? and folder=?', ('HDD63', 'Р')).fetchone()
        self.assertEqual(n, (11, 2, 1, 1, 4))         # прочие всего (с пустым); архивы, проекты, музыка, программы
        self.mark(('', 'Н2'), disk='HDD63')
        for kind in ('фото', (frozenset({hb.CAT_ARCH, hb.CAT_MUSIC}), False), (frozenset({hb.CAT_OTHER, hb.CAT_DOC}), True),
                     (frozenset({hb.CAT_PROJ, hb.CAT_DOC}), False), 'все'):
            sv.add_direction(num='Н2', kind=kind)
            d = sv.directions()['Н2']
            P = self.plan('HDD63')
            got = {k: v[0] for k, v in P.part_a.items() if v[0]}
            self.assertEqual(got, self.reference(d), kind)
            self.assertEqual(sum(got.values()), len(CAT_FILES))
            Pd = self.plan('HDD63', detail=True)                         # строки задания - те же файлы
            rows = {r[1] for v in Pd.rows.values() for r in v}
            self.assertEqual(len(rows), got.get((rz.O_COPY, 'Н2'), 0))
            self.assertFalse({'Р\\d.exe', 'Р\\e.dll', 'Р\\h.jpg.exe', 'Р\\j.ini'} & rows)   # программы - никогда
        self.assertEqual(P.part_a[(rz.O_TYPE, 'Н2')][0], 4)              # «все файлы» = все, кроме программ

    def test_never_at_any_size(self):
        """Замечание 1: программа - «никогда» при любом размере (пустой x.exe тоже), в обеих функциях типа."""
        from hb_core.derived import copy_kind
        from hb_core import consts as K
        ft = rz.fast_folder_type(fine=True)
        for ext in sorted(K.NEVER_COPY_EXT):
            nm = 'файл' + ext
            for size in (0, 1, 10 ** 6):
                self.assertEqual(copy_kind('П\\' + nm, nm, size), K.F_NEVER, (nm, size))
                self.assertEqual(ft('П\\' + nm, nm, size), K.F_NEVER, (nm, size))
                self.assertEqual(folder_type('П\\' + nm, nm, size), K.F_OTHER, (nm, size))   # прежний столбец - как был
        self.assertEqual(copy_kind('П\\x.zip', 'x.zip', 0), K.F_OTHER)              # пустой не-программа - «другие»
        self.assertEqual(copy_kind('П\\x.tmp', 'x.tmp', 5), K.F_JUNK)               # временные - мусор (тоже никогда)

    def test_same_task_and_names(self):
        """Замечания 3 и 7: старый разбор.json без «что копировать» не считается подготовленным; имя задания -
        допустимое имя папки Windows."""
        s_ = dict(key=[1, 'A'], num='Н1', kind=hb.KIND_MEDIA, targets=['HDD45'])
        meta = {'носитель': SRC, 'ключ': [1, 'A'], 'направление': 'Н1', 'цели': ['HDD45', 'HDD77']}
        self.assertFalse(sv.same_task(meta, SRC, s_))                                  # без ключа - «не совпадает»
        self.assertTrue(sv.same_task(dict(meta, **{'что копировать': hb.KIND_MEDIA}), SRC, s_))
        self.assertFalse(sv.same_task(dict(meta, **{'что копировать': hb.KIND_ALL}), SRC, s_))
        self.assertEqual(rz.safe_name('HDD60 — Что? <a|b>: "c"/d\\e. '), 'HDD60 — Что_ _a_b__ _c__d_e')
        make_disk(self.scans, 'HDD64', 'AAAA0064', [('Что?*\\1.jpg', 10, H[51])])
        hb.close_last()
        self.quiet(hb.connect)
        self.mark(('', 'Н2'), disk='HDD64')
        res = sv.razbor_tasks('HDD64', dry=True)
        self.assertEqual([x['name'] for x in res['specs']], ['HDD64 — Что__ — Работа'])

    def test_disk_data_error_asks(self):
        """Замечание 4: ошибка чтения базы при снятии диска - переспросить; «базы ещё нет» - данных нет."""
        import sqlite3
        from unittest import mock

        def broken():
            raise sqlite3.OperationalError('database is locked')
        with mock.patch.object(sv, 'ro', broken):
            self.assertTrue(sv._disk_has_data('HDD45'))

        def nodb():
            raise sv.Refused('База ещё собирается - подождите.')
        with mock.patch.object(sv, 'ro', nodb):
            self.assertFalse(sv._disk_has_data('HDD45'))
        self.assertTrue(sv._disk_has_data('HDD45'))
        self.assertFalse(sv._disk_has_data('HDD99'))

    def test_source_is_family_disk(self):
        """B: источник - сам 45: у «Семейного архива» задание только на 77, на себя не копирует."""
        self.mark(('', 'Н1'), disk='HDD45')
        res = sv.razbor_tasks('HDD45', dry=True)
        self.assertTrue(res['specs'])
        self.assertTrue(all(x['targets'] == ['HDD77'] and x['name'].endswith('— на 77') for x in res['specs']))
        self.assertNotIn('HDD45', res['plan'].part_b)


SP_DISK = 'HDD62'
SP_FILES = [                                                 # (путь, размер, sha или None); папки « X», «X », «X»
    (' X\\a.jpg', 100, H[30]),
    (' X\\ заметка.doc', 11, None),                          # пробел и в начале имени файла
    (' X\\Под\\b.jpg', 110, H[31]),
    ('X \\c.jpg', 120, H[32]),
    ('X \\d.jpg ', 125, None),                               # хвостовой пробел в имени файла
    ('X\\e.jpg', 130, H[33]),
    ('X\\f.doc', 12, None),
    ('X\\g.zip', 13, None),
]


class SpacesTest(V3Base):
    """Этап 16, ОШИБКА владельца: «В базе нет файлов по пути HDD51\\Перемещение перед Индонезией - временное» - имя
    папки на диске начинается с пробела, программа обрезала путь. Папки « X» (пробел в начале), «X » (в конце) и «X»
    лежат рядом: отметка, чтение отметок, маршрут, задания, исключение, ручная операция, частичный скан и списки окна
    действуют ровно на свою папку."""

    def setUp(self):
        super().setUp()
        make_disk(self.scans, SP_DISK, 'AAAA0062', [(p, s, h) for p, s, h in SP_FILES if h],
                  unhashed=[(p, s) for p, s, h in SP_FILES if not h])
        self.quiet(hb.connect)

    def files(self, disk=SP_DISK):
        c = self.db()
        return {r[0] for r in c.execute('select path from files where disk=?', (disk,))}

    def test_helpers(self):
        self.assertEqual(hb.clean_path(' X\\'), ' X')
        self.assertEqual(hb.clean_path('\\X \\'), 'X ')
        self.assertEqual(sv.check_rel(' Перемещение перед Индонезией - временное\\'),
                         ' Перемещение перед Индонезией - временное')
        with self.assertRaises(sv.Refused):
            sv.check_rel('   ')
        self.assertEqual(hb.row_fields([' HDD51 ', ' X ', ' не копировать '], paths=(1,), pad=1),
                         ['HDD51', ' X ', 'не копировать', ''])

    def test_marks_route_and_tasks_keep_spaces(self):
        pv = sv.marks_preview(SP_DISK, [(' X', 'Н1')])                          # было: «В базе нет файлов по пути…»
        self.assertEqual(pv['fields'], [[SP_DISK, ' X', sv.directions()['Н1'].verdict()]])
        self.assertIn(f'{SP_DISK}\\ X → ', pv['lines'][1])
        self.assertIn('3 файлов', pv['lines'][1])
        sv.add_marks_batch(SP_DISK, [(' X', 'Н1'), ('X ', 'Н2'), ('X', 'не копировать')])
        rows = hb.mark_rows(SP_DISK, sv.snapshot()['decisions'])
        self.assertEqual([r[1] for r in rows], [' X', 'X ', 'X'])              # в таблице и при чтении - как есть
        ms = hb.MarkSet.build(rows, sv.directions())
        self.assertEqual((ms.get(' X').num, ms.get('X ').num, ms.get('X').kind), ('Н1', 'Н2', hb.R_SKIP))
        with self.assertRaises(sv.Refused):                                      # уже так - не пишется второй раз
            sv.add_marks_batch(SP_DISK, [(' X', 'Н1')])
        P = self.plan(SP_DISK)
        self.assertEqual(self.a(P, rz.O_SKIP), (3, 130 + 12 + 13))
        self.assertEqual(P.part_a[(rz.O_COPY, 'Н2')][0], 2)                     # «X »: c.jpg и «d.jpg »
        P = self.plan(SP_DISK, detail=True)
        got = {p for rows_ in P.rows.values() for _d, p, *_ in rows_}
        self.assertTrue({' X\\a.jpg', ' X\\ заметка.doc', ' X\\Под\\b.jpg', 'X \\c.jpg', 'X \\d.jpg '} <= got, got)
        self.assertFalse({p for p in got if p.startswith('X\\')})
        res = sv.razbor_tasks(SP_DISK, dry=False)
        lst = []
        for s in res['specs']:
            t = hb.TASKS / s['name']
            lst += [x.split('\t')[1] for x in (t / 'список.tsv').read_text(encoding='utf-8').splitlines()]
        self.assertIn(' X\\ заметка.doc', lst)
        self.assertIn('X \\d.jpg ', lst)
        self.assertNotIn('X\\e.jpg', lst)
        # старые решения тоже не теряют пробел
        sv.add_decision(SP_DISK, ' X', 'пока не трогаем')
        self.assertIn((' X', 'пока не трогаем'), list(hb.decisions_for(SP_DISK)))

    def test_exclusion_manual_and_partial_hit_only_own_folder(self):
        sv.add_exclusion(SP_DISK, ' X')
        self.assertEqual({p for p in self.files() if p.startswith((' X', 'X'))},
                         {'X \\c.jpg', 'X \\d.jpg ', 'X\\e.jpg', 'X\\f.doc', 'X\\g.zip'})   # ушла только « X»
        sv.add_manual(time.strftime('%d.%m.%Y'), 'удалено', SP_DISK, 'X ')
        self.assertEqual({p for p in self.files() if p.startswith(('X', ' X'))}, {'X\\e.jpg', 'X\\f.doc', 'X\\g.zip'})
        self.assertEqual(hb.manual_rows()[-1][1][3], 'X ')                     # в таблице - как есть
        with self.assertRaises(sv.Refused):
            sv.add_manual(time.strftime('%d.%m.%Y'), 'удалено', SP_DISK, 'X ')               # повтор (сравнение без обрезки)
        from test_hashbase import make_partial
        make_partial(self.scans, SP_DISK, 'AAAA0062', ['X\\'], [('X\\e.jpg', 130, H[33]), ('X\\new.jpg', 7, H[34])])
        self.quiet(hb.connect)
        self.assertEqual({p for p in self.files() if p.startswith(('X', ' X'))}, {'X\\e.jpg', 'X\\new.jpg'})

    def test_partial_scan_of_leading_space_folder(self):
        from test_hashbase import make_partial
        make_partial(self.scans, SP_DISK, 'AAAA0062', [' X'], [(' X\\a.jpg', 100, H[30])])
        self.quiet(hb.connect)
        fs = self.files()
        self.assertNotIn(' X\\Под\\b.jpg', fs)                                  # скан « X» заменил только её
        self.assertTrue({'X \\c.jpg', 'X\\e.jpg', 'X\\f.doc'} <= fs)

    def test_lists_and_contested_keep_spaces(self):
        res = sv.file_list('nohash', SP_DISK, ' X')
        self.assertEqual([r[1] for r in res['rows']], [' X\\ заметка.doc'])
        self.assertEqual(res['scope'], ' X')
        res = sv.file_list('nohash', SP_DISK, 'X')
        self.assertEqual(sorted(r[1] for r in res['rows']), ['X\\f.doc', 'X\\g.zip'])
        rows = hb.contested_rows(self.db(), SP_DISK, 'X ')
        self.assertEqual([(r[0], r[1]) for r in rows], [(SP_DISK, 'X \\d.jpg ')])


class FileListTest(V3Base):
    """Этап 16: данные окна «Список файлов» - тот же расчёт, что числа «Разбора» (каждый файл один раз), «без хеша»,
    спорные поштучно, уникальные."""

    def test_copy_have_type_lists_match_plan(self):
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        P = self.plan()
        for num, kind, out in (('Н1', 'have', rz.O_HAVE), ('Н1', 'type', rz.O_TYPE), ('Н2', 'have', rz.O_HAVE),
                               ('Н2', 'type', rz.O_TYPE)):
            res = sv.file_list(kind, SRC, num=num)
            self.assertEqual((len(res['rows']), sum(r[2] for r in res['rows'])), self.a(P, out, num), (num, kind))
            self.assertEqual(len({r[1] for r in res['rows']}), len(res['rows']))     # файл - один раз
        for x in ('HDD45', 'HDD77'):
            res = sv.file_list('copy', SRC, num='Н1', target=x)
            st = {r[1]: r[6] for r in res['rows']}
            write = [p for p, w in st.items() if w.startswith(('нет на', 'без хеша'))]
            self.assertEqual(len(write), P.part_b[x][0], (x, st))              # войдёт в задание = часть Б (ячейка)
            self.assertIn(f'В задание войдёт {P.part_b[x][0]} файлов', res['notes'][0])
            self.assertNotIn('ВНИМАНИЕ', ' '.join(res['notes']))
        st = {r[1]: r[6] for r in sv.file_list('copy', SRC, num='Н1', target='HDD77')['rows']}
        self.assertEqual(st['Поход 2010\\Монтаж\\clip копия.mp4'], 'нет на HDD77 (по SHA-256)')     # представитель
        self.assertTrue(st['Поход 2010\\Монтаж\\clip.mp4'].startswith('повтор: то же содержимое, что «Поход 2010'
                                                                       '\\Монтаж\\clip копия.mp4»'))
        self.assertEqual(st['Поход 2010\\описание.doc'], 'без хеша — сравнить нельзя, копируется')
        self.assertNotIn('Поход 2010\\Фото\\1.jpg', st)                          # уже есть на 45 и 77
        have = {r[1]: r[7] for r in sv.file_list('have', SRC, num='Н1')['rows']}
        self.assertEqual(have['Поход 2010\\Фото\\1.jpg'], 'HDD45: X\\1.jpg; HDD77: Y\\1.jpg')      # все копии
        typ = {r[1]: r[6] for r in sv.file_list('type', SRC, num='Н1')['rows']}
        self.assertEqual(typ['Поход 2010\\Монтаж\\проект.prproj'],
                         'направление берёт только фото, видео, документы (только рядом с фото и видео); это — '
                         'другие · проект')
        self.assertEqual(typ['Документы\\письмо.doc'], 'документ не рядом с фото и видео: направление берёт '
                                                       'документы только рядом с ними')

    def test_drafts_overlap_and_errors(self):
        n2 = sv.directions()['Н2'].verdict()
        res = sv.file_list('copy', SRC, num='Н2', drafts=[('Работа', n2), ('Работа\\x', n2)])
        self.assertEqual(sorted(r[1] for r in res['rows']), ['Работа\\отчёт.doc', 'Работа\\схема.jpg'])  # черновик
        res = sv.file_list('copy', SRC, num='Н2', drafts=[('', n2), ('Работа', n2)])       # отметки пересекаются
        paths = [r[1] for r in res['rows']]
        self.assertEqual(len(paths), len(set(paths)))
        with self.assertRaises(sv.Refused):
            sv.file_list('nothing', SRC)
        with self.assertRaises(sv.Refused):
            sv.file_list('copy', SRC, num='Н9')

    def test_nohash_contested_unique(self):
        res = sv.file_list('nohash', SRC, 'Поход 2010')
        got = {r[1]: (r[5], r[6]) for r in res['rows']}
        self.assertEqual(set(got), {'Поход 2010\\Фото\\Thumbs.db', 'Поход 2010\\описание.doc',
                                    'Поход 2010\\Монтаж\\проект.prproj'})
        info = sv.nohash_info(SRC)
        self.assertEqual(info['folders']['Поход 2010'], 3)                      # столбец «Без хеша» - то же условие
        self.assertEqual(info['folders'][''], info['total'])
        self.assertEqual(info['total'], sum(1 for _p, s, h in FILES if not h and s))
        self.assertEqual(info['media'], 0)
        rows = hb.contested_rows(self.db(), SRC, 'Поход 2010')
        self.assertEqual(len(rows), len({(r[0], r[1]) for r in rows}))          # файл - один раз
        self.assertEqual(sv.contested_count(SRC, 'Поход 2010')['total'], len(rows))
        self.assertEqual({d: dict(f) for d, _l, f in sv.contested(SRC, 'Поход 2010')}, {SRC: {'Поход 2010': 3}})
        res = sv.file_list('contested', SRC, 'Поход 2010')
        self.assertTrue(all(r[6] == 'без хеша на этом носителе' for r in res['rows']))
        uniq = {r[1] for r in sv.file_list('unique', SRC)['rows']}
        self.assertNotIn('Поход 2010\\Фото\\1.jpg', uniq)                       # есть и на 45, и на 77
        self.assertIn('Работа\\схема.jpg', uniq)
        self.assertIn('без хеша', sv.file_list('unique', SRC)['notes'][0])

    def test_contested_counts_a_file_once(self):
        """Тёзка без хеша и запись Z/U/X на 45 - одна строка с двумя причинами."""
        import sqlite3
        c = sqlite3.connect(hb.DB)
        c.execute("insert into files(disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp) values "
                  "('HDD45', 'Z\\2.jpg', 200, null, 'тест', '2.jpg', 0, 'U', ?)", (S[2],))
        c.commit()
        c.close()
        rows = [r for r in hb.contested_rows(self.db(), 'HDD90', 'A') if r[0] == 'HDD45']
        self.assertEqual([r[1] for r in rows], ['Z\\2.jpg'])
        self.assertIn('копия не проверена (со слов владельца)', rows[0][5])


class CodeReview16Test(V3Base):
    """Этап 16, замечания критиков по коду: цель списка, степени в «Где копия» и спорных, одна нормализация пути,
    предел до сбора строк, «Фото и видео на носителе нет», расхождение итога видно в списке."""

    def raw(self, sql, args=()):
        import sqlite3
        c = sqlite3.connect(hb.DB)
        c.execute(sql, args)
        c.commit()
        c.close()

    def test_copy_target_must_be_disk_of_direction(self):
        self.mark(('Работа', 'Н2'))
        with self.assertRaises(sv.Refused):
            sv.file_list('copy', SRC, num='Н2', target='HDD999')
        with self.assertRaises(sv.Refused):
            sv.file_list('copy', SRC, num='Н2', target=SRC)
        with self.assertRaises(sv.Refused):
            sv.file_list('copy', SRC, num='Н3')                                    # у направления нет диска
        self.assertEqual(sv.file_list('copy', SRC, num='Н2')['target'], 'HDD91')

    def test_confirmed_record_never_contested_or_unchecked(self):
        # искусственная запись: S с заполненным sha_exp (в настоящей базе так не бывает - проверено чтением)
        self.raw("insert into files(disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp) values "
                 "('HDD45', 'W\\2.jpg', 200, ?, 'тест', '2.jpg', 0, 'S', ?)", (S[2], S[2]))
        rows = hb.contested_rows(self.db(), 'HDD90', 'A')
        self.assertNotIn(('HDD45', 'W\\2.jpg'), {(r[0], r[1]) for r in rows})
        c = self.db()
        got = sv._copies(c, {S[2]}, ['HDD45'], set())
        self.assertIn('HDD45: W\\2.jpg', got[S[2]])                                 # подтверждённая - без пометки
        self.assertFalse(any('W\\2.jpg (не проверена' in x for x in got[S[2]]))

    def test_one_path_normalization(self):
        p = hb.DECISIONS
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f'{SRC}\t\\ Поход 2010 \\\tпока не трогаем\t\n')
            f.write(f'{SRC}\t\\ Поход 2010 \\\t{sv.directions()["Н2"].verdict()}\t\n')
        self.assertIn((' Поход 2010 ', 'пока не трогаем'), list(hb.decisions_for(SRC)))
        self.assertIn(' Поход 2010 ', [r[1] for r in hb.mark_rows(SRC, sv.snapshot()['decisions'])])
        self.assertEqual(sv.check_rel('\\ Поход 2010 \\'), ' Поход 2010 ')

    def test_unique_limit_before_rows_and_no_media_text(self):
        from unittest import mock
        stop = mock.Mock(side_effect=AssertionError('строки не собирать'))
        with mock.patch.object(sv, 'LIST_MAX', 1), mock.patch.object(sv.hb, 'fast_folder_type', return_value=stop):
            with self.assertRaises(sv.Refused):
                sv.file_list('unique', SRC)
        make_disk(self.scans, 'HDD63', 'AAAA0063', [], unhashed=[('Д\\письмо.doc', 10)])
        self.quiet(hb.connect)
        info = sv.disk_hash_info('HDD63')
        self.assertEqual(info['hash'], 'Фото и видео на носителе нет')
        self.assertEqual(sv.disk_hash_info('HDD90')['hash'], 'Хеш есть у всех фото и видео')

    def test_wrong_totals_are_reported_in_list(self):
        self.mark(('Работа', 'Н2'))
        self.raw("update folders set n2 = n2 + 1, files = files + 1 where disk=? and folder='Работа'", (SRC,))
        res = sv.file_list('copy', SRC, num='Н2')
        self.assertTrue(any(x.startswith('ИТОГ НЕВЕРЕН') for x in res['notes']), res['notes'])


if __name__ == '__main__':
    unittest.main()
