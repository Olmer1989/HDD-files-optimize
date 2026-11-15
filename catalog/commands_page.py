"""Раздел окна «Команды»: любая команда hashbase.py из окна, без командной строки (этап 1, 15.11.2026).

Как устроено:
- Список команд и формы строятся САМИ из описания argparse (hb_cli.commands()): новая команда в catalog\\hb_cmd
  появляется здесь без правки окна. Команда с GUI = False в своём файле в окне не показывается.
- Понятные тексты окна - необязательные атрибуты в файле команды (командная строка их не использует):
    GUI_GROUP  - группа в списке слева (порядок групп - GROUPS ниже; без группы - «Другое»);
    GUI_ORDER  - место внутри группы (число);
    GUI_TITLE  - заголовок (вопрос или действие словами владельца); без него - HELP;
    GUI_HINT   - 2-4 строки: что делает, что значит ответ, что выбрать в полях (строки через \\n);
    GUI_ARGS   - имя аргумента (dest) -> подпись поля или (подпись, подсказка в пустом поле);
    GUI_PAIRS  - поле папки -> заголовок блока «диск + папка» одной строкой (или (заголовок, пояснение));
    GUI_NOTES  - имя аргумента -> серое пояснение под подписью поля;
    GUI_MAKES_TASK - True: вместо галочки --dry две кнопки «Посчитать» (--dry) и «Создать задание»;
    GUI_TASK_NAME  - имя задания по полям, например '{disk} → {to}, {date}' (пока владелец не исправит сам);
    GUI_FIELD_ORDER - порядок строк формы (имена аргументов); позиционные аргументы всё равно идут по argparse;
    GUI_EXTRA  - галочки только окна (в командную строку не идут): имя -> подпись; что они делают - решает окно
                 (move_after: после создания задания положить в него пометку sv.mark_task_move);
    GUI_MODES  - режимы формы: [{title, hint, fields, advanced, set, defaults, required, labels}] - окно показывает
                 выбор режима, его описание и только поля режима (set - значения, которые режим задаёт сам).
  У команды с несколькими именами (NAMES) любой из них может быть dict имя команды -> значение.
  Пары «диск + папка» находятся по именам аргументов (FOLDER_PAIR); две и больше пар в форме - блоками сами.
- Команда выполняется ОТДЕЛЬНЫМ процессом: python.exe catalog\\hashbase.py <аргументы>, без консольного окна.
  Окно передаёт ему свои корни данных (HB_ROOT, HB_SCAN_ROOTS) и HB_FULL_OUTPUT=1 - весь ответ без сокращения
  до 20 строк. Полный вывод последнего запуска - «_БАЗА\\ответы\\окно - последний вывод.txt».
- Команда с --yes в описании - команда записи: «Выполнить» всегда без --yes (предпросмотр); после успешного
  предпросмотра «Записать» повторяет те же аргументы с --yes после вопроса. Любая правка формы гасит «Записать».
- Сами команды в процессе окна не выполняются: hb_cli нужен только ради описания аргументов, а файл команды -
  только ради атрибутов GUI_* (читаются, ничего не вызывается).
"""
import argparse
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
from disk_ui import (ON_COLOR, OFF_COLOR, SIZE_RE, as_row, disk_key, disk_text, disk_title,  # noqa: F401
                     split_disks, style_item)   # общее с разделом «Диски и папки»

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import (QSizePolicy, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

TITLE = 'Архив дисков'
CAT = Path(__file__).resolve().parent
SCRIPT = CAT / 'hashbase.py'
LAST_OUTPUT = 'окно - последний вывод.txt'
SHOW_MAX = 5000                                  # строк на экране; всё целиком - в файле последнего вывода

GROUPS = ('Вопросы о диске', 'Подготовить задание', 'Записать (сначала предпросмотр)', 'Обслуживание')
OTHER = 'Другое'                                 # команды без GUI_GROUP - в конце списка
DISK_DEST = {'disk', 'disk_a', 'disk_b', 'disk2', 'to'}
FOLDER_PAIR = {'folder': 'disk', 'path': 'disk', 'source_folder': 'disk', 'folder_a': 'disk_a', 'folder_b': 'disk_b',
               'path2': 'disk2'}                 # поле папки -> поле диска, по которому строится дерево папок
SUGGEST = {'verdict': ['не нужно', 'пока не трогаем', 'раздел: ']}
SECTION_DEST = {'section'}                       # раздел - выбор из решений владельца по выбранному диску
LABELS = {'disk': 'Диск', 'disk_a': 'Диск A', 'disk_b': 'Диск B', 'disk2': 'Второй диск', 'to': 'Куда (носители)',
          'folder': 'Папка', 'folder_a': 'Папка A', 'folder_b': 'Папка B', 'path': 'Путь (папка или файл)',
          'path2': 'Второй путь', 'source_folder': 'Папка-источник', 'name': 'Имя задания', 'date': 'Дата',
          'action': 'Действие', 'verdict': 'Решение', 'note': 'Примечание', 'reason': 'Причина исправления',
          'line': 'Номер строки', 'depth': 'Сколько уровней папок показать', 'words': 'Слова (через пробел)',
          'section': 'Раздел', 'as_name': 'Имя источника'}   # запасные подписи, если в команде нет GUI_ARGS
SKIP = {'help', 'yes'}
PATH_RE = re.compile(r'[A-Za-z]:\\[^\n\t<>"«»|?*]*?\.(?:tsv|txt)(?!\w)')
FOLDER_HINT = 'например: Фото\\2014 — или нажмите «Выбрать…»'
CHOOSE_DISK = '— выберите носитель —'
ALL_DISKS = 'Все носители'
DEPTHS = [(1, '1 — только папки первого уровня'), (2, '2 — и их подпапки'), (3, '3 уровня'), (4, '4 уровня'),
          (5, '5 уровней'), (6, '6 уровней'), (7, '7 уровней'), (0, 'Все уровни вложенности')]   # 0 - все уровни


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


# ---------- тексты окна из файлов команд ----------

def command_module(p):
    """Модуль команды, загруженный hb_cli.commands(); только чтобы прочитать атрибуты GUI_*."""
    fn = p.get_default('_run')
    return sys.modules.get(getattr(fn, '__module__', '') or '')


def for_name(mod, attr, name, default=None):
    v = getattr(mod, attr, None) if mod is not None else None
    names = set(getattr(mod, 'NAMES', ()) or ())
    if isinstance(v, dict) and v and set(v) <= names:          # значение по именам команды
        v = v.get(name)
    return default if v is None else v


def gui_meta(name, hlp, p):
    """Что окно показывает о команде: заголовок, пояснение, группа, место, подписи полей, блоки «диск + папка»."""
    mod = command_module(p)
    first = (hlp or name)[:1].upper() + (hlp or name)[1:]
    group = for_name(mod, 'GUI_GROUP', name) or OTHER
    order = for_name(mod, 'GUI_ORDER', name, 999)
    return dict(title=for_name(mod, 'GUI_TITLE', name) or first, hint=for_name(mod, 'GUI_HINT', name, ''),
                group=group, order=order if isinstance(order, (int, float)) else 999,
                args=dict(for_name(mod, 'GUI_ARGS', name, {}) or {}),
                pairs=dict(for_name(mod, 'GUI_PAIRS', name, {}) or {}), modes=list(for_name(mod, 'GUI_MODES', name, []) or []),
                notes=dict(for_name(mod, 'GUI_NOTES', name, {}) or {}),
                makes_task=bool(for_name(mod, 'GUI_MAKES_TASK', name, False)),
                task_name=for_name(mod, 'GUI_TASK_NAME', name, ''),
                extra=dict(for_name(mod, 'GUI_EXTRA', name, {}) or {}),
                field_order=list(for_name(mod, 'GUI_FIELD_ORDER', name, []) or []),
                own=mod is not None and hasattr(mod, 'GUI_TITLE'))


def group_index(g):
    return GROUPS.index(g) if g in GROUPS else (len(GROUPS) + (1 if g == OTHER else 0))


def visible_commands():
    """[(имя, HELP, подпарсер)] для окна - по группам и порядку из GUI_GROUP / GUI_ORDER."""
    res = [(n, h, p, gui_meta(n, h, p)) for n, h, gui, p in hb_cli.commands() if gui]
    res.sort(key=lambda x: (group_index(x[3]['group']), x[3]['group'], x[3]['order'], x[0]))
    return [(n, h, p) for n, h, p, _ in res]


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


def split_long(text, width=95):
    """HTML-текст с переносами по словам каждые ~width знаков."""
    lines, cur = [], ''
    for w in text.split(' '):
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f'{cur} {w}' if cur else w
    lines.append(cur)
    return '<br>'.join(html.escape(x) for x in lines)


def gray(text, small=True):
    size = 'font-size:small;' if small else ''
    return f'<span style="color:gray;{size}">{html.escape(text)}</span>'


# ---------- носители: подключённые сверху ----------

class DiskCombo(QComboBox):
    """Выбор одного носителя: подключённые сверху (●, жирным), разделитель, отключённые серым.
    Значение - номер носителя (itemData); setCurrentText('HDD17') выбирает его по номеру."""

    def __init__(self, optional, empty=ALL_DISKS):
        super().__init__()
        self.optional, self.empty = optional, empty
        self.setPlaceholderText(CHOOSE_DISK)
        self.setMinimumWidth(260)
        self.setMaxVisibleItems(25)
        self.fill([])

    def fill(self, rows):
        cur = self.value()
        self.blockSignals(True)
        self.clear()
        if self.optional:
            self.addItem(self.empty, '')
        on, off = split_disks(rows)
        for r in on:
            self.addItem(disk_text(r), r['disk'])
            style_item(lambda role, v, i=self.count() - 1: self.setItemData(i, v, role), True)
        if on and off:
            self.insertSeparator(self.count())
        for r in off:
            self.addItem(disk_text(r), r['disk'])
            style_item(lambda role, v, i=self.count() - 1: self.setItemData(i, v, role), False)
        self.setCurrentText(cur)
        self.blockSignals(False)

    def value(self):
        if self.currentIndex() < 0:
            return ''
        return self.currentData() or ''

    def setCurrentText(self, text):              # noqa: N802 - как у QComboBox, но по номеру носителя
        v = (text or '').strip()
        if v.startswith('● '):
            v = v[2:]
        v = v.split(' — ')[0].strip()
        i = self.findData(v) if v else -1
        if v and i < 0:                          # носителя нет в списке (новый) - всё равно можно выбрать
            self.addItem(v, v)
            i = self.count() - 1
        self.setCurrentIndex(i if i >= 0 else (0 if self.optional else -1))


class DepthCombo(QComboBox):
    """Сколько уровней папок показать: 1…7 или все (0)."""

    def __init__(self, default):
        super().__init__()
        for v, t in DEPTHS:
            self.addItem(t, v)
        self.setValue(default if default is not None else 1)

    def value(self):
        return self.currentData()

    def setValue(self, v):                       # noqa: N802 - как у QSpinBox
        i = self.findData(v)
        if i < 0:
            self.addItem(f'{v} уровней', v)
            i = self.count() - 1
        self.setCurrentIndex(i)


# ---------- поле формы ----------

class Field:
    """Одно действие argparse -> виджет и аргументы командной строки. Значение по умолчанию не передаётся."""

    def __init__(self, page, act, changed, spec=None):
        self.page, self.act, self.dest = page, act, act.dest
        self.opt = act.option_strings[-1] if act.option_strings else None
        self.kind = self.pick_kind()
        self.required = (act.required if self.opt else act.nargs not in ('?', '*')) and self.kind != 'check'
        hlp = (act.help or '').replace('%%', '%')
        label, self.placeholder = (spec if isinstance(spec, (tuple, list)) else (spec, None)) if spec else (None, None)
        self.label = label or (hlp if self.kind == 'check' else LABELS.get(self.dest, hlp or self.opt or self.dest))
        self.pick_disk = False                   # «Выбрать…» выбирает и диск (CommandForm решает по парам)
        self.base_label, self.base_required, self.active, self.extra = self.label, self.required, True, False
        self.widget = self.build(changed)
        tip = ' '.join(x for x in (self.opt or '', hlp) if x)
        if tip:
            self.widget.setToolTip('Командная строка: ' + tip)

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
        if self.dest in SECTION_DEST:
            return 'section'
        if a.type is int:
            return 'int'
        return 'text'

    def build(self, changed):
        a, k = self.act, self.kind
        if k == 'check':                           # галочка + длинный текст с переносом строк
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            self.check = QCheckBox()
            self.check.toggled.connect(changed)
            lab = QLabel(split_long(self.label))  # перенос - вручную: перенос QLabel в форме ломает высоту строки
            lab.mousePressEvent = lambda e: self.check.toggle()
            lay.addWidget(self.check, 0, Qt.AlignTop)
            lay.addWidget(lab, 1, Qt.AlignTop)
            return box
        if k == 'disks':                           # несколько носителей: основные и подключённые, остальные - по кнопке
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            self.list = QListWidget()
            self.list.itemChanged.connect(changed)
            self.list.setUniformItemSizes(True)
            self.more = QPushButton()
            self.more.setFlat(True)
            self.more.setStyleSheet('QPushButton { color: #1565c0; text-align: left; padding: 0; }')
            self.more.setCursor(Qt.PointingHandCursor)
            self.more.clicked.connect(self.toggle_all)
            self.show_all, self.boxes, self.rows = False, {}, []
            lay.addWidget(self.list)
            lay.addWidget(self.more, 0, Qt.AlignLeft)
            self.set_disks([])
            return box
        if k == 'disk':
            self.combo = DiskCombo(optional=not self.required)     # у диска пары CommandForm сменит «Все носители»
            self.combo.currentIndexChanged.connect(changed)
            return self.combo
        if k == 'choice' or self.dest in SUGGEST:
            w = QComboBox()
            w.setEditable(k != 'choice')
            items = list(a.choices or []) if k == 'choice' else list(SUGGEST.get(self.dest, []))
            items = [''] + items                   # пусто - владелец выбирает сам
            w.addItems(items)
            w.currentTextChanged.connect(changed)
            if k != 'choice' and self.placeholder:
                w.lineEdit().setPlaceholderText(self.placeholder)
            self.combo = w
            return w
        if k == 'section':                         # свой текст или раздел из решений по диску
            w = QComboBox()
            w.setEditable(True)
            w.setMinimumWidth(320)
            self.combo, self.line = w, w.lineEdit()
            self.line.setPlaceholderText('выберите раздел из ваших решений по этому диску')
            w.currentTextChanged.connect(changed)
            return w
        if k == 'int':
            if self.dest == 'depth':               # уровни папок - выбором из списка, «все» = 0
                w = DepthCombo(a.default)
                w.setMaximumWidth(340)
                w.currentIndexChanged.connect(changed)
                return w
            w = QSpinBox()
            w.setRange(0 if a.default is None else min(1, a.default), 1_000_000)
            if a.default is None:
                w.setSpecialValueText(' ')         # 0 = пусто
            else:
                w.setValue(a.default)
            w.setMaximumWidth(140)
            w.valueChanged.connect(changed)
            return w
        if k in ('folders', 'lines'):
            box = QWidget()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            self.edit = QPlainTextEdit()
            self.edit.setPlaceholderText(self.placeholder or ('по одной в строке, можно «Выбрать…»; пусто — весь диск'
                                                              if k == 'folders' else 'по одной в строке'))
            self.edit.textChanged.connect(changed)
            self.edit.textChanged.connect(self.fit_edit)
            self.fit_edit()
            lay.addWidget(self.edit, 1)
            if k == 'folders':
                b = QPushButton('Выбрать…')
                b.clicked.connect(self.choose)
                lay.addWidget(b, 0, Qt.AlignTop)
            return box
        self.line = QLineEdit()
        self.line.textChanged.connect(changed)
        if self.placeholder:
            self.line.setPlaceholderText(self.placeholder)
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
        self.line.setPlaceholderText(self.placeholder or FOLDER_HINT)
        return box

    # --- носители из базы ---
    def set_disks(self, rows):
        if self.kind == 'disk':
            self.combo.fill(rows)
        elif self.kind == 'disks':
            checked = set(self.text()) if self.boxes else set(self.act.default or [])
            self.rows = [as_row(r) for r in rows]
            known = {r['disk'] for r in self.rows}
            extra = [{'disk': d, 'label': '', 'letter': ''} for d in sorted(checked - known)]
            on, off = split_disks(self.rows + extra)
            main = set(self.act.default or [])
            order = (sorted((r for r in on + off if r['disk'] in main), key=lambda r: disk_key(r['disk'])) + [r for r in on if r['disk'] not in main]
                     + [r for r in off if r['disk'] not in main])
            self.list.blockSignals(True)
            self.list.clear()
            self.boxes = {}
            for r in order:
                d = r['disk']
                it = QListWidgetItem(disk_text(r))
                it.setData(Qt.UserRole, d)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if d in checked else Qt.Unchecked)
                style_item(lambda role, v, it=it: it.setData(role, v), bool(r.get('letter')))
                it.setData(Qt.UserRole + 1, d in main or bool(r.get('letter')))      # видно всегда
                self.list.addItem(it)
                self.boxes[d] = it
            self.list.blockSignals(False)
            self.apply_filter()

    def apply_filter(self):
        shown = 0
        for it in self.boxes.values():
            keep = self.show_all or it.data(Qt.UserRole + 1) or it.checkState() == Qt.Checked
            it.setHidden(not keep)
            shown += keep
        hidden = len(self.boxes) - shown
        self.more.setText('▲ показать только основные и подключённые' if self.show_all
                          else f'▼ показать все носители (ещё {hidden})')
        self.more.setVisible(self.show_all or hidden > 0)
        row = self.list.sizeHintForRow(0) if self.boxes else 20
        self.list.setFixedHeight(min(max(shown, 1), 8) * max(row, 18) + 6)

    def fit_edit(self):
        """Поле «по одной в строке»: 2 строки, растёт по мере добавления (до 6)."""
        n = min(max(self.edit.document().blockCount(), 2), 6)
        self.edit.setFixedHeight(self.edit.fontMetrics().lineSpacing() * n + 12)

    def set_checked(self, disks):
        self.list.blockSignals(True)
        for d, it in self.boxes.items():
            it.setCheckState(Qt.Checked if d in disks else Qt.Unchecked)
        self.list.blockSignals(False)
        self.apply_filter()

    def set_sections(self, items):
        cur = self.line.text()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(items)
        self.combo.setEditText(cur)
        self.combo.blockSignals(False)

    def set_label(self, text, required):
        self.label, self.required = text, required
        if self.kind == 'folders' and not self.placeholder:
            self.edit.setPlaceholderText('по одной в строке, можно «Выбрать…»' + ('' if required else '; пусто — весь диск'))
        if getattr(self, 'row_label', None) is not None:
            note = getattr(self, 'note', '')
            if required and note.startswith('можно не указывать'):
                note = ''                          # режим сделал поле обязательным
            self.row_label.setText(CommandForm.label_html(text, required, note))

    def toggle_all(self):
        self.show_all = not self.show_all
        self.apply_filter()

    # --- значение ---
    def text(self):
        k = self.kind
        if k == 'check':
            return self.check.isChecked()
        if k == 'disks':
            return [d for d, it in self.boxes.items() if it.checkState() == Qt.Checked]
        if k == 'disk':
            return self.combo.value()
        if k == 'choice' or self.dest in SUGGEST:
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
        if self.pick_disk and disk_field is not None:          # дерево всех носителей: выбор сразу диска и папки
            dlg = FolderDialog(self.page.win, disk, rows=self.page.page.disks)
            if dlg.exec() == QDialog.Accepted and dlg.chosen is not None:
                disk_field.combo.setCurrentText(dlg.chosen_disk)
                self.line.setText(dlg.chosen)
            return
        if not disk:
            what = f'«{disk_field.label}»' if disk_field else 'диск'
            QMessageBox.information(self.page.win, TITLE, f'Сначала выберите {what} — папки выбираются на этом носителе.')
            return
        dlg = FolderDialog(self.page.win, disk)
        if dlg.exec() == QDialog.Accepted and dlg.chosen is not None:
            if self.kind == 'folders':
                self.edit.appendPlainText(dlg.chosen)
            else:
                self.line.setText(dlg.chosen)


class FolderDialog(QDialog):
    """Дерево папок по базе (диски не читаются); подпапки подгружаются при раскрытии.
    FolderDialog(win, 'HDD17') - папки одного диска; FolderDialog(win, 'HDD17', rows=sv.disks()) - верхний уровень -
    все носители (подключённые сверху), выбор сразу диска и папки: chosen_disk, chosen."""

    def __init__(self, win, disk, rows=None):
        super().__init__(win)
        self.win, self.disk, self.chosen, self.chosen_disk = win, disk, None, disk
        self.many = rows is not None
        self.setWindowTitle('Выберите носитель и папку' if self.many else f'Папка на {disk}')
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        if self.many:
            lay.addWidget(wrapped('Раскройте носитель и выберите папку; чтобы взять весь носитель — выберите его '
                                  'строку. <b style="color:#1b5e20">● Жирным</b> — подключённые сейчас.'))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['Папка', 'Файлов', 'ГБ'])
        self.tree.setColumnWidth(0, 500)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemDoubleClicked.connect(lambda it, col: self.accept() if it.childCount() == 0 or col else None)
        lay.addWidget(self.tree)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText('Выбрать')
        bb.button(QDialogButtonBox.Cancel).setText('Отмена')
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if not self.many:
            root = self.top(disk, f'{disk} (весь диск)')
            self.load(root)
            root.setExpanded(True)
            return
        on, off = split_disks(rows)
        current = None
        for r in on + off:
            it = self.top(r['disk'], disk_text(r))
            it.setText(1, f'{r.get("files") or 0:,}'.replace(',', ' ') if r.get('files') else '')
            it.setText(2, f'{r["gib"]:.0f}' if r.get('gib') else '')
            style_item(lambda role, v, it=it: it.setData(0, role, v), bool(r.get('letter')))
            it.addChild(QTreeWidgetItem(['…']))
            if r['disk'] == disk:
                current = it
        if current is not None:
            self.tree.setCurrentItem(current)
            current.setExpanded(True)
            self.tree.scrollToItem(current, QTreeWidget.PositionAtTop)

    def top(self, disk, text):
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole, '')
        it.setData(2, Qt.UserRole, disk)
        self.tree.addTopLevelItem(it)
        return it

    def disk_of(self, item):
        while item.parent() is not None:
            item = item.parent()
        return item.data(2, Qt.UserRole)

    def load(self, item):
        def fill(rows):
            item.takeChildren()
            for r in rows:
                ch = QTreeWidgetItem([r['name'], f'{r["files"]:,}'.replace(',', ' '), f'{r["gib"]:.1f}'])
                ch.setData(0, Qt.UserRole, r['path'])
                ch.addChild(QTreeWidgetItem(['…']))
                item.addChild(ch)
        item.setData(1, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, self.disk_of(item), item.data(0, Qt.UserRole), ok=fill)

    def expand(self, item):
        if not item.data(1, Qt.UserRole):
            self.load(item)

    def accept(self):
        it = self.tree.currentItem()
        if it is not None and it.data(0, Qt.UserRole) is not None:
            self.chosen, self.chosen_disk = it.data(0, Qt.UserRole), self.disk_of(it)
        super().accept()


# ---------- форма одной команды ----------

class CommandForm(QWidget):
    def __init__(self, page, name, hlp, parser):
        super().__init__()
        self.page, self.name, self.parser = page, name, parser
        self.meta = gui_meta(name, hlp, parser)
        self.write, self.task = is_write(parser), makes_task(parser)
        self.task_buttons = self.task and self.meta['makes_task']      # «Посчитать» / «Создать задание»
        self.fields, self.mode, self.auto_name = {}, None, None
        lay = QVBoxLayout(self)
        head = QLabel(f'<span style="font-size:large"><b>{html.escape(self.meta["title"])}</b></span>')
        head.setWordWrap(True)
        head.setToolTip(f'Командная строка: py catalog\\hashbase.py {name} — {hlp}')
        lay.addWidget(head)
        first = hlp[:1].upper() + hlp[1:]
        hint = self.meta['hint'] or (first if self.meta['title'] != first else '')
        if hint:
            lay.addWidget(wrapped('<br>'.join(html.escape(x) for x in hint.split('\n'))))
        if self.write:
            lay.addWidget(wrapped('<span style="color:#e65100">Сначала «Выполнить» — покажет, что изменится, и ничего '
                                  'не запишет; записать — кнопкой «Записать».</span>'))
        elif self.task_buttons and not self.meta['modes']:
            pass                                   # про «Посчитать» / «Создать задание» сказано в описании команды
        self.unsupported = [a.dest for a in parser._actions if not supported(a)]
        if self.unsupported:
            lay.addWidget(QLabel('Эту команду окно пока не умеет заполнять - запустите её из командной строки.'))
            lay.addWidget(wrapped(gray(f'Командная строка: py catalog\\hashbase.py {name}')))
            lay.addStretch()
            return
        acts = [a for a in parser._actions if a.dest not in SKIP]
        order = list(self.meta['field_order'])     # GUI_FIELD_ORDER - порядок строк формы (иначе как в argparse)
        acts.sort(key=lambda a: order.index(a.dest) if a.dest in order else len(order))
        for a in acts:
            self.fields[a.dest] = Field(self, a, page.form_changed, self.meta['args'].get(a.dest))
        for d, text in self.meta['extra'].items():      # галочки только окна
            act = argparse._StoreTrueAction(option_strings=[], dest=d, help=text)
            acts.append(act)
            self.fields[d] = Field(self, act, page.form_changed)
            self.fields[d].extra = True
        blocks = self.pair_blocks()
        self.form = form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self.row_of = {}                           # dest -> виджет строки формы (чтобы прятать строку)
        modes = self.meta['modes']
        if modes:                                  # выбор режима и его описание
            self.mode_box = QComboBox()
            for m in modes:
                self.mode_box.addItem(m.get('title', '?'))
            self.mode_hint = wrapped('')
            self.mode_hint.setStyleSheet('QLabel { background: #f3f6fa; border: 1px solid #d6dee8; '
                                         'border-radius: 4px; padding: 4px 6px; }')
            self.mode_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            mrow = QHBoxLayout()                   # над формой: в QFormLayout перенос строк считается неверно
            mrow.addWidget(QLabel('<b>Что подготовить:</b>'))
            mrow.addWidget(self.mode_box, 1)
            lay.addLayout(mrow)
            lay.addWidget(self.mode_hint)
        advanced = {d for m in modes for d in m.get('advanced', [])}
        done = set()
        for a in acts:
            f = self.fields[a.dest]
            if a.dest in done or a.dest in advanced:
                continue
            blk = blocks.get(a.dest)
            if blk:                                # диск и папка - одной строкой под общим заголовком
                d, p, title, note = blk
                done |= {d.dest, p.dest}
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(d.widget, 2)
                rl.addWidget(p.widget, 3)
                req = d.required or p.required
                form.addRow(self.label_widget(title, req, note or ('' if req else 'можно не указывать')), row)
                self.row_of[d.dest] = self.row_of[p.dest] = row
                continue
            self.add_field_row(f)
        if advanced:                               # «Дополнительно» - свёрнуто
            self.adv_btn = QPushButton('▶ Дополнительно')
            self.adv_btn.setFlat(True)
            self.adv_btn.setStyleSheet('QPushButton { color: #1565c0; text-align: left; padding: 0; }')
            self.adv_btn.setCursor(Qt.PointingHandCursor)
            self.adv_open = False
            self.adv_btn.clicked.connect(self.toggle_advanced)
            form.addRow('', self.adv_btn)
            for a in acts:
                if a.dest in advanced:
                    self.add_field_row(self.fields[a.dest])
        lay.addLayout(form)
        if not self.fields:
            lay.addWidget(QLabel('Заполнять ничего не нужно — нажмите «Выполнить».'))
        lay.addStretch()
        foot = []
        if any(f.base_required for f in self.fields.values()) or any(m.get('required') for m in modes):
            foot.append('* — обязательно заполнить')
        foot.append(f'Командная строка: py catalog\\hashbase.py {name}')
        lay.addWidget(wrapped(gray('   ·   '.join(foot))))
        if 'section' in self.fields and self.fields['section'].kind == 'section' and 'disk' in self.fields:
            self.fields['disk'].combo.currentIndexChanged.connect(self.fill_sections)
        if self.task_buttons and 'name' in self.fields:
            for f in self.fields.values():
                if f.dest != 'name':
                    self.connect_changed(f, self.update_name)
        if modes:
            self.mode_box.currentIndexChanged.connect(self.apply_mode)
            self.apply_mode(0)
        else:
            self.apply_mode(None)

    # --- построение ---
    def add_field_row(self, f):
        if f.kind == 'check':
            self.form.addRow('', f.widget)
            self.row_of[f.dest] = f.widget
            return
        note = self.meta['notes'].get(f.dest, '')
        if not note:
            if f.kind in ('folder', 'folders') and not f.required:
                note = 'можно не указывать — весь диск'
            elif f.kind == 'disk' and not f.required:
                note = 'можно не указывать — все носители'
        f.note = note
        f.row_label = self.label_widget(f.label, f.required, note)
        self.form.addRow(f.row_label, f.widget)
        self.row_of[f.dest] = f.widget

    @staticmethod
    def label_html(text, required, note=''):
        t = html.escape(text) + (' <b style="color:#c62828">*</b>' if required else '') + ':'
        if note:
            t += f'<br>{gray("(" + note + ")")}'
        return t

    def label_widget(self, text, required, note=''):
        lab = QLabel(self.label_html(text, required, note))
        lab.setAlignment(Qt.AlignRight | Qt.AlignTop)
        if len(text) > 24 or note:               # короткие подписи - одной строкой, длинные - с переносом
            lab.setWordWrap(True)
            lab.setMaximumWidth(260)
        return lab

    def pair_blocks(self):
        """Пары «диск + папка»: поле диска -> (поле диска, поле папки, заголовок, пояснение).
        У диска, к которому привязана ровно одна папка, «Выбрать…» выбирает и диск. Блоком одной строкой пара
        показывается, если она названа в GUI_PAIRS или таких пар в форме две и больше."""
        users = {}
        for f in self.fields.values():
            d = FOLDER_PAIR.get(f.dest)
            if f.kind in ('folder', 'folders') and d in self.fields and self.fields[d].kind == 'disk':
                users.setdefault(d, []).append(f)
        pairs = []
        for d, fs in users.items():
            if len(fs) == 1 and fs[0].kind == 'folder':
                fs[0].pick_disk = True
                self.fields[d].combo.empty = '— не указан —'          # пустой диск пары - не «все носители»
                self.fields[d].combo.fill([])
                pairs.append((self.fields[d], fs[0]))
        named = self.meta['pairs']
        res = {}
        for d, p in pairs:
            if p.dest in named or (not named and len(pairs) >= 2):
                t = named.get(p.dest) or p.label
                title, note = (t if isinstance(t, (tuple, list)) else (t, ''))
                res[d.dest] = (d, p, title, note)
        return res

    @staticmethod
    def connect_changed(f, slot):
        w = f.widget
        if f.kind == 'disks':
            f.list.itemChanged.connect(lambda *_: slot())
        elif f.kind == 'check':
            f.check.toggled.connect(lambda *_: slot())
        elif hasattr(f, 'combo') and f.kind in ('disk', 'section', 'choice'):
            (f.combo.currentIndexChanged if f.kind == 'disk' else f.combo.currentTextChanged).connect(lambda *_: slot())
        elif hasattr(f, 'edit'):
            f.edit.textChanged.connect(slot)
        elif hasattr(f, 'line'):
            f.line.textChanged.connect(lambda *_: slot())
        elif isinstance(w, (QComboBox,)):
            w.currentIndexChanged.connect(lambda *_: slot())

    # --- режимы ---
    def apply_mode(self, i):
        """Показать поля режима i (GUI_MODES); без режимов - все поля. Скрытые поля в командную строку не идут,
        кроме тех, что режим задаёт сам (set)."""
        modes = self.meta['modes']
        m = modes[i] if (modes and i is not None and 0 <= i < len(modes)) else None
        self.mode = i if m is not None else None
        shown = set(m.get('fields', [])) if m else set(self.fields)
        adv = set(m.get('advanced', [])) if m else set()
        setv = dict(m.get('set', {})) if m else {}
        req = set(m.get('required', [])) if m else set()
        labels = dict(m.get('labels', {})) if m else {}
        defaults = dict(m.get('defaults', {})) if m else {}
        if m is not None:
            self.mode_hint.setText(html.escape(m.get('hint', '')))
        for d, f in self.fields.items():
            f.active = d in shown or d in adv or d in setv
            visible = (d in shown) or (d in adv and getattr(self, 'adv_open', False))
            if self.task_buttons and d == 'dry':
                visible = False                    # вместо галочки - кнопка «Посчитать»
            if d in setv and d not in shown:
                visible = False
            if d in setv and f.kind == 'check':
                f.check.setChecked(bool(setv[d]))
            if m is not None and f.kind == 'disks':
                f.set_checked(list(defaults.get(d, f.act.default or [])))
            f.set_label(labels.get(d, f.base_label), f.base_required or d in req)
            w = self.row_of.get(d)
            if w is not None:
                self.form.setRowVisible(w, visible)
        if hasattr(self, 'adv_btn'):
            self.form.setRowVisible(self.adv_btn, bool(adv))
        self.fill_sections()
        self.update_name()
        self.page.form_changed()

    def toggle_advanced(self):
        self.adv_open = not self.adv_open
        self.adv_btn.setText(('▼' if self.adv_open else '▶') + ' Дополнительно')
        self.apply_mode(self.mode)

    def fill_sections(self, *_):
        f = self.fields.get('section')
        if f is None or f.kind != 'section':
            return
        disk = self.value('disk') if 'disk' in self.fields else ''
        f.set_sections(sections_for(disk) if disk else [])

    # --- имя задания ---
    def update_name(self, *_):
        """Имя задания по полям (GUI_TASK_NAME / task_name режима), пока владелец не исправил его вручную."""
        f = self.fields.get('name')
        if not self.task_buttons or f is None:
            return
        cur = f.line.text().strip()
        if cur and cur != self.auto_name:
            return                                 # владелец написал своё
        m = self.meta['modes'][self.mode] if self.mode is not None else {}
        tpl = m.get('task_name') or self.meta['task_name']
        if not tpl:
            return
        vals = {d: g.text() for d, g in self.fields.items() if g.active}
        new = task_name(tpl, vals) if vals.get('disk', True) else ''     # без диска имя ещё не из чего собрать
        self.auto_name = new
        f.line.blockSignals(True)
        f.line.setText(new)
        f.line.blockSignals(False)

    @property
    def win(self):
        return self.page.win

    def set_disks(self, rows):
        for f in self.fields.values():
            if f.kind in ('disk', 'disks'):
                f.set_disks(rows)
        if self.meta['modes'] and self.mode is not None:
            m = self.meta['modes'][self.mode]
            f = self.fields.get('to')
            if f is not None and f.kind == 'disks' and 'to' in m.get('defaults', {}) and not f.text():
                f.set_checked(list(m['defaults']['to']))
        self.update_name()

    def active(self):
        return [f for f in self.fields.values() if f.active and not f.extra]

    def argv(self):
        """(аргументы, None) или (None, что не так) - по-русски, до запуска."""
        if self.unsupported:
            return None, 'Эту команду окно пока не умеет заполнять.'
        fields = self.active()
        miss = [f.label for f in fields if f.required and f.empty()]
        if miss:
            return None, 'Заполните: ' + ', '.join(f'«{x}»' for x in miss) + '.'
        rank = {a.dest: i for i, a in enumerate(self.parser._actions)}
        pos = sorted((f for f in fields if not f.opt), key=lambda f: rank.get(f.dest, 0))   # порядок argparse
        for i, f in enumerate(pos):
            if f.empty() and any(not g.empty() for g in pos[i + 1:]):
                after = ', '.join(f'«{g.label}»' for g in pos[i + 1:] if not g.empty())
                return None, f'Заполните «{f.label}» или очистите {after}.'
        to = self.fields.get('to')
        if to is not None and to.active and to.kind == 'disks' and not to.text():
            return None, f'Отметьте хотя бы один носитель в «{to.label}».'
        args = [self.name]
        for f in pos:
            args += f.tokens()
        for f in sorted(fields, key=lambda f: rank.get(f.dest, 0)):
            if f.opt:
                args += f.tokens()
        err = check_argv(self.parser, args[1:])
        if err:
            return None, 'Команда не принимает такие аргументы: ' + err
        return args, None

    def value(self, dest):
        f = self.fields.get(dest)
        return f.text() if f else None


def sections_for(disk):
    """Разделы и отсрочки из решений владельца по диску (решения.tsv): «раздел: …», «пока не трогаем»."""
    try:
        decs = hb.decisions_for(disk)
    except OSError:
        return []
    return sorted({v.strip() for _, v in decs if v.strip() and not hb.is_drop(v)}, key=str.lower)


def task_name(tpl, values):
    """Имя папки задания по шаблону: {disk}, {to}, {date} и любые поля; символы, запрещённые в имени папки, убраны."""
    def val(v):
        if isinstance(v, list):
            v = ' и '.join(x.rsplit('\\', 1)[-1] for x in v) if v else ''
        return str(v or '')

    class Vals(dict):
        def __missing__(self, k):
            return ''
    vals = Vals({k: val(v) for k, v in values.items()})
    vals['date'] = dt.date.today().strftime('%d.%m.%Y')
    if not vals.get('to') and 'to' in values:
        vals['to'] = '…'
    s = tpl.format_map(vals)
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', ' ', s)
    s = re.sub(r'\(\s*\)', '', s)
    s = re.sub(r'\s{2,}', ' ', s).strip(' .')
    return s[:100].strip(' .')


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
        group = None
        bold = QFont()
        bold.setBold(True)
        for name, hlp, p in self.cmds:
            meta = gui_meta(name, hlp, p)
            if meta['group'] != group:             # заголовок группы: не выбирается
                group = meta['group']
                h = QListWidgetItem(group)
                h.setFlags(Qt.ItemIsEnabled)
                h.setFont(bold)
                h.setForeground(QBrush(QColor('#455a64')))
                h.setBackground(QBrush(QColor('#eceff1')))
                self.list.addItem(h)
            it = QListWidgetItem('   ' + meta['title'])
            it.setData(Qt.UserRole, name)
            it.setToolTip(f'Командная строка: py catalog\\hashbase.py {name}')
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
        # после ответа «можно ли удалить» = НЕТ / НЕДОСТАТОЧНО (логика v3, этап 2): диск и папка - те, что были при запуске
        self.btn_contested = QPushButton('Пересчитать хеши спорных файлов…')
        self.btn_contested.setToolTip('Где лежат файлы без хеша и неподтверждённые копии этой папки; подключённые диски - '
                                      'пересканировать с хешем всех файлов, остальные - какие подключить.')
        self.btn_contested.clicked.connect(self.contested)
        self.btn_contested.hide()
        self.candel_args = None
        bar.addWidget(self.btn_contested)
        self.state = QLabel('')
        bar.addWidget(self.state, 1)
        tl.addLayout(bar)
        right.addWidget(top)
        self.out = QTextBrowser()
        self.out.setOpenLinks(False)
        self.out.anchorClicked.connect(self.link)
        right.addWidget(self.out)
        right.setSizes([600, 240])
        lay.addWidget(right, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.drain)
        self.list.setCurrentRow(self.row_of(self.cmds[0][0]))

    # --- форма ---
    def row_of(self, name):
        return next(i for i in range(self.list.count()) if self.list.item(i).data(Qt.UserRole) == name)

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
        it = self.list.item(i) if 0 <= i < self.list.count() else None
        name = it.data(Qt.UserRole) if it is not None else None
        if not name:                             # заголовок группы
            return
        self.current = name
        self.stack.setCurrentWidget(self.form())
        self.form_changed()

    def select(self, name):
        self.list.setCurrentRow(self.row_of(name))
        return self.form()

    def form_changed(self, *_):
        self.preview = None                      # предпросмотр больше не соответствует форме
        if getattr(self, 'current', None) in self.forms:      # во время постройки формы - ещё нечего показывать
            self.buttons()

    def buttons(self):
        busy = self.run is not None
        f = self.form()
        self.btn_run.setText('Посчитать' if f.task_buttons else 'Выполнить')
        self.btn_write.setText('Создать задание' if f.task_buttons else 'Записать')
        self.btn_run.setToolTip('Посчитать, сколько файлов и куда; задание не создаётся' if f.task_buttons else '')
        self.btn_write.setToolTip('Создать задание с теми же полями, что в последнем «Посчитать»'
                                  if f.task_buttons else '')
        self.btn_run.setEnabled(not busy)
        self.btn_write.setVisible(f.write or f.task_buttons)
        self.btn_write.setEnabled(not busy and self.preview is not None and self.preview[0] == self.current)
        self.btn_stop.setEnabled(busy and not self.protected)

    def refresh(self):
        """При каждом показе раздела: носители и какие из них подключены СЕЙЧАС (service.disks -> volumes)."""
        self.win.bg.run(sv.disks, ok=self.got_disks, quiet=True)

    def got_disks(self, rows):
        self.disks = [as_row(r) for r in rows]
        for f in self.forms.values():
            f.set_disks(self.disks)

    # --- запуск ---
    def execute(self):
        f = self.form()
        args, err = f.argv()
        if err:
            QMessageBox.information(self, TITLE, err)
            return
        if f.task_buttons and '--dry' not in args:          # «Посчитать» - всегда без создания задания
            args = args + ['--dry']
        self.start(args)

    def write(self):
        if not self.preview or self.preview[0] != self.current:
            return
        args = self.preview[1]
        self.preview = None                      # повторное нажатие ничего не запишет
        self.buttons()
        if self.form().task_buttons:
            if QMessageBox.question(self, TITLE, f'Создать задание «{self.form().value("name")}» в «Запускаемые '
                                    'скрипты»?\n\nЗапускаете его вы — в разделе «Задания».') != QMessageBox.Yes:
                return
            self.start(args)
            return
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
        self.btn_contested.hide()
        self.candel_args = (f.value('disk'), f.value('folder') or '') if self.current == 'candel' else None
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
        form = self.form(self.cmd)
        if self.cmd == 'candel' and self.candel_args and any(x.startswith(('ОТВЕТ: НЕТ', 'ОТВЕТ: НЕДОСТАТОЧНО'))
                                                             for x in self.lines):
            self.btn_contested.setText(f'Пересчитать хеши спорных файлов ({self.candel_args[0]})…')
            self.btn_contested.show()
        if code == 0 and form.write and not self.yes:
            self.preview = (self.cmd, run.args)
            self.add(['Это предпросмотр. Если всё верно - нажмите «Записать».'], color='#e65100')
        if code == 0 and form.task_buttons and '--dry' in run.args:
            self.preview = (self.cmd, [x for x in run.args if x != '--dry'])
            self.add(['Это расчёт, задание не создано. Если всё верно - нажмите «Создать задание».'], color='#e65100')
        if code == 0 and self.task_dir is not None and self.task_dir.exists() and form.value('move_after'):
            self.mark_move(form)
        self.buttons()
        if code == 0 and self.yes:
            self.win.statusBar().showMessage('Записано. Применяю к базе…', 5000)
            self.win.apply_new()
        if code == 0 and self.task_dir is not None and self.task_dir.exists():
            if QMessageBox.question(self, TITLE, f'Создано задание «{self.task_dir.name}». Перейти в «Задания»?') == QMessageBox.Yes:
                self.win.open_page('Задания')

    def mark_move(self, form):
        """Галочка «разложить после копирования»: пометка в папке созданного задания (sv.mark_task_move)."""
        folders = form.value('folder') if form.fields.get('folder') and form.fields['folder'].active else None
        if not folders and form.fields.get('source_folder') and form.fields['source_folder'].active:
            folders = [form.value('source_folder')] if form.value('source_folder') else None
        try:
            path = sv.mark_task_move(self.task_dir, form.value('disk'), folders or None)
            self.add([f'Пометка «разложить после копирования»: {path}'], gray=True)
        except (OSError, sv.Refused) as e:
            self.add([f'Пометку «разложить после копирования» записать не удалось: {e}'], color='#c62828')

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

    def contested(self):
        """Окно «Пересчитать хеши спорных файлов» (то же, что в «Разборе носителя») для диска и папки проверки."""
        if not self.candel_args:
            return
        import razbor_page                       # не при загрузке: страница разбора сама берёт DiskCombo отсюда
        self.contested_dlg = razbor_page.ContestedDialog(self.win, *self.candel_args)
        self.contested_dlg.show()

    def copy(self):
        QGuiApplication.clipboard().setText('\n'.join(self.lines))
        self.win.statusBar().showMessage('Вывод скопирован - вставьте его в чат.', 5000)
