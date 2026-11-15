"""Дымовой тест окна «Архив дисков» без экрана (Qt offscreen) на временных данных.

Запуск из корня проекта:  py -m unittest catalog\\test_app.py
"""
import os
import sqlite3
import sys
import time
import unittest
from unittest import mock
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QThreadPool, Qt                 # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import app                                                 # noqa: E402
import commands_page as cpg                                # noqa: E402
import hashbase as hb                                      # noqa: E402
from test_hashbase import Base                             # noqa: E402

QAPP = QApplication.instance() or QApplication([])


def wait(cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        QAPP.processEvents()
        QThreadPool.globalInstance().waitForDone(50)
        QAPP.processEvents()
        if cond():
            return True
    return False


class WindowTest(Base):
    def setUp(self):
        super().setUp()
        t = hb.TASKS / 'Задание 1'
        t.mkdir(parents=True)
        (t / 'список.tsv').write_text('HDD77\tA\\2.jpg\t200\tф\t\n', encoding='utf-8')
        (t / 'Запустить.cmd').write_text('rem', encoding='utf-8')
        self.errors = []
        self.w = app.Window()
        self.w.show_error = self.errors.append
        self.assertTrue(wait(lambda: not self.w.updating), 'первая сборка базы в фоне не закончилась')

    def tearDown(self):
        self.w.timer.stop()
        QThreadPool.globalInstance().waitForDone(10000)
        self.w.close()
        super().tearDown()

    def test_pages(self):
        ov = self.w.pages[0][1]
        ov.refresh()
        self.assertTrue(wait(lambda: 'База собрана' in ov.text.toPlainText()))
        self.assertIn('HDD45', ov.text.toPlainText())
        self.assertIn('Задание 1', ov.text.toPlainText())                      # ждёт запуска
        self.w.nav.setCurrentRow(1)
        tasks = self.w.pages[1][1]
        self.assertTrue(wait(lambda: tasks.t.rowCount() == 1))
        self.assertEqual(tasks.t.item(0, 2).text(), 'не запускалось')
        self.w.nav.setCurrentRow(2)
        dp = self.w.pages[2][1]
        self.assertTrue(wait(lambda: dp.t.rowCount() == 4))
        row = [dp.t.item(i, 0).text() for i in range(4)].index('HDD90')
        dp.t.selectRow(row)
        root = dp.tree.topLevelItem(0)
        self.assertTrue(wait(lambda: root.childCount() == 2))                   # A и B, лениво
        names = sorted(root.child(i).text(0) for i in range(2))
        self.assertEqual(names, ['A', 'B'])
        a = next(root.child(i) for i in range(2) if root.child(i).text(0) == 'A')
        a.setExpanded(True)
        self.assertTrue(wait(lambda: a.childCount() == 1 and a.child(0).text(0) == 'sub'))
        dp.tree.setCurrentItem(a)
        dp.presence()
        self.assertTrue(wait(lambda: 'Нет на 45' in dp.info.text()))
        dp.search.setText('sub')
        dp.find()
        self.assertTrue(wait(lambda: dp.tree.topLevelItemCount() == 1 and 'A\\sub' in dp.tree.topLevelItem(0).text(0)))
        self.assertEqual(self.errors, [])

    def test_new_journal_is_applied_by_timer(self):
        self.w.check_sources()
        self.assertTrue(wait(lambda: self.w.sig is not None))
        self.task('T', [('HDD90', 'AAAA0090'), ('HDD77', 'AAAA0077')], 'Журнал копирования 2099-01-01 00-00-00.tsv',
                  ('время', 'цель', 'результат', 'размер', 'SHA-256 прочитанного', 'источник', 'куда'),
                  [('1', 'HDD77', 'скопирован, размер и SHA-256 совпали', '200', '0' * 63 + '2', 'K:\\A\\2.jpg', 'S:\\П\\2.jpg')])
        self.w.check_sources()
        # строку читаем только на чтение: connect() сам применил бы журнал, и окну было бы нечего применять
        def applied():
            if self.w.updating or not hb.DB.exists():
                return False
            c = sqlite3.connect(f'file:{hb.DB.as_posix()}?mode=ro', uri=True)
            try:
                return c.execute('select 1 from files where disk=? and path=?', ('HDD77', 'П\\2.jpg')).fetchone() is not None
            finally:
                c.close()
        self.assertTrue(wait(applied))
        self.assertIn('Применены новые модули', self.w.statusBar().currentMessage())


HIDDEN = {'recovery-plan', 'recovery-staging', 'family-plan', 'family-check'}


def put(f, **values):
    """Заполнить поля формы, как это сделал бы владелец."""
    for k, v in values.items():
        fld = f.fields[k]
        if fld.kind in ('disk', 'choice') or k in cpg.SUGGEST:
            fld.combo.setCurrentText(v)
        elif fld.kind == 'int':
            fld.widget.setValue(v)
        elif fld.kind == 'check':
            fld.check.setChecked(v)
        elif fld.kind in ('folders', 'lines'):
            fld.edit.setPlainText(v)
        else:
            fld.line.setText(v)


class CommandsTest(WindowTest):
    """Раздел «Команды»: формы из argparse, запуск hashbase.py отдельным процессом на временных данных."""

    def setUp(self):
        super().setUp()
        self.cp = self.w.page('Команды')
        self.asked = []

        def ask(*a, **k):
            self.asked.append(a[2])
            return cpg.QMessageBox.Yes
        self.patches = [mock.patch.object(cpg.QMessageBox, 'question', ask),
                        mock.patch.object(cpg.QMessageBox, 'information', lambda *a, **k: self.asked.append(a[2]))]
        for x in self.patches:
            x.start()
        self.w.open_page('Команды')
        self.assertTrue(wait(lambda: self.cp.disks))

    def tearDown(self):
        for x in self.patches:
            x.stop()
        if self.cp.run:
            self.cp.run.stop()
            wait(lambda: self.cp.run is None)
        super().tearDown()

    test_pages = test_new_journal_is_applied_by_timer = None      # уже проверены в WindowTest

    def run_cmd(self, name, timeout=90, write=False):
        (self.cp.write if write else self.cp.execute)()
        self.assertIsNotNone(self.cp.run, f'{name}: не запустилась; {self.asked}')
        self.assertTrue(wait(lambda: self.cp.run is None, timeout), f'{name}: не закончилась')
        return '\n'.join(self.cp.lines)

    def test_forms_for_all_visible_commands(self):
        names = [n for n, _, _ in self.cp.cmds]
        self.assertFalse(HIDDEN & set(names))
        self.assertEqual(self.cp.list.count(), len(names))
        for n in names:
            f = self.cp.select(n)
            self.assertFalse(f.unsupported, n)
            self.assertNotIn('yes', f.fields, n)
            args, err = f.argv()
            self.assertTrue(args or err, n)
        f = self.cp.select('manual')
        self.assertEqual(f.fields['date'].text(), time.strftime('%d.%m.%Y'))
        self.assertEqual(f.fields['action'].kind, 'choice')
        self.assertEqual(self.cp.select('mklist').fields['to'].text(), ['HDD45', 'HDD77'])
        combo = self.cp.select('where').fields['disk'].combo
        self.assertIn('HDD90', [combo.itemText(i) for i in range(combo.count())])
        dlg = cpg.FolderDialog(self.w, 'HDD90')                             # «Выбрать…»: дерево папок по базе
        root = dlg.tree.topLevelItem(0)
        self.assertTrue(wait(lambda: root.childCount() == 2))
        a = next(root.child(i) for i in range(2) if root.child(i).text(0) == 'A')
        dlg.tree.setCurrentItem(a)
        dlg.accept()
        self.assertEqual(dlg.chosen, 'A')

    def test_required_fields_and_argv(self):
        self.cp.select('decide')
        self.cp.execute()
        self.assertIsNone(self.cp.run)
        self.assertIn('Заполните', self.asked[-1])
        f = self.cp.select('mklist')
        put(f, disk='HDD90', name='Моё задание', folder='A\nB\\x', dry=True)
        f.fields['to'].boxes['HDD77'].setCheckState(Qt.Unchecked)
        args, err = f.argv()
        self.assertIsNone(err)
        self.assertEqual(args, ['mklist', 'HDD90', '--to', 'HDD45', '--name=Моё задание', '--folder=A', '--folder=B\\x',
                                '--dry'])
        f = self.cp.select('manual')                                        # пустой disk2 перед заполненным path2
        put(f, disk='HDD90', path='A', path2='B', action='удалено')
        args, err = f.argv()
        self.assertIn('Второй диск', err)
        f = self.cp.select('folders')                                       # значение по умолчанию не передаётся
        put(f, disk='HDD90', depth=1)
        self.assertEqual(f.argv()[0], ['folders', 'HDD90'])

    def test_read_command_in_subprocess(self):
        f = self.cp.select('folders')
        put(f, disk='HDD90', depth=2)
        text = self.run_cmd('folders')
        self.assertIn('Готово', self.cp.state.text(), text)
        self.assertIn('sub', text)                                          # A\sub - на глубине 2
        saved = hb.ANSWERS / cpg.LAST_OUTPUT
        self.assertTrue(saved.exists())
        self.assertIn(str(saved), self.cp.links)                            # путь к файлу - ссылка
        f = self.cp.select('fix-manual')                                    # код выхода 1 - заметно
        put(f, line=999, reason='проверка', action='удалено', disk='HDD90', path='A')
        self.run_cmd('fix-manual')
        self.assertIn('код выхода 1', self.cp.state.text())
        self.assertIsNone(self.cp.preview)
        self.assertFalse(self.cp.btn_write.isEnabled())

    def test_decide_preview_then_write(self):
        f = self.cp.select('decide')
        put(f, disk='HDD90', path='B', verdict='не нужно')
        rows = lambda: hb.DECISIONS.read_text(encoding='utf-8-sig') if hb.DECISIONS.exists() else ''   # noqa: E731
        text = self.run_cmd('decide')
        self.assertIn('предпросмотр', text)
        self.assertNotIn('не нужно', rows())
        self.assertTrue(self.cp.btn_write.isEnabled())
        put(f, path='B ')                                                   # правка формы гасит «Записать»
        self.assertFalse(self.cp.btn_write.isEnabled())
        self.run_cmd('decide')
        text = self.run_cmd('decide --yes', write=True)
        self.assertIn('Записано', text)
        self.assertIn('B\tне нужно', rows())
        self.assertTrue(any('Записать в таблицу' in x for x in self.asked))
        self.assertFalse(self.cp.btn_write.isEnabled())                    # второй раз - только после нового предпросмотра

    def test_mklist_creates_task_and_offers_tasks_page(self):
        f = self.cp.select('mklist')
        put(f, disk='HDD90', name='Новое задание')
        self.run_cmd('mklist')
        self.assertTrue((hb.TASKS / 'Новое задание').is_dir(), '\n'.join(self.cp.lines))
        self.assertIn('Создано задание', self.asked[-1])
        self.assertEqual(self.w.nav.currentRow(), 1)                       # «Задания»
        tasks = self.w.pages[1][1]
        self.assertTrue(wait(lambda: any(r['task'] == 'Новое задание' for r in tasks.rows)))


if __name__ == '__main__':
    unittest.main()
