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
# подсказки заголовков (16.11.2026, замечание 5 владельца): у каждого столбца - только про свой столбец, 1-2 строки
DISK_TIPS = {
    0: 'Номер диска по журналу сканирования и буква, если диск подключён.',
    1: 'Сколько места занимают все файлы диска по базе.',
    2: 'Хеш посчитан сканером по самому файлу —\nкопия подтверждена.',
    3: 'Скопировано программой со сверкой хеша —\nкопия подтверждена.',
    4: 'При копировании сверен только размер —\nкопия НЕ подтверждена.',
    5: 'Записано вручную в «Я сделал в Проводнике» —\nкопия НЕ подтверждена.',
    6: 'Хеш посчитан, но потом файл изменился (размер или дата).',
    7: 'Хеш у этих файлов не считали (обычно это не фото и не видео).'}
GROUP_TIPS = {'Копии проверены по хешу': 'Копия файла подтверждена по SHA-256.',
              'Копии не проверены': 'Файл в базе есть, но копия хешем не подтверждена.'}
# под таблицей - одна короткая строка на каждое красное число (замечание 4 владельца)
TODO_LINE = {
    4: ('{n} {files} — при копировании сверен только размер, копия не подтверждена',
        'пересчитать хеши (пересканировать с «Перечитать всё»)'),
    5: ('{n} {files} {checked} — {written} вручную в «Я сделал в Проводнике»', 'пересканировать эти папки'),
    6: ('у {n} {files_gen} хеш устарел — файл изменён после подсчёта', 'пересканировать эти папки')}
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
        out.append(dict(disk=d, cells=cells, red=red, nohash=nums[-1], in_base=bool(m.get('in_base')), nums=nums))
    return out


def files_word(n):
    n = abs(int(n or 0))
    if n % 10 == 1 and n % 100 != 11:
        return 'файл'
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return 'файла'
    return 'файлов'


def todo_items(rows):
    """Что сделать с красными числами: [(диск, столбец, текст строки, текст действия)] - по строке на число."""
    out = []
    for r in rows:
        for j in sorted(r['red']):
            n = r['nums'][j - 2]
            what, act = TODO_LINE[j]
            one = n % 10 == 1 and n % 100 != 11
            out.append((r['disk'], j, what.format(n=n_ru(n), files=files_word(n), files_gen='файла' if one else 'файлов',
                                                  checked='не проверен' if one else 'не проверены',
                                                  written='записан' if one else 'записаны'), act))
    return out


def rescan_tip(disk, n):
    """Подсказка кнопки «Пересканировать» - по пунктам."""
    gen = 'файла' if n % 10 == 1 and n % 100 != 11 else 'файлов'
    return (f'Пересканировать {disk}\n• посчитает хеш у {n_ru(n)} {gen} без хеша\n'
            '• нужен подключённый диск\n• откроет «Диски и папки» с этим диском')


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
    """Под таблицей - по короткой строке на каждое красное число: «⚠ HDD55: 432 файла не проверены — записаны вручную
    в «Я сделал в Проводнике». Что сделать: пересканировать эти папки → Перейти» (ссылка - «Диски и папки» с этим
    диском). Раньше здесь была общая «стена текста» по столбцам (замечание 4 владельца, 16.11.2026)."""
    import html as h
    lines = [f'<span style="color:{RED}">⚠</span> <b>{h.escape(d)}</b>: {h.escape(what)}. Что сделать: {h.escape(act)} → '
             f'<a href="rescan:{h.escape(d)}">Перейти</a>' for d, _j, what, act in todo_items(rows)]
    return '<br>'.join(lines)


class DiskTable(QFrame):
    """Таблица «Диски направлений» из настоящих виджетов (16.11.2026, замечания 4-5 владельца): двухуровневый
    заголовок, у каждого заголовка - своя короткая подсказка (общей подсказки на всю таблицу нет); столбец «Диск» по
    самому длинному имени («HDD55 · I:» не обрезается); «Пересканировать» - маленькая кнопка с подсказкой по пунктам
    (открывает «Диски и папки» с этим диском, on_rescan)."""
    LINE = '#d0d7de'

    def __init__(self, on_rescan):
        super().__init__()
        self.on_rescan = on_rescan
        self.setObjectName('disktable')
        self.setStyleSheet(f'QFrame#disktable {{ border:1px solid {self.LINE}; background:#ffffff; }}')
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(0)
        self.heads, self.buttons, self.cells, self.rows = {}, {}, [], []

    def _cell(self, text, r, c, rs=1, cs=1, head=False, sub=False, right=False, tip=''):
        lab = QLabel(text)
        lab.setTextFormat(Qt.RichText)
        lab.setWordWrap(False)
        bg = '#eef2f6' if head else '#f6f8fa' if sub else '#ffffff'
        weight = 'bold' if head else 'normal'
        lab.setStyleSheet(f'QLabel {{ background:{bg}; font-weight:{weight}; padding:4px 8px; '
                          f'border-right:1px solid {self.LINE}; border-bottom:1px solid {self.LINE}; }}')
        al = Qt.AlignRight if right else (Qt.AlignHCenter if (head or sub) and c else Qt.AlignLeft)
        lab.setAlignment(al | Qt.AlignVCenter)
        if tip:
            lab.setToolTip(tip)
        self.grid.addWidget(lab, r, c, rs, cs)
        return lab

    def clear(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.heads, self.buttons, self.cells = {}, {}, []

    def set_rows(self, rows):
        import html as h
        self.clear()
        self.rows = rows
        self.heads['Диск'] = self._cell('Диск', 0, 0, 2, 1, head=True, tip=DISK_TIPS[0])
        self.heads['Всего, ГБ'] = self._cell('Всего, ГБ', 0, 1, 2, 1, head=True, tip=DISK_TIPS[1])
        col = 2
        for title, subs in DISK_GROUPS:
            self.heads[title] = self._cell(h.escape(title), 0, col, 1, len(subs), head=True, tip=GROUP_TIPS[title])
            for k, s_ in enumerate(subs):
                self.heads[s_] = self._cell(HEAD_BREAKS.get(s_, h.escape(s_)), 1, col + k, sub=True,
                                            tip=DISK_TIPS[DISK_HEAD.index(s_)])
            col += len(subs)
        self.heads['Хеш не считался'] = self._cell('Хеш не<br>считался', 0, col, 2, 1, head=True, tip=DISK_TIPS[C_NOHASH])
        fm = QFontMetrics(self.font())
        bold = QFont(self.font())
        bold.setBold(True)
        fmb = QFontMetrics(bold)
        name_w = max([fmb.horizontalAdvance(r['cells'][0]) + (0 if r['in_base'] else fm.horizontalAdvance(' (нет описи)'))
                      for r in rows] + [fm.horizontalAdvance('Диск')]) + 24
        self.grid.setColumnMinimumWidth(0, name_w)
        for i, r in enumerate(rows):
            c = r['cells']
            name = '<b>' + h.escape(c[0]) + '</b>' + ('' if r['in_base'] else ' <span style="color:#8a8a8a">(нет описи)</span>')
            line = [self._cell(name, 2 + i, 0)]
            for j in range(1, C_NOHASH):
                v = h.escape(c[j])
                if j in r['red']:
                    v = f'<b style="color:{RED}">{v}</b>'
                line.append(self._cell(v, 2 + i, j, right=True))
            box = QWidget()
            box.setObjectName('nohash')
            box.setStyleSheet(f'QWidget#nohash {{ background:#ffffff; border-right:1px solid {self.LINE}; '
                              f'border-bottom:1px solid {self.LINE}; }}')
            hl = QHBoxLayout(box)
            hl.setContentsMargins(8, 2, 6, 2)
            hl.setSpacing(6)
            num = QLabel(h.escape(c[C_NOHASH]))
            num.setStyleSheet('background:transparent; border:none')
            hl.addStretch(1)
            hl.addWidget(num)
            if r['nohash']:
                b = QPushButton('Пересканировать')
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet('QPushButton { font-size:8pt; padding:1px 8px; border:1px solid #1e88e5; '
                                'border-radius:4px; color:#0d47a1; background:#e3f2fd; }'
                                'QPushButton:hover { background:#bbdefb; }')
                b.setToolTip(rescan_tip(r['disk'], r['nohash']))
                b.clicked.connect(lambda _=False, d=r['disk']: self.on_rescan(d))
                hl.addWidget(b)
                self.buttons[r['disk']] = b
            self.grid.addWidget(box, 2 + i, C_NOHASH)
            line.append(num)
            self.cells.append(line)

    def text(self):
        """Текст таблицы построчно (для проверок): ячейки через « | »."""
        doc = QTextDocument()
        out = []
        for lab in self.heads.values():
            doc.setHtml(lab.text())
            out.append(doc.toPlainText())
        lines = [' | '.join(out)]
        for line in self.cells:
            vals = []
            for lab in line:
                doc.setHtml(lab.text())
                vals.append(doc.toPlainText())
            lines.append(' | '.join(vals))
        return '\n'.join(lines)


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
        self.dt = DiskTable(lambda d: self.link_text('rescan:' + d))   # без общей подсказки на всю таблицу
        self.dt_empty = QLabel('<span style="color:#8a8a8a">Дисков нет: назначьте диски направлениям.</span>')
        self.dt_wrap = QWidget()
        wl = QHBoxLayout(self.dt_wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.dt)
        wl.addWidget(self.dt_empty)
        wl.addStretch(1)
        self.todo = QLabel('')
        self.todo.setWordWrap(True)
        self.todo.setTextFormat(Qt.RichText)
        self.todo.setStyleSheet('color:#333')
        self.todo.linkActivated.connect(self.link_text)
        self.checked = QLabel('')
        self.checked.setStyleSheet('color:gray')
        self.disk_card = card(self.dt_wrap, self.todo, self.checked)
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
        self.dt.set_rows(self.rows)
        self.dt.setVisible(bool(self.rows))
        self.dt_empty.setVisible(not self.rows)
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
