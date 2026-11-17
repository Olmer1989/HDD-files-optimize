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
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
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

    def scan(self, **types):
        args = Namespace(disk='HDD92', letter='Z', folder=['Котуй'], rehash_all=False, prior_root=None, yes=True, **types)
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
        self.assertTrue(res['lines'][0].startswith('Прочитано заново: '), res['lines'][0])  # итог сканера для владельца
        self.assertIn('Хеш взят из прежнего скана', res['lines'][0])
        self.assertIn('новые 1', res['lines'][1])
        self.assertIn('исчезли из базы 1', res['lines'][1])
        self.assertIn('хеш не совпал 1', res['lines'][1])                              # b.jpg: прежний хеш другой
        self.assertIn('стало S 0 (уже было S 1)', res['lines'][1])

    def test_selected_types_scan_is_accepted(self):
        """Сканер 1.6.0, хеш только у фото: база принимает скан как раньше. Документ с годным прежним хешем остаётся S,
        новый документ - без хеша (N), предупреждения «не прочитано» нет."""
        import hash_types
        (self.root / 'Котуй\\новый.docx').write_bytes(b'w' * 20)
        argv = hash_types.scanner_args([hb.CAT_PHOTO])
        v = dict(zip(argv[::2], argv[1::2]))
        job = self.scan(hash_ext=v['--hash-ext'], hash_skip_names=v['--hash-skip-names'],
                        hash_skip_path_re=v['--hash-skip-path-re'])
        self.assertEqual(sorted(self.reads), ['Котуй\\b.jpg', 'Котуй\\new.jpg'])
        rows = {p: (s, ev) for p, s, ev in self.db().execute("select path, sha, ev from files where disk='HDD92'")}
        self.assertEqual(rows['Котуй\\новый.docx'], (None, hb.EV_NONE))
        self.assertEqual(rows['Котуй\\a.jpg'], (sha(b'a' * 300), hb.EV_SCAN))
        res = sv.partial_outcome(job.name)
        self.assertTrue(res['accepted'], res)
        self.assertFalse([w for w in res['warn'] if 'не прочитано' in w], res['warn'])

    def test_preview_in_service(self):
        with sv_patch('volumes', return_value={SERIAL: str(self.root)}), \
                mock.patch('inventory.volume', return_value=(SERIAL, '', 'NTFS')):
            self.db()
            p = sv.rescan_plan('HDD92', ['котуй'])
            self.assertEqual(p['folders'], ['Котуй'])
            self.assertEqual((p['files'], p['reuse'][0], p['read'][0], p['gone']), (3, 1, 2, 1))
            self.assertIn('Прочитать с диска: 2 файлов', '\n'.join(p['lines']))
            argv = sv.rescan_argv('HDD92', 'F:', p['folders'])
            self.assertEqual(argv[argv.index('--folder') + 1], 'Котуй')
            self.assertTrue(argv[argv.index('--output') + 1].endswith(hb.PARTIAL_DIR))
            self.assertIn('--hash-all-types', argv)                                     # хеш у всех файлов - явно
            self.assertNotIn('--hash-ext', argv)
            self.assertEqual(sv.rescan_argv('HDD92', 'F:', p['folders'], cats=list(hb.COPY_CATS)), argv)  # все = прежнее
            only = sv.rescan_argv('HDD92', 'F:', p['folders'], cats=[hb.CAT_PHOTO, hb.CAT_VIDEO])
            self.assertIn('--hash-ext', only)
            self.assertNotIn('--hash-all-types', only)
            self.assertIn('--hash-skip-ext', sv.rescan_argv('HDD92', 'F:', p['folders'], cats=[hb.CAT_OTHER]))
            self.assertEqual(sv.rescan_argv('HDD92', 'F:', p['folders'], job='J', cats=[hb.CAT_PHOTO])[-2:],
                             ['resume', 'J'])                                         # продолжение - правило задания
            self.assertEqual(len(p['items']), 3)                                       # для оценки по типам в окне
            conf = sv.rescan_confirmed('HDD92', p['folders'])
            self.assertEqual(conf.get('Котуй\\a.jpg'), hb.EV_SCAN)
            self.assertIn('не фото и не видео', '\n'.join(p['lines']))                  # сколько ГБ - документы и пр.
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                import hb_cmd.rescan as cmd
                cmd.run(Namespace(disk='HDD92', folder=['Котуй'], rehash_all=False))
            self.assertIn('Взять хеш из прежней описи', out.getvalue())
        self.assertEqual(self.reads, [])
        with self.assertRaises(sv.Refused):                                            # не подключён
            with sv_patch('volumes', return_value={}):
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
            self.assertIn('Отметьте папки', info[-1])
            plan = dict(letter='F:', folders=['A'], read=[1, 2e9], reuse=[5, 3e9], errors=[],
                        lines=['HDD90: папок 1', 'Прочитать с диска: 1 файлов, 2,00 ГБ.'])
            proc = mock.Mock()
            proc.poll.return_value = 0
            proc.returncode = 0
            with sv_patch('rescan_plan', return_value=plan), \
                    sv_patch('rescan_start', return_value=proc) as start, \
                    sv_patch('partial_outcome', return_value=dict(accepted=True, warn=[],
                                                                                lines=['A: стало S 5; новые 1'])), \
                    mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
                dlg = rescan_dialog.RescanDialog(w, 'HDD90', ['A'])
                self.assertTrue(wait(lambda: dlg.go.isEnabled()))
                self.assertIn('Прочитать с диска', dlg.text.toPlainText())
                dlg.start()
                start.assert_called_once_with('HDD90', 'F:', ['A'], False, job=None, cats=None)
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
            # Галочки типов: оценка под галочками по предпросмотру, «Все типы», пустой выбор, передача выбора сканеру
            items = [('A\\a.jpg', 3 * 10 ** 9, '.jpg', False), ('A\\b.docx', 10 ** 9, '.docx', False),
                     ('A\\c.docx', 10 ** 9, '.docx', True), ('A\\d.zip', 2 * 10 ** 9, '.zip', False)]
            plan = dict(plan, items=items, rehash_all=False)
            proc.poll.return_value = None
            with sv_patch('rescan_plan', return_value=plan), \
                    sv_patch('rescan_confirmed', return_value={'A\\d.zip': 'C'}), \
                    sv_patch('rescan_start', return_value=proc) as start, \
                    mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as ask:
                dlg = rescan_dialog.RescanDialog(w, 'HDD90', ['A'])
                self.assertTrue(wait(lambda: dlg.go.isEnabled()))
                self.assertTrue(dlg.all_types.isChecked())
                self.assertIn('Будет прочитано примерно 3 файлов, 6,0 ГБ.', dlg.types_line.text())
                self.assertEqual([b.text() for b in dlg.type_box.values()][2], 'Документы (Word, Excel, PDF, тексты)')
                dlg.all_types.setChecked(False)
                self.assertFalse(dlg.go.isEnabled())
                self.assertIn('хотя бы один тип', dlg.types_line.text())
                dlg.type_box[hb.CAT_PHOTO].setChecked(True)
                dlg.type_box[hb.CAT_DOC].setChecked(True)
                self.assertTrue(dlg.go.isEnabled() and not dlg.all_types.isChecked())
                t = dlg.types_line.text()
                self.assertIn('Будет прочитано примерно 2 файлов, 4,0 ГБ.', t)
                self.assertIn('Без хеша останется 1 файлов (2,0 ГБ)', t)
                self.assertIn('У 1 из них в базе сейчас подтверждённый хеш', t)
                dlg.start()
                self.assertEqual(start.call_args.kwargs['cats'], [hb.CAT_PHOTO, hb.CAT_DOC])
                self.assertIn('Хеш считать у: фото, документы', ask.call_args[0][2])
                self.assertFalse(dlg.type_box[hb.CAT_VIDEO].isEnabled())               # после запуска не меняются
                dlg.running = False
            dlg.close()
        finally:
            w.timer.stop()
            QThreadPool.globalInstance().waitForDone(10000)
            w.close()


class TypesDialogTest(unittest.TestCase):
    """Окно без главного окна (фоновая работа - сразу): предупреждение о потере подтверждений, продолжение задания."""

    class Bg:
        def run(self, fn, *a, ok=None):
            r = fn(*a)
            if ok:
                ok(r)

    ITEMS = [('A\\a.jpg', 10 ** 9, '.jpg', False), ('A\\b.docx', 10 ** 9, '.docx', False),
             ('A\\c.zip', 10 ** 9, '.zip', False), ('A\\d.zip', 10 ** 9, '.zip', False)]

    def dialog(self, confirmed):
        from PySide6.QtWidgets import QApplication, QWidget
        import rescan_dialog
        self.qapp = QApplication.instance() or QApplication([])
        win = QWidget()
        win.bg = self.Bg()
        plan = dict(letter='F:', folders=['A'], read=[4, 4e9], reuse=[0, 0], errors=[], lines=['x'], items=self.ITEMS,
                    rehash_all=False)
        conf = sv_patch('rescan_confirmed', side_effect=OSError('нет базы')) if confirmed is None else \
            sv_patch('rescan_confirmed', return_value=confirmed)
        with sv_patch('rescan_plan', return_value=plan), conf:
            d = rescan_dialog.RescanDialog(win, 'HDD90', ['A'])
        self.addCleanup(d.close)
        self.keep = win
        return d

    def test_lost_count_follows_types(self):
        d = self.dialog({'A\\b.docx': 'C', 'A\\c.zip': 'S', 'A\\d.zip': 'C'})
        d.all_types.setChecked(False)
        d.type_box[hb.CAT_PHOTO].setChecked(True)
        self.assertIn('У 3 из них', d.types_line.text())                     # docx и два zip без хеша
        d.type_box[hb.CAT_ARCH].setChecked(True)
        self.assertIn('У 1 из них', d.types_line.text())                     # остался только docx
        d.type_box[hb.CAT_DOC].setChecked(True)
        self.assertNotIn('пропадёт', d.types_line.text())
        d.type_box[hb.CAT_DOC].setChecked(False)
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as ask:
            d.start()
        self.assertIn('У 1 файлов невыбранных типов подтверждение', ask.call_args[0][2])

    def test_unknown_confirmations_are_asked(self):
        from PySide6.QtWidgets import QMessageBox
        d = self.dialog(None)
        self.assertIsNone(d.plan['confirmed'])
        with mock.patch.object(QMessageBox, 'question', return_value=QMessageBox.No) as ask, \
                sv_patch('rescan_start') as start:
            d.start()                                                          # все типы - вопроса о потере нет
            self.assertNotIn('не удалось проверить', ask.call_args[0][2])
            d.all_types.setChecked(False)
            d.type_box[hb.CAT_PHOTO].setChecked(True)
            self.assertIn('проверить не удалось', d.types_line.text())
            d.start()
            self.assertIn('не удалось проверить, сколько подтверждённых хешей пропадёт', ask.call_args[0][2])
        start.assert_not_called()                                              # ответ «Нет» - не запускается

    def test_resume_keeps_job_rule(self):
        """Продолжение задания: окно передаёт только «resume <задание>», правило типов - из job.json."""
        files = (Path('ход.json'), Path('стоп.txt'), Path('вывод.txt'))         # настоящую «_БАЗА» не трогаем
        with sv_patch('rescan_files', return_value=files):
            a = sv.rescan_argv('HDD90', 'F:', ['A'], job='C:\\x\\HDD90_job', cats=None)
            b = sv.rescan_argv('HDD90', 'F:', ['A'], job='C:\\x\\HDD90_job', cats=[hb.CAT_PHOTO])
        self.assertEqual(a, b)
        self.assertEqual(a[-2:], ['resume', 'C:\\x\\HDD90_job'])
        self.assertFalse({'--hash-ext', '--hash-skip-ext', '--hash-all-types'} & set(a))


class TypesRuleTest(unittest.TestCase):
    """Одно правило: решение сканера по ключам окна == тип copy_kind среди выбранных, для всех неполных выборов."""

    def test_scanner_matches_copy_kind(self):
        import itertools
        import hash_types
        from hb_core.consts import CAT_OF_TYPE, JUNK_NAMES, NEVER_COPY_EXT
        from hb_core.derived import copy_kind
        from hb_core.util import name_key
        paths = ['Папка\\f' + e for e in hash_types.known_ext()]
        paths += ['П\\F' + e.upper() for e in hash_types.known_ext()[::3]]
        paths += ['П\\x.qqq', 'П\\без расширения', 'П\\a.jpg.exe', 'П\\a.exe.jpg', 'П\\.hidden', 'П\\~$отчёт.docx',
                  'П\\Proxy Media\\clip.mp4', 'П\\x.lrdata\\a.jpg', 'П\\Render Cache\\b.mov', 'П\\a.tar.gz']
        paths += ['П\\' + n for n in JUNK_NAMES] + ['П\\' + n.upper() for n in JUNK_NAMES]
        cats = list(hb.COPY_CATS)
        checked = 0
        for k in range(1, len(cats)):
            for sel in itertools.combinations(cats, k):
                rule = hash_types.scanner_rule(sel)
                for p in paths:
                    for size in (1, 5 * 10 ** 6, 0):
                        if size == 0 and rescan.ext_of(p) in NEVER_COPY_EXT:
                            continue        # пустая программа: базе хеш пустого файла не нужен (описано в hash_types)
                        want = CAT_OF_TYPE.get(copy_kind(p, name_key(p), size)) in sel
                        self.assertEqual(rescan.wants_hash(p, rule, size), want, (sel, p, size))
                        checked += 1
        self.assertGreater(checked, 50000)
        self.assertIsNone(hash_types.scanner_rule(cats))                     # все типы - без правила, как раньше
        self.assertEqual(hash_types.scanner_args(cats), [])

    def test_window_rule_equals_scanner_parse(self):
        """Ключи окна, разобранные самим сканером (portable.hash_types_of), дают то же правило, что в оценке окна."""
        import hash_types
        for sel in ([hb.CAT_PHOTO], [hb.CAT_OTHER, hb.CAT_MUSIC], [hb.CAT_DOC, hb.CAT_ARCH, hb.CAT_PROJ]):
            a = hash_types.scanner_args(sel)
            v = dict(zip(a[::2], a[1::2]))
            ns = Namespace(hash_ext=v.get('--hash-ext'), hash_skip_ext=v.get('--hash-skip-ext'),
                           hash_skip_names=v['--hash-skip-names'], hash_skip_path_re=v['--hash-skip-path-re'])
            self.assertEqual(rescan.hash_rule({'hash_types': portable.hash_types_of(ns)}), hash_types.scanner_rule(sel))
        with self.assertRaises(ValueError):
            hash_types.scanner_args([])


if __name__ == '__main__':
    unittest.main()
