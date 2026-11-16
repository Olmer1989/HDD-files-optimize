"""Общее для страниц окна «Архив дисков»: журнал ошибок окна, фоновые задачи, таблицы, числа (вынесено из app.py 16.11.2026)."""
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hb_core import api as hb  # noqa: E402  (ядро; hashbase.py - только обёртка командной строки)
import service as sv           # noqa: E402
import commands_page           # noqa: E402
import disk_ui                 # noqa: E402  (порядок и оформление носителей - общее с «Командами»)
import rescan_dialog           # noqa: E402
import explorer_page           # noqa: E402

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal   # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextDocument                     # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


TITLE = 'Архив дисков'


def log_error(text):
    try:
        hb.ANSWERS.mkdir(parents=True, exist_ok=True)
        with open(hb.ANSWERS / 'окно - ошибки.log', 'a', encoding='utf-8') as f:
            f.write(time.strftime('%d.%m.%Y %H:%M:%S ') + text + '\n')
    except OSError:
        pass


def gib(x):
    return f'{x:,.1f}'.replace(',', ' ')


# ---------- фоновые задачи: окно не замирает ----------

class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, fn, args, ok, fail):
        super().__init__()
        self.fn, self.args, self.sig = fn, args, _Signals()
        self.sig.done.connect(ok)
        self.sig.failed.connect(fail)

    def run(self):
        try:
            self.sig.done.emit(self.fn(*self.args))
        except SystemExit as e:
            self.sig.failed.emit(str(e))
        except Exception:                                     # noqa: BLE001
            self.sig.failed.emit(traceback.format_exc())


class Background:
    """Запуск функции в фоне; ответ приходит в главный поток. Держит ссылки, пока задача не закончится."""

    def __init__(self, window):
        self.window, self.jobs = window, set()

    def run(self, fn, *args, ok=None, quiet=False):
        def done(res, job=None):
            if ok:
                ok(res)

        def fail(text):
            log_error(text)
            if not quiet:
                self.window.show_error(text)
        job = Job(fn, args, done, fail)
        self.jobs.add(job)
        job.sig.done.connect(lambda *_: self.jobs.discard(job))
        job.sig.failed.connect(lambda *_: self.jobs.discard(job))
        QThreadPool.globalInstance().start(job)


def table(headers, stretch=0):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


def cell(text, right=False, color=None):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it
