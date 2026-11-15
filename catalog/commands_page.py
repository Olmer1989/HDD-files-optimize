"""Раздел окна «Команды»: любая команда hashbase.py из окна, без командной строки (этап 1, 15.11.2026).

Как устроено:
- Список команд и формы строятся САМИ из описания argparse (hb_cli.commands()): новая команда в catalog\\hb_cmd
  появляется здесь без правки окна. Команда с GUI = False в своём файле в окне не показывается.
- Команда выполняется ОТДЕЛЬНЫМ процессом: python.exe catalog\\hashbase.py <аргументы>, без консольного окна.
  Окно передаёт ему свои корни данных (HB_ROOT, HB_SCAN_ROOTS) и HB_FULL_OUTPUT=1 - весь ответ без сокращения
  до 20 строк. Полный вывод последнего запуска - «_БАЗА\\ответы\\окно - последний вывод.txt».
- Команда с --yes в описании - команда записи: «Выполнить» всегда без --yes (предпросмотр); после успешного
  предпросмотра «Записать» повторяет те же аргументы с --yes после вопроса. Любая правка формы гасит «Записать».
- Сами команды в процессе окна не выполняются: hb_cli нужен только ради описания аргументов.
"""
import contextlib
import datetime as dt
import html
import io
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

import hb_cli                                   # только описание команд (commands()); main/_run не вызываются
from hb_core import api as hb
import service as sv

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
CAT = Path(__file__).resolve().parent
SCRIPT = CAT / 'hashbase.py'
LAST_OUTPUT = 'окно - последний вывод.txt'
SHOW_MAX = 5000                                  # строк на экране; всё целиком - в файле последнего вывода

DISK_DEST = {'disk', 'disk_a', 'disk_b', 'disk2', 'to'}
FOLDER_PAIR = {'folder': 'disk', 'path': 'disk', 'source_folder': 'disk', 'folder_a': 'disk_a', 'folder_b': 'disk_b',
               'path2': 'disk2'}                 # поле папки -> поле диска, по которому строится дерево папок
SUGGEST = {'verdict': ['не нужно', 'пока не трогаем', 'раздел: ']}
LABELS = {'disk': 'Диск', 'disk_a': 'Диск A', 'disk_b': 'Диск B', 'disk2': 'Второй диск', 'to': 'Куда (носители)',
          'folder': 'Папка', 'folder_a': 'Папка A', 'folder_b': 'Папка B', 'path': 'Путь (папка или файл)',
          'path2': 'Второй путь', 'source_folder': 'Папка-источник', 'name': 'Имя задания', 'date': 'Дата',
          'action': 'Действие', 'verdict': 'Решение', 'note': 'Примечание', 'reason': 'Причина исправления',
          'line': 'Номер строки', 'depth': 'Глубина (уровней папок)', 'words': 'Слова (через пробел)',
          'section': 'Раздел', 'as_name': 'Имя источника'}
SKIP = {'help', 'yes'}
PATH_RE = re.compile(r'[A-Za-z]:\\[^\n\t<>"«»|?*]*?\.(?:tsv|txt)(?!\w)')


def python_exe():
    """python.exe рядом с pythonw.exe окна (у pythonw нет вывода); если его нет - тот же интерпретатор."""
    exe = Path(sys.executable)
    if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists():
        return str(exe.with_name('python.exe'))
    return str(exe)


def child_env():
    env = os.environ.copy()
    env.update(hb.child_env())
    env.update(HB_FULL_OUTPUT='1', PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    return env


def visible_commands():
    return [(n, h, p) for n, h, gui, p in hb_cli.commands() if gui]


def is_write(p):
    return any(a.dest == 'yes' for a in p._actions)


def makes_task(p):
    return p.get_default('task_root') == 'scripts'


def supported(act):
    k = type(act).__name__
    if act.dest in SKIP:
        return True
    if k == '_StoreTrueAction':
        return True
    if k == '_AppendAction':
        return act.nargs is None
    return k == '_StoreAction' and act.nargs in (None, '?', '+')


def wrapped(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    return lab


def quote(x):
    return f'"{x}"' if (' ' in x or not x) else x


# ---------- поле формы ----------

class Field:
    """Одно действие argparse -> виджет и аргументы командной строки. Значение по умолчанию не передаётся."""

    def __init__(self, page, act, changed):
        self.page, self.act, self.dest = page, act, act.dest
        self.opt = act.option_strings[-1] if act.option_strings else None
        self.kind = self.pick_kind()
        self.required = (act.required if self.opt else act.nargs not in ('?', '*')) and self.kind != 'check'
        hlp = (act.help or '').replace('%%', '%')
        self.label = hlp if self.kind == 'check' else LABELS.get(self.dest, hlp or self.opt or self.dest)
        self.widget = self.build(changed)
        tip = ' '.join(x for x in (self.opt or '', hlp) if x)
        if tip:
            self.widget.setToolTip(tip)

    def pick_kind(self):
        a, k = self.act, type(self.act).__name__
        if k == '_StoreTrueAction':
            return 'check'
        if k == '_AppendAction':
            return 'folders' if self.dest in FOLDER_PAIR else 'lines'
        if self.dest == 'to' and a.nargs == '+':
            return 'disks'
        if self.dest in DISK_DEST:
            return 'disk'
        if self.dest in FOLDER_PAIR:
            return 'folder'
        if a.choices:
            return 'choice'
        if a.type is int:
            return 'int'
        return 'text'

    def build(self, changed):
        a, k = self.act, self.kind
        if k == 'check':                           # галочка + длинный текст help с переносом строк
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            self.check = QCheckBox()
            self.check.toggled.connect(changed)
            lab = QLabel(html.escape(self.label))
            lab.setWordWrap(True)
            lab.mousePressEvent = lambda e: self.check.toggle()
            lay.addWidget(self.check, 0, Qt.AlignTop)
            lay.addWidget(lab, 1)
            return box
        if k == 'disks':                           # несколько носителей: список с галочками, в несколько колонок
            w = QListWidget()
            w.setFlow(QListWidget.LeftToRight)
            w.setWrapping(True)
            w.setResizeMode(QListWidget.Adjust)
            w.setFixedHeight(96)
            w.itemChanged.connect(changed)
            self.list, self.boxes = w, {}
            self.set_disks(list(a.default or []))
            return w
        if k in ('disk', 'choice') or self.dest in SUGGEST:
            w = QComboBox()
            w.setEditable(k != 'choice')
            items = list(a.choices or []) if k == 'choice' else list(SUGGEST.get(self.dest, []))
            items = [''] + items                   # пусто - владелец выбирает сам
            w.addItems(items)
            w.currentTextChanged.connect(changed)
            self.combo = w
            if k == 'disk':
                w.setMinimumWidth(140)
            return w
        if k == 'int':
            w = QSpinBox()
            w.setRange(0 if a.default is None else min(1, a.default), 1_000_000)
            if a.default is None:
                w.setSpecialValueText(' ')         # 0 = пусто
            else:
                w.setValue(a.default)
            w.valueChanged.connect(changed)
            return w
        if k in ('folders', 'lines'):
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            self.edit = QPlainTextEdit()
            self.edit.setPlaceholderText('по одной в строке; можно оставить пустым')
            self.edit.setFixedHeight(70)
            self.edit.textChanged.connect(changed)
            lay.addWidget(self.edit, 1)
            if k == 'folders':
                b = QPushButton('Выбрать…')
                b.clicked.connect(self.choose)
                lay.addWidget(b, 0, Qt.AlignTop)
            return box
        self.line = QLineEdit()
        self.line.textChanged.connect(changed)
        if self.dest == 'date':
            self.line.setText(dt.date.today().strftime('%d.%m.%Y'))
        elif isinstance(a.default, str):
            self.line.setText(a.default)
        if k != 'folder':
            return self.line
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.line, 1)
        b = QPushButton('Выбрать…')
        b.clicked.connect(self.choose)
        lay.addWidget(b)
        self.line.setPlaceholderText('путь от корня диска' + ('' if self.required else '; пусто - весь диск'))
        return box

    # --- носители из базы ---
    def set_disks(self, disks):
        if self.kind == 'disk':
            cur = self.combo.currentText()
            self.combo.blockSignals(True)
            self.combo.clear()
            self.combo.addItems([''] + disks)
            self.combo.setCurrentText(cur)
            self.combo.blockSignals(False)
        elif self.kind == 'disks':
            checked = set(self.text()) if self.boxes else set(self.act.default or [])
            self.list.blockSignals(True)
            self.list.clear()
            self.boxes = {}
            for d in sorted(set(disks) | checked):
                it = QListWidgetItem(d)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if d in checked else Qt.Unchecked)
                self.list.addItem(it)
                self.boxes[d] = it
            self.list.blockSignals(False)

    # --- значение ---
    def text(self):
        k = self.kind
        if k == 'check':
            return self.check.isChecked()
        if k == 'disks':
            return [d for d, it in self.boxes.items() if it.checkState() == Qt.Checked]
        if k in ('disk', 'choice') or self.dest in SUGGEST:
            return self.combo.currentText().strip()
        if k == 'int':
            v = self.widget.value()
            return '' if (v == 0 and self.act.default is None) else str(v)
        if k in ('folders', 'lines'):
            return [x.strip() for x in self.edit.toPlainText().splitlines() if x.strip()]
        return self.line.text().strip()

    def empty(self):
        v = self.text()
        return not v

    def tokens(self):
        """Аргументы командной строки; значение, равное значению по умолчанию, не передаётся."""
        v, a = self.text(), self.act
        if self.kind == 'check':
            return [self.opt] if v else []
        if self.kind == 'disks':
            return [] if (not v or v == list(a.default or [])) else [self.opt] + v
        if self.kind in ('folders', 'lines'):
            return [f'{self.opt}={x}' for x in v]
        if not v:
            return []
        if self.opt:
            if self.kind == 'int' and a.default is not None and str(a.default) == v:
                return []
            if a.nargs == '+':
                return [self.opt] + v.split()
            return [f'{self.opt}={v}']
        return v.split() if a.nargs == '+' else [v]

    def choose(self):
        disk_field = self.page.fields.get(FOLDER_PAIR.get(self.dest, 'disk'))
        disk = disk_field.text() if disk_field else ''
        if not disk:
            QMessageBox.information(self.page.win, TITLE, 'Сначала выберите диск.')
            return
        dlg = FolderDialog(self.page.win, disk)
        if dlg.exec() == QDialog.Accepted and dlg.chosen is not None:
            if self.kind == 'folders':
                self.edit.appendPlainText(dlg.chosen)
            else:
                self.line.setText(dlg.chosen)


class FolderDialog(QDialog):
    """Дерево папок диска по базе (диск не читается); подпапки подгружаются при раскрытии."""

    def __init__(self, win, disk):
        super().__init__(win)
        self.win, self.disk, self.chosen = win, disk, None
        self.setWindowTitle(f'Папка на {disk}')
        self.resize(700, 520)
        lay = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Папка', 'Файлов', 'ГБ'])
        self.tree.setColumnWidth(0, 460)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemDoubleClicked.connect(lambda *_: self.accept())
        lay.addWidget(self.tree)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Выбрать')
        bb.button(QDialogButtonBox.Cancel).setText('Отмена')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        root = QTreeWidgetItem([f'{disk} (весь диск)'])
        root.setData(0, Qt.UserRole, '')
        self.tree.addTopLevelItem(root)
        self.load(root)
        root.setExpanded(True)

    def load(self, item):
        def fill(rows):
            item.takeChildren()
            for r in rows:
                ch = QTreeWidgetItem([r['name'], f'{r["files"]:,}'.replace(',', ' '), f'{r["gib"]:.1f}'])
                ch.setData(0, Qt.UserRole, r['path'])
                ch.addChild(QTreeWidgetItem(['…']))
                item.addChild(ch)
        item.setData(1, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, self.disk, item.data(0, Qt.UserRole), ok=fill)

    def expand(self, item):
        if not item.data(1, Qt.UserRole):
            self.load(item)

    def accept(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, Qt.UserRole) is not None:
            self.chosen = it.data(0, Qt.UserRole)
        super().accept()


# ---------- форма одной команды ----------

class CommandForm(QWidget):
    def __init__(self, page, name, hlp, parser):
        super().__init__()
        self.page, self.name, self.parser = page, name, parser
        self.write, self.task = is_write(parser), makes_task(parser)
        self.fields = {}
        lay = QVBoxLayout(self)
        lay.addWidget(wrapped(f'<b>{html.escape(hlp[:1].upper() + hlp[1:])}</b>'))
        note = f'<span style="color:gray">py catalog\\hashbase.py {name}</span>'
        if self.write:
            note += ('<br><span style="color:#e65100">Команда записи: «Выполнить» показывает предпросмотр и ничего '
                     'не пишет; записать - кнопкой «Записать».</span>')
        lay.addWidget(wrapped(note))
        self.unsupported = [a.dest for a in parser._actions if not supported(a)]
        if self.unsupported:
            lay.addWidget(QLabel('Эту команду окно пока не умеет заполнять - запустите её из командной строки.'))
            lay.addStretch()
            return
        form = QFormLayout()
        for a in parser._actions:
            if a.dest in SKIP:
                continue
            f = Field(self, a, page.form_changed)
            self.fields[a.dest] = f
            if f.kind == 'check':
                form.addRow('', f.widget)
            else:
                form.addRow(f.label + (' *' if f.required else '') + ':', f.widget)
        lay.addLayout(form)
        if not self.fields:
            lay.addWidget(QLabel('Параметров нет.'))
        lay.addStretch()

    @property
    def win(self):
        return self.page.win

    def set_disks(self, disks):
        for f in self.fields.values():
            if f.kind in ('disk', 'disks'):
                f.set_disks(disks)

    def argv(self):
        """(аргументы, None) или (None, что не так) - по-русски, до запуска."""
        if self.unsupported:
            return None, 'Эту команду окно пока не умеет заполнять.'
        miss = [f.label for f in self.fields.values() if f.required and f.empty()]
        if miss:
            return None, 'Заполните: ' + ', '.join(f'«{x}»' for x in miss) + '.'
        pos = [f for f in self.fields.values() if not f.opt]
        for i, f in enumerate(pos):
            if f.empty() and any(not g.empty() for g in pos[i + 1:]):
                return None, f'Заполните «{f.label}» или очистите поля после него.'
        if 'to' in self.fields and self.fields['to'].kind == 'disks' and not self.fields['to'].text():
            return None, 'Отметьте хотя бы один носитель в «Куда».'
        args = [self.name]
        for f in pos:
            args += f.tokens()
        for f in self.fields.values():
            if f.opt:
                args += f.tokens()
        err = check_argv(self.parser, args[1:])
        if err:
            return None, 'Команда не принимает такие аргументы: ' + err
        return args, None

    def value(self, dest):
        f = self.fields.get(dest)
        return f.text() if f else None


def check_argv(parser, argv):
    """Проверка тем же разбором, что у командной строки; ничего не выполняет."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            parser.parse_args(argv)
    except SystemExit:
        lines = err.getvalue().strip().splitlines()
        return lines[-1] if lines else 'ошибка разбора'
    return None


# ---------- запуск отдельным процессом ----------

class Run:
    """Один подпроцесс hashbase.py; строки вывода копятся в очереди, окно забирает их по таймеру."""

    def __init__(self, args):
        self.args, self.q, self.code = args, queue.Queue(), None
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.proc = subprocess.Popen([python_exe(), '-X', 'utf8', '-u', str(SCRIPT), *args], cwd=str(CAT.parent),
                                     env=child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                                     creationflags=flags)
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            for line in self.proc.stdout:
                self.q.put(line.rstrip('\r\n'))
        finally:
            self.proc.stdout.close()
            self.code = self.proc.wait()
            self.q.put(None)                     # конец

    def stop(self):
        try:
            self.proc.kill()
        except OSError:
            pass


class CommandsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.forms, self.disks = win, {}, []
        self.run, self.lines, self.links, self.preview = None, [], [], None
        self.protected = self.yes = False
        self.cmds = visible_commands()
        lay = QHBoxLayout(self)
        self.list = QListWidget()
        self.list.setFixedWidth(330)
        self.list.setWordWrap(True)
        for name, hlp, _ in self.cmds:
            it = QListWidgetItem(hlp[:1].upper() + hlp[1:])
            it.setData(Qt.UserRole, name)
            it.setToolTip(f'py catalog\\hashbase.py {name}')
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self.pick)
        lay.addWidget(self.list)
        right = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.stack)
        tl.addWidget(scroll, 1)
        bar = QHBoxLayout()
        self.btn_run = QPushButton('Выполнить')
        self.btn_write = QPushButton('Записать')
        self.btn_stop = QPushButton('Остановить')
        self.btn_copy = QPushButton('Копировать вывод')
        for b, fn in ((self.btn_run, self.execute), (self.btn_write, self.write), (self.btn_stop, self.stop),
                      (self.btn_copy, self.copy)):
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.state = QLabel('')
        bar.addWidget(self.state, 1)
        tl.addLayout(bar)
        right.addWidget(top)
        self.out = QTextBrowser()
        self.out.setOpenLinks(False)
        self.out.anchorClicked.connect(self.link)
        right.addWidget(self.out)
        right.setSizes([470, 330])
        lay.addWidget(right, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain)
        self.list.setCurrentRow(0)

    # --- форма ---
    def form(self, name=None):
        name = name or self.current
        if name not in self.forms:
            n, h, p = next(c for c in self.cmds if c[0] == name)
            self.forms[name] = CommandForm(self, n, h, p)
            self.forms[name].set_disks(self.disks)
            self.stack.addWidget(self.forms[name])
        return self.forms[name]

    @property
    def fields(self):
        return self.form().fields

    def pick(self, i):
        if not 0 <= i < len(self.cmds):
            return
        self.current = self.cmds[i][0]
        self.stack.setCurrentWidget(self.form())
        self.form_changed()

    def select(self, name):
        self.list.setCurrentRow([c[0] for c in self.cmds].index(name))
        return self.form()

    def form_changed(self, *_):
        self.preview = None                      # предпросмотр больше не соответствует форме
        if getattr(self, 'current', None) in self.forms:      # во время постройки формы - ещё нечего показывать
            self.buttons()

    def buttons(self):
        busy = self.run is not None
        f = self.form()
        self.btn_run.setEnabled(not busy)
        self.btn_write.setVisible(f.write)
        self.btn_write.setEnabled(not busy and self.preview is not None and self.preview[0] == self.current)
        self.btn_stop.setEnabled(busy and not self.protected)

    def refresh(self):
        self.win.bg.run(sv.disks, ok=self.got_disks, quiet=True)

    def got_disks(self, rows):
        self.disks = [r['disk'] for r in rows]
        for f in self.forms.values():
            f.set_disks(self.disks)

    # --- запуск ---
    def execute(self):
        args, err = self.form().argv()
        if err:
            QMessageBox.information(self, TITLE, err)
            return
        self.start(args)

    def write(self):
        if not self.preview or self.preview[0] != self.current:
            return
        args = self.preview[1]
        self.preview = None                      # повторное нажатие ничего не запишет
        self.buttons()
        shown = ' '.join(quote(x) for x in args)
        if QMessageBox.question(self, TITLE, f'Записать в таблицу владельца?\n\n{shown}\n\nКопия таблицы до записи '
                                'сохранится в «_БАЗА\\архив таблиц».') != QMessageBox.Yes:
            return
        self.start(args + ['--yes'])

    def start(self, args):
        f = self.form()
        self.yes = '--yes' in args
        self.task_dir = None
        if f.task and '--dry' not in args and f.value('name'):
            d = hb.TASKS / f.value('name')
            self.task_dir = None if d.exists() else d     # только задание, созданное именно этим запуском
        self.protected = self.yes or (f.task and '--dry' not in args)
        self.cmd, self.lines, self.links = self.current, [], []
        self.out.clear()
        self.add(['> hashbase.py ' + ' '.join(quote(x) for x in args)], gray=True)
        try:
            self.run = Run(args)
        except OSError as e:
            self.run = None
            self.fail(f'Не удалось запустить команду: {e}')
            return
        self.state.setText('<span style="color:#1565c0">Выполняется…</span>')
        self.buttons()
        self.timer.start(100)

    def stop(self):
        if self.run and not self.protected and QMessageBox.question(self, TITLE, 'Остановить команду?') == QMessageBox.Yes:
            self.run.stop()

    def can_close(self):
        if self.run is None:
            return True
        if self.protected:
            QMessageBox.information(self, TITLE, 'Идёт запись или создание задания - дождитесь окончания.')
            return False
        if QMessageBox.question(self, TITLE, 'Команда ещё выполняется. Остановить её и закрыть окно?') != QMessageBox.Yes:
            return False
        self.run.stop()
        return True

    def drain(self):
        if not self.run:
            return
        batch, done = [], False
        while True:
            try:
                x = self.run.q.get_nowait()
            except queue.Empty:
                break
            if x is None:
                done = True
                break
            batch.append(x)
        if batch:
            self.add(batch)
        if done:
            self.finish(self.run.code)

    def add(self, lines, gray=False, color=None):
        start = len(self.lines)
        self.lines += lines
        show = lines[:max(0, SHOW_MAX - start)]
        if show:
            col = color or ('gray' if gray else None)
            body = '<br>'.join(self.linkify(x) for x in show)
            self.out.append(f'<span style="color:{col}">{body}</span>' if col else body)
        if start < SHOW_MAX <= len(self.lines):
            self.out.append(f'<i>… дальше не показано - весь вывод в «{LAST_OUTPUT}» (ссылка внизу)</i>')

    def linkify(self, line):
        res, pos = [], 0
        for m in PATH_RE.finditer(line):
            res.append(html.escape(line[pos:m.start()]))
            self.links.append(m.group(0))
            res.append(f'<a href="f{len(self.links) - 1}">{html.escape(m.group(0))}</a>')
            pos = m.end()
        res.append(html.escape(line[pos:]))
        return ''.join(res).replace('  ', '&nbsp; ')

    def finish(self, code):
        self.timer.stop()
        run, self.run = self.run, None
        saved = hb.ANSWERS / LAST_OUTPUT
        try:
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text('\n'.join(self.lines) + '\n', encoding='utf-8-sig')
            tail = [f'Весь вывод: {saved}']
        except OSError:
            tail = []
        if code == 0:
            self.state.setText('<span style="color:#2e7d32">Готово.</span>')
            self.add(tail, gray=True)
        else:
            self.state.setText(f'<b style="color:#c62828">Ошибка: код выхода {code}.</b>')
            self.add([f'Команда завершилась с ошибкой (код выхода {code}).'] + tail, color='#c62828')
        if code == 0 and self.form(self.cmd).write and not self.yes:
            self.preview = (self.cmd, run.args)
            self.add(['Это предпросмотр. Если всё верно - нажмите «Записать».'], color='#e65100')
        self.buttons()
        if code == 0 and self.yes:
            self.win.statusBar().showMessage('Записано. Применяю к базе…', 5000)
            self.win.apply_new()
        if code == 0 and self.task_dir is not None and self.task_dir.exists():
            if QMessageBox.question(self, TITLE, f'Создано задание «{self.task_dir.name}». Перейти в «Задания»?') == QMessageBox.Yes:
                self.win.open_page('Задания')

    def fail(self, text):
        self.state.setText(f'<b style="color:#c62828">{html.escape(text)}</b>')
        self.buttons()

    # --- вывод ---
    def link(self, url):
        s = url.toString()
        if not s.startswith('f'):
            return
        path = Path(self.links[int(s[1:])])
        menu = QMenu(self)
        a_file = menu.addAction('Открыть файл')
        a_dir = menu.addAction('Открыть папку')
        a_copy = menu.addAction('Копировать путь')
        act = menu.exec(QCursor.pos())
        try:
            if act is a_file:
                os.startfile(str(path))
            elif act is a_dir:
                subprocess.Popen(['explorer', '/select,', str(path)])
            elif act is a_copy:
                QGuiApplication.clipboard().setText(str(path))
        except OSError as e:
            QMessageBox.information(self, TITLE, f'Не открылось: {e}')

    def copy(self):
        QGuiApplication.clipboard().setText('\n'.join(self.lines))
        self.win.statusBar().showMessage('Вывод скопирован - вставьте его в чат.', 5000)
