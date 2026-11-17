"""«Выбор источников»: тексты и вид по замечаниям владельца 18.11.2026 (экран 4) - «Из содержимого …», «Типы файлов: …»,
пояснение цветов над деревом, строка «без хеша» с архивным диском, «Спорные» без «45 и 77», одна галочка у носителя.

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_texts_18
Настоящие диски, таблицы и задания не используются.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.razbor.base import *                          # noqa: E402,F401,F403 - общая основа
from PySide6.QtCore import Qt                             # noqa: E402

from ui.razbor import common, texts_cell, texts_head    # noqa: E402

DIR1 = SimpleNamespace(num='Н1', disks=['HDD45'])
ROW_ON = {'disk': 'HDD45', 'label': 'WD - 16 ТБ - Бэкап фото и видео', 'letter': 'H:', 'total_bytes': 16 * 10 ** 12}
ROW_OFF = {'disk': 'HDD45', 'label': 'WD - 16 ТБ - Бэкап фото и видео', 'letter': ''}
NH = dict(n=37945, folders=['a'] * 27, root=0, cats=[], copies={})


class TextsUnitTest(unittest.TestCase):
    """Тексты без окна (п. 2, 4, 5)."""

    def test_archive_where(self):
        self.assertEqual(texts_head.archive_where(DIR1, [ROW_ON]), 'Архивном диске А1 (H: «Бэкап фото и видео», 16 ТБ)')
        self.assertEqual(texts_head.archive_where(DIR1, [ROW_OFF]), 'Архивном диске А1 (HDD45 «Бэкап фото и видео»)')
        self.assertEqual(texts_head.archive_where(DIR1, []), 'Архивном диске А1 (HDD45)')         # метки нет
        two = SimpleNamespace(num='Н1', disks=['HDD45', 'HDD77'])
        self.assertEqual(texts_head.archive_where(two, [ROW_ON]),
                         'Архивных дисках А1 (H: «Бэкап фото и видео», 16 ТБ и HDD77)')
        self.assertEqual(texts_head.archive_where(two, [ROW_ON], carrier='HDD77'),
                         'Архивном диске А1 (H: «Бэкап фото и видео», 16 ТБ)')       # носитель сам не считается

    def test_nohash_line(self):
        kinds = 'Типы файлов: «фото», «видео», «документы рядом с ними» — согласно настройкам А1'
        h = texts_cell.nohash_html(NH, 1, 'H:', 70388, where=texts_head.archive_where(DIR1, [ROW_ON]), kinds=kinds)
        self.assertIn('✖ Из 70 388 файлов, которых нет на Архивном диске А1 (H: «Бэкап фото и видео», 16 ТБ), '
                      'у 37 945 нет хеша</b> (в 27 папках)', h)
        self.assertIn('Показать</a>', h)
        self.assertIn(kinds + '.', h)
        self.assertIn('Копирование будет возможно только после того, как у них будет просчитан хеш.', h)
        self.assertIn('только эти папки и только нужные типы файлов', h)
        self.assertNotIn('появится хеш', h)
        self.assertIn('Из 1 файла, которого нет на H:', texts_cell.nohash_html(dict(NH, n=1, folders=[]), 1, 'H:', 1))

    def test_contested_note(self):
        self.assertIn('непроверенные копии на архивных дисках.', common.CONTESTED_NOTE)
        self.assertNotIn('45 и 77', common.CONTESTED_NOTE)


class TextsPageTest(PageBase):
    """Тексты и вид на странице (п. 1-3, 6)."""

    def test_kinds_and_head(self):
        self.open()
        m = self.p.model
        self.assertEqual(texts_head.kinds_line(m.dirs['Н1']),
                         'Типы файлов: «фото», «видео», «документы рядом с ними» — согласно настройкам А1')
        self.assertEqual(texts_head.kinds_line(m.dirs['Н2']),
                         'Типы файлов: все, кроме программ и временных — согласно настройкам А2')
        self.p.set_dest('Н2')
        self.settle()
        t = self.p.missing.text()
        self.assertIn(f'Из содержимого {SRC} нет на HDD91 ', t)
        self.assertNotIn(f'На {SRC} нет на', t)
        self.assertNotIn('как в настройках', t)

    def test_legend(self):
        self.open()
        self.p.set_dest('Н2')
        self.settle()
        self.assertTrue(self.p.legend.isVisibleTo(self.p))
        (b1, l1), (b2, l2) = self.p.legend_rows
        self.assertEqual(l1.text(), 'зелёный — папка отмечена, из неё есть что копировать на HDD91')
        self.assertEqual(l2.text(), 'розовый — папка отмечена, но копировать из неё нечего: всё уже есть на HDD91 или '
                                    'нет файлов выбранных типов')
        self.assertEqual((b1.width(), b1.height(), b2.width(), b2.height()), (14, 14, 14, 14))
        self.assertIn(f'background:{common.SEL_BG}', b1.styleSheet())
        self.assertIn(f'background:{common.NONE_BG}', b2.styleSheet())
        self.p.set_dest('Н1')                                                   # два диска: «HDD45 и HDD77»
        self.settle()
        self.assertIn('копировать на HDD45 и HDD77', l1.text())
        self.p.mode_except.setChecked(True)                                      # там отмеченные - красным
        self.settle()
        self.assertFalse(self.p.legend.isVisibleTo(self.p))

    def test_one_check_at_carrier_row(self):
        self.open()
        self.p.set_dest('Н2')
        self.settle()
        root = self.p.items['']
        self.assertFalse(self.p.tree.rootIsDecorated())                         # стрелки у строки носителя нет
        checks = [c for c in range(self.p.tree.columnCount()) if root.data(c, Qt.CheckStateRole) is not None]
        self.assertEqual(checks, [rp.C_CHECK])                                   # одна галочка - «выбрать все»
        root.setExpanded(False)                                                  # свернуть носитель нельзя
        self.assertTrue(root.isExpanded())
        for b in (self.p.mode_only, self.p.mode_every, self.p.mode_except):     # подсказки переносятся, не обрезаются
            self.assertTrue(b.toolTip().startswith('<p>'), b.toolTip())
        self.assertIn('Весь носитель — на этот диск', self.p.mode_every.toolTip())


if __name__ == '__main__':
    unittest.main()
