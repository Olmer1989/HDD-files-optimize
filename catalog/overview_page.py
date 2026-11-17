"""Страница «Обзор» окна «Архив дисков» (вынесено из app.py 16.11.2026; блок «Направления» - directions_page.py)."""
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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ui_common import *  # noqa: E402,F401,F403  (общее: gib, table, cell, Background, log_error)
from ui_common import _Signals  # noqa: E402,F401


# ---------- Обзор ----------

# Таблица «Диски направлений: что на них лежит по базе» (18.11.2026) - в окне «Содержимое выбранного диска»
# (disk_content_dialog.py, сама таблица - disk_table.py). Прежние имена (gb_ru, n_ru, files_word, DiskTable …)
# отдаются отсюда, как раньше: их берут ui/disks, app и переходник disks_page.
from disk_table import *  # noqa: E402,F401,F403

UNIQUE_NOTE = 'Файлы лежат в исключённых папках — не потерять при ручном переносе.'
CARD_CSS = 'QFrame#card { background:#ffffff; border:1px solid #d0d7de; border-radius:6px; }'


def unique_li(u):
    """Не используется с 18.11.2026 (имя нужно переходнику disks_page). Строка «HDD77 — 301 фото и видео, 15,9 ГБ» + «Открыть список»; уточнения - мелко второй строкой; без путей."""
    import html as h
    disk = h.escape(u['disk'])
    if u.get('missing'):
        return f'<li><b>{disk}</b> — файл списка не найден: пересоберите базу.</li>'
    link = f' &nbsp;<a href="list:{disk}">Открыть список</a>'
    if u.get('files') is None:
        return f'<li><b>{disk}</b> — фото и видео, которых больше нигде нет{link}</li>'
    more = []
    if u.get('small'):
        more.append(f'из них мелких картинок (меньше 50 КБ) — {u["small"]}')
    if u.get('nohash'):
        more.append(f'видео .m2t/.dv, которым на других дисках хеш не считали, — {u["nohash"]}')
    note = h.escape('; '.join(more) + '. ' + UNIQUE_NOTE if more else UNIQUE_NOTE)
    return (f'<li><b>{disk}</b> — {u["files"]} фото и видео, {gb_ru(u["bytes"] / hb.GIB)} ГБ{link}'
            f'<br><span style="color:#777; font-size:8pt">{note}</span></li>')


def attention_html(groups):
    """«Требует внимания»: группы с заголовками; ссылка tasks: - экран «Задания на копирование». Группы «Файлы, которых
    больше нигде нет» нет (18.11.2026, решение владельца); unique_li и UNIQUE_NOTE остались - их отдаёт переходник."""
    import html as h
    if not groups:
        return '<p style="color:#2e7d32">Ничего не требует внимания.</p>'
    out = []
    for g in groups:
        out.append(f'<p style="margin:4px 0 0 0"><b>{h.escape(g["title"])}</b></p><ul style="margin-top:2px">')
        for x in g['items']:
            if g['key'] == 'tasks':
                out.append(f'<li>«{h.escape(x["task"])}» — {h.escape(x["state"])}: сделано {x["done"]} из '
                           f'{x["total"]}, ошибок {x["errors"]}</li>')
            else:
                out.append(f'<li>{h.escape(str(x))}</li>')
        out.append('</ul>')
        if g['key'] == 'tasks':
            out.append('<p style="margin-top:0"><a href="tasks:">Открыть Задания на копирование</a></p>')
    return ''.join(out)


class HtmlLabel(QLabel):
    """Надпись с HTML и ссылками, высота - по содержимому (вместо QTextBrowser с пустой рамкой)."""

    def __init__(self):
        super().__init__()
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setOpenExternalLinks(False)
        self.setTextInteractionFlags(Qt.TextBrowserInteraction)

    def setHtml(self, html_):                                 # noqa: N802
        self.setText(html_)

    def toHtml(self):                                         # noqa: N802
        return self.text()

    def toPlainText(self):                                    # noqa: N802
        doc = QTextDocument()
        doc.setHtml(self.text())
        return doc.toPlainText()


def card(*widgets):
    f = QFrame()
    f.setObjectName('card')
    f.setStyleSheet(CARD_CSS)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(10, 8, 10, 8)
    for w in widgets:
        lay.addWidget(w)
    return f


class OverviewPage(QWidget):
    """«Обзор» (четвёртый круг, 16.11.2026): направления строками-карточками; «Требует внимания» - карточка по размеру
    содержимого. Вся страница - одна вертикальная прокрутка, горизонтальной нет. Таблица «что лежит на дисках по базе»
    с 18.11.2026 - в окне «Содержимое выбранного диска» (кнопка в карточке направления, disk_content_dialog)."""

    def __init__(self, win):
        super().__init__()
        self.win, self.ov, self.groups = win, None, []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.scroll = scroll
        lay = QVBoxLayout(body)
        top = QHBoxLayout()
        self.btn = QPushButton('Обновить')
        self.btn.clicked.connect(self.refresh)
        title = QLabel('Обзор')
        f = title.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.btn)
        lay.addLayout(top)
        self.steps = StepsBar(win, 0)                     # шаги работы: «1. Куда копируем» (этап 11)
        lay.addWidget(self.steps)
        self.dirs = __import__('directions_page').DirectionsSection(win)     # «Направления» (логика v3, этап 4)
        self.dirs.on_saved = self.load
        lay.addWidget(self.dirs)
        lay.addSpacing(10)
        lay.addWidget(QLabel('<b>Требует внимания</b>'))
        self.text = HtmlLabel()
        self.text.linkActivated.connect(self.link)
        lay.addWidget(card(self.text))
        lay.addStretch(1)

    def refresh(self):
        self.dirs.refresh()
        self.load()

    def load(self):
        self.text.setHtml('<p>Считаю…</p>')
        self.win.bg.run(lambda: (sv.overview([]), sv.tasks()), ok=self.render)   # числа дисков - в окне диска

    def render(self, res):
        ov, tasks = res
        self.ov = ov
        self.groups = sv.attention(ov, tasks)
        self.text.setHtml(attention_html(self.groups))

    def link(self, url):
        s = url if isinstance(url, str) else url.toString()
        if s.startswith('tasks:'):
            self.win.open_page(disk_ui.TASKS_PAGE)
