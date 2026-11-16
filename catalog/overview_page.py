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
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ui_common import *  # noqa: E402,F401,F403  (общее: gib, table, cell, Background, log_error)
from ui_common import _Signals  # noqa: E402,F401


# ---------- Обзор ----------

# Таблица «Диски направлений» (четвёртый круг, 16.11.2026): Диск · Всего, ГБ · «Копии проверены по хешу» (при
# сканировании / скопировано программой) · «Копии не проверены» (сверен только размер / со слов / хеш устарел) ·
# «Хеш не считался» + «Пересканировать». «Подключён» и «Свободно» - в строках направлений.
DISK_GROUPS = (('Копии проверены по хешу', ('при сканировании', 'скопировано программой')),
               ('Копии не проверены', ('сверен только размер', 'со слов «Я сделал в Проводнике»',
                                        'хеш устарел (файл изменён)')))
# в заголовке - переносы, чтобы таблица помещалась при ширине окна 1280
HEAD_BREAKS = {'скопировано программой': 'скопировано<br>программой', 'сверен только размер': 'сверен только<br>размер',
               'со слов «Я сделал в Проводнике»': 'со слов «Я сделал<br>в Проводнике»',
               'хеш устарел (файл изменён)': 'хеш устарел<br>(файл изменён)'}
DISK_HEAD = ['Диск', 'Всего, ГБ', 'при сканировании', 'скопировано программой', 'сверен только размер',
             'со слов «Я сделал в Проводнике»', 'хеш устарел (файл изменён)', 'Хеш не считался']
C_NOHASH = 7
# столбцы 2..6 - степени подтверждения S, C, Z, U, X (буквы владельцу не показываются); Z, U, X - не копия
DISK_TIPS = {
    1: 'Сколько места занимают все файлы этого диска по базе (последняя опись и записи копирования).',
    2: 'Файлов, у которых хеш посчитан сканером по самому файлу — копия подтверждена.',
    3: 'Файлов, скопированных программой (шаблоном копирования) со сверкой хеша прочитанного — копия подтверждена.',
    4: 'Файлов, у которых при копировании сверен только размер (или «уже есть») — копия НЕ подтверждена.',
    5: 'Файлов, записанных со слов владельца на странице «Я сделал в Проводнике» — копия НЕ подтверждена.',
    6: 'После подсчёта хеша у файла поменялись размер или дата. Пересканируйте папку, чтобы пересчитать хеш.',
    7: 'Файлов, у которых хеш не считался (обычно это файлы не фото и не видео). Чтобы посчитать хеш — пересканируйте '
       'папки (раздел «Диски и папки» → пересканирование).'}
RESCAN_TODO = 'Что делать: пересканировать папку — подключите диск, «Диски и папки» → «Пересканировать выбранные».'
WEAK_TODO = {
    4: 'Что делать: пересчитать хеши спорных файлов — подключите диск, «Диски и папки» → «Пересканировать выбранные» '
       'с галочкой «Перечитать всё».',
    5: RESCAN_TODO,
    6: 'Как: подключите диск, «Диски и папки» → «Пересканировать выбранные».'}
RED = '#c62828'
UNIQUE_NOTE = 'Файлы лежат в исключённых папках — не потерять при ручном переносе.'
CARD_CSS = 'QFrame#card { background:#ffffff; border:1px solid #d0d7de; border-radius:6px; }'


def gb_ru(x):
    """15,9 - как пишет владелец."""
    return gib(x).replace('.', ',')


def n_ru(n):
    return f'{n or 0:,}'.replace(',', ' ')


def shown_disks(dirs, checked):
    """Нижняя таблица «Обзора»: диски отмеченных направлений по порядку; ничего не отмечено - диски всех направлений,
    у которых есть диск. Отмеченное направление без диска (в окне его отметить нельзя, но файл выбора могли поправить
    или диск сняли командой) - в приписку «у Н… диск не назначен». -> (диски, показаны ли все, приписка)."""
    want = set(checked)
    marked = [d for n, d in dirs.items() if n in want]
    every = not marked
    pick = [d for d in dirs.values() if d.disks] if every else marked
    disks = list(dict.fromkeys(x for d in pick for x in d.disks))
    if every:
        note = 'галочек нет — показаны все' if disks else ''
    else:
        note = '; '.join(f'у {d.num} диск не назначен' for d in marked if not d.disks)
    return disks, every, note


def disk_rows(disks, info):
    """Строки таблицы дисков: [dict(disk, cells=[8 текстов], red={столбцы}, nohash=число)]."""
    out = []
    for d in disks:
        m = info[d]
        ev = m['ev']
        nums = [ev.get(k, 0) for k in sv.EV_COLS + (hb.EV_NONE,)]
        name = f'{d} · {m["letter"]}' if m.get('letter') else d
        cells = [name, gb_ru(m['gib'])] + [n_ru(x) for x in nums]
        red = {j for j in (4, 5, 6) if nums[j - 2]}
        out.append(dict(disk=d, cells=cells, red=red, nohash=nums[-1], in_base=bool(m.get('in_base'))))
    return out


def disk_table_html(rows):
    """HTML-таблица с двухуровневым заголовком; ненулевые «не проверены» - красным; «Хеш не считался» - ссылка."""
    import html as h
    th = 'style="background:#eef2f6; color:#333; font-weight:bold; padding:4px 8px"'
    th2 = 'style="background:#f6f8fa; color:#444; padding:3px 8px; font-weight:normal"'
    out = ['<table cellspacing="0" cellpadding="0" border="1" style="border-collapse:collapse; border-color:#d0d7de">',
           f'<tr><th rowspan="2" align="left" {th}>Диск</th><th rowspan="2" {th}>Всего, ГБ</th>']
    for title, subs in DISK_GROUPS:
        out.append(f'<th colspan="{len(subs)}" {th}>{h.escape(title)}</th>')
    out.append(f'<th rowspan="2" {th}>Хеш не<br>считался</th></tr><tr>')
    for _title, subs in DISK_GROUPS:
        for s in subs:
            out.append(f'<th {th2}>{HEAD_BREAKS.get(s, h.escape(s))}</th>')
    out.append('</tr>')
    for r in rows:
        c = r['cells']
        name = h.escape(c[0]) + ('' if r['in_base'] else ' <span style="color:#8a8a8a">(нет описи)</span>')
        out.append(f'<tr><td style="padding:4px 8px"><b>{name}</b></td>')
        for j in range(1, C_NOHASH):
            v = h.escape(c[j])
            if j in r['red']:
                v = f'<b style="color:{RED}">{v}</b>'
            out.append(f'<td align="right" style="padding:4px 8px">{v}</td>')
        v = h.escape(c[C_NOHASH])
        if r['nohash']:
            v += f' · <a href="rescan:{h.escape(r["disk"])}">Пересканировать</a>'
        out.append(f'<td align="right" style="padding:4px 8px">{v}</td></tr>')
    out.append('</table>')
    return ''.join(out)


def todo_html(rows):
    """Под таблицей - что делать с красными числами (подсказок у ячеек HTML-таблицы нет)."""
    import html as h
    cols = sorted({j for r in rows for j in r['red']})
    if not cols:
        return ''
    lines = [f'<b style="color:{RED}">{h.escape(DISK_HEAD[j])}</b> ({", ".join(r["disk"] for r in rows if j in r["red"])}): '
             f'{h.escape(DISK_TIPS[j])} {h.escape(WEAK_TODO[j])}' for j in cols]
    return '<br>'.join(lines)


def unique_li(u):
    """Строка «HDD77 — 301 фото и видео, 15,9 ГБ» + «Открыть список»; уточнения - мелко второй строкой; без путей."""
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
    """«Требует внимания»: группы с заголовками; ссылки - tasks: (экран «Задания на копирование»), list:<диск>."""
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
            elif g['key'] == 'unique':
                out.append(unique_li(x))
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
    """«Обзор» (четвёртый круг, 16.11.2026): направления строками-карточками; «Диски направлений: что на них лежит по
    базе» - таблица с группами столбцов; «Требует внимания» - карточка по размеру содержимого. Вся страница - одна
    вертикальная прокрутка, горизонтальной нет."""

    def __init__(self, win):
        super().__init__()
        self.win, self.ov, self.groups, self.rows = win, None, [], []
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
        self.dirs.on_choice = self.paint_disks
        self.dirs.on_saved = self.load
        lay.addWidget(self.dirs)
        lay.addSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel('<b>Диски направлений: что на них лежит по базе</b>'))
        self.all_note = QLabel('')
        self.all_note.setStyleSheet('color:#8a8a8a')
        head.addWidget(self.all_note)
        head.addStretch()
        lay.addLayout(head)
        self.dt = HtmlLabel()
        self.dt.setWordWrap(False)
        self.dt.setToolTip('\n'.join(f'{DISK_HEAD[j]}: {t}' for j, t in DISK_TIPS.items()))
        self.dt.linkActivated.connect(self.link_text)
        self.todo = QLabel('')
        self.todo.setWordWrap(True)
        self.todo.setStyleSheet('font-size:9pt; color:#444')
        self.checked = QLabel('')
        self.checked.setStyleSheet('color:gray')
        self.disk_card = card(self.dt, self.todo, self.checked)
        lay.addWidget(self.disk_card)
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
        self.win.bg.run(lambda: (sv.overview(), sv.tasks()), ok=self.render)

    def render(self, res):
        ov, tasks = res
        self.ov = ov
        self.groups = sv.attention(ov, tasks)
        self.paint_disks()
        self.checked.setText(f'Числа — по базе; подключён ли диск и свободное место — проверено в {ov["checked"]}.')
        self.text.setHtml(attention_html(self.groups))

    def current_dirs(self):
        data = self.dirs.data
        if data is not None:
            return data['dirs'], self.dirs.checked()
        return sv.directions(), __import__('directions_page').load_choice()

    def paint_disks(self):
        """Строки - диски отмеченных направлений (или всех); из уже полученных чисел, без запроса к базе."""
        if self.ov is None:
            return
        dirs, checked = self.current_dirs()
        disks, every, note = shown_disks(dirs, checked)
        info = self.ov['disks_info']
        missing = [d for d in disks if d not in info]
        if missing and not getattr(self, '_reloading', False):     # диск назначен после подсчёта - посчитать заново
            self._reloading = True
            self.load()
            return
        self._reloading = False
        disks = [d for d in disks if d in info]
        self.all_note.setText(note)
        self.rows = disk_rows(disks, info)
        self.dt.setHtml(disk_table_html(self.rows) if self.rows else
                        '<span style="color:#8a8a8a">Дисков нет: назначьте диски направлениям.</span>')
        t = todo_html(self.rows)
        self.todo.setText(t)
        self.todo.setVisible(bool(t))

    def list_path(self, disk):
        u = next((x for g in self.groups if g['key'] == 'unique' for x in g['items'] if x.get('disk') == disk), None)
        return (u or {}).get('list')

    def link_text(self, s):
        if s.startswith('rescan:'):
            self.win.open_page('Диски и папки')
            self.win.page('Диски и папки').show_disk(s[7:])

    def link(self, url):
        s = url if isinstance(url, str) else url.toString()
        if s.startswith('tasks:'):
            self.win.open_page(disk_ui.TASKS_PAGE)
        elif s.startswith('list:'):
            path = self.list_path(s[5:])
            if path and os.path.exists(path):
                os.startfile(path)
            else:
                QMessageBox.information(self, TITLE, 'Файл списка не найден — пересоберите базу.')
