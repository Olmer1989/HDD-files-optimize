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

    def test_step1(self):
        """Шаг 1 «Перед копированием» (макет 18.11.2026): красный - есть файлы без хеша; зелёный - у всех есть."""
        h = texts_cell.step1_html(NH, 1, 'HDD09', 70388)
        self.assertIn('<b>✖</b></span> <b>1. Посчитать хеш на HDD09 — <span style="color:#c62828">обязательно</span>', h)
        self.assertIn('У 37 945 из 70 388 файлов для копирования нет хеша. Без него копию нельзя проверить. ', h)
        self.assertIn('<a href="nh-list:" style="color:#1565c0">Какие файлы</a>', h)
        self.assertIn('У 1 из 1 файла для копирования', texts_cell.step1_html(dict(NH, n=1), 1, 'HDD09', 1))
        self.assertIn('✓ 1. Хеш есть у всех файлов для копирования', texts_cell.step1_html(dict(NH, n=0), 1, 'X', 5))
        self.assertIn('✓ 1. Хеш есть у всех', texts_cell.step1_html(None, 0, 'X', 5))       # быстрый признак: нет
        self.assertIn('идёт проверка', texts_cell.step1_html(None, 3, 'X', 5))
        self.assertIn('не посчитано (проба)', texts_cell.step1_html({'error': 'проба'}, 3, 'X', 5))

    def test_step2(self):
        k = dict(k=39, folders=['a'], root=0, cats=[], sample=['H:\\a\\1.jpg'])
        h = texts_cell.step2_html(2, 'HDD45', 'H:', k)
        self.assertIn('2. Посчитать хеш у файлов на H: с тем же именем и размером — '
                      '<span style="color:#757575">по желанию</span>', h)
        self.assertIn('На H: лежат 39 файлов с теми же именами и размерами, что у файлов для копирования, но без хеша. '
                      'Если посчитать их хеш, часть файлов может оказаться «уже есть» и не скопируется второй раз.', h)
        self.assertIn('href="nh-clist:HDD45"', h)
        h1 = texts_cell.step2_html(2, 'HDD45', 'H:', dict(k, k=1, sample=[]))
        self.assertIn('На H: лежит 1 файл', h1)
        self.assertNotIn('Какие файлы', h1)                                       # списка нет - без ссылки
        self.assertEqual(texts_cell.kinds_note('А1'),
                         'Настройка А1 — общая для всех носителей; уже созданные задания не меняются.')
        self.assertEqual(texts_cell.SKIP_TEXT, 'Не копируются (другой тип)')

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
