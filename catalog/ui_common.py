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


# ---------- шаги работы: «1. Куда копируем · 2. Что копируем · 3. Копирование» (этап 11, 16.11.2026) ----------

# (вкладка окна, жирная часть, пояснение)
STEPS = (('Обзор', '1. Куда копируем', 'выберите диск'),
         ('Разбор носителя', '2. Что копируем', 'папки на носителе'),
         (disk_ui.TASKS_PAGE, '3. Копирование', 'запуск заданий'))
STEP_NOW = ('#e3f2fd', '#1e88e5', '#0d47a1')       # фон, рамка, текст текущего шага
STEP_OTHER = ('#f1f3f5', '#d0d7de', '#5f6b76')


class StepPlate(QFrame):
    """Одна плашка шага; щелчок по нетекущей - открыть вкладку шага (win.open_page)."""

    def __init__(self, bar, i):
        super().__init__()
        self.bar, self.i = bar, i
        self.page_name, bold, small = STEPS[i]
        self.current = i == bar.current
        self.setObjectName('step')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        self.label = QLabel(f'<b>{bold}</b> — {small}')
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        lay.addWidget(self.label)
        bg, border, fg = STEP_NOW if self.current else STEP_OTHER
        width = 2 if self.current else 1
        self.setStyleSheet(f'QFrame#step {{ background:{bg}; border:{width}px solid {border}; border-radius:6px; }}'
                           f'QFrame#step QLabel {{ color:{fg}; background:transparent; border:none; }}')
        if self.current:
            self.setToolTip('Вы здесь')
        elif self.can_open():
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f'Открыть вкладку «{self.page_name}»')

    def can_open(self):
        return self.page_name in [n for n, _ in getattr(self.bar.win, 'pages', [])]

    def mouseReleaseEvent(self, e):                            # noqa: N802
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.bar.open(self.i)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mousePressEvent(self, e):                              # noqa: N802
        if e.button() == Qt.LeftButton:
            e.accept()                                         # плашка забирает щелчок - отпускание придёт сюда же
            return
        super().mousePressEvent(e)


class StepsBar(QWidget):
    """Шаги работы вверху вкладок «Обзор» (0), «Разбор носителя» (1), «Задания на копирование» (2): три плашки
    равной ширины; текущая - голубая с рамкой, остальные серые и открывают свою вкладку."""

    def __init__(self, win, current):
        super().__init__()
        self.win, self.current = win, current
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 6)
        lay.setSpacing(8)
        self.plates = [StepPlate(self, i) for i in range(len(STEPS))]
        for p in self.plates:
            lay.addWidget(p, 1)

    def open(self, i):
        """Щелчок по плашке i (тесты зовут напрямую)."""
        p = self.plates[i]
        if i != self.current and p.can_open():
            self.win.open_page(p.page_name)


def cell(text, right=False, color=None):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it
