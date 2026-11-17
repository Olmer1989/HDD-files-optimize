"""Экран «Обзор», правки владельца 17.11.2026: заголовок «Выберите Архивный диск…», без пояснения, голубая кнопка
«+ Добавить архивный диск…», номер «А1» вместо «Н1», плашки «📁 Файлы будут скопированы…» на каждый диск,
ёмкость диска в строке диска. Qt offscreen, временные данные (обвязка - из test_directions_page).

Запуск из папки catalog:  python -m unittest test_overview_screen1
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))      # запуск и из корня проекта (catalog.test_overview_screen1)
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import directions_look as dl  # noqa: E402
import directions_section as ds  # noqa: E402
import disk_ui  # noqa: E402
from test_directions_page import QAPP, DirBase, sv, wait     # noqa: F401 - обвязка (временная база, три направления)

BY = {'HDD45': dict(disk='HDD45', label='WD20 - 2 ТБ - Бэкап фото и видео', letter='H:', total_bytes=16_000_900_165_632),
      'HDD78': dict(disk='HDD78', label='WD40 - 4 ТБ - Путешествия', letter='', total_bytes=4_000_787_030_016),
      'HDD90': dict(disk='HDD90', label='Старый', letter='G:')}
CONNECTED = '📁 Файлы будут скопированы в папку H:\\ПЕРЕНОС с других дисков'
OFFLINE = '📁 Файлы будут скопированы на диск HDD78 в папку «ПЕРЕНОС с других дисков»'


class PureTest(unittest.TestCase):
    def test_show_num(self):
        for a, b in (('Н1', 'А1'), ('н2', 'А2'), ('H3', 'А3'), ('h4', 'А4'), ('Н12', 'А12'), ('Х', 'Х'), ('Н', 'Н'),
                     ('Нх', 'Нх'), (None, None), ('', '')):
            self.assertEqual(dl.show_num(a), b, a)

    def test_folder_text(self):
        self.assertEqual(ds.folder_text('HDD45', BY), CONNECTED)
        self.assertEqual(ds.folder_text('HDD78', BY), OFFLINE)
        self.assertEqual(ds.folder_text('HDD99', BY), OFFLINE.replace('HDD78', 'HDD99'))   # диска нет в базе
        self.assertEqual(ds.folder_text('HDD45', BY, 2), CONNECTED + ' (копия 2)')
        self.assertNotIn('На носителе', ds.folder_text('HDD45', BY) + ds.folder_text('HDD78', BY))

    def test_capacity_in_disk_row(self):
        on = dl.disk_row_html('HDD45', BY, {'HDD45': 421.4}, False)
        self.assertIn('H: Бэкап фото и видео — HDD45</span>', on)
        self.assertIn('· ёмкость диска 16 ТБ', on)
        self.assertLess(on.index('ёмкость диска'), on.index('свободно 421 ГБ'))       # ёмкость - перед «свободно»
        off = dl.disk_row_html('HDD78', BY, {}, False)
        self.assertIn('· ёмкость диска 4 ТБ', off)
        self.assertLess(off.index('ёмкость диска'), off.index('не подключён'))
        self.assertNotIn('ёмкость', dl.disk_row_html('HDD90', BY, {'HDD90': 1.0}, False))   # объёма нет - без ёмкости
        self.assertNotIn('ёмкость', dl.disk_row_html('HDD99', BY, {}, False))

    def test_tb_text_moved(self):
        from ui.razbor import texts_head
        self.assertIs(texts_head.tb_text, disk_ui.tb_text)
        self.assertEqual(disk_ui.tb_text(16_000_900_165_632), '16 ТБ')
        self.assertEqual(disk_ui.tb_text(None), '')


class ScreenTest(DirBase):
    def test_head_and_button(self):
        s = self.section()
        self.assertEqual(s.title.text(), 'Выберите Архивный диск для наполнения его файлами')
        self.assertFalse(hasattr(s, 'sub'))                                          # пояснения нет
        texts = ' '.join(w.text() for w in s.findChildren(ds.QLabel))
        self.assertNotIn('Отметьте галочкой', texts)
        self.assertNotIn('На носителе', texts)
        self.assertEqual(s.b_add.text(), '+ Добавить архивный диск…')
        self.assertIn('архивный диск', s.b_add.toolTip())
        self.assertIn('#e3f2fd', s.b_add.styleSheet())
        self.assertIn(':hover', s.b_add.styleSheet())
        self.assertGreaterEqual(s.b_add.minimumHeight(), ds.add_height())
        self.assertIn('А1 Семейный архив', s.cards['Н1'].name.text())               # в данных - «Н1», на экране «А1»
        self.assertNotIn('Н1', s.cards['Н1'].name.text())

    def test_folder_plates(self):
        s = self.section()                                                           # Работа - на одном диске HDD91
        s.data['by']['HDD45'] = dict(disk='HDD45', label='Бэкап', letter='H:')      # подключён
        s.data['by']['HDD91'] = dict(disk='HDD91', label='Работа', letter='H:')
        s.data['by'].pop('HDD77', None)                                              # не подключён
        s.paint_disks()
        one = s.cards['Н2'].folders
        self.assertEqual([x.text() for x in one], [CONNECTED])
        self.assertIn('внутри — папка с именем носителя', one[0].toolTip())
        two = [x.text() for x in s.cards['Н1'].folders]                              # два диска - две плашки
        self.assertEqual(len(two), 2)
        self.assertEqual(two[0], CONNECTED + ' (копия 1)')
        self.assertEqual(two[1], OFFLINE.replace('HDD78', 'HDD77') + ' (копия 2)')   # HDD77 не подключён
        self.assertEqual(s.cards['Н3'].folders, [])                                  # без диска - плашки нет

    def test_overview_note_shows_a_num(self):
        import app
        dirs = sv.directions()
        self.assertEqual(app.shown_disks(dirs, ['Н3'])[2], 'у А3 диск не назначен')


class ContentWindowTest(DirBase):
    """18.11.2026: таблица «Диски направлений: что на них лежит по базе» - не на «Обзоре», а в окне «Содержимое
    выбранного диска» (кнопка «Подробнее о содержимом диска…» в карточке с диском)."""

    def windows(self):
        from disk_content_dialog import DiskContentDialog
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, DiskContentDialog) and w.isVisible()]

    def tearDown(self):
        for w in self.windows():
            w.close()
        super().tearDown()

    def test_no_table_on_overview(self):
        import app
        ov = app.OverviewPage(self.win)
        ov.refresh()
        self.assertTrue(wait(lambda: ov.ov is not None and ov.dirs.data is not None), self.win.errors)
        texts = ' '.join(w.text() for w in ov.findChildren(ds.QLabel))
        self.assertNotIn('Диски направлений', texts)
        self.assertIn('Требует внимания', texts)
        self.assertFalse(hasattr(ov, 'dt'))

    def test_button_only_with_disk(self):
        s = self.section()
        for num in ('Н1', 'Н2'):
            self.assertEqual(s.cards[num].btn_more.text(), 'Подробнее о содержимом диска…')
        self.assertIsNone(s.cards['Н3'].btn_more)                                   # без диска - кнопки нет
        self.assertNotIn(ds.MORE_TEXT, [b.text() for b in s.cards['Н3'].findChildren(ds.QPushButton)])

    def test_click_opens_one_window_with_card_disks(self):
        s = self.section()
        s.data['by']['HDD91'] = dict(disk='HDD91', label='WD20 - 2 ТБ - Бэкап фото и видео', letter='H:')
        card = s.cards['Н2']
        was = card.box.isChecked()
        QTest.mouseClick(card.btn_more, Qt.LeftButton)
        self.assertEqual(card.box.isChecked(), was)                                  # галочку не трогает
        w = s.content['Н2']
        self.assertEqual(w.windowTitle(), 'Содержимое выбранного диска — H: Бэкап фото и видео — HDD91')
        self.assertFalse(w.isModal())
        self.assertTrue(wait(lambda: w.rows), self.win.errors)
        self.assertEqual([r['disk'] for r in w.rows], ['HDD91'])                     # только диск этой карточки
        self.assertIn('Числа — по базе', w.checked.text())
        self.assertIn('Хеш не', w.dt.text())
        QTest.mouseClick(card.btn_more, Qt.LeftButton)                               # второй щелчок - то же окно
        self.assertIs(s.content['Н2'], w)
        self.assertEqual(len(self.windows()), 1)
        s.cards['Н1'].btn_more.click()                                               # направление на двух дисках
        w1 = s.content['Н1']
        self.assertTrue(wait(lambda: w1.rows), self.win.errors)
        self.assertEqual([r['disk'] for r in w1.rows], ['HDD45', 'HDD77'])
        self.assertEqual(len(self.windows()), 2)

    def test_close_before_load(self):
        s = self.section()
        w = s.show_content('Н1')
        self.assertEqual(w.wait.text(), 'Считаю…')
        w.close()                                                                    # ответ фона ещё не пришёл
        QThreadPool.globalInstance().waitForDone(10000)
        for _ in range(5):
            QAPP.processEvents()
        self.assertEqual(self.win.errors, [])
        w2 = s.show_content('Н1')                                                    # закрытое - открывается заново
        self.assertIsNot(w2, w)
        self.assertTrue(wait(lambda: w2.rows), self.win.errors)


if __name__ == '__main__':
    unittest.main()
