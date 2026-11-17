"""«Диски и папки»: «Досчитать хеш» (18.11.2026) - кнопка над деревом, пункт правого щелчка по папке, кнопка «у выбранных»
в окне списка файлов без хеша; неактивно у неподключённого диска; метка «А1» в «Решении владельца».
Окно пересканирования подменено заглушкой: сканирование не запускается.

Запуск из корня проекта:  py -m unittest catalog.test_disks_rehash
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication, QWidget        # noqa: E402

import app                                                 # noqa: E402
import rescan_dialog                                       # noqa: E402
import service as sv                                       # noqa: E402
from hb_core import api as hb                              # noqa: E402
from tests.sv_patch import sv_patch_multiple                # noqa: E402
from ui.disks import common as dk                           # noqa: E402
import test_disks_page as tdp                              # noqa: E402 - носители, папки, фон без потоков

QAPP = QApplication.instance() or QApplication([])
MEDIA = [hb.CAT_PHOTO, hb.CAT_VIDEO]
NOHASH = dict(total=5, media=3, by_type=[2, 1, 1, 0, 1], zux=0, folders={'': 5, 'Фото': 3, 'Прочее': 2},
              media_folders=['Фото'], media_root=1)


def hash_info(d):
    return dict(text='опись от 01.01.2026', tip='', hash='⚠ Без хеша 3 фото и видео — копию нельзя проверить',
                alarm=True, nohash=NOHASH)


class QWin(QWidget):
    """Главное окно для окна списка (родитель - виджет): фон без потоков."""
    def __init__(self):
        super().__init__()
        self.bg, self.rescan = tdp.Bg(), None


class Made:
    """Заглушка RescanDialog: запоминает аргументы."""
    def __init__(self):
        self.calls = []

    def __call__(self, win, disk, folders, cats=None):
        self.calls.append((disk, list(folders), cats))
        return mock.Mock(running=False)


class TopFoldersTest(unittest.TestCase):
    def test_nested_and_root(self):
        """Папки - родители файлов; вложенная в уже взятую не повторяется; корень - отдельно числом."""
        paths = ['A\\1.jpg', 'A\\B\\2.jpg', 'A\\B\\C\\3.mp4', 'D\\E\\4.jpg', 'D\\F\\5.jpg', '6.jpg']
        self.assertEqual(hb.scan_folders(paths), (['A', 'D\\E', 'D\\F'], 1))


class DisksRehashTest(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(r) for r in tdp.ROWS]
        self.p = sv_patch_multiple(disks=lambda: [dict(r) for r in self.rows], folder_children=tdp.children,
                                   hash_dates=lambda d, p: dict(text='', hint=''), generation=lambda: 'g1',
                                   disk_hash_info=hash_info, nohash_info=lambda d: NOHASH,
                                   find_folders=lambda words: [])
        self.p.start()
        self.win = tdp.Win()
        self.page = app.DisksPage(self.win)
        self.page.refresh()
        self.made = Made()
        self.m = mock.patch.object(rescan_dialog, 'RescanDialog', self.made)
        self.m.start()

    def tearDown(self):
        self.m.stop()
        self.p.stop()

    def root(self):
        return self.page.tree.topLevelItem(0)

    def test_button_over_tree(self):
        b = self.page.rehash_btn
        self.assertFalse(b.isHidden())
        self.assertEqual(b.text(), 'Досчитать хеш фото и видео (3)…')
        self.assertTrue(b.isEnabled())
        self.assertIn('Файлы прямо в корне (1) не войдут', b.toolTip())
        b.click()
        self.assertEqual(self.made.calls, [('HDD09', ['Фото'], MEDIA)])

    def test_folder_menu(self):
        foto, other, empty = (self.root().child(i) for i in range(3))
        menu = self.page.rehash_menu(foto)
        act = menu.actions()[0]
        self.assertEqual(act.text(), 'Досчитать хеш в этой папке…')
        self.assertTrue(act.isEnabled())
        act.trigger()
        self.assertEqual(self.made.calls, [('HDD09', ['Фото'], MEDIA)])
        self.assertFalse(self.page.rehash_menu(empty).actions()[0].isEnabled())   # без хеша нет - неактивно
        self.page.rehash_menu(self.root()).actions()[0].trigger()                 # весь диск - папки фото и видео
        self.assertEqual(self.made.calls[-1], ('HDD09', ['Фото'], MEDIA))
        self.assertIsNone(self.page.rehash_menu(None))

    def test_not_connected(self):
        """Диск не подключён: кнопка и пункт меню неактивны, подсказка «Подключите диск»; окно не открывается."""
        for r in self.rows:
            r['letter'] = ''
        self.page.refresh()
        b = self.page.rehash_btn
        self.assertFalse(b.isEnabled())
        self.assertEqual(b.toolTip(), 'Подключите диск')
        act = self.page.rehash_menu(self.root().child(0)).actions()[0]
        self.assertFalse(act.isEnabled())
        self.assertEqual(act.toolTip(), 'Подключите диск')
        with mock.patch.object(app.QMessageBox, 'information', lambda *a: None):
            self.page.open_rehash('HDD09', ['Фото'])
        self.assertEqual(self.made.calls, [])

    def test_mark_shows_a_number(self):
        foto = self.root().child(0)
        self.assertEqual(foto.data(dk.T_DEC, dk.MARK_ROLE)['text'], 'А2 Работа')   # в данных - «Н2 Работа»
        self.assertIn('А2 Работа', foto.toolTip(dk.T_DEC))
        self.assertEqual(self.root().child(1).data(dk.T_DEC, dk.MARK_ROLE)['text'], 'не копировать')


class FileListRehashTest(unittest.TestCase):
    """Окно «Показать» (список без хеша): «Досчитать хеш у выбранных…» - папки выделенных без вложенных, типы
    выделенных файлов (начальные галочки окна)."""
    ROWS = [('HDD09', 'A\\1.jpg', 10, 0, None, hb.F_PHOTO, '', ''),
            ('HDD09', 'A\\B\\2.doc', 10, 0, None, hb.F_TEXT, '', ''),
            ('HDD09', 'C\\3.mp4', 10, 0, None, hb.F_VIDEO, '', ''),
            ('HDD09', 'D\\4.jpg', 10, 0, None, hb.F_PHOTO, '', '')]

    def setUp(self):
        self.win = QWin()

    def open(self, letter):
        from ui.filelist import page as fp
        data = dict(kind='nohash', disk='HDD09', folder='', scope='HDD09', why='нет хеша', notes=[], rows=self.ROWS)
        disks = [dict(disk='HDD09', label='', letter=letter)]
        with sv_patch_multiple(file_list=lambda **kw: dict(data), disks=lambda: disks):
            w = fp.FileListWindow(self.win, kind='nohash', disk='HDD09')
        return w

    def select(self, w, names):
        from PySide6.QtCore import QItemSelectionModel
        sm = w.view.selectionModel()
        for i in range(w.model.rowCount()):
            if w.model.row(i)[2] in names:
                sm.select(w.model.index(i, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        w.update_buttons()

    def test_selected(self):
        w = self.open('F:')
        self.assertFalse(w.rehash_btn.isHidden())
        self.assertFalse(w.rehash_btn.isEnabled())                                   # ничего не выделено
        self.select(w, {'1.jpg', '2.doc', '3.mp4'})
        self.assertTrue(w.rehash_btn.isEnabled())
        self.assertIn('Сканер работает по папкам', w.rehash_btn.toolTip())
        made = Made()
        with mock.patch.object(rescan_dialog, 'RescanDialog', made):
            w.rehash_selected()
        self.assertEqual(made.calls, [('HDD09', ['A', 'C'], [hb.CAT_PHOTO, hb.CAT_VIDEO, hb.CAT_DOC])])
        w.close()

    def test_not_connected_and_other_lists(self):
        w = self.open('')
        self.select(w, {'1.jpg'})
        self.assertFalse(w.rehash_btn.isEnabled())
        self.assertEqual(w.rehash_btn.toolTip(), 'Подключите диск')
        w.close()
        from ui.filelist import page as fp
        with sv_patch_multiple(file_list=lambda **kw: dict(kind='unique', disk='HDD09', folder='', scope='', why='',
                                                           notes=[], rows=[]), disks=lambda: []):
            w = fp.FileListWindow(self.win, kind='unique', disk='HDD09')
        self.assertTrue(w.rehash_btn.isHidden())                                     # только список «без хеша»
        w.close()


if __name__ == '__main__':
    unittest.main()
