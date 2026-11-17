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


HANG_LOG = 'окно - зависания.log'
HANG_DUMP_S = 5                                   # дольше - стеки всех потоков (faulthandler, C-поток)
HANG_GAP_S = 1.5                                  # окно не отвечало дольше - строка без стека
SLOW_S = 1.0                                      # медленная операция дерева - строка с именем и временем


def hang_log(text):
    """Строка в «окно - зависания.log» (рядом с «окно - ошибки.log»)."""
    try:
        hb.ANSWERS.mkdir(parents=True, exist_ok=True)
        with open(hb.ANSWERS / HANG_LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%d.%m.%Y %H:%M:%S ') + text + '\n')
    except OSError:
        pass


def timed(name):
    """Замер операции окна (этап 17): дольше SLOW_S - строка в журнал зависаний (имя, секунды, подробность)."""
    def deco(fn):
        def run(*a, **k):
            t = time.perf_counter()
            try:
                return fn(*a, **k)
            finally:
                dt = time.perf_counter() - t
                if dt > SLOW_S:
                    extra = ''
                    try:
                        extra = f', строк дерева {len(a[0].items)}' if hasattr(a[0], 'items') else ''
                    except Exception:                       # noqa: BLE001
                        pass
                    hang_log(f'медленно: {name} {dt:.1f} с{extra}')
        run.__name__, run.__doc__ = fn.__name__, fn.__doc__
        return run
    return deco


class Watchdog(QObject):
    """Сторож зависаний окна (этап 17). faulthandler.dump_traceback_later(HANG_DUMP_S) перевзводится таймером главного
    потока раз в секунду: если главный поток не вернулся в цикл событий дольше HANG_DUMP_S - C-поток faulthandler пишет
    стеки всех потоков в журнал зависаний (и при удержанном GIL). Промежуток между тиками дольше HANG_GAP_S - строка
    «окно не отвечало X с» (короткие зависания - без стека)."""

    def __init__(self, parent=None, interval_ms=1000):
        super().__init__(parent)
        self.file, self.last = None, time.monotonic()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.tick)

    def start(self):
        import faulthandler
        try:
            hb.ANSWERS.mkdir(parents=True, exist_ok=True)
            self.file = open(hb.ANSWERS / HANG_LOG, 'a', encoding='utf-8')
        except OSError:
            return False
        self.faulthandler = faulthandler
        self.last = time.monotonic()
        self.arm()
        self.timer.start()
        return True

    def arm(self):
        self.faulthandler.cancel_dump_traceback_later()
        self.file.flush()
        self.faulthandler.dump_traceback_later(HANG_DUMP_S, repeat=False, file=self.file)

    def tick(self):
        now = time.monotonic()
        gap = now - self.last
        self.last = now
        if gap > HANG_GAP_S:
            try:
                self.file.write(time.strftime('%d.%m.%Y %H:%M:%S ') + f'окно не отвечало {gap:.1f} с '
                                f'(стеки - выше, если дольше {HANG_DUMP_S} с)\n')
                self.file.flush()
            except OSError:
                pass
        self.arm()

    def stop(self):
        self.timer.stop()
        if self.file is not None:
            self.faulthandler.cancel_dump_traceback_later()
            self.file.close()
            self.file = None


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
STEPS = (('Назначить Архивный диск', 'Назначить Архивный диск', 'выберите диск'),
         ('Выбор источников', 'Выбор источников', 'папки на носителе'),
         (disk_ui.TASKS_PAGE, disk_ui.TASKS_PAGE, 'запуск заданий'))
STEP_RAZBOR = 1                                    # «2. Что копируем» - как кнопка «Дальше: выбрать папки на носителе»
NEED_DISK = 'Сначала отметьте диск: галочка у направления на вкладке «Назначить Архивный диск».'
STEP_NOW = ('#e3f2fd', '#1e88e5', '#0d47a1')       # фон, рамка, текст текущего шага
STEP_OTHER = ('#f1f3f5', '#d0d7de', '#5f6b76')
STEP_TALLER = 1.3                                  # плашка шага выше прежней (замечание владельца 17.11.2026)


class StepPlate(QFrame):
    """Одна плашка шага; щелчок по нетекущей - открыть вкладку шага (win.open_page)."""

    def __init__(self, bar, i):
        super().__init__()
        self.bar, self.i = bar, i
        self.page_name, bold, small = STEPS[i]
        self.current = i == bar.current
        self.setObjectName('step')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)              # 17.11.2026: плашка на 30 % выше (было 6 сверху и снизу)
        self.label = QLabel(f'<b>{bold}</b> — {small}')
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        lay.addWidget(self.label)
        bg, border, fg = STEP_NOW if self.current else STEP_OTHER
        width = 2 if self.current else 1
        line = self.label.heightForWidth(10000)              # текст в одну строку
        self.setMinimumHeight(round((line + 12 + 2 * width) * STEP_TALLER))   # прежняя высота в одну строку × 1,3
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
        """Щелчок по плашке i (тесты зовут напрямую). «2. Что копируем» работает как кнопка «Дальше: выбрать папки на
        носителе» (16.11.2026): нужен отмеченный в «Обзоре» диск (направление с диском); выбор сохранён, «Разбор»
        ставит его в списки (use_choice) и открывается; ничего не отмечено - не переходит, подсказка «Сначала отметьте
        диск». «3. Копирование» открывает задания всегда."""
        p = self.plates[i]
        if i == self.current or not p.can_open():
            return
        if i == STEP_RAZBOR:
            import directions_page                              # не на уровне модуля: directions_page - страница окна
            try:
                ok = bool(directions_page.chosen())
            except Exception:                                   # noqa: BLE001 - таблиц нет: как «ничего не выбрано»
                ok = False
            if not ok:
                self.say_choose(p)
                return
            page = self.win.page(p.page_name) if hasattr(self.win, 'page') else None
            if page is not None and hasattr(page, 'use_choice'):
                page.use_choice()
        self.win.open_page(p.page_name)

    def say_choose(self, plate):
        """Подсказка у плашки и в строке состояния: перехода нет."""
        from PySide6.QtWidgets import QToolTip
        text = NEED_DISK
        if hasattr(self.win, 'statusBar'):
            self.win.statusBar().showMessage(text, 8000)
        if plate.isVisible():
            QToolTip.showText(plate.mapToGlobal(plate.rect().bottomLeft()), text, plate)
        self.last_hint = text


def cell(text, right=False, color=None):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    return it
