"""«Архив дисков» - окно программы: Обзор, Задания, Диски и папки, Команды (этап 1 переноса команд, 15.11.2026).

Запуск: ярлык на рабочем столе или  pythonw catalog\\app.py
Окно - оболочка над тем же ядром: считает hashbase.py, данные даёт пакет service, копируют и перемещают те же
шаблоны (в своём окне PowerShell, с вопросом «да» и остановкой по Q). Окно ничего не удаляет и базу открытой
не держит. Каждые 10 секунд оно проверяет, не появились ли новые журналы или строки таблиц, и само применяет
их к базе. Ошибки - в «_БАЗА\\ответы\\окно - ошибки.log».
"""
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

from ui_common import *  # noqa: E402,F401,F403  (общее для страниц; вынесено 16.11.2026)
from ui_common import _Signals  # noqa: E402,F401
from overview_page import *  # noqa: E402,F401,F403  (страница «Обзор»)
from ui.disks.page import DisksPage  # noqa: E402  (страница «Диски и папки»: пакет ui/disks)


# ---------- главное окно ----------

def count_ru(n):
    """11 300 000 -> «11,3 млн», 45 600 -> «45,6 тыс.», 950 -> «950»."""
    n = n or 0
    if n >= 1_000_000:
        return f'{n / 1_000_000:.1f}'.replace('.', ',') + ' млн'
    if n >= 10_000:
        return f'{n / 1000:.1f}'.replace('.', ',') + ' тыс.'
    return f'{n:,}'.replace(',', ' ')


def footer_text(info):
    """(built «15.11.2026 22:52», носителей, файлов) -> «База собрана 15.11 22:52: носителей 57, файлов 11,3 млн»."""
    if not info:
        return 'База ещё не собрана'
    built, n, files = info
    return f'База собрана {built_short(built)}: носителей {n}, файлов {count_ru(files)}'


def built_short(built):
    """meta.built («15.11.2026 22:52» - так пишет сборка; на всякий случай и ISO «2026-11-15 22:52:10») -> «15.11 22:52»."""
    import re
    b = (built or '').strip()
    m = re.match(r'(\d{1,2})\.(\d{1,2})\.\d{4}\D+(\d{1,2}):(\d{2})', b)
    if m:
        return f'{int(m[1]):02}.{int(m[2]):02} {int(m[3]):02}:{m[4]}'
    m = re.match(r'\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})', b)
    if m:
        return f'{m[2]}.{m[1]} {m[3]}:{m[4]}'
    return b or '—'


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.resize(1250, 800)
        self.bg = Background(self)
        self.updating, self.sig = False, None
        self.pages = [('Обзор', OverviewPage(self)),
                      ('Разбор носителя', __import__('razbor_page').RazborPage(self)),
                      (disk_ui.TASKS_PAGE, __import__('ui.tasks.page', fromlist=['TasksPage']).TasksPage(self)),
                      ('Диски и папки', DisksPage(self)),
                      ('Я сделал в Проводнике', explorer_page.ExplorerPage(self)),
                      ('Команды', commands_page.CommandsPage(self))]
        self.nav = QListWidget()
        self.nav.setFixedWidth(200)                  # «Задания на копирование» - целиком
        f = QFont()
        f.setPointSize(11)
        self.nav.setFont(f)
        self.stack = QStackedWidget()
        for name, page in self.pages:
            self.nav.addItem(name)
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.go)
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(self.nav)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_sources)
        self.timer.start(10000)
        self.footer = QLabel('')                      # подвал: «База собрана 15.11 22:52: носителей 57, файлов 11,3 млн»
        self.statusBar().addPermanentWidget(self.footer)
        self.show_footer()                            # готовая база - сразу, не дожидаясь проверки новых модулей
        self.nav.setCurrentRow(0)
        self.apply_new()
        self.watchdog = Watchdog(self)                # этап 17: зависания окна - в «окно - зависания.log»
        self.watchdog.start()

    def go(self, i):
        self.stack.setCurrentIndex(i)
        if not hb.DB.exists() or sv.generation() is None:
            self.statusBar().showMessage('База собирается - экран откроется, когда она будет готова (при первом запуске - несколько минут).')
            return
        self.pages[i][1].refresh()

    def page(self, name):
        return next(p for n, p in self.pages if n == name)

    def open_page(self, name):
        self.nav.setCurrentRow([n for n, _ in self.pages].index(name))

    def closeEvent(self, e):                                  # noqa: N802
        if not self.page('Команды').can_close():
            e.ignore()
            return
        if not self.page('Я сделал в Проводнике').can_close():
            QMessageBox.information(self, TITLE, 'Идёт запись или исправление на странице «Я сделал в Проводнике». '
                                    'Дождитесь окончания.')
            e.ignore()
            return
        if getattr(self, 'rescan', None) is not None and self.rescan.running:
            QMessageBox.information(self, TITLE, 'Идёт пересканирование папок. Сначала остановите его.')
            e.ignore()
            return
        super().closeEvent(e)
        if e.isAccepted() and getattr(self, 'watchdog', None) is not None:
            self.watchdog.stop()

    def show_error(self, text):
        short = text.strip().splitlines()[-1] if text.strip() else 'ошибка'
        QMessageBox.warning(self, TITLE, f'Не получилось: {short}\n\nПодробно - в «_БАЗА\\ответы\\окно - ошибки.log».')

    def show_footer(self):
        try:
            info = sv.base_info()
        except Exception:                                     # noqa: BLE001 - подвал не должен ронять окно
            info = None
        self.footer.setText(footer_text(info))

    def check_sources(self):
        if self.updating:
            return
        self.bg.run(sv.sources_signature, ok=self.on_signature, quiet=True)

    def on_signature(self, sig):
        if self.sig is not None and sig != self.sig:
            self.apply_new()
        self.sig = sig

    def apply_new(self, then=None):
        """Применить новые модули (журналы, строки таблиц, сканы) - в фоне; затем перечитать экран.
        then(результат) - вызвать после применения (окно пересканирования показывает итог приёма)."""
        if self.updating:
            if then:                                  # идёт другое применение - повторить после него
                QTimer.singleShot(2000, lambda: self.apply_new(then))
            return
        self.updating = True
        self.statusBar().showMessage('Проверяю новые журналы и записи…')

        def done(res):
            self.updating = False
            gen = sv.generation()
            msg = {'update': 'Применены новые модули.', 'rebuild': 'База собрана заново.'}.get(res, '')
            self.show_footer()
            if msg:
                self.statusBar().showMessage(msg, 15000)
            else:
                self.statusBar().clearMessage()
            if gen:
                self.stack.currentWidget().refresh()
            if then:
                then(res)

        def fail(text):
            self.updating = False
            log_error(text)
            self.statusBar().showMessage('Не удалось обновить базу - подробности в «окно - ошибки.log».')
            if then:
                then(None)
        job = Job(hb.update, (None, True), done, fail)
        self.bg.jobs.add(job)
        QThreadPool.globalInstance().start(job)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(TITLE)
    sys.excepthook = lambda t, v, tb: (log_error(''.join(traceback.format_exception(t, v, tb))),
                                       QMessageBox.warning(None, TITLE, f'Ошибка: {v}'))
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
