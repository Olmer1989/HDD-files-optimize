"""«Копирование»: «Отменить задание…» (service.jobs_cancel, ui/tasks/flow_cancel; утверждено владельцем 18.11.2026).

Запуск из корня проекта:  py -m unittest catalog.tests.test_cancel_task
Временные папки; настоящие задания и диски не используются. Ничего не удаляется - проверяется и это.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication                  # noqa: E402

import build_pilot as bp                                    # noqa: E402
import hashbase as hb                                       # noqa: E402
import service as sv                                        # noqa: E402
from hb_core import paths                                   # noqa: E402
from service import jobs_cancel as jc                       # noqa: E402
from tests.sv_patch import sv_patch                         # noqa: E402
from ui.tasks import model_load                             # noqa: E402
from ui.tasks.page import TasksPage                         # noqa: E402
from ui.tasks.view_table import TableView                   # noqa: E402
from test_hashbase import LOG_HEAD                          # noqa: E402
from test_tasks_move import FakeWin                         # noqa: E402

QAPP = QApplication.instance() or QApplication([])
OK = 'скопирован, размер и SHA-256 совпали'


def files(root):
    """Все файлы под папкой: относительный путь -> байты."""
    return {str(p.relative_to(root)): p.read_bytes() for p in Path(root).rglob('*') if p.is_file()}


class CancelBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='cancel_task_'))
        self.out = self.tmp / 'Каталог дисков'
        self.out.mkdir()
        self.saved = bp.OUT_DIR
        bp.OUT_DIR = self.out
        hb.set_root(self.out)
        self.root = hb.TASKS
        self.root.mkdir()
        self.canc = self.root / sv.CANCEL_DIR

    def tearDown(self):
        bp.OUT_DIR = self.saved
        hb.set_root(bp.OUT_DIR)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, name, n=4, done=0, move=False):
        """Задание копирования (или перемещения) с n строками и журналом на done строк (0 - не запускалось)."""
        t = self.root / name
        t.mkdir()
        (t / 'тома.tsv').write_text('HDD58\tS58\nHDD78\tS78\n', encoding='utf-8')
        (t / ('перемещение.tsv' if move else 'список.tsv')).write_text(
            ''.join(f'HDD78\tP\\{i}.mp4\t100\tф\t\n' for i in range(n)), encoding='utf-8')
        (t / 'Запустить.cmd').write_text('rem', encoding='utf-8')
        if done:
            rows = [('10:00:00', 'HDD78', OK, '100', 'h', f'D:\\P\\{i}.mp4', f'L:\\P\\{i}.mp4') for i in range(done)]
            (t / 'Журнал копирования 2026-11-18 10-00-00.tsv').write_text(
                '\t'.join(LOG_HEAD) + '\n' + ''.join('\t'.join(x) + '\n' for x in rows), encoding='utf-8-sig')
        return t

    def cancel(self, *names, running=(), queue=None):
        return jc.cancel_tasks(list(names), self.root, running=list(running), queue=queue)


class CancelServiceTest(CancelBase):
    def test_moves_folder_and_writes_line(self):
        t = self.make('1 - HDD58 на L', done=2)
        before = files(t)
        res = self.cancel(t.name)
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0]['ok'], res)
        self.assertFalse(t.exists())
        dest = self.canc / t.name
        self.assertEqual(Path(res[0]['dest']), dest)
        self.assertEqual(files(dest), before)                          # ничего не удалено и не изменено
        lines = (self.canc / sv.CANCEL_LOG).read_text(encoding='utf-8').splitlines()
        self.assertEqual(lines[0].split('\t'), list(jc.CANCEL_HEAD))
        f = lines[1].split('\t')
        self.assertEqual(f[1:], [t.name, str(dest), 'прервано', '2 из 4'])
        self.make('2 - ещё')
        self.cancel('2 - ещё')
        lines = (self.canc / sv.CANCEL_LOG).read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines), 3)                                # заголовок - один раз
        self.assertEqual(lines[2].split('\t')[3], 'не запускалось')

    def test_name_taken_gets_number(self):
        self.canc.mkdir()
        for name in ('А', 'А (2)'):
            (self.canc / name).mkdir()
            (self.canc / name / 'старое.txt').write_text(name, encoding='utf-8')
        self.make('А')
        res = self.cancel('А')
        self.assertEqual(Path(res[0]['dest']), self.canc / 'А (3)')
        self.assertEqual((self.canc / 'А' / 'старое.txt').read_text(encoding='utf-8'), 'А')     # старое цело
        self.assertEqual((self.canc / 'А (2)' / 'старое.txt').read_text(encoding='utf-8'), 'А (2)')

    def test_name_taken_between_check_and_rename(self):
        self.make('Б')
        real, calls = os.rename, []

        def rename(src, dst):
            calls.append(Path(dst).name)
            if len(calls) == 1:
                raise FileExistsError(dst)
            return real(src, dst)
        with mock.patch.object(jc.os, 'rename', side_effect=rename):
            res = self.cancel('Б')
        self.assertEqual(calls, ['Б', 'Б (2)'])
        self.assertEqual(Path(res[0]['dest']), self.canc / 'Б (2)')

    def test_running_not_moved(self):
        t = self.make('Идёт', done=1)
        res = self.cancel(t.name, running=[f'powershell -File "{t}\\Копировать.ps1"'])
        self.assertFalse(res[0]['ok'])
        self.assertIn('идёт', res[0]['reason'])
        self.assertTrue(t.exists())
        self.assertFalse(self.canc.exists())

    def test_unknown_running_not_moved(self):
        t = self.make('Неизвестно')
        res = jc.cancel_tasks([t.name], self.root, running=None)
        self.assertFalse(res[0]['ok'])
        self.assertTrue(t.exists())

    def test_in_working_queue_not_moved(self):
        a, b = self.make('Первое'), self.make('Второе')
        queue = hb.BASE_DIR / jc.QUEUE_FILE
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_bytes(f'@echo off\r\ncall "{a / "Запустить.cmd"}"\r\ncall "{b / "Запустить.cmd"}"\r\n'.encode('utf-8'))
        working = [f'C:\\Windows\\system32\\cmd.exe /c ""{queue}" "']
        res = self.cancel(b.name, running=working)
        self.assertFalse(res[0]['ok'])
        self.assertIn('очереди', res[0]['reason'])
        self.assertTrue(b.exists())
        res = self.cancel(b.name, running=[])                          # очередь не работает - можно
        self.assertTrue(res[0]['ok'], res)

    def test_permission_error_not_moved(self):
        t = self.make('Занято')
        with mock.patch.object(jc.os, 'rename', side_effect=PermissionError(13, 'Отказано в доступе')):
            res = self.cancel(t.name)
        self.assertFalse(res[0]['ok'])
        self.assertIn('папка занята', res[0]['reason'])
        self.assertIn('Отказано в доступе', res[0]['reason'])
        self.assertTrue(t.exists())
        self.assertFalse((self.canc / sv.CANCEL_LOG).exists())

    def test_log_error_is_warning_move_kept(self):
        t = self.make('Без строки')
        (self.canc / sv.CANCEL_LOG).mkdir(parents=True)               # записать строку нельзя
        res = self.cancel(t.name)
        self.assertTrue(res[0]['ok'])
        self.assertIn('не записана', res[0]['warn'])
        self.assertTrue((self.canc / t.name).exists())

    def test_only_copy_tasks_in_allowed_states(self):
        mv = self.make('Перемещение', move=True)
        done = self.make('Готово', done=4)
        res = self.cancel(mv.name, done.name, 'нет такого')
        self.assertEqual([x['ok'] for x in res], [False, False, False])
        self.assertIn('перемещение', res[0]['reason'])
        self.assertIn('готово', res[1]['reason'])
        self.assertTrue(mv.exists() and done.exists())
        self.assertEqual(sv.can_cancel(dict(kind='копирование', state='готово с ошибками')), '')

    def test_underscore_folders_are_not_tasks(self):
        self.make('Обычное')
        self.cancel(self.make('Отменяемое').name)
        fake = self.root / '_Служебная'
        fake.mkdir()
        (fake / 'список.tsv').write_text('HDD78\tP\\1.mp4\t1\tф\t\n', encoding='utf-8')
        with sv_patch('running_scripts', return_value=[]):
            self.assertEqual([r['task'] for r in sv.tasks(self.root)], ['Обычное'])

    def test_journal_paths_see_cancelled(self):
        t = self.make('С журналом', done=2)
        self.cancel(t.name)
        logs = [Path(p) for p in paths.journal_paths()]
        self.assertIn(self.canc / t.name / 'Журнал копирования 2026-11-18 10-00-00.tsv', logs)

    def test_nothing_deleted(self):
        for i in range(3):
            self.make(f'З{i}', done=i)
        before = sorted(files(self.root).values())
        self.cancel('З0', 'З1', 'З2')
        after = files(self.root)
        self.assertEqual(sorted(v for k, v in after.items() if not k.endswith(sv.CANCEL_LOG)), before)


class CancelPageTest(CancelBase):
    def rows(self):
        with sv_patch('running_scripts', return_value=[]), sv_patch('volumes', return_value={}), \
                mock.patch.object(model_load, 'serial_names', return_value={'S58': 'HDD58', 'S78': 'HDD78'}):
            return model_load.load(self.root)

    def test_button_confirm_and_result(self):
        self.make('Ждёт')
        self.make('Перенос', move=True)
        page = TasksPage(FakeWin())
        page.refresh = lambda: page.render(self.rows())
        page.render(self.rows())
        self.assertFalse(page.cancel_btn.isEnabled())                 # ничего не выбрано
        names = [r['task'] for r in page.trows]
        page.t.selectRow(names.index('Перенос'))
        self.assertFalse(page.cancel_btn.isEnabled())
        self.assertIn('перемещение не отменяется', page.cancel_btn.toolTip())
        page.t.selectRow(names.index('Ждёт'))
        self.assertTrue(page.cancel_btn.isEnabled())
        lab = page.t.cellWidget(names.index('Ждёт'), 1)
        self.assertIn('#e3f2fd', lab.text())                          # серый второй ряд в выделенной строке - светлый
        self.assertNotIn('#e3f2fd', page.t.cellWidget(names.index('Перенос'), 1).text())
        asked, said = [], []
        page.say = said.append
        page.confirm = lambda text, yes, no: asked.append((text, yes, no)) or False
        page.cancel_task()
        self.assertTrue((self.root / 'Ждёт').exists())                # «Не отменять» - ничего не произошло
        text, yes, no = asked[0]
        self.assertEqual((yes, no), ('Отменить задание', 'Не отменять'))
        self.assertIn('Будет отменено:', text)
        self.assertIn('«Запускаемые скрипты\\_Отменённые»', text)
        page.confirm = lambda *a: True
        real = jc.cancel_tasks
        with sv_patch('cancel_tasks', side_effect=lambda names: real(names, self.root, running=[])):
            page.cancel_task()
        self.assertTrue((self.canc / 'Ждёт').exists())
        self.assertIn('Отменено заданий: 1', said[-1])
        self.assertEqual([r['task'] for r in page.rows], ['Перенос'])  # список обновлён

    def test_what_html_plain(self):
        self.assertNotIn('#ffffff', TableView._what_html('a', 'b', False))
        self.assertIn('#ffffff', TableView._what_html('a', 'b', True))


if __name__ == '__main__':
    unittest.main()
