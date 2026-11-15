"""Раздел «Диски и папки» без экрана (Qt offscreen): порядок носителей, состояние описи по-русски, автовыбор.

Запуск из корня проекта:  py -m unittest catalog.test_disks_page
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt                              # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import app                                                 # noqa: E402
import commands_page as cpg                                # noqa: E402
import disk_ui                                             # noqa: E402

QAPP = QApplication.instance() or QApplication([])


def row(disk, letter='', status='complete', label=''):
    return dict(disk=disk, label=label, letter=letter, files=10, gib=1.0, status=status, scanned='01.01.2026', partial=0)


ROWS = [row('Flash01'), row('Flash02', 'G:'), row('HDD09', 'F:', label='WDS200T1X0E - 2 ТБ - Работа - SN850'),
        row('HDD01', status='running'), row('HDD18', 'K:', status='complete_with_inventory_errors'), row('HDD100')]


class Bg:
    """Фон без потоков: функция выполняется сразу."""
    def __init__(self):
        self.calls = []

    def run(self, fn, *args, ok=None, quiet=False):
        self.calls.append((fn, args))
        res = fn(*args)
        if ok:
            ok(res)


class Win:
    def __init__(self):
        self.bg = Bg()


class DiskUiTest(unittest.TestCase):
    def test_order(self):
        self.assertEqual([r['disk'] for r in disk_ui.ordered(ROWS)],
                         ['HDD09', 'HDD18', 'Flash02', 'HDD01', 'HDD100', 'Flash01'])

    def test_status(self):
        self.assertEqual(disk_ui.status_text('complete'), 'полная')
        self.assertEqual(disk_ui.status_text('complete_with_inventory_errors'), 'полная, есть нечитаемые места')
        self.assertEqual(disk_ui.status_text('running'), 'не закончена')
        self.assertEqual(disk_ui.status_text(''), '—')
        self.assertNotIn('_', disk_ui.status_text('something_new'))

    def test_commands_page_uses_same_functions(self):
        self.assertIs(cpg.split_disks, disk_ui.split_disks)
        self.assertIs(cpg.disk_text, disk_ui.disk_text)
        self.assertIs(cpg.style_item, disk_ui.style_item)


class DisksPageTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.multiple(app.sv, disks=lambda: [dict(r) for r in ROWS],
                                     folder_children=lambda disk, path: [
                                         dict(name='Фото', path='Фото', files=5, gib=0.5, types=[0.5, 0, 0, 0, 0],
                                              decision='')] if path == '' else [],
                                     hash_dates=lambda d, p: dict(text='', hint=''))
        self.p.start()
        self.page = app.DisksPage(Win())
        self.page.refresh()

    def tearDown(self):
        self.p.stop()

    def col(self, j):
        return [self.page.t.item(i, j).text() for i in range(self.page.t.rowCount())]

    def test_order_and_marks(self):
        self.assertEqual(self.col(0), ['● HDD09', '● HDD18', '● Flash02', 'HDD01', 'HDD100', 'Flash01'])
        self.assertEqual(self.col(2)[:3], ['F:', 'K:', 'G:'])
        self.assertEqual(self.page.t.item(3, 2).text(), '—')
        self.assertTrue(self.page.t.item(0, 0).font().bold())
        self.assertFalse(self.page.t.item(3, 0).font().bold())
        self.assertEqual(self.page.t.horizontalHeaderItem(1).text(), 'Название')
        self.assertEqual(self.page.t.item(0, 1).text(), 'Работа - SN850 (2 ТБ)')
        self.assertIn('WDS200T1X0E', self.page.t.item(0, 1).toolTip())

    def test_status_in_russian(self):
        st = dict(zip([x.lstrip('● ') for x in self.col(0)], self.col(6)))
        self.assertEqual(st['HDD09'], 'полная')
        self.assertEqual(st['HDD18'], 'полная, есть нечитаемые места')
        self.assertEqual(st['HDD01'], 'не закончена')
        self.assertIn('running', self.page.t.item(3, 6).toolTip())

    def test_first_connected_selected_with_folders(self):
        self.assertEqual(self.page.disk, 'HDD09')
        self.assertEqual(self.page.t.currentRow(), 0)
        root = self.page.tree.topLevelItem(0)
        self.assertEqual(root.text(0), 'HDD09 (весь диск)')
        self.assertEqual([root.child(i).text(0) for i in range(root.childCount())], ['Фото'])

    def test_refresh_keeps_choice(self):
        self.page.t.setCurrentCell(4, 0)                 # HDD100
        self.assertEqual(self.page.disk, 'HDD100')
        self.page.refresh()
        self.assertEqual(self.page.disk, 'HDD100')
        self.assertEqual(self.page.t.item(self.page.t.currentRow(), 0).text(), 'HDD100')

    def test_nothing_connected(self):
        with mock.patch.object(app.sv, 'disks', lambda: [row('HDD01'), row('Flash01')]):
            p = app.DisksPage(Win())
            p.refresh()
        self.assertIsNone(p.disk)
        self.assertEqual(p.tree.topLevelItemCount(), 0)


if __name__ == '__main__':
    unittest.main()
