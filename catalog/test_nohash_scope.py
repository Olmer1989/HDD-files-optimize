"""«Без хеша» только для того, что пойдёт на диск (17.11.2026): ядро (razbor_scope, planner - непрочитанные),
приём частичного скана (issues непрочитанных), service.nohash_check.

Запуск из корня проекта:  py -m unittest catalog.test_nohash_scope
Временные данные; настоящие диски, таблицы и задания не используются.
"""
import os
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hashbase as hb                                        # noqa: E402
from tests.sv_patch import sv                              # noqa: E402
from hb_core import razbor as rz                             # noqa: E402
from hb_core import razbor_scope as rs                       # noqa: E402
from hb_core.consts import HASH_UNREAD_KIND, UNREAD_KIND     # noqa: E402
from test_hashbase import NS, make_disk, make_partial        # noqa: E402
from test_logic_v3 import FILES, H, SRC, V3Base              # noqa: E402

DOC = 'Поход 2010\\описание.doc'                             # документ рядом с фото (подпапка) - без хеша
T_FUTURE = 4102444800                                        # 2100 год: частичный скан новее полной описи


class ScopeTest(V3Base):
    def check(self, *marks):
        if marks:
            self.mark(*marks)
        return sv.nohash_check(SRC, 'Н1')

    def test_only_what_goes_to_disk(self):
        """N - только файлы без хеша, которые пойдут на 45 и 77: документы рядом с фото - да, без фото рядом, не
        подходящие по типу и мусор - нет; число - то же, что у итога (файлов без хеша к записи на диск)."""
        r = self.check(('', 'Н1'))
        P = self.plan()
        self.assertEqual(r['n'], P.unhashed_copy['HDD45'][0])
        self.assertEqual(r['n'], P.unhashed_copy['HDD77'][0])
        self.assertIn(DOC, r['sample'])
        self.assertIn('Работа\\отчёт.doc', r['sample'])                    # рядом со схема.jpg
        for p in ('Документы\\письмо.doc', 'корень.txt', 'Поход 2010\\Монтаж\\проект.prproj',
                  'Поход 2010\\Фото\\Thumbs.db'):
            self.assertNotIn(p, r['sample'])
        self.assertEqual(r['cats'], [hb.CAT_DOC])                          # только типы файлов из N
        self.assertEqual(r['folders'], sorted({rs.parent_of(p) for p in r['sample']} - {''}))
        self.assertEqual(r['unread'], [])
        self.assertEqual(r['errors'], [])

    def test_inheritance_and_zero(self):
        """Отмечена папка, где все подходящие файлы с хешем, - N = 0; «не копировать» внутри отмеченной - не в N."""
        self.assertEqual(self.check(('Друзья', 'Н1'))['n'], 0)
        r = self.check(('Поход 2010', 'Н1'))
        self.assertEqual(r['sample'], [DOC])
        self.assertEqual(r['folders'], ['Поход 2010'])
        self.assertEqual(self.check(('Поход 2010', 'не копировать'), ('Поход 2010\\Фото', 'Н1'))['n'], 0)

    def test_scan_folders_without_nested_repeats(self):
        self.assertEqual(rs.scan_folders(['A\\1', 'A\\B\\2', 'C\\D\\3', '4']), (['A', 'C\\D'], 1))
        self.assertEqual(rs.top_folders({'A\\B', 'A', 'B\\C'}), {'A', 'B\\C'})
        self.assertEqual(rs.top_folders({'A', ''}), {''})

    def test_namesakes_on_archive_only_for_copied_files(self):
        """K: на 45 файл без хеша с тем же именем и размером, что у файла, который пойдёт на 45 (с хешем или без);
        тёзка файла, который не копируется (письмо.doc без фото рядом), не считается."""
        make_disk(self.scans, 'HDD93', 'AAAA0093', [])                    # чтобы сборка шла заново
        job = next(self.scans.glob('HDD45 - тест/*'))
        hb.close_last()
        con = sqlite3.connect(job / 'inventory.sqlite')
        con.executemany("insert into files values (?, ?, '0', '0', '', 32, 'other')",
                        [('Старое\\описание.doc', 10), ('Старое\\схема.jpg', 70), ('Старое\\письмо.doc', 30),
                         ('Старое\\описание пустое.doc', 0)])
        con.commit(); con.close()
        self.quiet(hb.cmd_rebuild, NS())
        r = self.check(('', 'Н1'))
        k = r['copies']['HDD45']
        self.assertEqual(sorted(k['sample']), ['Старое\\описание.doc', 'Старое\\схема.jpg'])
        self.assertEqual(k['k'], 2)
        self.assertEqual(k['folders'], ['Старое'])
        self.assertEqual(k['cats'], sorted([hb.CAT_DOC, hb.CAT_PHOTO]))
        self.assertEqual(r['copies']['HDD77']['k'], 0)


class UnreadTest(V3Base):
    """Файл, который при ПЕРЕсканировании снова не прочитался: не копируется (причина «не прочитан»), задание
    остальных не держит; ошибка первой полной описи - не причина исключать (он в N, его пересканируют)."""

    def partial(self, name, files, when, unread=(), folders=('Поход 2010',)):
        job = make_partial(self.scans, SRC, 'AAAA0060', list(folders), list(files) + [(p, s, None) for p, s, _ in unread],
                           name=name)
        con = sqlite3.connect(job / 'hashes.sqlite')
        for p, _s, why in unread:
            con.execute("update hashes set status='error', error=? where path=?", (why, p))
        con.commit(); con.close()
        os.utime(job / 'inventory.sqlite', (when, when))
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())

    def rest(self):
        return [(p, s, h) for p, s, h in FILES if p.startswith('Поход 2010\\') and p != DOC and h]

    def put_issue(self, path, kind, note):
        self.db()                                                        # база собрана
        hb.close_last()
        con = sqlite3.connect(hb.DB)                                     # временная база теста
        con.execute('insert into issues values (?,?,?,?)', (SRC, path, kind, note))
        con.commit(); con.close()

    def issues(self):
        return self.db().execute('select path, kind, note from issues where disk=?', (SRC,)).fetchall()

    def test_unread_after_rescan_is_excluded_not_blocking(self):
        self.partial('p1', self.rest(), T_FUTURE, unread=[(DOC, 10, 'Отказано в доступе')])
        self.assertIn((DOC, UNREAD_KIND, 'error: Отказано в доступе'), self.issues())
        self.mark(('', 'Н1'))
        P = self.plan(detail=True)                                         # сверка сумм - без ошибок
        self.assertIn((DOC, 'HDD45', rz.B_UNREAD, 10), P.blocked)
        self.assertIn((DOC, 'HDD77', rz.B_UNREAD, 10), P.blocked)
        g = next(k for k in P.groups if k[1] == 'Поход 2010')
        self.assertEqual(P.group_state(g), rz.G_COPY)                      # остальные копируются
        self.assertNotIn(DOC, {r[1] for rows in P.rows.values() for r in rows})
        self.assertTrue(any('снова не прочитаны' in x for x in rz.attention_lines(P)))
        r = sv.nohash_check(SRC, 'Н1')
        self.assertNotIn(DOC, r['sample'])                                 # N и непрочитанные не пересекаются
        self.assertEqual(r['unread'], [(DOC, 'error: Отказано в доступе', 10)])
        self.assertEqual(r['n'], P.unhashed_copy['HDD45'][0])

    def test_type_not_selected_keeps_old_error_success_clears(self):
        self.partial('p1', self.rest(), T_FUTURE, unread=[(DOC, 10, 'сбой')])
        # тип «документы» не выбран: сканер файл не пробовал - прежняя ошибка остаётся
        job = make_partial(self.scans, SRC, 'AAAA0060', ['Поход 2010'], self.rest() + [(DOC, 10, None)], name='p2')
        con = sqlite3.connect(job / 'hashes.sqlite')
        con.execute('delete from hashes where path=?', (DOC,))
        con.commit(); con.close()
        os.utime(job / 'inventory.sqlite', (T_FUTURE + 10, T_FUTURE + 10))
        hb.close_last()
        self.quiet(hb.cmd_rebuild, NS())
        self.assertIn((DOC, UNREAD_KIND, 'error: сбой'), self.issues())
        self.partial('p3', self.rest() + [(DOC, 10, H[40])], T_FUTURE + 20)  # прочитан - ошибки нет, хеш есть
        self.assertNotIn(DOC, {p for p, _k, _n in self.issues()})
        self.mark(('', 'Н1'))
        self.assertNotIn(DOC, sv.nohash_check(SRC, 'Н1')['sample'])

    def test_first_inventory_error_is_not_excluded(self):
        """Ошибка полной описи (kind «не прочитан при подсчёте хеша») - файл остаётся в N: его надо пересканировать."""
        self.put_issue(DOC, HASH_UNREAD_KIND, 'error')
        self.mark(('', 'Н1'))
        self.assertEqual([x for x in self.plan().blocked if x[0] == DOC], [])
        r = sv.nohash_check(SRC, 'Н1')
        self.assertIn(DOC, r['sample'])
        self.assertEqual(r['unread'], [])

    def test_unread_outside_marked_folders_is_not_read(self):
        """Непрочитанные вне папок, которые куда-то копируются, планировщик поштучно не читает (весь носитель - нет)."""
        self.put_issue('Документы\\письмо.doc', UNREAD_KIND, 'x')
        self.mark(('Друзья', 'Н1'))
        P = self.plan()
        self.assertEqual(P.blocked, [])


if __name__ == '__main__':
    unittest.main()
