"""Окно «Посчитать хеш — HDD18» (кнопка «Посчитать хеш (N)» на «Выбор источников», 18.11.2026, макет владельца).

Запуск из корня проекта:  py -m unittest catalog.tests.razbor.test_hash_dialog
Без главного окна: фоновая работа - сразу; service подменяется (sv_patch). Сканер не запускается, настоящие диски,
база и «_БАЗА» не используются.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QWidget   # noqa: E402

import service as sv                                       # noqa: E402
from hb_core.consts import CAT_DOC                         # noqa: E402
from tests.sv_patch import sv_patch                        # noqa: E402 - подмена имён service во всех подмодулях
from ui.razbor import dialog_hash                          # noqa: E402

JOB = 'C:\\x\\HDD18_job'
ITEMS = [('A\\a.doc', 10 ** 9, '.doc', False), ('A\\b.doc', 10 ** 9, '.doc', False),
         ('A\\c.jpg', 2 * 10 ** 9, '.jpg', True)]
NH = dict(n=1, folders=['A'], cats=[CAT_DOC], sample=['A\\a.doc'], root=0)


class Bg:
    def run(self, fn, *a, ok=None):
        r = fn(*a)
        if ok:
            ok(r)


class HashDialogTest(unittest.TestCase):
    def setUp(self):
        self.qapp = QApplication.instance() or QApplication([])
        self.win = QWidget()
        self.win.bg = Bg()
        self.win.apply_new = lambda then=None: then and then('update')
        self.shown = []
        tmp = Path(tempfile.mkdtemp())
        self.files = (tmp / 'ход.json', tmp / 'стоп.txt', tmp / 'вывод.txt')
        self.progress = {}
        self.proc = mock.Mock()
        self.proc.poll.return_value = None
        for p in (sv_patch('rescan_files', return_value=self.files),
                  sv_patch('read_progress', side_effect=lambda d: dict(self.progress)),
                  sv_patch('rescan_confirmed', return_value={})):
            p.start()
            self.addCleanup(p.stop)
        self.start = sv_patch('rescan_start', return_value=self.proc)
        self.started = self.start.start()
        self.addCleanup(self.start.stop)

    def dialog(self, items=ITEMS, nh=NH, plan_error=None, check=None):
        plan = dict(letter='F:', folders=['A'], read=[3, 4e9], reuse=[0, 0], errors=[], lines=['HDD18: папок 1'],
                    items=items, rehash_all=False)
        kw = dict(side_effect=sv.Refused(plan_error)) if plan_error else dict(return_value=plan)
        with sv_patch('rescan_plan', **kw):
            d = dialog_hash.HashDialog(self.win, 'HDD18', nh, 'H:', check or (lambda: ('HDD18', 'А1', [])),
                                       lambda x: 'список: ' + ', '.join(x['sample']),
                                       lambda t, b: self.shown.append((t, b)))
        self.addCleanup(lambda: (setattr(d, 'running', False), setattr(d, 'stage', 'done'), d.close()))
        return d

    def text(self, d):
        return d.head.text() + d.body.text()

    def run_to_end(self, d, status, code):
        self.progress.update(job=JOB, new_files=2, percent=100 if code == 0 else 40, status=status)
        self.proc.poll.return_value = code
        self.proc.returncode = code
        d.poll()

    def test_intro_text_and_start_without_question(self):
        d = self.dialog()
        t = self.text(d)
        self.assertEqual(d.windowTitle(), 'Посчитать хеш — HDD18')
        self.assertIn('Посчитать хеш у 1 файла на HDD18 (F:)', t)
        self.assertIn('Документы из отмеченных папок, которые пойдут на H:. Без хеша их нельзя скопировать.', t)
        self.assertIn('Программа прочитает 2 файла (2,0 ГБ): сканер читает папку целиком, поэтому хеш заодно появится '
                      'ещё у 1 файла.', t)
        self.assertIn('Время будет видно после начала', t)
        self.assertFalse(d.findChildren(QCheckBox))                             # галочек типов и «Перечитать всё» нет
        self.assertTrue(d.go.isEnabled() and d.go.text() == 'Посчитать' and d.close_btn.text() == 'Отмена')
        d.link('more')
        self.assertIn('HDD18: папок 1', self.shown[-1][1])
        with mock.patch.object(QMessageBox, 'question', side_effect=AssertionError('второго вопроса нет')):
            d.go.click()
        self.started.assert_called_once_with('HDD18', 'F:', ['A'], False, job=None, cats=[CAT_DOC])
        self.assertTrue(d.running and d.go.isHidden() and not d.halt.isHidden())
        self.progress.update(new_files=1, percent=50, eta_seconds=600)
        d.poll()
        self.assertIn('Прочитано 1 из 2 файлов', d.body.text())
        self.assertIn('Осталось ~10 мин.', d.body.text())
        with mock.patch.object(QMessageBox, 'information') as info:
            d.close()                                                           # во время работы не закрывается
        info.assert_called_once()
        self.assertTrue(d.running)

    def test_no_extra_line_when_read_equals_n(self):
        d = self.dialog(items=ITEMS[:1])
        self.assertIn('Программа прочитает 1 файл (1,0 ГБ).', d.body.text())
        self.assertNotIn('заодно', d.body.text())

    def test_preview_error_blocks_start(self):
        d = self.dialog(plan_error='Диск HDD18 не подключён')
        self.assertIn('Диск HDD18 не подключён', d.body.text())
        self.assertFalse(d.go.isEnabled())

    def test_done_all_hashed(self):
        d = self.dialog()
        d.start()
        with sv_patch('partial_outcome', return_value=dict(accepted=True, lines=[], warn=[])), \
                sv_patch('nohash_check', return_value=dict(n=0, sample=[], folders=[])) as chk:
            self.run_to_end(d, 'complete', 0)
        chk.assert_called_once_with('HDD18', 'А1', [])
        self.assertIn('✓ Хеш есть у всех файлов, которые пойдут на H:.', d.body.text())
        self.assertIn('нажмите «Начать копирование…»', d.body.text())
        self.assertFalse(d.running)
        self.assertTrue(d.go.isHidden() and d.close_btn.text() == 'Закрыть')

    def test_done_some_left(self):
        d = self.dialog()
        d.start()
        with sv_patch('partial_outcome', return_value=dict(accepted=True, lines=[], warn=[])), \
                sv_patch('nohash_check', return_value=dict(n=3, sample=['A\\x.doc'], folders=['A'])):
            self.run_to_end(d, 'complete', 0)
        self.assertIn('Без хеша осталось 3 нужных файла', d.body.text())
        self.assertIn('Копирование пока невозможно', d.body.text())
        d.link('nh-list')
        self.assertEqual(self.shown[-1][1], 'список: A\\x.doc')

    def test_not_accepted(self):
        d = self.dialog()
        d.start()
        with sv_patch('partial_outcome', return_value=dict(accepted=False, lines=['A: хеш не совпал'], warn=[])), \
                sv_patch('nohash_check') as chk:
            self.run_to_end(d, 'complete', 0)
        self.assertIn('База скан не приняла', d.body.text())
        self.assertIn('A: хеш не совпал', d.body.text())
        chk.assert_not_called()

    def test_stop_and_resume(self):
        d = self.dialog()
        d.start()
        d.stop()
        self.assertEqual(self.files[1].read_text(encoding='utf-8'), 'stop')
        self.run_to_end(d, 'interrupted', 1)
        t = d.body.text()
        self.assertIn('Остановлено', t)
        self.assertIn('Прочитано 2 из 2. Копирование станет возможно', t)
        self.assertTrue(not d.go.isHidden() and d.go.text() == 'Продолжить' and d.go.isEnabled())
        self.proc.poll.return_value = None
        d.go.click()
        self.assertEqual(self.started.call_args.kwargs, dict(job=JOB, cats=[CAT_DOC]))
        self.assertTrue(d.running)

    def test_failed_not_stopped(self):
        d = self.dialog()
        d.start()
        self.run_to_end(d, 'error', 2)
        self.assertIn('Не закончено: error', d.body.text())
        self.assertEqual(d.go.text(), 'Продолжить')

    def test_check_uses_state_at_opening(self):
        """Итог - для носителя, направления и отметок на момент открытия окна; предупреждения базы - серым."""
        page = dict(dest='А1', rows=[('A', 'copy')])
        d = self.dialog(check=lambda: ('HDD18', page['dest'], page['rows']))
        page['dest'] = 'А2'
        page['rows'].append(('B', 'copy'))                                       # страница поменялась, пока шёл скан
        d.start()
        with sv_patch('partial_outcome', return_value=dict(accepted=True, lines=[], warn=['1 файл не прочитан'])), \
                sv_patch('nohash_check', return_value=dict(n=0, sample=[], folders=[])) as chk:
            self.run_to_end(d, 'complete', 0)
        chk.assert_called_once_with('HDD18', 'А1', [('A', 'copy')])
        self.assertIn('✓ Хеш есть у всех', d.body.text())
        self.assertIn('1 файл не прочитан', d.body.text())

    def test_no_second_window(self):
        """«Посчитать хеш (N)» при открытом окне: окно поднимается, второе не открывается; идёт скан - сообщение."""
        from types import SimpleNamespace
        from ui.razbor import flow_nohash
        for running in (False, True):
            old = mock.Mock(running=running)
            old.isVisible.return_value = True
            page = SimpleNamespace(nohash_result=lambda: NH, writing=False, win=SimpleNamespace(rescan=old))
            with mock.patch.object(dialog_hash, 'HashDialog') as made, \
                    mock.patch.object(QMessageBox, 'information') as info:
                flow_nohash.NohashFlow.scan_nohash(page)
            made.assert_not_called()
            old.raise_.assert_called_once()
            old.activateWindow.assert_called_once()
            self.assertEqual(info.called, running)
            self.assertIs(page.win.rescan, old)

    def test_cannot_close_while_applying_and_checking(self):
        d = self.dialog()
        later = []
        self.win.bg = SimpleBg(later)
        d.start()
        with sv_patch('partial_outcome', return_value=dict(accepted=True, lines=[], warn=[])), \
                sv_patch('nohash_check', return_value=dict(n=0, sample=[], folders=[])):
            self.run_to_end(d, 'complete', 0)
            for stage in ('apply', 'check'):
                self.assertEqual(d.stage, stage)
                self.assertFalse(d.close_btn.isEnabled())
                with mock.patch.object(QMessageBox, 'information') as info:
                    d.reject()                                                  # Esc
                    d.close()                                                   # крестик
                self.assertEqual(info.call_count, 2)
                self.assertIn('подождите', info.call_args.args[2])
                fn, a, ok = later.pop(0)
                ok(fn(*a))
        self.assertEqual(d.stage, 'done')
        self.assertTrue(d.close_btn.isEnabled())
        with mock.patch.object(QMessageBox, 'information') as info:
            d.reject()
        info.assert_not_called()

    def test_stop_write_error_shown(self):
        self.files[1].mkdir()                                                   # файл остановки не записать
        d = self.dialog()
        d.start()
        d.stop()
        self.assertIn('Не удалось остановить:', d.body.text())
        self.assertTrue(d.halt.isEnabled())
        self.assertFalse(d.stopping)

    def test_apply_error_not_accepted_and_closable(self):
        def boom(then=None):
            raise RuntimeError('база занята')
        self.win.apply_new = boom
        d = self.dialog()
        d.start()
        with sv_patch('nohash_check') as chk:
            self.run_to_end(d, 'complete', 0)
        self.assertIn('База скан не приняла', d.body.text())
        self.assertIn('база занята', d.body.text())
        self.assertEqual(d.stage, 'done')
        self.assertTrue(d.close_btn.isEnabled())
        chk.assert_not_called()


class SimpleBg:
    """Фоновая работа - по шагам (тест сам выполняет отложенное)."""
    def __init__(self, later):
        self.later = later

    def run(self, fn, *a, ok=None):
        self.later.append((fn, a, ok))


if __name__ == '__main__':
    unittest.main()
