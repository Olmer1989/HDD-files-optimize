"""Дымовой тест окна «Архив дисков» без экрана (Qt offscreen) на временных данных.

Запуск из корня проекта:  py -m unittest catalog\\test_app.py
"""
import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtCore import QThreadPool, Qt                 # noqa: E402
from PySide6.QtWidgets import QApplication                 # noqa: E402

import app                                                 # noqa: E402
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


if __name__ == '__main__':
    unittest.main()
