"""«Разбор носителя»: Этап 12: направление на нескольких дисках; перенесённое; отметки в корне «Скопировано…».

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_stage12
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа


class Stage12Test(PageBase):
    """Этап 12 (решения владельца 16.11): шаги - в самом верху, групповые галочки мышью, 45 и 77 раздельно."""

    def show(self, w=1600, h=1000):
        from test_app import QAPP
        self.w.resize(w, h)
        self.w.show()
        QAPP.processEvents()

    def test_steps_above_head(self):
        lay = self.p.layout()
        self.assertEqual(lay.indexOf(self.p.steps), 0)                          # первым в странице
        self.open()
        self.show()
        self.assertLess(self.p.steps.mapTo(self.p, QPoint(0, 0)).y(), self.p.where.mapTo(self.p, QPoint(0, 0)).y())
        self.assertLess(self.p.steps.geometry().bottom(), self.p.where.mapTo(self.p, QPoint(0, 0)).y())

    def click_check(self, path, mods=None, double=False):
        """Настоящий щелчок мышью по индикатору галочки строки (как владелец)."""
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QStyleOptionViewItem
        from test_app import QAPP
        it = self.item(path)
        tree = self.p.tree
        tree.scrollToItem(it)
        QAPP.processEvents()
        idx = tree.indexFromItem(it, rp.C_CHECK)
        opt = QStyleOptionViewItem()
        tree.itemDelegate().initStyleOption(opt, idx)
        opt.rect = tree.visualRect(idx)
        r = tree.style().subElementRect(rp.QStyle.SE_ItemViewItemCheckIndicator, opt, tree)
        self.assertTrue(r.isValid() and r.width() > 0, path)
        mods = rp.Qt.NoModifier if mods is None else mods
        if double:                                    # как настоящий двойной щелчок: щелчок, затем «двойное» нажатие
            QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
            QTest.mouseDClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
        else:
            QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, mods, r.center())
        QAPP.processEvents()

    def test_group_checks_by_mouse(self):
        self.open()
        self.show()
        m = self.p.model
        group = ('Друзья', 'Работа', 'Документы')
        self.p.tree.clearSelection()
        for f in group:
            self.item(f).setSelected(True)
        self.assertEqual(self.owns(), {})
        self.click_check('Работа')                                               # галочка одной из выделенных
        self.assertEqual(self.owns(), {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # одним шагом отмены
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))   # выделение осталось
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Checked for f in group))
        self.click_check('Друзья')                                               # снять - тоже у всей группы
        self.assertEqual(self.owns(), {})
        self.assertEqual(len(m.undo_stack), 2)
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.assertTrue(wait(lambda: sorted(self.p.selected_folders()) == sorted(group)))
        self.click_check('Смешанная')                                            # невыделенная - только она
        self.assertEqual(self.owns(), {'смешанная': N1})
        self.assertEqual(len(m.undo_stack), 3)
        self.assertEqual(sorted(self.p.selected_folders()), sorted(group))         # Qt: щелчок по галочке выделение не меняет
        self.assertTrue(all(self.item(f).checkState(rp.C_CHECK) == rp.Qt.Unchecked for f in group))
        self.click_check('Смешанная')                                            # снова невыделенная - только она
        self.assertEqual(self.owns(), {})
        self.p.undo()                                                            # «Отменить последнее» - шагами
        self.assertEqual(set(self.owns()), {'смешанная'})
        self.p.undo()
        self.p.undo()
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
        self.assertIsNone(self.p.tree.press_sel)                                 # после щелчка не осталось
        self.settle()

    def test_one_disk_direction_has_no_blocks(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Работа', 'Н2'))
        self.open()
        self.plan()
        self.assertEqual(self.p.dest, 'Н2')
        c = self.p.copy_cell
        self.assertEqual(c.blocks, [])
        self.assertFalse(c.blocks_box.isVisibleTo(c))
        self.assertIn('Уже есть на HDD91', c.body.text())
        self.assertIn('Копировать на HDD91', c.body.text())
        h = self.p.where.text()
        self.assertTrue(h.startswith('Диск назначения: '))
        self.assertNotIn('копии', h)
        self.assertNotIn('Копия', self.p.dest_info.text())

    def test_disk_missing_from_rows(self):
        """Проверка кода (п. 1): диска направления нет в списке дисков - подписи не падают, диск - номером."""
        import types
        d = types.SimpleNamespace(num='Н9', name='Проба', disks=('HDD45', 'HDD99'))
        rows = [dict(disk='HDD45', label='WD - 2 ТБ - Бэкап фото и видео', letter='H:', free_gib=10.0)]
        info = rp.dest_info_html(d, rows)
        self.assertIn('Копия 1 — H: Бэкап фото и видео (HDD45): свободно 10,0 ГБ', info)
        self.assertIn('Копия 2 — Накопитель (HDD99): подключите диск', info)
        h = rp.head_html(d, rows)
        self.assertIn('Накопитель — HDD99', h)
        self.assertEqual(rp.dest_text(d, rows), 'Н9 Проба — H: и HDD99 (две копии)')
        self.assertEqual(rp.disk_ui.disk_place('HDD99'), 'Накопитель')            # строка - через as_row

    def test_blocks_follow_state(self):
        """Проверка кода (п. 6): те же диски - блоки не пересоздаются, но текст и рамка меняются по состоянию."""
        c = self.p.copy_cell
        c.set_blocks([('HDD45', 'не помещается', 'short'), ('HDD77', 'место не проверено', 'unknown')])
        frames = [b[1] for b in c.blocks]
        self.assertIn(rp.BLOCK_LOOK['short'][0], frames[0].styleSheet())
        c.set_blocks([('HDD45', 'помещается', 'ok'), ('HDD77', 'место не проверено', 'unknown')])
        self.assertEqual([b[1] for b in c.blocks], frames)                      # те же рамки
        self.assertIn(rp.BLOCK_LOOK['ok'][0], frames[0].styleSheet())
        self.assertNotIn(rp.BLOCK_LOOK['short'][0], frames[0].styleSheet())
        self.assertEqual(c.block_texts()['HDD45'], 'помещается')
        self.assertEqual(c.block_states(), {'HDD45': 'ok', 'HDD77': 'unknown'})
        c.set_blocks([])
        self.assertEqual(c.blocks, [])
        self.assertFalse(c.blocks_box.isVisibleTo(c))

    def test_group_applied_once(self):
        """Проверка кода (п. 4): групповое действие - ровно один раз (один шаг отмены) и при Ctrl-щелчке по галочке,
        и при двойном щелчке; Ctrl-щелчок по имени - галочки выделенным один раз (нажатие и отпускание)."""
        from PySide6.QtTest import QTest
        from test_app import QAPP
        self.open()
        self.show()
        m, tree = self.p.model, self.p.tree
        group = ('Друзья', 'Работа', 'Документы')
        tree.clearSelection()
        for f in group:
            self.item(f).setSelected(True)
        steps = len(m.undo_stack)
        self.click_check('Работа', rp.Qt.ControlModifier)                       # Ctrl-щелчок по галочке выделенной
        wait(lambda: False, 0.3)
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
        self.assertEqual(len(m.undo_stack), steps + 1)
        self.click_check('Работа', double=True)                                   # двойной щелчок
        wait(lambda: False, 0.3)
        states = {self.item(f).checkState(rp.C_CHECK) for f in group}
        self.assertEqual(len(states), 1)                                         # у всей группы одинаково
        self.assertEqual(len(m.undo_stack), steps + 2)                           # двойной щелчок - одно переключение
        self.assertEqual(set(self.owns()), set())                                   # у всей группы - снято
        self.assertIsNone(tree.press_sel)
        # Ctrl-щелчок по ИМЕНИ ещё одной папки: выделенным ставятся галочки - одним шагом (нажатие + отпускание)
        before = len(m.undo_stack)
        it = self.item('Смешанная')
        tree.scrollToItem(it)
        QAPP.processEvents()
        QTest.mouseClick(tree.viewport(), rp.Qt.LeftButton, rp.Qt.ControlModifier,
                         tree.visualItemRect(it).center())
        wait(lambda: len(self.p.selected_folders()) == 4)
        wait(lambda: False, 0.3)
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы', 'смешанная'})
        self.assertEqual(len(m.undo_stack), before + 1)
        self.settle()


class MovedPartialTest(PageBase):
    """Проверка кода (п. 5): папка перенесена на носителе раньше («ПЕРЕНЕСЕНО → 45 и 77»), её файл есть только на
    45 - в ядре «копировать» (недостаёт на 77); «уже есть» по дискам: на 45 - да, на 77 - нет; есть на обоих - в ядре
    «перенесено», в «отмечено» и «уже есть» не входит."""

    def rescan(self, disk, serial, folder, files):
        """Пересканирование папки диска (частичный скан с хешами) и пересборка временной базы."""
        from test_hashbase import make_partial
        make_partial(self.scans, disk, serial, [folder], files, name=f'part_{len(files)}')
        self.quiet(hb.connect)

    def check(self, want_total, want_have):
        self.open()
        P = self.plan()
        cp = P.part_a.get((rz.O_COPY, 'Н1'), (0, 0))
        hv = P.part_a.get((rz.O_HAVE, 'Н1'), (0, 0))
        total = (cp[0] + hv[0], cp[1] + hv[1])
        self.assertEqual(total, want_total)
        have = self.p.model.have_on_disk('Н1')
        self.assertEqual(have, want_have)
        for x in ('HDD45', 'HDD77'):                                             # недостающее = часть Б ядра
            self.assertEqual(P.part_b.get(x, [0, 0])[0], total[0] - have[x][0], x)
        return P

    def test_moved_partial(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        base45 = [('X\\1.jpg', 100, S[1]), ('X\\2.jpg', 200, S[2])]
        base77 = [('Y\\1.jpg', 100, S[1])]
        self.rescan('HDD45', 'AAAA0045', 'X', base45 + [('X\\z.jpg', 300, H[25])])   # z.jpg - только на 45
        self.mark(('Старое', 'Н1'), ('Работа', 'Н1'))
        P = self.check((3, 300 + 20 + 70), {'HDD45': (1, 300), 'HDD77': (0, 0)})
        self.assertEqual(P.part_a.get((rz.O_MOVED, None), (0, 0))[0], 0)
        self.p.model.drafts.clear()
        self.p.choose_disk('HDD45')                                              # уйти с носителя, чтобы перечитать
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.model.disk == 'HDD45'))
        self.settle()
        QThreadPool.globalInstance().waitForDone(20000)                          # окно не читает базу во время сборки
        self.rescan('HDD77', 'AAAA0077', 'Y', base77 + [('Y\\z.jpg', 300, H[25])])   # z.jpg - и на 77
        P = self.check((2, 20 + 70), {'HDD45': (0, 0), 'HDD77': (0, 0)})
        self.assertEqual(P.part_a.get((rz.O_MOVED, None), (0, 0)), [1, 300])


class CopiedRootMarksTest(V3Base):
    """Этап 13: «Скопировано на …» (из журнала перемещения) и папки внутри можно отметить для ДРУГОГО направления;
    отметка - по нынешнему пути, действует только там; отметка носителя и исходные отметки внутрь не проникают."""
    ROOT = 'Скопировано на Работа (91)'

    def setUp(self):
        super().setUp()
        os.utime(next(self.scans.glob('HDD60 - тест/*')) / 'inventory.sqlite', (1580000000, 1580000000))
        t = self.out / 'Перенос HDD60'
        t.mkdir()
        (t / 'тома.tsv').write_text('HDD60\tAAAA0060\n', encoding='utf-8')
        (t / 'Журнал перемещения 2025-01-01 00-00-00.tsv').write_text(
            'время\tрезультат\tразмер\tsha-256\tоткуда\tкуда\n'
            f'10:00\tперемещён\t70\t{H[21]}\tK:\\Работа\\схема.jpg\tK:\\{self.ROOT}\\Работа\\схема.jpg\n',
            encoding='utf-8-sig')
        self.quiet(hb.connect)
        self.mark(('', 'Н1'), ('Работа', 'Н2'))

    def test_marks_inside_copied_root(self):
        R = self.ROOT
        m = rp.Model(sv.razbor_tree(SRC))
        self.assertIn(R, m.roots)
        self.assertFalse(m.is_service(R))
        self.assertTrue(m.markable(R))
        self.assertTrue(m.is_service(MOVED))                                 # старая «ПЕРЕНЕСЕНО» - по-прежнему нет
        # без своей отметки - «уже перенесено»: ни отметка носителя (Н1), ни исходная «Работа» (Н2) не проникают
        self.assertEqual((m.route[R].state, m.route[R + '\\Работа'].state), (rp.R_NONE, rp.R_NONE))
        self.assertEqual(m.look(R + '\\Работа')['kind'], 'moved')
        ck = m.check(R, 'Н1', 'only')
        self.assertEqual((ck['on'], ck['checkable']), (False, True))
        # галочка всей служебной папки для Н1 - отметка по нынешнему пути; подпапка - вместе с ней (серая)
        pairs = m.include_pairs([R], 'Н1')
        self.assertEqual(pairs, [(R, sv.directions()['Н1'].verdict())])
        m.set_marks(pairs)
        self.assertEqual(list(m.drafts), [R.lower()])
        self.assertEqual(m.drafts[R.lower()]['path'], R)
        r = m.route[R + '\\Работа']
        self.assertEqual((r.state, r.num), (rp.R_DIR, 'Н1'))
        self.assertTrue(rz.is_second(r, m.roots))
        self.assertIn('ещё одна копия', m.look(R + '\\Работа')['tip'])
        self.assertTrue(m.check(R + '\\Работа', 'Н1', 'only')['gray'])
        self.assertEqual(m.route['Работа'].num, 'Н2')                        # исходная папка - не задета
        # запись и ядро: отметка хранится нынешним путём, ядро считает так же, как окно
        sv.add_marks_batch(SRC, m.batch()[0])
        P = sv._plan(SRC)
        self.assertEqual(P.errors, [])
        self.assertEqual(P.part_a[(rz.O_COPY, 'Н1')][1] >= 70, True)          # схема (нет на 45 и 77) - копировать
        groups = {g['folder']: g for g in rz.group_states(P)}
        self.assertEqual(groups[R]['num'], 'Н1')
        dirs = sv.directions()
        ms = hb.MarkSet.build(hb.mark_rows(SRC, hb.table_bytes(hb.DECISIONS)), dirs)
        self.assertEqual(sv.folder_mark(R + '\\Работа', ms, dirs, m.roots)['text'], 'Н1 Семейный архив')
        self.assertEqual(sv.folder_mark(R, ms, dirs, m.roots)['own'], True)


if __name__ == '__main__':
    unittest.main()
