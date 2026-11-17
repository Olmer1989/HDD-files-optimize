"""«Разбор носителя»: Замечания владельца и критиков этапа 8 и третьего круга.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_review
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа


class Review8Test(PageBase):
    """Проверка кода этапа 8 критиками: «Только выбранные» при носителе в другом направлении, «Все папки» снимает
    только исключения внутри D, «кроме N папок» - свои исключения, «Ничего не отмечено», длинный текст списка."""

    def test_only_with_carrier_in_other_direction_says_where_rest_goes(self):
        self.mark(('', 'Н2'))
        self.open()
        self.p.set_dest('Н1')
        self.p.toggle(['Поход 2010'], True)
        self.p.mode_except.setChecked(True)
        self.p.mode_only.setChecked(True)                                        # корень - снова сохранённый Н2
        self.assertEqual(self.p.model.route[''].num, 'Н2')
        P = self.plan()
        note = self.p.mode_note.text()
        self.assertIn('Весь носитель отмечен «Всё — в Работа (91)»: папки без галочки идут туда', note)
        v = [P.part_a.get((o, 'Н2'), (0, 0)) for o in (rz.O_COPY, rz.O_HAVE)]
        self.assertIn(rp.files_word(v[0][0] + v[1][0]), note)
        self.p.set_dest('Н2')                                                    # для Н2 это «Все папки» - строки нет
        self.assertNotIn('Весь носитель отмечен', self.p.mode_note.text())

    def test_every_drops_only_exclusions_inside_dest(self):
        self.mark(('Друзья', 'Н2'), ('Друзья\\Наши', 'не копировать'), ('Документы', 'не копировать'))
        self.open()
        self.assertEqual(self.p.dest, 'Н1')
        self.p.mode_every.setChecked(True)
        d = {k: x['verdict'] for k, x in self.p.model.drafts.items()}
        self.assertEqual(d, {'': N1, 'документы': rp.INHERIT})                  # «Наши» внутри Н2 - не тронута
        self.assertEqual(self.p.model.route['Друзья\\Наши'].state, rp.R_SKIP)
        self.settle()

    def test_except_counts_only_own_exclusions(self):
        self.mark(('Смешанная', 'Н2'))
        self.open()
        self.p.mode_except.setChecked(True)
        self.p.toggle(['Друзья'], True)
        self.p.toggle(['Друзья\\Наши'], True)                                   # серая - не меняется
        self.assertEqual(self.p.counts()[1], 1)                                  # Смешанная (Н2) и служебная - не «кроме»
        self.plan()
        self.assertIn('Отмечено: весь носитель, кроме 1 папки ·', self.p.copy_cell.body.text())

    def test_nothing_marked_and_long_dest_text(self):
        self.open()
        self.plan()
        self.assertIn('Ничего не отмечено — поставьте галочки у папок', self.p.copy_cell.body.text())
        self.assertNotIn('Отмечено 0', self.p.copy_cell.body.text())
        box = self.p.dest_box
        longest = max(box.html_width(box.itemData(i, rp.Qt.UserRole + 5)) for i in range(box.count()))
        self.assertGreaterEqual(box.view().minimumWidth(), longest)              # список во всю ширину пункта
        box.setMinimumWidth(0)
        box.setFixedWidth(160)                                                   # закрытое поле узкое - «…»
        box.grab()
        self.assertEqual(box.toolTip(), box.currentText())


class Round3Test(PageBase):
    """Третий круг «Разбора» (решения владельца 16.11): режим выбран всегда, «выбрать все», красный в «Все, кроме»,
    «Идёт пересчёт», верхний блок формой, ячейки «Остаётся» нет."""

    def test_default_mode_and_form(self):
        self.open()
        self.assertTrue(self.p.mode_only.isChecked())                            # по умолчанию - «Только выбранные»
        self.assertTrue(all(w.isCheckable() for w in self.p.mode_btn.values()))
        self.assertIsInstance(self.p.mode_only, rp.QPushButton)                  # кнопки, не переключатели
        self.assertEqual(self.p.mode_note.text(), rp.MODE_NOTE[rp.ONLY])          # строка пояснения режима
        page_text = ' '.join(w.text() for w in self.p.findChildren(rp.QLabel))
        self.assertNotIn('Сначала выберите режим', page_text)
        self.assertIn('не подключён', self.p.info.text())                        # плашка под полем носителя
        self.assertIn('опись от', self.p.info.text())
        info = self.p.dest_info.text().split('<br>')                           # диски теста не подключены
        self.assertEqual(len(info), 3)                                           # по строке на каждый диск
        self.assertIn('Копия 1 — ', info[0])
        self.assertIn('(HDD45): подключите диск, чтобы проверить свободное место.', info[0])
        self.assertIn('(HDD77): подключите диск', info[1])
        self.assertGreaterEqual(self.p.dest_box.minimumHeight(),
                                rp.QFontMetrics(self.p.dest_box.font()).height() + 16)   # поле выше - низ не обрезан
        self.p.mode_except.setChecked(True)
        self.assertTrue(self.p.mode_except.isChecked() and not self.p.mode_only.isChecked())
        self.assertEqual(self.p.mode_note.text(), rp.MODE_NOTE[rp.EXCEPT])
        self.p.dest = None                                                       # без диска назначения - всё равно режим
        self.p.sync_mode()
        self.assertTrue(self.p.mode_only.isChecked())
        self.assertFalse(self.p.mode_only.isEnabled())
        self.p.set_dest('Н1')
        self.settle()

    def test_select_all_at_root(self):
        self.open()
        m = self.p.model
        tops = self.p.tops()
        self.assertNotIn(MOVED, tops)                                            # служебная - не участвует
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.toggle(['Работа'], True)
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)
        undo = len(m.undo_stack)
        self.p.items[''].setCheckState(rp.C_CHECK, rp.Qt.Checked)               # щелчок - все верхние
        self.assertTrue(all(m.is_dir(m.route[f], 'Н1') for f in tops))
        self.assertEqual(len(m.undo_stack), undo + 1)                            # одним шагом
        self.assertEqual(self.p.items[''].checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertNotIn('', m.drafts)                                           # весь носитель не трогается
        self.p.items[''].setCheckState(rp.C_CHECK, rp.Qt.Unchecked)             # снять все
        self.assertFalse(any(m.is_dir(m.route[f], 'Н1') for f in tops))
        self.p.mode_every.setChecked(True)                                       # в других режимах у корня галочки нет
        self.assertIsNone(self.p.items[''].data(rp.C_CHECK, rp.Qt.CheckStateRole))
        self.settle()

    def test_except_mode_is_red_without_green(self):
        self.open()
        self.p.mode_except.setChecked(True)
        self.p.toggle(['Друзья'], True)                                          # «не копировать»
        it = self.item('Друзья')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.EXC_BG)
        self.assertEqual(it.foreground(rp.C_NAME).color().name(), rp.BLUE)      # не сохранено - синий курсив
        sub = self.item('Друзья\\Наши')
        self.assertEqual(sub.background(rp.C_NAME).color().name(), rp.EXC_BG)  # вместе с родителем - тоже красный фон
        greens = [f for f, x in self.p.items.items() if x.background(rp.C_NAME).color().name() == rp.SEL_BG]
        self.assertEqual(greens, [])                                             # зелёного в этом режиме нет
        self.assertFalse(hasattr(self.p, 'tree_legend'))                         # строки-легенды нет (18.11.2026)
        self.p.mode_only.setChecked(True)
        self.settle()

    def test_busy_label_while_recount(self):
        self.open()
        self.assertFalse(self.p.busy_lab.isVisibleTo(self.p))
        self.p.toggle(['Работа'], True)
        self.assertTrue(self.p.busy_lab.isVisibleTo(self.p))                     # сразу после правки
        self.assertTrue(self.p.blink.isActive())
        self.assertIn('Идёт пересчёт', self.p.busy_lab.text())
        self.settle()
        self.assertTrue(wait(lambda: not self.p.busy_lab.isVisibleTo(self.p)))
        self.assertFalse(self.p.blink.isActive())


if __name__ == '__main__':
    unittest.main()
