"""Пересканирование выбранных папок: приём базой скана сканера 1.4.0, предпросмотр в service, окно (offscreen).
Временные папки; настоящие диски и данные не используются.

Запуск из корня проекта:  py -m unittest catalog.test_rescan_folders
"""
from argparse import Namespace
import contextlib
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
CAT = Path(__file__).resolve().parent
sys.path.insert(0, str(CAT))
sys.path.insert(0, str(CAT.parent / 'scanner'))
import hashbase as hb                                      # noqa: E402
import service as sv                                       # noqa: E402
import portable                                            # noqa: E402  (сканер)
import rescan                                              # noqa: E402
from test_hashbase import Base                             # noqa: E402
from test_rescan import SERIAL, make_full_job, rewrite_same, sha, scanner_patches   # noqa: E402


class RescanBaseTest(Base):
    """Скан выбранных папок сканером 1.4.0 база принимает без правок: степень S только в своих папках."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp / 'source'
        (self.root / 'Котуй' / 'д1').mkdir(parents=True)
        (self.root / 'Прочее').mkdir()
        for rel, data in {'Котуй\\a.jpg': b'a' * 300, 'Котуй\\b.jpg': b'b' * 200, 'Котуй\\д1\\c.mp4': b'c' * 500,
                          'Прочее\\x.jpg': b'x' * 100}.items():
            (self.root / rel).write_bytes(data)
        time.sleep(0.05)
        self.full, self.record = make_full_job(self.scans, 'HDD92', self.root)
        os.utime(self.full / 'inventory.sqlite', (time.time() - 3600, time.time() - 3600))
        time.sleep(0.05)
        rewrite_same(self.root / 'Котуй\\b.jpg', b'B' * 200)
        (self.root / 'Котуй\\д1\\c.mp4').unlink()
        (self.root / 'Котуй\\new.jpg').write_bytes(b'n' * 70)
        self.reads = []
        self.patches = scanner_patches(self.root, self.record, self.reads)
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        portable.JOB_LOG = None
        super().tearDown()

    def scan(self):
        args = Namespace(disk='HDD92', letter='Z', folder=['Котуй'], rehash_all=False, prior_root=None, yes=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(portable.start_partial(args, dict(self.record), (self.scans / hb.PARTIAL_DIR).resolve()), 0)
        return next((self.scans / hb.PARTIAL_DIR).glob('*/HDD92_*'))

    def test_partial_scan_is_accepted(self):
        before = dict(self.db().execute("select path, ev from files where disk='HDD92'").fetchall())
        self.assertEqual(before['Котуй\\д1\\c.mp4'], hb.EV_SCAN)
        job = self.scan()
        self.assertEqual(sorted(self.reads), ['Котуй\\b.jpg', 'Котуй\\new.jpg'])     # a.jpg - из прежней описи
        rows = {p: (s, ev) for p, s, ev in self.db().execute("select path, sha, ev from files where disk='HDD92'")}
        self.assertEqual(rows['Котуй\\a.jpg'], (sha(b'a' * 300), hb.EV_SCAN))
        self.assertEqual(rows['Котуй\\b.jpg'], (sha(b'B' * 200), hb.EV_SCAN))         # новое содержимое
        self.assertEqual(rows['Котуй\\new.jpg'], (sha(b'n' * 70), hb.EV_SCAN))
        self.assertNotIn('Котуй\\д1\\c.mp4', rows)                                     # исчез
        self.assertEqual(rows['Прочее\\x.jpg'], (sha(b'x' * 100), hb.EV_SCAN))         # вне папки - не тронуто
        origin = dict(self.db().execute("select path, origin from files where disk='HDD92'").fetchall())
        self.assertIn(job.name, origin['Котуй\\a.jpg'])
        self.assertNotIn(job.name, origin['Прочее\\x.jpg'])
        res = sv.partial_outcome(job.name)
        self.assertTrue(res['accepted'], res)
        self.assertIn('новые 1', res['lines'][0])
        self.assertIn('исчезли из базы 1', res['lines'][0])
        self.assertIn('хеш не совпал 1', res['lines'][0])                              # b.jpg: прежний хеш другой
        self.assertIn('стало S 0 (уже было S 1)', res['lines'][0])

    def test_preview_in_service(self):
        with mock.patch.object(sv, 'volumes', return_value={SERIAL: str(self.root)}), \
                mock.patch('inventory.volume', return_value=(SERIAL, '', 'NTFS')):
            self.db()
            p = sv.rescan_plan('HDD92', ['котуй'])
            self.assertEqual(p['folders'], ['Котуй'])
            self.assertEqual((p['files'], p['reuse'][0], p['read'][0], p['gone']), (3, 1, 2, 1))
            self.assertIn('Прочитать с диска: 2 файлов', '\n'.join(p['lines']))
            argv = sv.rescan_argv('HDD92', 'F:', p['folders'])
            self.assertEqual(argv[argv.index('--folder') + 1], 'Котуй')
            self.assertTrue(argv[argv.index('--output') + 1].endswith(hb.PARTIAL_DIR))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                import hb_cmd.rescan as cmd
                cmd.run(Namespace(disk='HDD92', folder=['Котуй'], rehash_all=False))
            self.assertIn('Взять хеш из прежней описи', out.getvalue())
        self.assertEqual(self.reads, [])
        with self.assertRaises(sv.Refused):                                            # не подключён
            with mock.patch.object(sv, 'volumes', return_value={}):
                sv.rescan_plan('HDD92', ['Котуй'])


class RescanWindowTest(Base):
    """Дымовой тест окна: кнопка, предпросмотр, подтверждение, ход, итог приёма. Сканер не запускается."""

    def test_dialog(self):
        from PySide6.QtCore import QThreadPool
        from PySide6.QtWidgets import QApplication, QMessageBox
        import app
        import rescan_dialog
        qapp = QApplication.instance() or QApplication([])

        def wait(cond, timeout=30):
            end = time.time() + timeout
            while time.time() < end:
                qapp.processEvents()
                QThreadPool.globalInstance().waitForDone(50)
                qapp.processEvents()
                if cond():
                    return True
            return False
        w = app.Window()
        try:
            self.assertTrue(wait(lambda: not w.updating))
            dp = w.page('Диски и папки')
            info = []
            with mock.patch.object(QMessageBox, 'information', side_effect=lambda *a: info.append(a[2])):
                dp.rescan()                                                            # ничего не выбрано
            self.assertIn('Выберите диск', info[-1])
            plan = dict(letter='F:', folders=['A'], read=[1, 2e9], reuse=[5, 3e9], errors=[],
                        lines=['HDD90: папок 1', 'Прочитать с диска: 1 файлов, 2,00 ГБ.'])
            proc = mock.Mock()
            proc.poll.return_value = 0
            proc.returncode = 0
            with mock.patch.object(sv, 'rescan_plan', return_value=plan), \
                    mock.patch.object(sv, 'rescan_start', return_value=proc) as start, \
                    mock.patch.object(sv, 'partial_outcome', return_value=dict(accepted=True, warn=[],
                                                                                lines=['A: стало S 5; новые 1'])), \
                    mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                dlg = rescan_dialog.RescanDialog(w, 'HDD90', ['A'])
                self.assertTrue(wait(lambda: dlg.go.isEnabled()))
                self.assertIn('Прочитать с диска', dlg.text.toPlainText())
                dlg.start()
                start.assert_called_once_with('HDD90', 'F:', ['A'], False, job=None)
                self.assertTrue(dlg.running and dlg.halt.isEnabled())
                dlg.stop()
                self.assertTrue(sv.rescan_files('HDD90')[1].exists())                  # файл остановки
                sv.rescan_files('HDD90')[0].write_text(json.dumps({'job': 'C:\\x\\HDD90_job', 'status': 'complete',
                                                                    'percent': 100}), encoding='utf-8')
                dlg.poll()
                self.assertFalse(dlg.running)
                self.assertTrue(wait(lambda: 'Принято базой' in dlg.text.toPlainText()))
                self.assertIn('стало S 5', dlg.text.toPlainText())
            dlg.close()
        finally:
            w.timer.stop()
            QThreadPool.globalInstance().waitForDone(10000)
            w.close()


if __name__ == '__main__':
    unittest.main()
