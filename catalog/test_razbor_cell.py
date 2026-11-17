"""Ячейка «Копировать на диск …» (razbor_cell, вынесено из razbor_page на этапе 18) и правки по критикам кода этапа 18:
плашка блока диска, когда отмечены только файлы другого типа; строка выделенного файла окна «Список файлов».

Запуск из корня проекта:  py -m unittest catalog.test_razbor_cell
Настоящие диски, таблицы и задания не используются.
"""
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import razbor_cell as rc                                   # noqa: E402
import razbor_page as rp                                   # noqa: E402
import service as sv                                       # noqa: E402
from test_app import wait                                  # noqa: E402
from tests.razbor.base import PageBase                     # noqa: E402 - шаг А: основа тестов разбора

G = 1024 ** 3


class CellTest(unittest.TestCase):
    def test_disk_block_states(self):
        import types
        G = 1024 ** 3
        P = types.SimpleNamespace(part_a={}, disk='HDD60')
        space = {'HDD45': ('H:', 500 * G, 1000 * G, 4096)}
        cap = sv.capacity({'HDD45': [3, G], 'HDD77': [2, G]}, space, {}, disks=['HDD45', 'HDD77'])
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (5, 4 * G), (2, 3 * G), 'H: Бэкап фото и видео', 'H:',
                                   2)
        self.assertEqual(st, 'ok')
        self.assertIn('Копия 1 — H: Бэкап фото и видео (HDD45)', t)
        self.assertIn(f'<b>Копировать на H:</b></td><td align="right" style="color:{rp.GREEN}">3 файла', t)
        self.assertIn('Уже есть на H:</td><td align="right">2 файла</td><td align="right"><b>3,0 ГБ</b></td><td> <a', t)
        self.assertIn('Поместится: нужно', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (5, 4 * G), None, 'Путешествия')
        self.assertIn('Уже есть на HDD77: считаю…', t)
        cap = sv.capacity({'HDD45': [3, 600 * G]}, space, {}, disks=['HDD45', 'HDD77'])
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (5, 4 * G), (0, 0), 'H: Бэкап', 'H:')
        self.assertEqual(st, 'short')
        self.assertIn('Не помещается: нужно', t)
        t, st = rp.disk_block_html(2, 'HDD77', cap['HDD77'], P, (5, 4 * G), (5, 4 * G), 'Путешествия', 'HDD77', 1)
        self.assertEqual(st, 'none')
        self.assertIn(f'<span style="color:{rp.RED}"><b>Копировать нечего: все файлы выбранного в настройках типа уже есть '
                      'на HDD77</b>', t)
        self.assertNotIn('Показать', t)                                          # нули без «Показать»; «уже есть» не совпал
        t, st = rp.disk_block_html(1, 'HDD60', cap['HDD77'], P, (5, 4 * G), None, 'Носитель')
        self.assertIn('Это сам носитель', t)

    def test_only_other_type_gives_plate(self):
        """Критики 18 (GPT-1, DeepSeek-11/12): копировать 0, уже есть 0, отмечены только файлы другого типа - честная
        красная плашка и в одном диске, и в блоке каждого диска."""
        P = types.SimpleNamespace(part_a={}, disk='HDD60')
        space = {'HDD45': ('H:', 500 * G, 1000 * G, 4096)}
        cap = sv.capacity({}, space, {}, disks=['HDD45', 'HDD77'])
        text = 'Копировать нечего: в отмеченных папках нет файлов выбранного в настройках типа'
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (0, 0), (0, 0), 'H: Бэкап', 'H:', 0, 3)
        self.assertEqual(st, 'none')
        self.assertIn(f'<span style="color:{rp.RED}"><b>{text}</b>', t)
        t, st = rp.disk_block_html(1, 'HDD45', cap['HDD45'], P, (0, 0), (0, 0), 'H: Бэкап', 'H:', 0)
        self.assertNotIn('Копировать нечего', t)                                 # ничего не отмечено - без плашки
        self.assertIn(text, rp.plate_html('H:', cap['HDD45'], 0, 0, 2)[0])
        self.assertIn('уже есть на H:', rp.plate_html('H:', cap['HDD45'], 0, 1, 2)[0])   # всё нужного типа уже есть

    def test_cell_module_is_separate(self):
        """Вынос механический: имена ячейки - те же объекты в razbor_page; razbor_cell не тянет окно."""
        for name in ('dest_cell_html', 'disk_block_html', 'plate_html', 'cell_numbers', 'vol', 'esc', 'gb', 'GRAY'):
            self.assertIs(getattr(rp, name), getattr(rc, name))
        src = Path(rc.__file__).read_text(encoding='utf-8')
        self.assertNotIn('razbor_page', src.split('"""', 2)[2])
        self.assertNotIn('PySide6', src)
        self.assertFalse(hasattr(rp, 'where_html'))                              # прежняя строка места удалена


class FileLineTest(PageBase):
    """Критики 18 (GPT-2/3): строка «Файл: …» гаснет, когда выделение снято или список перестроен; путь - как текст."""

    def tearDown(self):
        for w in list(getattr(self.w, 'file_lists', [])):
            w.close()
        super().tearDown()

    def test_file_line_follows_selection(self):
        import directions_page as dp
        dp.save_choice(['Н1'])
        self.mark(('', 'Н1'))
        self.open()
        self.plan()
        w = self.p.show_list('have')
        self.assertTrue(wait(lambda: w.data is not None, 60))
        if not w.model.rowCount():
            w = self.p.show_list('type')
            self.assertTrue(wait(lambda: w.data is not None, 60))
        self.assertTrue(wait(lambda: w.model.rowCount() > 0, 30))
        self.assertEqual(w.file_line.textFormat(), rp.Qt.PlainText)
        w.view.selectRow(0)
        self.assertTrue(w.file_line.text().startswith('Файл: '))
        w.view.clearSelection()                                                  # текущая строка осталась
        self.assertTrue(w.view.currentIndex().isValid())
        self.assertEqual(w.file_line.text(), '')
        w.view.selectRow(0)
        self.assertTrue(w.file_line.text())
        w.model.set_filter(name_sub='нет-такого-имени')                          # список перестроен
        self.assertEqual(w.file_line.text(), '')


if __name__ == '__main__':
    unittest.main()
