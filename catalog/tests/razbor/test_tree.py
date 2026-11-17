"""«Разбор носителя»: Дерево, выбор диска назначения, расположение верха.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_tree
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа


class TreeTest(PageBase):
    def test_tree_inheritance_exceptions_and_display(self):
        """Этап 8: колонка галочек слева; своя отметка D - активная галочка и зелёный фон; подпапки - серая
        неактивная галочка, бледный текст, тот же фон; служебная папка и весь носитель - без галочки."""
        self.open()
        root = self.p.items['']
        names = {root.child(i).text(rp.C_NAME) for i in range(root.childCount())}
        self.assertTrue({'Поход 2010', 'Работа', 'Друзья', 'Документы', 'Смешанная', MOVED} <= names, names)
        self.assertEqual(self.p.dest, 'Н1')                       # «Обзор» пуст, режима нет - первое с диском
        self.assertTrue(self.p.mode_only.isChecked())
        self.assertIn('режим не выбран', self.to(''))
        self.assertEqual(self.item('Поход 2010').text(rp.C_FILES), '7')
        self.assertEqual(self.item('Поход 2010').text(rp.C_PHOTO), '2')
        self.assertEqual(root.checkState(rp.C_CHECK), rp.Qt.Unchecked)            # у носителя - «выбрать все»
        self.assertIsNone(self.item(MOVED).data(rp.C_CHECK, rp.Qt.CheckStateRole))
        it = self.item('Поход 2010')
        self.assertEqual(it.checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.assertTrue(it.flags() & rp.Qt.ItemIsUserCheckable)
        it.setCheckState(rp.C_CHECK, rp.Qt.Checked)                              # как щелчок владельца
        self.assertEqual(self.p.model.drafts['поход 2010']['verdict'], N1)
        it = self.item('Поход 2010')
        self.assertEqual(it.background(rp.C_NAME).color().name(), rp.SEL_BG)
        self.assertTrue(it.text(rp.C_NAME).startswith('• '))                      # не сохранено
        self.assertTrue(it.font(rp.C_NAME).italic())
        ch = self.item('Поход 2010\\Фото')
        self.assertEqual(ch.checkState(rp.C_CHECK), rp.Qt.Checked)
        self.assertTrue(ch.data(rp.C_CHECK, rp.GRAY_ROLE))                        # бледная (вместе с родителем)
        self.assertTrue(ch.flags() & rp.Qt.ItemIsUserCheckable)                   # этап 17: но активная
        self.assertEqual(ch.foreground(rp.C_NAME).color().name(), rp.PALE)
        self.assertEqual(ch.background(rp.C_NAME).color().name(), rp.SEL_BG)     # один зелёный фон
        self.assertIn('вместе с родительской', ch.toolTip(rp.C_NAME))
        self.assertIn('Снимите галочку', ch.toolTip(rp.C_NAME))
        self.assertEqual(self.p.toggle(['Поход 2010\\Фото'], False), 1)          # этап 17: снять = исключить
        self.assertEqual(self.p.model.drafts['поход 2010\\фото']['verdict'], rp.SKIP)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)   # исключение внутри
        self.assertEqual(self.p.toggle(['Поход 2010\\Фото'], True), 1)           # поставить = снять исключение
        self.assertNotIn('поход 2010\\фото', self.p.model.drafts)
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.Checked)
        # снять галочку = снять свою отметку: черновик пуст, папка снова не выбрана
        self.item('Поход 2010').setCheckState(rp.C_CHECK, rp.Qt.Unchecked)
        self.assertEqual(self.p.model.drafts, {})
        self.assertEqual(self.item('Поход 2010\\Фото').checkState(rp.C_CHECK), rp.Qt.Unchecked)
        # подпапка, отмеченная отдельно, внутри выбранной: снятие её галочки - исключение («не копировать»)
        self.p.toggle(['Поход 2010\\Монтаж'], True)
        self.p.toggle(['Поход 2010'], True)
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], N1)   # своя осталась
        self.p.toggle(['Поход 2010\\Монтаж'], False)
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], rp.SKIP)
        self.assertEqual(self.item('Поход 2010\\Монтаж').checkState(rp.C_CHECK), rp.Qt.Unchecked)
        self.p.undo()
        self.assertEqual(self.p.model.drafts['поход 2010\\монтаж']['verdict'], N1)
        self.assertFalse(self.p.model.markable(MOVED))
        self.assertEqual(self.to(MOVED + '\\Старое'), 'уже перенесено')
        self.assertEqual(self.asked, [])

    def test_route_contract_against_reference(self):
        """Маршрут окна = независимый расчёт (самая глубокая отметка, последняя строка, снятие, служебная папка) - для
        КАЖДОЙ папки и с указанием решающей отметки (а не только суммы)."""
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('ДРУЗЬЯ', 'не копировать'), ('Друзья\\Наши', 'Н3'),
                  (MOVED + '\\Старое', 'Н2'), ('Смешанная', 'Н3'))
        self.mark(('Смешанная', 'как у родителя'), ('Друзья\\Наши', 'Н2'))
        self.open()
        m = self.p.model
        self.p.apply(['Поход 2010\\Монтаж'], rp.SKIP)
        self.p.apply(['Работа'], rp.INHERIT)                   # снятие сохранённой отметки - черновиком
        for ms, route in ((m.full_ms, m.route), (m.saved_ms, m.route_saved)):
            for f in m.folders:
                ref = reference_route(m, f, ms)
                r = route[f]
                self.assertEqual(r.mark.row if r.mark else None, ref.row if ref else None, f)
                if ref is not None:
                    exp = rz._mark_route(ref, m.dirs)
                    self.assertEqual((r.state, r.num), (exp.state, exp.num), f)
        self.assertEqual(m.route['Друзья\\Наши'].num, 'Н2')          # последняя строка пути
        self.assertEqual(m.route['Смешанная'].state, m.route[''].state)   # «как у родителя» сняла отметку
        self.assertEqual(m.cell('Работа')['dirty'], 'drop')
        self.assertTrue(m.cell('Работа')['text'].startswith('• снять свою отметку → Семейный архив'))
        self.assertEqual(m.cell(MOVED + '\\Старое')['kind'], 'own')
        # итог ядра с тем же черновиком: файлы «не копировать» - те, что окно показывает «не копировать»
        P = self.plan()
        skip_files = sum(1 for p, _s, _h in FILES if m.route[hb.parent_of(p)].state == rp.R_SKIP)
        self.assertEqual(P.part_a[(rz.O_SKIP, None)][0], skip_files)

    def test_same_original_path_inside_and_outside_moved_folder(self):
        make_disk(self.scans, 'HDD61', 'AAAA0061', [('Поход\\a.jpg', 10, S[7]), (MOVED + '\\Поход\\b.jpg', 20, S[8])])
        self.quiet(hb.connect)
        m = rp.Model(sv.razbor_tree('HDD61'))
        self.assertEqual(m.set_mark([MOVED + '\\Поход'], N2), 1)
        self.assertEqual(list(m.drafts), ['поход'])                     # одна отметка по исходному пути
        self.assertEqual(m.route['Поход'].num, 'Н2')
        self.assertEqual(m.route[MOVED + '\\Поход'].num, 'Н2')
        self.assertIn('Та же отметка действует и на', m.cell('Поход')['tip'])
        self.assertEqual(len(m.batch()[0]), 1)

    def test_have_column(self):
        self.mark(('', 'Семейный архив'), ('Работа', 'Н2'), ('Друзья', 'не копировать'))
        self.open()
        self.assertEqual(self.item('Поход 2010\\Фото').text(rp.C_HAVE), '1')     # 1.jpg есть на 45 и 77, 2.jpg - только на 45
        self.assertEqual(self.item('Поход 2010').text(rp.C_HAVE), '1')
        self.assertEqual(self.item('Работа').text(rp.C_HAVE), '0')               # направление с диском, ничего нет
        self.assertEqual(self.item('Друзья').text(rp.C_HAVE), '—')               # не копировать
        self.assertEqual(self.p.items[''].text(rp.C_HAVE), '1')
        self.p.apply(['Поход 2010\\Фото'], N2)                                   # исключение в подпапке: своё направление
        self.assertEqual(self.item('Поход 2010\\Фото').text(rp.C_HAVE), '0')
        self.assertEqual(self.item('Поход 2010').text(rp.C_HAVE), '0')


class ChoiceTest(PageBase):
    def test_opens_with_direction_chosen_in_overview(self):
        """Этап 8: диск назначения - первое по номеру направление, отмеченное в «Обзоре»; сохранённая отметка всего
        носителя не меняется; если она про другое направление - строка под переключателями."""
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.open()
        self.assertEqual(self.p.dest, 'Н2')
        self.assertEqual(self.p.dest_box.currentData(), 'Н2')
        self.assertFalse(self.p.dest_box.isVisibleTo(self.p))                 # этап 16: строки выбора диска нет
        self.assertTrue(self.p.where.text().startswith('Диск назначения: Накопитель — HDD91'), self.p.where.text())
        self.assertNotIn('Работа', self.p.where.text())                        # имя направления - в ячейке, не в плашке
        self.assertNotIn('отмечено ещё', self.p.where.text())
        self.assertEqual(self.p.model.drafts, {})                                # ничего не отмечено молча
        self.p.set_dest('Н1')                                                    # владелец выбрал другое
        self.assertEqual(self.p.dest, 'Н1')
        dp.save_choice(['Н2', 'Н1'])                                             # снова из «Обзора»: по номеру - Н1
        self.p.set_dest('Н2')
        self.p.use_choice()
        self.assertEqual(self.p.dest, 'Н1')
        self.assertIn('В «Обзоре» отмечено ещё: А2 Работа', self.p.where.text())   # первое по номеру - и сказано
        self.mark(('', 'Н2'))                                                    # сохранённый режим - «всё в Н2»
        dp.save_choice(['Н1'])
        self.p.load_disk(SRC, keep=False)
        self.assertTrue(wait(lambda: self.p.model is not None and self.p.loading is None))
        self.p.use_choice()
        self.assertEqual(self.p.dest, 'Н1')
        self.assertTrue(self.p.mode_only.isChecked())                            # корень ≠ Н1 - «Только выбранные»
        self.assertIn('Весь носитель отмечен «Всё — в Работа (91)»', self.p.mode_note.text())
        self.assertEqual(self.p.model.drafts, {})
        self.p.set_dest('Н2')                                                    # для Н2 корень = Н2 - «Все папки»
        self.assertTrue(self.p.mode_every.isChecked())
        self.assertNotIn('Весь носитель отмечен', self.p.mode_note.text())
        self.settle()


class LayoutTest(PageBase):
    """Этап 8: тексты списков «Выберите носитель» и «Диск назначения», заголовок, «Задания на копирование»."""

    def test_texts_of_lists_and_head(self):
        import types
        rows = [dict(disk='HDD09', label='SN850X - 2 ТБ - Монтаж - SN850', letter='F:'),
                dict(disk='HDD45', label='WD20 - 2 ТБ - Бэкап фото и видео', letter='H:'),
                dict(disk='HDD77', label='WD40 - 4 ТБ - Путешествия', letter='')]
        self.assertEqual(rp.carrier_text(rows[0]), 'F: Монтаж - SN850 — HDD09 (по журналу сканирования дисков)')
        self.assertEqual(rp.carrier_text(rows[2]), 'Путешествия (не подключён) — HDD77 (по журналу '
                                                   'сканирования дисков)')
        self.assertEqual(rp.carrier_text(dict(disk='HDD61', label='ACASIS EC-7352 - 750 ГБ', letter='')),
                         'Накопитель (не подключён) — HDD61 (по журналу сканирования дисков)')   # метки нет - «Накопитель»
        d1 = sv.directions()['Н1']
        # этап 12: направление на двух дисках - коротко, диски не сливаются в одну строку
        self.assertEqual(rp.dest_text(d1, rows), 'А1 Семейный архив — H: и HDD77 (две копии)')
        self.assertIn(f'<span style="color:{rp.ORANGE}"><b>А1 Семейный архив</b></span>', rp.dest_html(d1, rows))
        h = rp.head_html(d1, rows, {'HDD45': ('H:', 421 * 1024 ** 3, 2 * 10 ** 12, 4096)})
        # этап 16: «Диск назначения: H: Бэкап фото и видео — HDD45, 2 ТБ · свободно …» - диск вместо направления
        self.assertTrue(h.startswith('Диск назначения — две копии:<br>'), h)
        self.assertNotIn('Семейный архив', h)
        lines = h.split('<br>')
        self.assertEqual(len(lines), 3)                                        # заголовок, два диска
        self.assertTrue(lines[1].endswith('H: Бэкап фото и видео — HDD45, 2 ТБ <span style="color:#33691e">· свободно '
                                          '421,0 ГБ</span>'), lines[1])
        self.assertIn('Путешествия — HDD77 <span', lines[2])
        self.assertIn('не подключён', lines[2])                                 # плашка - у своего диска
        self.assertNotIn('не подключён', lines[1])
        d3 = types.SimpleNamespace(num='Н3', name='Фильмы', disks=('HDD55',))
        h = rp.head_html(d3, [dict(disk='HDD55', label='WD20 - 2 ТБ - My Book', letter='I:')],
                         {'HDD55': ('I:', 421 * 1024 ** 3, 16000900165632, 4096)})
        self.assertEqual(h, 'Диск назначения: I: My Book — HDD55, 16 ТБ <span style="color:#33691e">· свободно 421,0 ГБ'
                            '</span>')
        off = rp.head_html(d3, [dict(disk='HDD55', label='WD20 - 2 ТБ - My Book', letter='')])
        self.assertTrue(off.startswith('Диск назначения: My Book — HDD55 <span'), off)   # объём не известен - нет
        self.assertIn('не подключён', off)
        self.assertNotIn('Фильмы', h + off)
        self.assertEqual(rp.tb_text(500107862016), '500 ГБ')
        self.assertEqual(rp.tb_text(4000787030016), '4 ТБ')
        self.assertEqual(rp.tb_text(1500301910016), '1,5 ТБ')
        o = rp.head_html(d3, [dict(disk='HDD55', label='', letter='I:')], others=[types.SimpleNamespace(num='Н7',
                                                                                                         name='Ещё')])
        self.assertIn('отмечено ещё: А7 Ещё', o)
        for x in (rp.carrier_text(rows[0]), rp.dest_text(d1, rows)):
            self.assertNotIn('ТБ)', x)                                          # ни модели, ни объёма
        # в окне: строки списков по той же схеме, подключённые сверху (в тестах дисков нет - все «не подключён»)
        self.open()
        texts = [self.p.disk_box.itemText(i) for i in range(self.p.disk_box.count())]
        self.assertTrue(all(t.endswith('(по журналу сканирования дисков)') for t in texts if t), texts)
        by = {r['disk']: r for r in self.p.disk_rows}
        pl = lambda d: rp.place(by[d], d)                                                     # noqa: E731
        self.assertTrue(pl('HDD60').endswith('(не подключён)'))
        self.assertIn(rp.carrier_text(by['HDD60']), texts)
        dest = [self.p.dest_box.itemText(i) for i in range(self.p.dest_box.count())]
        self.assertEqual(dest, ['А1 Семейный архив — HDD45 и HDD77 (две копии)',
                                f'{pl("HDD91")} — А2 Работа — HDD91 (по журналу сканирования дисков)'])  # Н3 без диска
        self.assertIn(rp.ORANGE, self.p.dest_box.current_html())
        self.assertEqual([w.text() for w in (self.p.mode_only, self.p.mode_every, self.p.mode_except)],
                         ['Только выбранные папки', 'Все папки', 'Все, кроме выбранных'])
        self.assertEqual(self.p.copy_cell.title.text(), 'Копировать на два диска — две копии')
        # п. 3 этапа 12: имя направления под заголовком - оранжевым и жирным, номера HDD - обычным текстом
        self.assertEqual(self.p.copy_cell.sub.text(), f'<span style="color:{rp.ORANGE}"><b>Семейный архив</b></span>, '
                                                      'HDD45 и HDD77')
        self.assertNotIn('color', self.p.copy_cell.sub.styleSheet())           # не серая строка
        self.p.set_dest('Н2')
        self.assertEqual(self.p.copy_cell.title.text(), 'Копировать на диск ' + rp.short_place(by['HDD91'], 'HDD91'))
        self.assertEqual(self.p.copy_cell.sub.text(), f'<span style="color:{rp.ORANGE}"><b>Работа</b></span>, HDD91')
        self.assertEqual(self.p.copy_cell.blocks, [])                          # один диск - блоков нет
        self.p.set_dest('Н1')
        self.assertFalse(hasattr(self.p, 'stay_cell'))                         # ячейку «Остаётся» владелец убрал
        self.assertTrue(self.p.copy_cell.acceptDrops())
        self.assertIn('Shift/Ctrl — несколько папок сразу', self.p.tree_hint.text())
        for gone in ('apply_box', 'apply_btn', 'unmark_btn', 'mode_dir'):
            self.assertFalse(hasattr(self.p, gone), gone)
        self.assertEqual(self.p.tree.headerItem().text(rp.C_NAME), 'Папка')
        self.assertNotIn('Куда', [self.p.tree.headerItem().text(i) for i in range(self.p.tree.columnCount())])


if __name__ == '__main__':
    unittest.main()
