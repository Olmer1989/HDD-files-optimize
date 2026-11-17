"""«Разбор носителя»: Этап 18: полные пути в списке файлов, ячейка «Копировать», частичная галочка.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_stage18
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа


class Stage18Test(PageBase):
    """Этап 18: «Отмечено» = сумма трёх строк ячейки (с мусором и вложенными отметками), частичная галочка у
    неотмеченной папки с отмеченными подпапками (оба дерева), пути с буквой и без, строка выделенного файла."""

    def tearDown(self):
        for w in list(getattr(self.w, 'file_lists', [])):
            w.close()
        super().tearDown()

    def test_marked_equals_three_rows(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        self.mark(('Поход 2010', 'Н1'), ('Поход 2010\\Фото', 'Н1'), ('Поход 2010\\Монтаж', 'не копировать'),
                  ('Документы', 'Н1'))
        self.open()
        P = self.plan()
        v = rp.cell_numbers(self.p.dest_dir(), P)
        m = self.p.model
        ref = [(p, s) for p, s, _h in FILES if m.is_dir(m.route[hb.parent_of(p)], 'Н1')]   # независимо: маршрут папки
        self.assertEqual(v['total'], (len(ref), sum(s for _p, s in ref)))       # без двойного счёта
        self.assertEqual(tuple(a + b + c for a, b, c in zip(v['copy'], v['have'], v['skip'])), v['total'])
        self.assertGreater(P.junk_dir['Н1'][0], 0)                               # Thumbs.db - в «не копируются»
        self.assertIn(f'Отмечено 2 папки · {rp.files_word(len(ref))}', self.p.copy_cell.body.text())
        lst = sv.file_list('type', SRC, num='Н1')
        self.assertEqual(len(lst['rows']), v['skip'][0])                         # «Показать» = число строки
        self.assertIn('Поход 2010\\Фото\\Thumbs.db', {r[1] for r in lst['rows']})

    def test_unmarked_parent_with_marked_subfolders(self):
        import directions_page as dp
        dp.save_choice(['Н2'])
        self.mark(('Поход 2010\\Фото', 'Н2'), ('Поход 2010\\Монтаж', 'Н2'))     # как «Алтай 2022 …» на HDD09
        self.open()
        it = self.item('Поход 2010')
        self.assertEqual(it.checkState(rp.C_CHECK), rp.Qt.PartiallyChecked)      # «Разбор»: частичная
        self.assertEqual(it.data(rp.C_CHECK, rp.PART_ROLE), 'on')
        self.plan()
        w = self.p.show_list('copy:HDD91')
        self.assertTrue(wait(lambda: w.data is not None, 60))
        par = w.f_items['Поход 2010']
        self.assertEqual(par.checkState(0), rp.Qt.PartiallyChecked)             # окно: частичная, раскрыта
        self.assertTrue(par.isExpanded())
        self.assertEqual(w.f_items['Поход 2010\\Фото'].checkState(0), rp.Qt.Checked)
        self.assertEqual(w.f_items['Поход 2010\\Монтаж'].checkState(0), rp.Qt.Checked)
        par.setCheckState(0, rp.Qt.Checked)                                      # щелчок по частичной - выбрать всю
        self.assertEqual(self.own('Поход 2010'), sv.directions()['Н2'].verdict())
        self.settle()
        self.assertEqual(self.item('Поход 2010').checkState(rp.C_CHECK), rp.Qt.Checked)
        # пути: носитель не подключён - «HDD60\…»; строка выделенного файла
        self.assertIn('Носитель: <b>HDD60</b>', w.carrier.text())
        self.assertIn('не подключён', w.carrier.text())
        self.assertTrue(wait(lambda: w.model.rowCount() > 0, 30))
        w.view.selectRow(0)
        w.show_file_line()
        r = w.model.row(0)
        self.assertEqual(w.model.data(w.model.index(0, 0)), f'HDD60\\{r[1]}')
        self.assertTrue(w.file_line.text().startswith(f'Файл: HDD60\\{r[1]}\\{r[2]}'))
        w.model.letters = {'HDD60': 'F:'}                                        # подключён - с буквой
        self.assertEqual(w.model.data(w.model.index(0, 0)), f'F:\\{r[1]}')
        self.assertEqual(rp.sv.full_path('HDD60', '', {'HDD60': 'F:'}), 'F:\\')
        self.assertEqual(rp.sv.full_path('HDD60', ' X ', {}), 'HDD60\\ X ')       # пробелы не трогаются


if __name__ == '__main__':
    unittest.main()
