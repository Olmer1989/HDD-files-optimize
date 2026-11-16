"""«Архив дисков» - окно программы: Обзор, Задания, Диски и папки, Команды (этап 1 переноса команд, 15.11.2026).

Запуск: ярлык на рабочем столе или  pythonw catalog\\app.py
Окно - оболочка над тем же ядром: считает hashbase.py, данные даёт service.py, копируют и перемещают те же
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

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal   # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication                                  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,  # noqa: E402
                               QListWidget, QMainWindow, QMessageBox, QPushButton, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
STATE_COLOR = {'идёт': '#1565c0', 'готово': '#2e7d32', 'готово с ошибками': '#c62828', 'прервано': '#e65100',
               'состояние неизвестно': '#6d4c41', 'не запускалось': '#455a64'}


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


# ---------- Обзор ----------

DISK_HEAD = ['Диск', 'Подключён', 'Свободно', 'Общий объём\nфайлов, ГБ', 'Проверено по хешу\nпри сканировании',
             'Скопировано программой,\nхеш сверен', 'Скопировано, сверен\nтолько размер',
             'Со слов «Я сделал\nв Проводнике»', 'Изменились\nпосле проверки']
# столбцы 4..8 - степени подтверждения S, C, Z, U, X (буквы владельцу не показываются); Z, U, X - не копия
DISK_TIPS = {
    3: 'Сколько места занимают все файлы этого диска по базе (последняя опись и записи копирования).',
    4: 'Файлов, у которых хеш посчитан сканером по самому файлу — копия подтверждена.',
    5: 'Файлов, скопированных программой (шаблоном копирования) со сверкой хеша прочитанного — копия подтверждена.',
    6: 'Файлов, у которых при копировании сверен только размер (или «уже есть») — копия НЕ подтверждена.',
    7: 'Файлов, записанных со слов владельца на странице «Я сделал в Проводнике» — копия НЕ подтверждена.',
    8: 'Файлов, которые изменились после подсчёта хеша — копия НЕ подтверждена.'}
RESCAN_TODO = 'Что делать: пересканировать папку — подключите диск, «Диски и папки» → «Пересканировать папку…».'
WEAK_TODO = {
    6: 'Что делать: пересчитать хеши спорных файлов — подключите диск, «Диски и папки» → «Пересканировать папку…» '
       'с галочкой «Перечитать всё».',
    7: RESCAN_TODO,
    8: RESCAN_TODO}
RED = '#c62828'
MAX_DISK_ROWS = 8
UNIQUE_NOTE = 'Файлы лежат в исключённых папках — не потерять при ручном переносе.'


def gb_ru(x):
    """15,9 - как пишет владелец."""
    return gib(x).replace('.', ',')


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
    """«Требует внимания»: группы с заголовками; ссылки - tasks: (экран «Задания»), list:<диск> (файл списка)."""
    import html as h
    if not groups:
        return '<p style="color:#2e7d32">Ничего не требует внимания.</p>'
    out = []
    for g in groups:
        out.append(f'<h4 style="margin-bottom:2px">{h.escape(g["title"])}</h4><ul style="margin-top:2px">')
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
            out.append('<p style="margin-top:0"><a href="tasks:">Открыть Задания</a></p>')
    return ''.join(out)


class OverviewPage(QWidget):
    """«Обзор» (второй круг, 16.11.2026): «Направления»; «Диски направлений: что на них лежит по базе» (диски
    отмеченных направлений, иначе - всех); «Требует внимания» по группам. Строка «База собрана …» - в подвале окна."""

    def __init__(self, win):
        super().__init__()
        self.win, self.ov, self.groups = win, None, []
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.btn = QPushButton('Обновить')
        self.btn.clicked.connect(self.refresh)
        top.addWidget(QLabel('<b>Обзор</b>'))
        top.addStretch()
        top.addWidget(self.btn)
        lay.addLayout(top)
        self.dirs = __import__('directions_page').DirectionsSection(win)     # «Направления» (логика v3, этап 4)
        self.dirs.on_choice = self.paint_disks
        self.dirs.on_saved = self.load
        lay.addWidget(self.dirs)
        head = QHBoxLayout()
        head.addWidget(QLabel('<b>Диски направлений: что на них лежит по базе</b>'))
        self.all_note = QLabel('')
        self.all_note.setStyleSheet('color:#8a8a8a')
        head.addWidget(self.all_note)
        head.addStretch()
        lay.addLayout(head)
        self.dt = table(DISK_HEAD)
        self.dt.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.dt.setSelectionMode(QAbstractItemView.NoSelection)
        for j, tip in DISK_TIPS.items():
            self.dt.horizontalHeaderItem(j).setToolTip(tip)
        lay.addWidget(self.dt)
        self.checked = QLabel('')
        self.checked.setStyleSheet('color:gray')
        lay.addWidget(self.checked)
        lay.addWidget(QLabel('<b>Требует внимания</b>'))
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.setOpenExternalLinks(False)
        self.text.anchorClicked.connect(self.link)
        lay.addWidget(self.text, 1)

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
        self.checked.setText(f'Свободное место проверено в {ov["checked"]}.')
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
        self.dt.setRowCount(len(disks))
        for i, d in enumerate(disks):
            m = info[d]
            ev = m['ev']
            free = f'{gb_ru(m["free_gib"])} ГБ' if 'free_gib' in m else '—'
            vals = [d, m['letter'] or 'нет', free, gb_ru(m['gib'])] + \
                [f'{ev.get(k, 0):,}'.replace(',', ' ') for k in sv.EV_COLS]
            for j, v in enumerate(vals):
                it = cell(v, right=j >= 2)
                if j == 0:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    if not m.get('in_base'):
                        it.setToolTip(f'{d}: в базе нет описи этого диска — числа нулевые.')
                if j >= 6 and ev.get(sv.EV_COLS[j - 4], 0):
                    it.setForeground(QColor(RED))
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                    it.setToolTip(DISK_TIPS[j] + '\n' + WEAK_TODO[j])
                elif j >= 3:
                    it.setToolTip(DISK_TIPS[j])
                self.dt.setItem(i, j, it)
        self.dt.resizeRowsToContents()
        # высота - не больше MAX_DISK_ROWS строк, дальше прокрутка внутри таблицы («Требует внимания» не вытесняется)
        h = self.dt.horizontalHeader().height() + sum(self.dt.rowHeight(i) for i in range(min(len(disks), MAX_DISK_ROWS))) + 6
        self.dt.setFixedHeight(max(h, 60))

    def list_path(self, disk):
        u = next((x for g in self.groups if g['key'] == 'unique' for x in g['items'] if x.get('disk') == disk), None)
        return (u or {}).get('list')

    def link(self, url):
        s = url.toString()
        if s.startswith('tasks:'):
            self.win.open_page('Задания')
        elif s.startswith('list:'):
            path = self.list_path(s[5:])
            if path and os.path.exists(path):
                os.startfile(path)
            else:
                QMessageBox.information(self, TITLE, 'Файл списка не найден — пересоберите базу.')


# ---------- Задания ----------

class TasksPage(QWidget):
    HEAD = ['Задание', 'Вид', 'Состояние', 'Обработано', 'Ошибок и пропусков']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows = win, []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('<b>Задания</b> - папки в «Запускаемые скрипты». Копирование и перемещение идут в '
                             'своём окне: там спросят «да», остановка - клавиша Q.'))
        self.t = table(self.HEAD)
        lay.addWidget(self.t)
        bar = QHBoxLayout()
        for text, fn in (('Обновить', self.refresh), ('Запустить…', self.launch), ('Открыть папку', self.open_dir),
                         ('Открыть журнал', self.open_log), ('Сводка для чата', self.to_chat)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def refresh(self):
        self.win.bg.run(sv.tasks, ok=self.render, quiet=True)

    def render(self, rows):
        sel = self.current()
        self.rows = rows
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.t.setItem(i, 0, cell(r['task']))
            self.t.setItem(i, 1, cell(r['kind']))
            self.t.setItem(i, 2, cell(r['state'], color=STATE_COLOR.get(r['state'])))
            self.t.setItem(i, 3, cell(f'{r["done"]} из {r["total"]}', right=True))
            self.t.setItem(i, 4, cell(r['errors'] + r['skipped'], right=True))
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        busy = any(r['state'] == 'идёт' for r in rows)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()

    def current(self):
        i = self.t.currentRow()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def need(self):
        r = self.current()
        if not r:
            QMessageBox.information(self, TITLE, 'Сначала выберите задание в таблице.')
        return r

    def launch(self):
        r = self.need()
        if not r:
            return
        d = hb.TASKS / r['task']
        if r['state'] == 'идёт':
            QMessageBox.information(self, TITLE, 'Это задание уже идёт.')
            return
        how = (Path(d) / 'Как запустить.txt')
        info = how.read_text(encoding='utf-8-sig')[:900] if how.exists() else ''
        ans = QMessageBox.question(self, TITLE, f'Запустить «{r["task"]}»?\n\n{info}\n\nОткроется отдельное окно: проверьте '
                                   'сводку и введите «да». Остановить - клавиша Q, повторный запуск продолжит.')
        if ans != QMessageBox.Yes:
            return
        os.startfile(str(d / 'Запустить.cmd'))
        QTimer.singleShot(3000, self.refresh)
        self.timer.start(5000)

    def open_dir(self):
        r = self.need()
        if r:
            os.startfile(str(hb.TASKS / r['task']))

    def open_log(self):
        r = self.need()
        if r and r['journal']:
            os.startfile(r['journal'])
        elif r:
            QMessageBox.information(self, TITLE, 'Журнала ещё нет: задание не запускалось.')

    def to_chat(self):
        r = self.need()
        if r:
            QGuiApplication.clipboard().setText(
                f'Задание «{r["task"]}» ({r["kind"]}): {r["state"]}; обработано {r["done"]} из {r["total"]}, ошибок '
                f'{r["errors"]}, пропусков {r["skipped"]}. Журнал: {r["journal"] or "нет"}')
            self.win.statusBar().showMessage('Сводка скопирована - вставьте её в чат.', 5000)


# ---------- Диски и папки ----------

class DisksPage(QWidget):
    HEAD = ['Диск', 'Название', 'Сейчас', 'Файлов', 'ГБ', 'Опись', 'Состояние описи', 'Частичных сканов']
    TREE = ['Папка', 'Файлов', 'ГБ', 'фото', 'видео', 'тексты', 'прочие', 'мусор', 'Решение владельца']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.disk, self.found = win, [], None, False   # found - показаны найденные папки
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel('<b>Диски и папки</b>'))
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти папки по словам, например: Сафари')
        self.search.returnPressed.connect(self.find)
        top.addWidget(self.search, 1)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        lay.addLayout(top)
        split = QSplitter(Qt.Vertical)
        self.t = table(self.HEAD, stretch=1)
        self.t.itemSelectionChanged.connect(self.pick)
        split.addWidget(self.t)
        low = QWidget()
        ll = QVBoxLayout(low)
        ll.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.TREE)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)      # несколько папок - с Ctrl
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemSelectionChanged.connect(self.selected)
        ll.addWidget(self.tree)
        self.dates = QLabel('')                 # «Хеши измерены: …» для выбранной папки
        self.dates.setWordWrap(True)
        self.dates.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ll.addWidget(self.dates)
        bar = QHBoxLayout()
        b = QPushButton('Чего из папки нет на 45 и 77?')
        b.clicked.connect(self.presence)
        bar.addWidget(b)
        self.rescan_btn = QPushButton('Пересканировать папку…')
        self.rescan_btn.setToolTip('Подключённый диск: заново прочитать только новые и изменённые файлы выбранных папок '
                                   '(можно выбрать несколько с Ctrl). Сначала - предпросмотр, затем подтверждение.')
        self.rescan_btn.clicked.connect(self.rescan)
        bar.addWidget(self.rescan_btn)
        self.info = QLabel('')
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setWordWrap(True)
        bar.addWidget(self.info, 1)
        ll.addLayout(bar)
        split.addWidget(low)
        split.setSizes([260, 520])
        lay.addWidget(split)

    def refresh(self):
        """При каждом показе раздела и по «Обновить»: носители и какие из них подключены сейчас."""
        self.win.bg.run(sv.disks, ok=self.render)

    def render(self, rows):
        """Подключённые сейчас - первыми (● жирным, зелёным), затем HDD по номеру, флешки в конце.
        Выбор сохраняется; если ничего не выбрано - выбирается первый подключённый и показываются его папки."""
        rows = disk_ui.ordered(rows)
        self.rows = rows
        self.t.blockSignals(True)
        self.t.clearSelection()
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            on = bool(r.get('letter'))
            name = disk_ui.disk_title(r) or '—'
            vals = [f'● {r["disk"]}' if on else r['disk'], name, r['letter'] or '—',
                    f'{r["files"]:,}'.replace(',', ' '), gib(r['gib']), r['scanned'],
                    disk_ui.status_text(r['status']), r['partial'] or '']
            tips = {1: f'{r["disk"]}: {r["label"]}' if r.get('label') else '',
                    6: f'В описи: {r["status"]}' if r.get('status') else ''}
            for j, v in enumerate(vals):
                it = cell(v, right=j in (3, 4, 7))
                it.setData(Qt.UserRole, r['disk'])
                if tips.get(j):
                    it.setToolTip(tips[j])
                if on:
                    disk_ui.style_item(it.setData, True)
                self.t.setItem(i, j, it)
        self.t.blockSignals(False)
        disks = [r['disk'] for r in rows]
        if self.disk in disks:                   # тот же носитель: дерево папок не перестраивать
            self.t.blockSignals(True)
            self.t.setCurrentCell(disks.index(self.disk), 0)
            self.t.blockSignals(False)
        elif not self.found:
            first = next((i for i, r in enumerate(rows) if r.get('letter')), None)
            if first is not None:
                self.t.setCurrentCell(first, 0)  # -> pick(): папки верхнего уровня

    def pick(self):
        i = self.t.currentRow()
        if 0 <= i < len(self.rows):
            self.found = False
            self.disk = self.rows[i]['disk']
            self.tree.clear()
            self.info.setText('')
            root = QTreeWidgetItem([f'{self.disk} (весь диск)'])
            root.setData(0, Qt.UserRole, '')
            self.tree.addTopLevelItem(root)
            self.load(root)
            root.setExpanded(True)

    def load(self, item):
        disk, path = self.disk, item.data(0, Qt.UserRole)

        def fill(rows):
            item.takeChildren()
            for r in rows:
                ch = QTreeWidgetItem([r['name'], f'{r["files"]:,}'.replace(',', ' '), gib(r['gib'])] +
                                     [gib(x) for x in r['types']] + [r['decision']])
                for k in range(1, 8):
                    ch.setTextAlignment(k, Qt.AlignRight | Qt.AlignVCenter)
                ch.setData(0, Qt.UserRole, r['path'])
                ch.addChild(QTreeWidgetItem(['…']))            # раскрывается лениво
                item.addChild(ch)
        item.setData(1, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, disk, path, ok=fill)

    def expand(self, item):
        if not item.data(1, Qt.UserRole):
            self.load(item)

    def presence(self):
        it = self.tree.currentItem()
        if not it or self.disk is None:
            QMessageBox.information(self, TITLE, 'Выберите диск и папку.')
            return
        path = it.data(0, Qt.UserRole) or ''
        self.info.setText('Считаю…')

        def show(r):
            self.info.setText(f'{self.disk}\\{path or "(весь диск)"}: файлов с хешем {r["files"]:,} ({gib(r["gib"])} ГБ). '
                              f'Нет на 45: {gib(r["no45"])} ГБ, нет на 77: {gib(r["no77"])} ГБ, больше нигде: '
                              f'{gib(r["only"])} ГБ. Без хеша (сравнение только по имени и размеру): '
                              f'{r["nohash"]:,}.'.replace(',', ' '))
        self.win.bg.run(sv.folder_presence, self.disk, path, ok=show)

    def selected(self):
        """Выбрана одна папка: «когда измерены хеши» - в фоне; ответ для уже сменившейся папки не показывается."""
        self.info.setText('')
        items = self.tree.selectedItems()
        if self.disk is None or len(items) != 1:
            self.dates.setText('')
            return
        disk, path = self.disk, items[0].data(0, Qt.UserRole) or ''
        self.dates.setText('Когда измерены хеши: считаю…')

        def show(r):
            cur = self.tree.selectedItems()
            if self.disk != disk or len(cur) != 1 or (cur[0].data(0, Qt.UserRole) or '') != path:
                return
            self.dates.setText(r['text'] + ' ' + r['hint'])
        self.win.bg.run(sv.hash_dates, disk, path, ok=show, quiet=True)

    def rescan(self):
        """Пересканировать выбранные папки подключённого диска: окно предпросмотра; скан - только по подтверждению."""
        items = [it for it in self.tree.selectedItems() if it.data(0, Qt.UserRole)]
        if self.disk is None or not items:
            QMessageBox.information(self, TITLE, 'Выберите диск и одну или несколько его папок (с Ctrl). '
                                    'Весь диск целиком - это полное сканирование, его делает сканер дисков.')
            return
        row = next((r for r in self.rows if r['disk'] == self.disk), {})
        if not row.get('letter'):
            QMessageBox.information(self, TITLE, f'{self.disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, self.disk, [it.data(0, Qt.UserRole) for it in items])
        self.win.rescan.show()

    def find(self):
        words = self.search.text().split()
        if not words:
            return

        def show(rows):
            self.tree.clear()
            self.disk, self.found = None, True
            self.t.blockSignals(True)
            self.t.clearSelection()
            self.t.blockSignals(False)
            for r in rows:
                it = QTreeWidgetItem([f'{r["disk"]}\\{r["path"]}', f'{r["files"]:,}'.replace(',', ' '), gib(r['gib'])])
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                self.tree.addTopLevelItem(it)
            self.info.setText(f'Найдено папок: {len(rows)} (вложенные совпадения не показаны).')
        self.win.bg.run(sv.find_folders, words, ok=show)


# ---------- главное окно ----------

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.resize(1250, 800)
        self.bg = Background(self)
        self.updating, self.sig = False, None
        self.pages = [('Обзор', OverviewPage(self)),
                      ('Разбор носителя', __import__('razbor_page').RazborPage(self)),
                      ('Задания', __import__('tasks_page').TasksPage(self)), ('Диски и папки', DisksPage(self)),
                      ('Я сделал в Проводнике', explorer_page.ExplorerPage(self)),
                      ('Команды', commands_page.CommandsPage(self))]
        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
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
        self.nav.setCurrentRow(0)
        self.apply_new()

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

    def show_error(self, text):
        short = text.strip().splitlines()[-1] if text.strip() else 'ошибка'
        QMessageBox.warning(self, TITLE, f'Не получилось: {short}\n\nПодробно - в «_БАЗА\\ответы\\окно - ошибки.log».')

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
            msg = {'update': 'Применены новые модули. ', 'rebuild': 'База собрана заново. '}.get(res, '')
            self.statusBar().showMessage(f'{msg}База собрана {gen}.')
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
