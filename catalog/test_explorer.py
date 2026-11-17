"""Тест страницы «Я сделал в Проводнике» (explorer_diff + explorer_page) на временных данных и временном «диске».

Запуск из корня проекта:  py -m unittest catalog.test_explorer
"""
import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import Qt                               # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox     # noqa: E402

import explorer_diff as ed                                 # noqa: E402
import explorer_page as ep                                 # noqa: E402
import hashbase as hb                                      # noqa: E402
import service as sv                                       # noqa: E402
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
from test_hashbase import Base                             # noqa: E402

QAPP = QApplication.instance() or QApplication([])
TODAY = time.strftime('%d.%m.%Y')


def put(root, rel, size):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'x' * size)
    os.utime(p, ns=(0, 0))               # дата как в описи теста (mtime_ns = 0)
    return p


class DiskBase(Base):
    """Временный «диск» HDD90: как в описи, затем изменения «в Проводнике»."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / 'диск'
        for rel, size in [('A\\1.jpg', 100), ('A\\2.jpg', 200), ('A\\sub\\3.mp4', 300), ('B\\4.jpg', 400),
                          ('B\\5.jpg', 500), ('A\\заметки.doc', 10)]:
            put(self.root, rel, size)
        self.db()                                             # база собрана
        # что владелец сделал в Проводнике:
        for x in ('B\\4.jpg', 'B\\5.jpg'):                   # удалил папку B
            (self.root / x).unlink()
        (self.root / 'B').rmdir()
        os.rename(self.root / 'A\\2.jpg', self.root / 'A\\2-новое.jpg')       # переименовал файл
        (self.root / 'C').mkdir()
        os.rename(self.root / 'A\\sub\\3.mp4', self.root / 'C\\3.mp4')        # перенёс содержимое A\sub в C
        (self.root / 'A\\sub').rmdir()
        put(self.root, 'N\\новый.txt', 5)                    # новая папка неизвестно откуда
        put(self.root, 'Z\\4.jpg', 400)                      # скопировал Z с HDD91
        put(self.root, 'A\\$RECYCLE.BIN\\x.jpg', 7)          # служебная папка: не проверяется

    def scan(self, folders=('A', 'B', 'N', 'Z'), **kw):
        hb.close_last()
        return ed.scan('HDD90', str(self.root), list(folders), **kw)

    def kinds(self, diff):
        return sorted((u['kind'], u.get('src_disk', ''), u.get('src', ''), u['path']) for u in diff.units)

    def rows(self):
        return [f[:6] for _, f in hb.manual_rows()]


class DiffTest(DiskBase):
    def test_finds_moves_deletions_copies(self):
        d = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        self.assertEqual(self.kinds(d), [
            ('copy', 'HDD91', 'Z', 'Z'),
            ('gone', '', '', 'B'),
            ('move', '', 'A\\2.jpg', 'A\\2-новое.jpg'),
            ('move', '', 'A\\sub', 'C'),
            ('new', '', '', 'N')])
        self.assertTrue(any('служебная' in why for _, why in d.bad))
        gone = next(u for u in d.units if u['kind'] == 'gone')
        self.assertEqual((gone['files'], gone['bytes'], len(gone['children'])), (2, 900, 2))

    def test_not_scanned_folder_is_not_gone(self):
        d = self.scan(folders=('A',))           # B не выбрана - её исчезновение не ищется
        self.assertFalse([u for u in d.units if u['path'].startswith('B')])

    def test_unreadable_place_gives_no_deletions(self):
        real = os.scandir

        def scandir(path):
            if str(path).endswith('\\A'):
                raise PermissionError(13, 'Отказано в доступе')
            return real(path)
        with mock.patch.object(ed.os, 'scandir', scandir):
            d = self.scan(folders=('A',))
        self.assertEqual([u for u in d.units if u['kind'] in ('gone', 'move')], [])
        self.assertTrue(any(p == 'A' for p, _ in d.bad))

    def test_stop_discards_result(self):
        stop = threading.Event()
        stop.set()
        with self.assertRaises(ed.Stopped):
            self.scan(stop=stop)

    def test_write_all_and_rescan_shows_only_unknown(self):
        d = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        rows = ed.selection_rows(d, {i: None for i, u in enumerate(d.units) if u['kind'] != 'new'})
        self.assertIn('удалено — 1 папка (2 файла', ed.summary(rows))
        res = ed.write(TODAY, rows, diff=d)
        self.assertEqual((len(res['written']), res['failed']), (4, None))
        self.assertIsNone(self.row('HDD90', 'B\\4.jpg'))
        self.assertEqual(self.row('HDD90', 'A\\2-новое.jpg')[1], 'S')     # внутри диска: подтверждение сохранилось
        self.assertEqual(self.row('HDD90', 'C\\3.mp4')[1], 'S')
        self.assertEqual(self.row('HDD90', 'Z\\4.jpg')[1], 'U')           # копия «со слов»
        d2 = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        self.assertEqual(self.kinds(d2), [('new', '', '', 'N')])

    def test_part_of_folder_gives_file_rows(self):
        d = self.scan()
        i = next(i for i, u in enumerate(d.units) if u['kind'] == 'gone' and u['path'] == 'B')
        rows = ed.selection_rows(d, {i: [0]})
        self.assertEqual([r[:5] for r in rows], [('удалено', 'HDD90', 'B\\4.jpg', '', '')])

    def test_precheck_refuses_everything(self):
        d = self.scan()
        rows = ed.selection_rows(d, {i: None for i, u in enumerate(d.units) if u['kind'] == 'gone'})
        before = self.rows()
        with self.assertRaises(sv.Refused):                       # дата раньше описи
            ed.write('01.01.2020', rows, diff=d)
        (self.root / 'B').mkdir()
        put(self.root, 'B\\4.jpg', 400)
        with self.assertRaises(sv.Refused):                       # на диске снова есть
            ed.write(TODAY, rows, diff=d)
        self.assertEqual(self.rows(), before)

    def test_destination_changed_after_check_is_refused(self):
        d = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        rows = ed.selection_rows(d, {i: None for i, u in enumerate(d.units) if u['kind'] == 'move'})
        put(self.root, 'C\\ещё.jpg', 3)                           # в папку назначения добавили файл
        with self.assertRaises(sv.Refused):
            ed.write(TODAY, rows, diff=d)

    def test_folder_with_unchecked_place_is_not_paired(self):
        put(self.root, 'C\\$RECYCLE.BIN\\y.jpg', 1)                # внутри C есть непроверенное место
        d = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        self.assertNotIn('move', [u['kind'] for u in d.units if u['path'] == 'C'])

    def test_same_size_other_date_is_reported(self):
        os.utime(self.root / 'A\\1.jpg', (10 ** 9, 10 ** 9))
        d = self.scan(folders=('A',))
        self.assertEqual([x[0] for x in d.touched], ['A\\1.jpg'])

    def test_stale_base_is_refused(self):
        d = self.scan()
        rows = ed.selection_rows(d, {i: None for i, u in enumerate(d.units) if u['kind'] == 'gone'})
        d.generation = 'другая'
        with self.assertRaises(sv.Refused):
            ed.write(TODAY, rows, diff=d)

    def test_failure_midway_is_reported_and_retry_skips_written(self):
        d = self.scan(folders=('A', 'B', 'C', 'N', 'Z'))
        rows = ed.selection_rows(d, {i: None for i, u in enumerate(d.units) if u['kind'] in ('gone', 'move')})
        before = hb.MANUAL.read_bytes()

        def add(*a, **kw):
            raise OSError('диск переполнен')
        res = ed.write(TODAY, rows, diff=d, add=add)                  # пакет: всё или ничего
        self.assertEqual((len(res['written']), len(res['remaining'])), (0, len(rows) - 1))
        self.assertIn('ОСТАНОВЛЕНО', ed.result_text(res))
        self.assertEqual(hb.MANUAL.read_bytes(), before)
        res2 = ed.write(TODAY, rows)
        self.assertEqual((len(res2['skipped']), len(res2['written'])), (0, len(rows)))
        res3 = ed.write(TODAY, rows)                                  # повтор: всё уже записано
        self.assertEqual((len(res3['skipped']), len(res3['written'])), (len(rows), 0))

    def test_offline_rows(self):
        self.assertEqual(ed.offline_rows('HDD90', 'удалено', ['A', 'A\\sub', 'B']),
                         [('удалено', 'HDD90', 'A', '', ''), ('удалено', 'HDD90', 'B', '', '')])
        self.assertEqual(ed.offline_rows('HDD90', 'перемещено', ['A\\sub'], 'HDD91', 'Архив\\'),
                         [('перемещено', 'HDD90', 'A\\sub', 'HDD91', 'Архив\\sub')])
        with self.assertRaises(sv.Refused):
            ed.offline_rows('HDD90', 'скопировано', ['A'])


class RecordsTest(DiskBase):
    def test_recorded_and_fix(self):
        sv.add_manual(TODAY, 'удалено', 'HDD90', 'B\\4.jpg')
        sv.add_manual(TODAY, 'удалено', 'HDD90', 'B\\5.jpg')
        rec = ed.recorded('HDD90')
        self.assertEqual([r['line'] for r in rec], [3, 2])                 # новые сверху
        self.assertIn('удалено HDD90\\B\\5.jpg', rec[0]['text'])
        old = rec[0]['fields']
        new = ed.fix_check([TODAY, 'удалено', 'HDD90', 'B', '', '', ''], ['HDD90', 'HDD91'])
        with self.assertRaises(sv.Refused):
            ed.fix(3, old, new, '  ')                                       # нужна причина
        with self.assertRaises(sv.Refused):
            ed.fix(3, ['другое'] + old[1:], new, 'ошибся')                  # строку изменили
        ed.fix(3, old, new, 'надо было всю папку')
        f = dict(hb.manual_rows())[3]
        self.assertEqual(f[3], 'B')
        self.assertIn('надо было всю папку', f[6])
        with self.assertRaises(sv.Refused):
            ed.fix_check([TODAY, 'перемещено', 'HDD90', 'B', '', '', ''], ['HDD90'])   # нет «куда»


# ---------- страница ----------

class SyncBg:
    def __init__(self, win):
        self.win = win

    def run(self, fn, *args, ok=None, quiet=False):
        res = fn(*args)
        if ok:
            ok(res)


class FakeWin:
    def __init__(self):
        self.errors = []
        self.bg = SyncBg(self)

    def show_error(self, text):
        self.errors.append(text)


class PageTest(DiskBase):
    def setUp(self):
        super().setUp()
        real = sv.disks
        self.patches = [
            sv_patch('disks', lambda: [dict(r, letter='T:' if r['disk'] == 'HDD90' else '') for r in real()]),
            mock.patch.object(ed, 'disk_root', lambda disk: (str(self.root), None)),
            mock.patch.object(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes),
            mock.patch.object(QMessageBox, 'information', lambda *a, **k: None),
            mock.patch.object(QMessageBox, 'warning', lambda *a, **k: None)]
        for p in self.patches:
            p.start()
        hb.close_last()
        self.win = FakeWin()
        self.page = ep.ExplorerPage(self.win)
        self.page.refresh()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.page.close()
        super().tearDown()

    def group(self, kind):
        t = self.page.changes.tree
        return next(t.topLevelItem(i) for i in range(t.topLevelItemCount())
                    if t.topLevelItem(i).data(0, ep.ROLE) == ('group', kind))

    def test_check_tick_write(self):
        ch = self.page.changes
        self.assertEqual(ch.disk.currentData(), 'HDD90')              # подключённый - первым
        self.assertEqual(ch.mode.currentIndex(), 0)
        names = [ch.folders.item(i).data(ep.ROLE) for i in range(ch.folders.count())]
        self.assertIn('C', names)                                     # новая папка на диске есть в выборе
        ch.start_scan()
        self.assertEqual(self.win.errors, [])
        self.assertIsNotNone(ch.diff)
        self.group('gone').setCheckState(0, Qt.Checked)
        ch.update_summary()
        self.assertIn('удалено — 1 папка', ch.summary.text())
        self.assertFalse(self.group('new').flags() & Qt.ItemIsUserCheckable)   # неизвестное не записывается
        mv = self.group('move')                                        # выделить мышью и нажать пробел
        for i in range(mv.childCount()):
            mv.child(i).setSelected(True)
        ch._toggle_tree()
        ch.update_summary()
        self.assertIn('перемещено внутри диска — 1 папка и 1 файл', ch.summary.text())
        ch.write()
        self.assertEqual(sorted(r[1] for r in self.rows()), ['перемещено', 'перемещено', 'удалено'])
        self.assertIsNone(ch.diff)

    def test_filter_hides_old(self):
        ch = self.page.changes
        ch.start_scan()
        ch.only_after.setChecked(True)                                # все даты - 1970 год: всё скрыто
        self.group('gone').setCheckState(0, Qt.Checked)
        self.assertEqual(ch.rows(), [])
        self.assertIn('скрыто', ch.only_after.text())

    def test_offline_disk(self):
        ch = self.page.changes
        ch.disk.setCurrentIndex(ch.disk.findData('HDD45'))
        self.assertEqual(ch.mode.currentIndex(), 1)
        it = ch.otree.topLevelItem(0)
        self.assertEqual(it.data(0, ep.ROLE), 'X')
        it.setCheckState(0, Qt.Checked)
        ch.update_summary()
        self.assertIn('удалено — 1 папка (2 файла', ch.summary.text())
        ch.write()
        self.assertEqual(self.rows()[-1], [TODAY, 'удалено', 'HDD45', 'X', '', ''])

    def test_records_tab_and_fix_dialog(self):
        sv.add_manual(TODAY, 'удалено', 'HDD90', 'B\\4.jpg')
        rt = self.page.records
        self.page.tabs.setCurrentIndex(1)
        self.assertEqual(rt.table.rowCount(), 1)
        rt.table.selectRow(0)
        row = rt.selected()
        dlg = ep.FixDialog(rt, row, rt.disks)
        dlg.check()
        self.assertIn('почему', dlg.msg.text().lower())
        dlg.p1.setText('B')
        dlg.reason.setText('вся папка')
        dlg.check()
        self.assertEqual(dlg.result(), 1)
        rt.start_fix(row, dlg.result_fields, dlg.reason.text())
        self.assertEqual(dict(hb.manual_rows())[2][3], 'B')
        self.assertIn('Исправлено', rt.status.text())


if __name__ == '__main__':
    unittest.main()
