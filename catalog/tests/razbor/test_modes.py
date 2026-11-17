"""«Разбор носителя»: Три режима, «уже есть», итог.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_modes
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа


class ModesTest(PageBase):
    """Этап 8: три режима ↔ отметки ядра, галочки нескольких выделенных, папки другого направления, бросок в ячейку,
    числа ячеек = план ядра."""

    def check_consistent(self):
        """Галочки на экране = маршрут ядра (Model.routes): в «Только»/«Все папки» галочка ⇔ папка идёт в D, в
        «Все, кроме» ⇔ «не копировать»."""
        m, mode = self.p.model, self.p.mode()
        for f, it in self.p.items.items():
            ck = m.check(f, self.p.dest, mode)
            if ck is None:
                continue
            r = m.route[f]
            want = r.state == rp.R_SKIP if mode == rp.EXCEPT else m.is_dir(r, self.p.dest)
            self.assertEqual(it.checkState(rp.C_CHECK) == rp.Qt.Checked, want, f)

    def test_three_modes_map_to_core_marks(self):
        self.open()
        m = self.p.model
        self.assertEqual(self.p.mode(), rp.ONLY)
        self.p.toggle(['Поход 2010', 'Работа'], True)                           # «Только выбранные»: галочка = Н1
        self.assertEqual(self.owns(), {'поход 2010': N1, 'работа': N1})
        self.item('Поход 2010\\Фото')
        self.check_consistent()
        # «Все папки»: весь носитель - в Н1
        self.p.mode_every.setChecked(True)
        self.assertEqual(self.own(''), N1)
        self.assertEqual(self.p.mode(), rp.EVERY)
        self.assertTrue(self.p.mode_hint.text().startswith('•'))
        self.item('Друзья\\Наши')
        self.check_consistent()
        self.assertTrue(self.p.items['Друзья'].data(rp.C_CHECK, rp.GRAY_ROLE))   # всё - от всего носителя, серым
        # «Все, кроме выбранных»: галочка = «не копировать»
        self.p.mode_except.setChecked(True)
        self.assertEqual(self.p.mode(), rp.EXCEPT)
        self.assertEqual(self.p.items['Друзья'].checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.items['Друзья'].setCheckState(rp.C_CHECK, rp.Qt.Checked)
        self.assertEqual(self.own('друзья'), rp.SKIP)
        self.assertEqual(self.p.items['Друзья\\Наши'].checkState(rp.C_CHECK), rp.Qt.Checked)     # исключена с родителем
        self.assertTrue(self.p.items['Друзья\\Наши'].data(rp.C_CHECK, rp.GRAY_ROLE))
        self.check_consistent()
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], 2)                     # a.jpg и b.jpg
        self.assertIn('Отмечено: весь носитель, кроме 1 папки', self.p.copy_cell.body.text())
        self.p.items['Друзья'].setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # снять исключение
        self.assertEqual(self.own('друзья'), rp.INHERIT)
        self.p.toggle(['Друзья'], True)
        # «Все папки» снимает исключения одним шагом отмены
        self.p.mode_every.setChecked(True)
        self.assertEqual(self.own('друзья'), rp.INHERIT)
        self.p.undo()
        self.assertEqual(self.own('друзья'), rp.SKIP)
        # обратно «Только выбранные»: отметки носителя до «Все папки» не было - «ничего, кроме отмеченных»; свои Н1
        self.p.mode_only.setChecked(True)
        self.assertEqual(self.own(''), rp.SKIP)
        self.assertEqual(self.own('поход 2010'), N1)
        self.assertEqual(self.p.mode(), rp.ONLY)
        self.check_consistent()
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_NONE, None)][0] if (rz.O_NONE, None) in P.part_a else 0, 0)
        self.assertEqual(self.asked, [])

    def test_only_returns_to_saved_mode_of_other_direction(self):
        self.mark(('', 'Н2'))
        self.open()
        self.assertEqual(self.p.dest, 'Н2')                                     # «Обзор» пуст - направление носителя
        self.p.set_dest('Н1')
        self.assertTrue(self.p.mode_only.isChecked())
        self.p.mode_except.setChecked(True)                                      # корень - Н1
        self.assertEqual(self.own(''), N1)
        self.settle()                                                            # этап 16: Н1 уже записано в таблицу
        self.p.mode_only.setChecked(True)                                        # вернуть прежнее «всё в Н2»
        self.assertEqual(self.own(''), sv.directions()['Н2'].verdict())
        self.assertEqual(self.p.model.route[''].num, 'Н2')
        self.settle()
        self.assertEqual(self.p.model.saved_ms.get('').num, 'Н2')

    def test_check_applies_to_all_selected(self):
        """Решение 16.11: выделение нескольких папок (Shift/Ctrl) сразу ставит галочки всем выделенным (один шаг
        отмены); щелчок по галочке потом снимает только её."""
        self.open()
        m = self.p.model
        self.p.tree.clearSelection()
        for f in ('Друзья', 'Работа', 'Документы'):
            self.item(f).setSelected(True)

        class Ev:
            def __init__(self, mods):
                self.mods = mods

            def modifiers(self):
                return self.mods

            def position(self):
                return QPointF(-5, -5)                                        # не по колонке галочек
        self.p.tree.multi(Ev(rp.Qt.NoModifier))                                  # без Shift/Ctrl - ничего
        wait(lambda: False, 0.5)
        self.assertEqual(self.owns(), {})
        self.p.tree.multi(Ev(rp.Qt.ControlModifier))                             # Ctrl-щелчок - всем сразу
        self.assertTrue(wait(lambda: len(self.owns()) == 3))
        self.assertEqual(self.owns(), {'друзья': N1, 'работа': N1, 'документы': N1})
        self.assertEqual(len(m.undo_stack), 1)                                   # один шаг отмены
        self.assertTrue(wait(lambda: len(self.p.selected_folders()) == 3))       # выделение осталось
        self.item('Документы').setCheckState(rp.C_CHECK, rp.Qt.Unchecked)       # этап 12: у всей выделенной группы
        self.assertEqual(self.owns(), {})
        self.assertEqual(len(m.undo_stack), 2)
        self.p.check_selected()                                                  # повтор: уже отмеченные не трогаются
        self.assertEqual(set(self.owns()), {'друзья', 'работа', 'документы'})
        self.settle()

    def test_folder_of_other_direction(self):
        self.mark(('Работа', 'Н2'), ('Смешанная', 'Н2'))
        self.open()
        it = self.item('Работа')
        self.assertEqual(it.checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.assertEqual(it.data(rp.C_NAME, rp.TAG_ROLE), 'А2')                  # мелкая серая метка (на экране «А»)
        self.assertIn('Папка отмечена для «А2 Работа» (91)', it.toolTip(rp.C_NAME))
        self.assertIn('перейдёт на этот диск', it.toolTip(rp.C_NAME))
        it.setCheckState(rp.C_CHECK, rp.Qt.Checked)                              # перенос - без переспроса
        self.assertEqual(self.p.model.drafts['работа']['verdict'], N1)
        self.assertIsNone(self.item('Работа').data(rp.C_NAME, rp.TAG_ROLE))
        self.assertTrue(self.item('Работа').text(rp.C_NAME).startswith('• '))
        self.assertEqual(self.asked, [])
        # «Все, кроме выбранных»: галочка = исключение, папку другого направления так не перенести - только бросок
        self.p.mode_except.setChecked(True)
        ck = self.p.model.check('Смешанная', 'Н1', rp.EXCEPT)
        self.assertFalse(ck['checkable'])
        self.assertEqual(ck['tag'], 'А2')
        self.assertIn('перетащите', ck['tip'])
        self.assertEqual(self.p.toggle(['Смешанная'], True), 0)
        self.assertEqual(self.p.copy_cell.drop_folders(['Смешанная']), 1)
        self.assertEqual(self.p.model.route['Смешанная'].num, 'Н1')
        self.settle()

    def test_drop_into_copy_cell(self):
        self.open()
        m = self.p.model
        md = self.p.tree.mimeData([self.p.items[''], self.item('Поход 2010'), self.item(MOVED)])
        self.assertEqual(rp.mime_folders(md), ['Поход 2010'])                     # не весь носитель, не служебная
        self.assertFalse(self.p.items[''].flags() & rp.Qt.ItemIsDragEnabled)
        self.assertEqual(self.p.copy_cell.drop_folders(['Поход 2010', '', MOVED]), 1)
        self.assertEqual(m.drafts['поход 2010']['verdict'], N1)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertEqual(self.p.copy_cell.drop_folders(['Поход 2010\\Фото']), 0)  # уже идёт с родителем - ничего
        self.p.mode_except.setChecked(True)                                      # в «Все, кроме» бросок снимает исключение
        self.p.toggle(['Друзья'], True)
        self.assertEqual(m.drafts['друзья']['verdict'], rp.SKIP)
        self.assertEqual(self.p.copy_cell.drop_folders(['Друзья']), 1)
        self.assertNotIn('друзья', m.drafts)
        self.settle()

    def test_cell_numbers_match_plan(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        self.mark(('', 'не копировать'), ('Поход 2010', 'Н1'), ('Работа', 'Н1'), ('Поход 2010\\Монтаж', 'не копировать'))
        self.open()
        self.assertEqual(self.p.mode(), rp.ONLY)
        P = self.plan()
        cp, hv = P.part_a[(rz.O_COPY, 'Н1')], P.part_a.get((rz.O_HAVE, 'Н1'), (0, 0))
        tp, jk = P.part_a.get((rz.O_TYPE, 'Н1'), (0, 0)), P.junk_dir['Н1']
        body = self.p.copy_cell.body.text()
        # этап 18: «Отмечено» - все файлы отмеченных папок: копировать + уже есть + не копируются по типу (и мусор)
        n_all, b_all = cp[0] + hv[0] + tp[0] + jk[0], cp[1] + hv[1] + tp[1] + jk[1]
        self.assertIn(f'Отмечено 2 папки · {rp.files_word(n_all)} · {rp.vol(b_all)}', body)
        self.assertIn(rp.SKIP_TEXT, body)                                        # общая серая строка
        # этап 12: два диска - два блока «Копия 1 / Копия 2», числа каждого - по плану ядра для этого диска
        texts = self.p.copy_cell.block_texts()
        self.assertEqual(list(texts), ['HDD45', 'HDD77'])
        by = {r['disk']: r for r in self.p.disk_rows}
        total = (cp[0] + hv[0], cp[1] + hv[1])
        self.assertEqual(total, (5, 400))            # 1.jpg, 2.jpg, описание.doc, схема.jpg, отчёт.doc
        have = self.p.model.have_on_disk('Н1')
        self.assertEqual(have, {'HDD45': (2, 300), 'HDD77': (1, 100)})          # 1.jpg - на обоих, 2.jpg - только на 45
        self.assertEqual(min(have.values()), tuple(hv))                          # «на всех дисках» = часть А ядра
        for i, x in enumerate(('HDD45', 'HDD77'), 1):
            t = texts[x]
            pb = P.part_b[x]
            self.assertEqual(pb[0], total[0] - have[x][0])                       # недостающее на диске = часть Б ядра
            self.assertIn(f'Копия {i} — {rp.esc(rp.disk_ui.disk_place(by[x]))} ({x})', t)
            self.assertIn(f'<b>Копировать на {x}</b></td><td align="right" style="color:{rp.GREEN}">'
                          f'{rp.files_word(pb[0])}', t)
            self.assertIn(f'Уже есть на {x}</td><td align="right">{rp.files_word(have[x][0])}', t)
            self.assertIn(f'Место не проверено: {x} не подключён', t)
        self.assertNotIn('Уже есть на обоих', body)                              # общая часть - одна строка «Отмечено»
        self.assertNotIn('Место не проверено', body)
        self.assertNotIn('на 45', body + ''.join(texts.values()))                # никаких голых «на 45»
        self.assertEqual(self.p.copy_cell.block_states(), {'HDD45': 'unknown', 'HDD77': 'unknown'})
        blocks = [b[1] for b in self.p.copy_cell.blocks]
        lay = self.p.copy_cell.layout()
        self.assertLess(lay.indexOf(self.p.copy_cell.body), lay.indexOf(self.p.copy_cell.blocks_box))
        row = next(i for i in range(lay.count()) if lay.itemAt(i).layout()            # строка кнопок (17.11.2026: с
                   and lay.itemAt(i).layout().indexOf(self.p.tasks_btn) >= 0)           # «Отсканировать эти папки»)
        self.assertLess(lay.indexOf(self.p.copy_cell.blocks_box), row)                  # кнопка - под блоками
        self.assertTrue(all('border:1px solid' in b.styleSheet() for b in blocks))   # у каждого блока - рамка
        n, b = rp.stay_numbers(P)
        moved = P.part_a.get((rz.O_MOVED, None), (0, 0))[0]
        self.assertEqual(cp[0] + hv[0] + n + moved, P.total[0])                  # отмечено + остаётся + перенесено = опись
        self.assertEqual(self.p.copy_cell.state, 'unknown')
        # 17.11.2026: документы без хеша пойдут на диски - задания только после пересканирования (test_nohash)
        self.assertTrue(wait(lambda: self.p.nohash_result() is not None, 30))
        self.assertGreater(self.p.nohash_result()['n'], 0)
        self.assertFalse(self.p.tasks_btn.isEnabled())
        self.assertIn('Сначала хеш', self.p.tasks_btn.toolTip())
        self.assertIs(self.p.tasks_btn, self.p.copy_cell.btn)


class HaveNearTest(PageBase):
    def test_have_docs_only_near_matches_planner(self):
        """Замечание 2: «Уже есть» при «документы только рядом» = ядро: документ без фото рядом - не в «Уже есть»."""
        make_disk(self.scans, 'HDD64', 'AAAA0064', [('A\\x.doc', 10, S[1]), ('B\\y.doc', 10, S[1]),
                                                     ('B\\z.jpg', 10, H50)])
        hb.close_last()
        self.quiet(hb.connect)
        self.mark(('', 'Н1'), disk='HDD64')
        self.p.refresh()
        self.assertTrue(wait(lambda: any(r['disk'] == 'HDD64' for r in self.p.disk_rows)))
        self.open('HDD64')
        self.assertEqual(self.item('A').text(rp.C_HAVE), '0')                    # документ без фото рядом
        self.assertEqual(self.item('B').text(rp.C_HAVE), '1')                    # y.doc - рядом с z.jpg, есть на 45 и 77
        P = sv.razbor('HDD64')
        self.assertEqual(P.part_a[(rz.O_HAVE, 'Н1')][0], int(self.p.items[''].text(rp.C_HAVE)))
        self.assertEqual(P.part_a[(rz.O_TYPE, 'Н1')][0], 1)


class SummaryTest(PageBase):
    def test_modes_and_summary_equals_inventory(self):
        self.open()
        self.p.mode_every.setChecked(True)                                     # диск назначения - Н1
        P = self.plan()
        self.assertEqual(P.errors, [])
        self.assertEqual(P.total[0], len(FILES))
        self.assertEqual(sum(v[0] for v in P.part_a.values()), len(FILES))
        text = self.p.summary.toPlainText()
        self.assertIn('Итого = опись носителя', text)
        self.assertIn('HDD45', text)
        self.assertIn('не подключён — место не проверено', text)
        self.assertIn('сравнение только по имени и размеру', text)              # описание.doc без хеша
        self.assertIn('Посчитано в', self.p.sum_state.text())
        # «Только выбранные» = «ничего, кроме отмеченных»: всё - «не копировать», кроме уже перенесённого
        self.p.mode_only.setChecked(True)
        P = self.plan()
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], len(FILES) - 1)
        self.assertEqual(P.part_a[(rz.O_MOVED, None)][0], 1)
        self.assertIn('Писать на диски нечего', self.p.summary.toPlainText())
        self.p.apply(['Друзья'], N2)
        P = self.plan()
        self.assertEqual(dict(P.part_b), {'HDD91': [2, 185]})
        self.assertEqual(self.own(''), rp.SKIP)

    def test_stale_answer_is_not_shown(self):
        self.open()
        self.p.mode_every.setChecked(True)
        self.p.changed()                                    # правка во время расчёта: ревизия растёт сразу
        self.assertNotEqual(self.p.plan_rev, self.p.rev)
        self.settle()
        self.assertEqual(self.p.plan_rev, self.p.rev)


if __name__ == '__main__':
    unittest.main()
