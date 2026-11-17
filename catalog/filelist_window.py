"""Окно «Список файлов» (этап 16, 16.11.2026; документ - «Логика_v3_разбор_носителя.md», раздел «Этап 16»).

Одно окно для всех списков: к копированию, уже есть, не подходит по типу («Разбор носителя»), без хеша («Диски и
папки»), спорные, уникальные. Данные - service.file_list (ничего не пишет в базу); окно тоже ничего не пишет.

Как устроено:
- список загружается целиком в фоне (до service.LIST_MAX строк), окно открыто сразу («Загружаю…»); ответ для
  закрытого окна или устаревшего запроса отбрасывается;
- FileModel (QAbstractTableModel) сама сортирует и фильтрует весь набор на Python (список номеров строк, list.sort по
  ключу): QSortFilterProxyModel вызывает data() из Python на каждое сравнение - 100 тыс. строк сортировались 30 с
  (замер этапа 16), list.sort - 0,02 с. Пустые даты и размеры - «—», при сортировке всегда в конце;
- фильтр: 5 типов, «папка содержит…», «имя содержит…» - без учёта регистра, пробелы ввода НЕ обрезаются;
- итог (файлов, ГБ, по 5 типам) - по всему списку и по показанным строкам.
"""
import csv
import os
import subprocess
import time
import unicodedata

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox, QSplitter, QTableView, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import disk_ui
import service as sv
from ui_common import log_error

TITLE = 'Архив дисков'
SEP = '\\'
XLSX_MAX = 1_048_575                 # строк данных на листе Excel (плюс строка заголовка)
FILTER_MS = 300
TREE_CHUNK = 500                     # этап 17: дети папки в дереве окна - порциями
SMALL_KB = 10                        # «мелкие картинки» - фото до 10 КБ (замечание владельца: 1–10 КБ)
RELOAD_MS = 400                      # после правки отметок - перечитать список (несколько правок - одно чтение)
F_ROLE, F_MORE, F_PART = Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3   # роли дерева окна
MARK_KINDS = ('copy', 'have', 'type')
KIND_TITLE = {'copy': 'к копированию на', 'have': 'уже есть на', 'type': 'не подходит по типу для',
              'nohash': 'без хеша', 'contested': 'спорные файлы', 'unique': 'только на этом носителе'}
# столбцы: ключ -> заголовок
C_DISK, C_FOLDER, C_NAME, C_TYPE, C_SIZE, C_DATE, C_HASH, C_WHY, C_WHERE = (
    'disk', 'folder', 'name', 'type', 'size', 'date', 'hash', 'why', 'where')
HEAD = {C_DISK: 'На каком диске', C_FOLDER: 'Где лежит', C_NAME: 'Имя', C_TYPE: 'Тип', C_SIZE: 'Размер', C_DATE: 'Дата',
        C_HASH: 'Хеш', C_WHY: 'Почему', C_WHERE: 'Где копия'}
WIDTH = {C_DISK: 90, C_FOLDER: 330, C_NAME: 220, C_TYPE: 110, C_SIZE: 80, C_DATE: 115, C_HASH: 150, C_WHY: 330,
         C_WHERE: 420}
EV_ORDER = {'S': 0, 'C': 1, 'Z': 2, 'U': 3, 'X': 4}
# строка модели
R_DISK, R_FOLDER, R_NAME, R_K, R_T5, R_SIZE, R_MTIME, R_EV, R_WHY, R_WHERE, R_FLC, R_NLC = range(12)


def columns(kind):
    """Столбцы списка: общие + «На каком диске» и «Почему спорный» у спорных, «Где копия» у «уже есть»."""
    cols = [C_FOLDER, C_NAME, C_TYPE, C_SIZE, C_DATE, C_HASH]
    if kind == 'contested':
        cols = [C_DISK] + cols + [C_WHY]
    elif kind == 'have':
        cols = cols + [C_WHERE]
    else:
        cols = cols + [C_WHY]
    return cols


def head(kind, col):
    if col == C_WHY:
        return sv.WHY_HEAD.get(kind, 'Почему')
    return HEAD[col]


def norm(text):
    """Строка для поиска «содержит»: единая форма Unicode и нижний регистр; пробелы НЕ обрезаются (этап 16)."""
    return unicodedata.normalize('NFC', text or '').lower()


def size_text(b):
    if b is None:
        return '—'
    if b >= 1024 ** 3:
        return f'{b / 1024 ** 3:.2f} ГБ'.replace('.', ',')
    if b >= 1024 ** 2:
        return f'{b / 1024 ** 2:.1f} МБ'.replace('.', ',')
    if b >= 1024:
        return f'{b / 1024:.0f} КБ'
    return f'{b} Б'


def gb_text(b):
    return f'{(b or 0) / 1024 ** 3:.1f}'.replace('.', ',')


def n_text(n):
    return f'{n or 0:,}'.replace(',', ' ')


def date_ok(mt):
    return mt is not None and mt > 0


def date_text(mt):
    return time.strftime('%d.%m.%Y %H:%M', time.localtime(mt)) if date_ok(mt) else '—'


def files_word(n):
    n10, n100 = n % 10, n % 100
    w = 'файл' if n10 == 1 and n100 != 11 else 'файла' if n10 in (2, 3, 4) and n100 not in (12, 13, 14) else 'файлов'
    return f'{n_text(n)} {w}'


class Busy:
    """Курсор ожидания на время сортировки и фильтра всего набора (510 тыс. строк: 0,2–1,2 с, замер критиков по коду)."""

    def __enter__(self):
        if QApplication.instance() is not None:
            QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))

    def __exit__(self, *exc):
        if QApplication.instance() is not None:
            QApplication.restoreOverrideCursor()


def place_of(r, letters):
    """«Где лежит» (этап 18): полный путь папки файла - с буквой подключённого носителя («F:\\Алёнкин клип»), иначе
    «HDD09\\Алёнкин клип». Пробелы в именах не трогаются."""
    return sv.full_path(r[R_DISK], r[R_FOLDER], letters)


def file_path(r, letters):
    """Полный путь файла строки (с буквой или номером носителя)."""
    return place_of(r, letters).rstrip(SEP) + SEP + r[R_NAME]


def export_values(rows, idx, cols, letters=None):
    """Строки для Excel/CSV в порядке показа (размер - числом байт, дата - текстом); в фоновом потоке: rows и idx -
    снимок модели (список строк модели не меняется, сортировка и фильтр создают новые списки номеров)."""
    out = []
    for i in idx:
        r = rows[i]
        vals = []
        for col in cols:
            if col == C_SIZE:
                vals.append(r[R_SIZE] if r[R_SIZE] is not None else '')
            elif col == C_DATE:
                vals.append(date_text(r[R_MTIME]) if date_ok(r[R_MTIME]) else '')
            elif col == C_FOLDER:
                vals.append(place_of(r, letters or {}))
            else:
                vals.append(FileModel.text(None, r, col))
        out.append(vals)
    return out


def prepare(data):
    """Строки service.file_list -> строки модели (в фоновом потоке): папка и имя - из пути без обрезки, нижний регистр
    для поиска (папки - общим кэшем)."""
    folders, flc = {}, {}
    rows = []
    for disk, path, size, mt, ev, k, why, where in data['rows']:
        i = path.rfind(SEP)
        folder, name = (path[:i], path[i + 1:]) if i >= 0 else ('', path)
        folder = folders.setdefault(folder, folder)
        lc = flc.get(folder)
        if lc is None:
            lc = flc[folder] = norm(folder)
        rows.append((disk, folder, name, k, sv.type5(k), size, mt, ev, why or '', where or '', lc, norm(name)))
    data['model_rows'] = rows
    return data


class FileModel(QAbstractTableModel):
    """Весь список в памяти; сортировка и фильтр - номерами строк (order - весь набор по сортировке, idx - видимые)."""

    def __init__(self, kind='nohash'):
        super().__init__()
        self.kind, self.cols, self.rows, self.order, self.idx = kind, columns(kind), [], [], []
        self.sort_col, self.sort_desc = None, False
        self.types, self.folder_sub, self.name_sub = set(range(5)), '', ''
        self.folder_prefix, self.min_size = '', 0          # этап 17: щелчок по папке дерева; «меньше N КБ - скрыть»
        self.letters = {}                                   # этап 18: буквы подключённых носителей («Где лежит»)

    # --- данные ---
    def set_rows(self, kind, rows):
        self.beginResetModel()
        self.kind, self.cols, self.rows = kind, columns(kind), rows
        self.order = list(range(len(rows)))
        self._apply()
        self.endResetModel()
        if self.sort_col is not None and self.sort_col < len(self.cols):
            self.sort(self.sort_col, Qt.DescendingOrder if self.sort_desc else Qt.AscendingOrder)

    def rowCount(self, parent=QModelIndex()):                        # noqa: N802
        return 0 if parent.isValid() else len(self.idx)

    def columnCount(self, parent=QModelIndex()):                     # noqa: N802
        return 0 if parent.isValid() else len(self.cols)

    def row(self, i):
        return self.rows[self.idx[i]]

    def text(self, r, col):                              # self не нужен: вызывается и из export_values
        if col == C_DISK:
            return r[R_DISK]
        if col == C_FOLDER:
            return place_of(r, self.letters if self is not None else {})
        if col == C_NAME:
            return r[R_NAME]
        if col == C_TYPE:
            return sv.TYPE_WORD.get(r[R_K], 'другие')
        if col == C_SIZE:
            return size_text(r[R_SIZE])
        if col == C_DATE:
            return date_text(r[R_MTIME])
        if col == C_HASH:
            return sv.hash_text(r[R_EV])
        if col == C_WHY:
            return r[R_WHY]
        return r[R_WHERE]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, col = self.rows[self.idx[index.row()]], self.cols[index.column()]
        if role == Qt.DisplayRole:
            return self.text(r, col)
        if role == Qt.ToolTipRole:
            if col in (C_FOLDER, C_NAME):
                return file_path(r, self.letters)
            if col in (C_WHY, C_WHERE):
                return self.text(r, col)
            if col == C_SIZE and r[R_SIZE] is not None:
                return f'{n_text(r[R_SIZE])} байт'
        if role == Qt.TextAlignmentRole and col == C_SIZE:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ForegroundRole:
            if col == C_WHY and r[R_WHY].startswith(('⚠', 'не будет')):
                return QColor('#c62828')
            if col == C_HASH and r[R_EV] in ('Z', 'U', 'X'):
                return QColor('#e65100')
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self.cols):
            return head(self.kind, self.cols[section])
        return None

    # --- сортировка: весь набор; пустые даты и размеры - в конце при любом направлении ---
    def key_of(self, col):
        rows = self.rows
        if col == C_DISK:
            return lambda i: (disk_ui.disk_key(rows[i][R_DISK]), rows[i][R_FLC], rows[i][R_NLC])
        if col == C_FOLDER:
            return lambda i: (rows[i][R_FLC], rows[i][R_NLC])
        if col == C_NAME:
            return lambda i: (rows[i][R_NLC], rows[i][R_FLC])
        if col == C_TYPE:
            return lambda i: (rows[i][R_T5], sv.TYPE_WORD.get(rows[i][R_K], ''), rows[i][R_FLC], rows[i][R_NLC])
        if col == C_SIZE:
            return lambda i: rows[i][R_SIZE]
        if col == C_DATE:
            return lambda i: rows[i][R_MTIME]
        if col == C_HASH:
            return lambda i: (EV_ORDER.get(rows[i][R_EV] or '', 9), rows[i][R_FLC], rows[i][R_NLC])
        if col == C_WHY:
            return lambda i: (rows[i][R_WHY].lower(), rows[i][R_FLC], rows[i][R_NLC])
        return lambda i: (rows[i][R_WHERE].lower(), rows[i][R_FLC], rows[i][R_NLC])

    def sort(self, column, order=Qt.AscendingOrder):
        if not (0 <= column < len(self.cols)):
            return
        self.sort_col, self.sort_desc = column, order == Qt.DescendingOrder
        col = self.cols[column]
        key = self.key_of(col)
        with Busy():
            self._sort(col, key)

    def _sort(self, col, key):
        self.beginResetModel()
        full = range(len(self.rows))
        if col in (C_SIZE, C_DATE):
            ok = (lambda i: self.rows[i][R_SIZE] is not None) if col == C_SIZE else \
                (lambda i: date_ok(self.rows[i][R_MTIME]))
            good = [i for i in full if ok(i)]
            empty = [i for i in full if not ok(i)]
            good.sort(key=key, reverse=self.sort_desc)
            empty.sort(key=lambda i: (self.rows[i][R_FLC], self.rows[i][R_NLC]))
            self.order = good + empty
        else:
            self.order = sorted(full, key=key, reverse=self.sort_desc)
        self._apply()
        self.endResetModel()

    # --- фильтр ---
    def set_filter(self, types=None, folder_sub=None, name_sub=None, folder_prefix=None, min_size=None):
        if folder_prefix is not None:
            self.folder_prefix = folder_prefix
        if min_size is not None:
            self.min_size = int(min_size)
        if types is not None:
            self.types = set(types)
        if folder_sub is not None:
            self.folder_sub = norm(folder_sub)
        if name_sub is not None:
            self.name_sub = norm(name_sub)
        with Busy():
            self.beginResetModel()
            self._apply()
            self.endResetModel()

    def filtered(self):
        return (self.types != set(range(5)) or bool(self.folder_sub) or bool(self.name_sub) or bool(self.folder_prefix)
                or self.min_size > 0)

    def _apply(self):
        """Все фильтры - вместе (И): типы, «папка содержит», «имя содержит», папка дерева (она и вложенные; путь -
        как есть, без обрезки), «меньше N байт - скрыть» (размер неизвестен - не скрывается)."""
        rows, ts, fs, ns = self.rows, self.types, self.folder_sub, self.name_sub
        fp, ms = self.folder_prefix, self.min_size
        if not self.filtered():
            self.idx = list(self.order)
            return
        fpp = fp + SEP
        self.idx = [i for i in self.order if rows[i][R_T5] in ts and (not fs or fs in rows[i][R_FLC])
                    and (not ns or ns in rows[i][R_NLC])
                    and (not fp or rows[i][R_FOLDER] == fp or rows[i][R_FOLDER].startswith(fpp))
                    and (not ms or rows[i][R_SIZE] is None or rows[i][R_SIZE] >= ms)]

    # --- итог ---
    @staticmethod
    def totals_of(rows, idx):
        """-> (файлов, байт, [файлов по 5 типам], [байт по 5 типам])."""
        n, b, nt, bt = 0, 0, [0] * 5, [0] * 5
        for i in idx:
            r = rows[i]
            s = r[R_SIZE] or 0
            n += 1
            b += s
            nt[r[R_T5]] += 1
            bt[r[R_T5]] += s
        return n, b, nt, bt

    def totals(self, visible=True):
        return self.totals_of(self.rows, self.idx if visible else range(len(self.rows)))

    # --- выгрузка ---
    def export_rows(self):
        """Видимые строки в порядке показа: значения для Excel/CSV (см. export_values)."""
        return export_values(self.rows, self.idx, self.cols, self.letters)


def totals_line(t):
    n, b, nt, _bt = t
    return (f'<b>{files_word(n)} · {gb_text(b)} ГБ</b> — ' +
            ' · '.join(f'{w} {n_text(x)}' for w, x in zip(sv.TYPE5, nt)))


def save_table(path, heads, rows):
    """Запись видимых строк: .csv - UTF-8 с BOM, разделитель «;» (кавычки по правилам CSV - имена с «;» и кавычками
    не ломают столбцы); иначе .xlsx (openpyxl, потоковая запись). -> путь."""
    if str(path).lower().endswith('.csv'):
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            w = csv.writer(f, delimiter=';', quoting=csv.QUOTE_MINIMAL)
            w.writerow(heads)
            w.writerows(rows)
        return path
    if len(rows) > XLSX_MAX:
        raise sv.Refused(f'Строк {len(rows)} - больше, чем помещается на лист Excel ({XLSX_MAX}).')
    from openpyxl import Workbook
    wb = Workbook(write_only=True)
    ws = wb.create_sheet('Список файлов')
    ws.append(heads)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def collapse(folders):
    """Папки для пересканирования: вложенные в другую выбранную - убираются (её пересканирует верхняя)."""
    res = []
    for f in sorted(set(folders), key=lambda x: (x.count(SEP), x.lower())):
        fl = f.lower()
        if not any(fl == t.lower() or fl.startswith(t.lower() + SEP) for t in res):
            res.append(f)
    return res


class FileListWindow(QWidget):
    """Отдельное окно (не вкладка). spec - аргументы service.file_list: kind, disk, folder, num, target, drafts."""

    def __init__(self, win, page=None, **spec):
        super().__init__(win, Qt.Window)
        self.win, self.spec = win, dict(spec)
        self.page = page if spec.get('kind') in MARK_KINDS else None   # этап 17: галочки дерева = отметки «Разбора»
        self.keep = set()                     # папки, снятые в этом окне: видны с 0 файлов, галочку можно вернуть
        self.only = None                      # «показать эти папки»: дерево только из них (и предков)
        self.f_items, self.f_count, self.f_kids = {}, {}, {}
        self.painting = False
        self.kind, self.disk = spec['kind'], spec['disk']
        self.closed, self.req, self.data = False, 0, None
        self.disk_rows = []
        self.setWindowTitle(f'Список файлов — {self.disk}')
        self.resize(1300, 760)
        lay = QVBoxLayout(self)
        self.title = QLabel(f'{self.disk} · {KIND_TITLE.get(self.kind, "")}')
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.sub = QLabel('')
        self.sub.setWordWrap(True)
        self.sub.setTextFormat(Qt.RichText)
        self.sub.setStyleSheet('color:#37474f')
        lay.addWidget(self.sub)
        self.carrier = QLabel('')                          # этап 18: «Носитель: HDD09 «SN850» — сейчас подключён как F:»
        self.carrier.setTextFormat(Qt.RichText)
        lay.addWidget(self.carrier)
        self.total = QLabel('Загружаю список из базы (диски не читаются)…')
        self.total.setTextFormat(Qt.RichText)
        self.total.setWordWrap(True)
        lay.addWidget(self.total)
        self.notes = QLabel('')
        self.notes.setWordWrap(True)
        self.notes.setStyleSheet('color:#5d4037')
        self.notes.hide()
        lay.addWidget(self.notes)
        self.stale = QLabel('Данные устарели (папки пересканированы) — нажмите «Обновить».')
        self.stale.setStyleSheet('background:#fff3e0; color:#e65100; border:1px solid #ffb74d; padding:5px; '
                                 'font-weight:bold')
        self.stale.hide()
        lay.addWidget(self.stale)
        # фильтры
        fl = QHBoxLayout()
        fl.addWidget(QLabel('<b>Показать:</b>'))
        self.type_boxes = []
        for i, w in enumerate(sv.TYPE5):
            b = QCheckBox(w)
            b.setChecked(True)
            b.toggled.connect(self.filter_later)
            self.type_boxes.append(b)
            fl.addWidget(b)
        fl.addSpacing(16)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText('папка содержит…')
        self.folder_edit.textChanged.connect(self.filter_later)
        fl.addWidget(self.folder_edit, 1)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText('имя содержит…')
        self.name_edit.textChanged.connect(self.filter_later)
        fl.addWidget(self.name_edit, 1)
        fl.addWidget(QLabel('скрыть меньше'))
        self.size_box = QSpinBox()                         # этап 17: «меньше N КБ - скрыть», 0 - выключено
        self.size_box.setRange(0, 10 ** 7)
        self.size_box.setSuffix(' КБ')
        self.size_box.setSpecialValueText('—')
        self.size_box.setToolTip('Скрыть файлы меньше стольких КБ (0 - показать все). Файлы с неизвестным размером не '
                                 'скрываются.')
        self.size_box.valueChanged.connect(self.filter_later)
        fl.addWidget(self.size_box)
        lay.addLayout(fl)
        self.shown = QLabel('')
        self.shown.setTextFormat(Qt.RichText)
        self.shown.setStyleSheet('color:#1565c0')
        lay.addWidget(self.shown)
        # таблица
        self.model = FileModel(self.kind)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setSortingEnabled(True)
        self.view.horizontalHeader().setSortIndicatorShown(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)   # не по содержимому: 510 тыс. строк
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setWordWrap(False)
        self.view.setTextElideMode(Qt.ElideMiddle)        # этап 18: длинный путь - многоточие в середине, полный - в подсказке
        self.view.setToolTip('Щелчок по заголовку столбца - сортировка по всему списку. Ctrl/Shift - выделить несколько.')
        # этап 17: слева - дерево папок списка (щелчок - фильтр; галочки - отметки «Разбора»)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.small = QLabel('')                              # «Мелкие картинки до 10 КБ: N файлов в M папках»
        self.small.setTextFormat(Qt.RichText)
        self.small.setWordWrap(True)
        self.small.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.small.linkActivated.connect(self.toggle_small)
        self.ftree = QTreeWidget()
        self.ftree.setHeaderLabels(['Папка', 'Файлов'])
        self.ftree.header().setStretchLastSection(False)
        self.ftree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.ftree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.ftree.setUniformRowHeights(True)
        self.ftree.itemExpanded.connect(self.f_expand)
        self.ftree.itemClicked.connect(self.f_clicked)
        self.ftree.itemChanged.connect(self.f_changed)
        ll.addWidget(self.ftree, 1)
        ll.addWidget(self.small)                           # этап 18: под деревом - дерево и таблица выровнены по верху
        self.marks_note = QLabel('')
        self.marks_note.setWordWrap(True)
        self.marks_note.setStyleSheet('color:#757575; font-size:8pt')
        ll.addWidget(self.marks_note)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.view)
        split.setSizes([360, 940])
        lay.addWidget(split, 1)
        self.set_widths()
        # кнопки
        bl = QHBoxLayout()
        self.open_btn = QPushButton('Открыть в Проводнике')
        self.open_btn.setToolTip('Папка выделенного файла, файл выделен. Только если подключён именно этот носитель '
                                 '(буква - по серийному номеру тома).')
        self.open_btn.clicked.connect(self.open_explorer)
        self.excel_btn = QPushButton('Сохранить в Excel…')
        self.excel_btn.setToolTip('Все показанные строки (с фильтром и сортировкой).')
        self.excel_btn.clicked.connect(self.save_excel)
        self.rescan_btn = QPushButton('Пересканировать папки выделенных…')
        self.rescan_btn.setToolTip('Папки выделенных файлов (вложенные - вместе с верхней) - в окно пересканирования с '
                                   'выбором типов. Сначала - вопрос с числом папок и файлов.')
        self.rescan_btn.clicked.connect(self.rescan)
        self.refresh_btn = QPushButton('Обновить')
        self.refresh_btn.clicked.connect(self.load)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close)
        for w in (self.open_btn, self.excel_btn, self.rescan_btn):
            bl.addWidget(w)
        bl.addStretch()
        bl.addWidget(self.refresh_btn)
        bl.addWidget(close)
        lay.addLayout(bl)
        self.state = QLabel('')
        self.state.setStyleSheet('color:#555')
        self.state.setWordWrap(True)
        self.file_line = QLabel('')                        # этап 18: «Файл: …» / «Копия: …» выделенной строки
        self.file_line.setTextFormat(Qt.PlainText)                  # путь показывается буквально (& и т. п.)
        self.file_line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.file_line.setWordWrap(True)
        self.file_line.setStyleSheet('color:#263238')
        lay.addWidget(self.file_line)
        lay.addWidget(self.state)
        self.ftimer = QTimer(self)
        self.ftimer.setSingleShot(True)
        self.ftimer.timeout.connect(self.apply_filter)
        self.sel_timer = QTimer(self)
        self.sel_timer.setSingleShot(True)
        self.sel_timer.timeout.connect(self.count_selected)
        self.view.selectionModel().selectionChanged.connect(lambda *_: (self.sel_timer.start(250), self.show_file_line()))
        self.view.selectionModel().currentChanged.connect(lambda *_: self.show_file_line())
        self.model.modelReset.connect(self.show_file_line)           # фильтр, сортировка, новый список - строка гаснет
        self.sel_folders = []
        self.reload_timer = QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.timeout.connect(self.load)
        if self.page is not None:
            self.page.marks_changed.connect(self.on_marks)
            self.page.saving_changed.connect(self.on_saving)
        self.update_buttons()
        self.load()

    # --- загрузка ---
    def load(self):
        self.req += 1
        req = self.req
        self.busy(True)
        self.total.setText('Загружаю список из базы (диски не читаются)…')
        spec = dict(self.spec)
        if self.page is not None and self.can_mark():
            spec['drafts'] = self.page.model.draft_rows()   # тот же черновик, что у «Разбора»

        def job():
            data = prepare(sv.file_list(**spec))
            try:
                data['disk_rows'] = sv.disks()
            except Exception:                                     # noqa: BLE001 - подписи дисков не обязательны
                data['disk_rows'] = []
            return data

        self.win.bg.run(lambda: _safe(job), ok=lambda res: self.got(req, res), quiet=True)

    def got(self, req, res):
        if self.closed or req != self.req:
            return                                               # окно закрыто или ответ устарел
        self.busy(False)
        kind, val = res
        if kind != 'ok':
            self.total.setText(f'<span style="color:#c62828">Список не получен: {_esc(_last_line(val))}</span>')
            return
        self.data = val
        self.disk_rows = val.get('disk_rows') or []
        self.model.letters = {r['disk']: r['letter'] for r in self.disk_rows if r.get('letter')}
        self.model.set_rows(self.kind, val['model_rows'])
        self.carrier.setText(self.carrier_text())
        self.set_widths()
        self.stale.hide()
        self.title.setText(self.title_text())
        self.sub.setText(f'Папка: <b>{_esc(val["scope"])}</b> и вложенные. Почему эти файлы: {_esc(val["why"])}.')
        notes = val.get('notes') or []
        self.notes.setText('\n'.join(notes))
        bad = any(x.startswith(('ИТОГ НЕВЕРЕН', 'ВНИМАНИЕ')) for x in notes)
        self.notes.setStyleSheet('color:#c62828; font-weight:bold' if bad else 'color:#5d4037')
        self.notes.setVisible(bool(val.get('notes')))
        self.build_tree()
        self.show_totals()
        self.update_buttons()

    # --- дерево папок списка (этап 17) ---
    def carrier_text(self):
        """«Носитель: HDD09 «SN850» — сейчас подключён как F:» / «… — не подключён» (буква - по серийному номеру тома из
        описи, как у «Открыть в Проводнике»)."""
        r = next((x for x in self.disk_rows if x['disk'] == self.disk), None) or {'disk': self.disk, 'label': '',
                                                                                   'letter': ''}
        name = disk_ui.disk_name(r)
        head = f'Носитель: <b>{_esc(self.disk)}</b>' + (f' «{_esc(name)}»' if name else '')
        if r.get('letter'):
            return head + f' — <span style="color:#2e7d32">сейчас подключён как <b>{_esc(r["letter"])}</b></span>'
        return head + ' — <span style="color:#e65100">не подключён</span> (пути — от номера носителя)'

    def show_file_line(self):
        """Строка под таблицей: «Файл: <полный путь>» и (у списка «уже есть») «Копия: <полный путь>» - текущей строки;
        текст выделяется мышью."""
        ix = self.view.currentIndex()
        if not ix.isValid() or ix.row() >= self.model.rowCount() or not self.view.selectionModel().isSelected(ix):
            self.file_line.setText('')
            return
        r = self.model.row(ix.row())
        lines = ['Файл: ' + file_path(r, self.model.letters)]
        if r[R_WHERE]:
            lines.append('Копия: ' + r[R_WHERE])
        self.file_line.setText('\n'.join(lines))

    def expand_marked(self):
        """Этап 18 (правка владельца): папки дерева, которые идут в диск назначения, а родитель - нет (верхние
        отмеченные, как 4 подпапки «Алтай 2022 …» на HDD09), видны сразу: их предки раскрываются."""
        p = self.page
        if p is None or p.model is None or p.disk != self.disk:
            return
        m, num = p.model, self.spec.get('num')
        tops = [f for f in self.f_count if f and m.is_dir(m.route.get(f), num)
                and not m.is_dir(m.route.get(f.rsplit(SEP, 1)[0] if SEP in f else ''), num)]
        for f in sorted(tops, key=lambda x: x.count(SEP)):
            chain, a = [], f
            while SEP in a:
                a = a.rsplit(SEP, 1)[0]
                chain.append(a)
            for a in reversed(chain):
                it = self.f_items.get(a)
                if it is None:
                    break
                if not it.data(1, F_ROLE):
                    self.f_fill(it)
                it.setExpanded(True)

    def build_tree(self):
        """Папки с файлами списка и их предки (+ снятые в этом окне - с 0 файлов); число - файлов в папке с вложенными.
        Дети создаются по раскрытию, порциями по TREE_CHUNK. Раскрытые узлы сохраняются по путям."""
        rows = self.model.rows
        direct = {}
        for r in rows:
            direct[r[R_FOLDER]] = direct.get(r[R_FOLDER], 0) + 1
        small = {}
        for r in rows:
            if r[R_T5] == 0 and r[R_SIZE] is not None and 0 < r[R_SIZE] <= SMALL_KB * 1024:
                small[r[R_FOLDER]] = small.get(r[R_FOLDER], 0) + 1
        self.small_folders = set(small)
        n_small = sum(small.values())
        if n_small:
            link = 'все папки' if self.only is not None else 'показать эти папки'
            self.small.setText(f'Мелкие картинки до {SMALL_KB} КБ: <b>{n_text(n_small)}</b> {files_word(n_small).split()[-1]}'
                               f' в {n_text(len(small))} папках — <a href="small" style="color:#1565c0">{link}</a>')
        else:
            self.small.setText('')
            self.only = None
        base = set(direct) if self.only is None else set(self.only) & set(direct)
        count, kids = {}, {}
        for f in base | self.keep:
            n = direct.get(f, 0)
            a = f
            while True:
                count[a] = count.get(a, 0) + n
                if not a:
                    break
                p = a.rsplit(SEP, 1)[0] if SEP in a else ''
                kids.setdefault(p, set()).add(a)
                a = p
        count.setdefault('', 0)
        self.f_count = count
        self.f_kids = {p: sorted(v, key=lambda x: x.lower()) for p, v in kids.items()}
        opened = {f for f, it in self.f_items.items() if it.isExpanded()}
        self.painting = True
        self.ftree.blockSignals(True)
        try:
            self.ftree.clear()
            self.f_items = {}
            root = QTreeWidgetItem([f'весь список ({n_text(count.get("", 0))})', ''])
            root.setData(0, F_ROLE, '')
            root.setToolTip(0, 'Щелчок - показать файлы всех папок (сбросить фильтр по папке).')
            self.ftree.addTopLevelItem(root)
            self.f_items[''] = root
            self.f_fill(root)
            root.setExpanded(True)
            for f in sorted(opened, key=lambda x: x.count(SEP)):
                it = self.f_items.get(f)
                if it is not None and f:
                    if not it.data(1, F_ROLE):
                        self.f_fill(it)
                    it.setExpanded(True)
        finally:
            self.ftree.blockSignals(False)
            self.painting = False
        self.refresh_checks()
        self.expand_marked()                                # каждый f_fill сам обновляет галочки

    def f_fill(self, item, start=0):
        p = item.data(0, F_ROLE)
        kids = self.f_kids.get(p, [])
        was = self.ftree.signalsBlocked()
        self.ftree.blockSignals(True)
        try:
            if start == 0:
                item.takeChildren()
            else:
                for i in reversed(range(item.childCount())):
                    if item.child(i).data(0, F_MORE) is not None:
                        item.takeChild(i)
            item.setData(1, F_ROLE, True)                         # дети созданы
            new = []
            for f in kids[start:start + TREE_CHUNK]:
                ch = QTreeWidgetItem([f.rsplit(SEP, 1)[-1], n_text(self.f_count.get(f, 0))])
                ch.setData(0, F_ROLE, f)
                ch.setToolTip(0, f'{self.disk}\\{f}')
                ch.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                if self.f_kids.get(f):
                    ch.addChild(QTreeWidgetItem(['…', '']))
                self.f_items[f] = ch
                new.append(ch)
            rest = len(kids) - start - TREE_CHUNK
            if rest > 0:
                more = QTreeWidgetItem([f'ещё {n_text(rest)} папок — показать', ''])
                more.setData(0, F_MORE, (p, start + TREE_CHUNK))
                more.setForeground(0, QColor('#1565c0'))
                new.append(more)
            item.addChildren(new)
        finally:
            self.ftree.blockSignals(was)
        self.refresh_checks()

    def f_expand(self, item):
        if not item.data(1, F_ROLE) and item.data(0, F_ROLE) is not None:
            self.f_fill(item)

    def f_clicked(self, item, col=0):
        if getattr(self, 'check_click', False):     # щелчок по галочке, а не по имени: фильтр не трогаем
            self.check_click = False
            return
        more = item.data(0, F_MORE)
        if more is not None:
            parent = self.f_items.get(more[0])
            if parent is not None:
                self.f_fill(parent, more[1])
            return
        f = item.data(0, F_ROLE)
        if f is None:
            return
        self.model.set_filter(folder_prefix=f)                     # И с остальными фильтрами; корень - сброс
        self.show_totals()
        self.update_buttons()

    def toggle_small(self, _href=''):
        """«показать эти папки» (только папки с мелкими картинками) / «все папки»."""
        self.only = None if self.only is not None else set(self.small_folders)
        self.build_tree()

    def can_mark(self):
        """Галочки дерева = отметки страницы «Разбор»: только для её носителя и диска назначения, не во время записи."""
        p = self.page
        return bool(p is not None and p.model is not None and p.disk == self.disk and p.dest == self.spec.get('num')
                    and not p.writing and not p.saving)

    def refresh_checks(self):
        """Галочки дерева по маршруту «Разбора»: папка идёт в диск назначения - отмечена (с исключениями внутри -
        частично), иначе - нет. Пока «Разбор» пишет или выбран другой носитель / диск - неактивны."""
        p = self.page
        if p is None or self.closed:
            return
        ok = self.can_mark()
        m = p.model if p.model is not None and p.disk == self.disk else None
        num = self.spec.get('num')
        if p.saving or p.writing:
            self.marks_note.setText('Идёт запись отметок в «Разборе носителя» — галочки ненадолго неактивны.')
        elif not ok:
            self.marks_note.setText('Галочки неактивны: в «Разборе носителя» сейчас другой носитель или диск назначения.')
        else:
            self.marks_note.setText('Галочка снята — папка не копируется (сохраняется сразу; «Отменить последнее» — в '
                                    '«Разборе носителя»). Щелчок по имени — показать файлы папки.')
        part = m.partial(num) if m is not None else {}
        self.painting = True
        was = self.ftree.signalsBlocked()
        self.ftree.blockSignals(True)
        try:
            for f, it in self.f_items.items():
                if not f or m is None or not m.markable(f):
                    it.setData(0, Qt.CheckStateRole, None)
                    continue
                on = m.is_dir(m.route.get(f), num)
                pm = part.get(f)
                st = Qt.PartiallyChecked if (on and pm == 'off') or (not on and pm == 'on') else \
                    (Qt.Checked if on else Qt.Unchecked)
                fl = it.flags()
                it.setFlags((fl | Qt.ItemIsUserCheckable) if ok else (fl & ~Qt.ItemIsUserCheckable))
                it.setCheckState(0, st)
                it.setData(1, F_PART, pm if st == Qt.PartiallyChecked else None)   # что делает щелчок
        finally:
            self.ftree.blockSignals(was)
            self.painting = False

    def on_saving(self, _on=False):
        self.refresh_checks()

    def f_changed(self, item, col):
        if self.painting or col != 0:
            return
        self.check_click = True                     # тот же щелчок придёт и в itemClicked - он не фильтр
        QTimer.singleShot(0, lambda: setattr(self, 'check_click', False))   # только для этого щелчка
        f = item.data(0, F_ROLE)
        if not f or not self.can_mark():
            self.refresh_checks()
            return
        part = item.data(1, F_PART)                    # частичная: 'off' - снять всю, 'on' - выбрать всю
        on = (part == 'on') if part else item.checkState(0) == Qt.Checked
        self.keep.add(f)
        if not self.page.set_in_dest([f], on):
            self.refresh_checks()

    def on_marks(self, _rev=0):
        """Отметки в «Разборе» изменились: галочки - сразу, список - перечитать (ответ старого запроса отбросится)."""
        if self.closed:
            return
        self.refresh_checks()
        self.reload_timer.start(RELOAD_MS)

    def busy(self, on):
        for w in (self.open_btn, self.excel_btn, self.rescan_btn, self.refresh_btn):
            w.setEnabled(not on)

    def set_widths(self):
        for j, col in enumerate(self.model.cols):
            self.view.setColumnWidth(j, WIDTH.get(col, 120))

    def place(self, disk):
        r = next((x for x in self.disk_rows if x['disk'] == disk), None)
        name = disk_ui.disk_place(r) if r else ''
        return f'{name} ({disk})' if name and name != disk else disk

    def title_text(self):
        d = self.data or {}
        what = KIND_TITLE.get(self.kind, '')
        if self.kind == 'copy':
            return f'{self.disk} · {what} {self.place(d.get("target"))}'
        if self.kind == 'have':
            return f'{self.disk} · {what} ' + ' и '.join(self.place(x) for x in d.get('targets') or [])
        if self.kind == 'type':
            return f'{self.disk} · {what} «{d.get("direction", "")}»'
        return f'{self.disk} · {what}'

    def show_totals(self):
        m = self.model
        self.total.setText('Всего: ' + totals_line(m.totals(visible=False)))
        if m.filtered():
            self.shown.setText('Показаны по фильтру: ' + totals_line(m.totals()))
        else:
            self.shown.setText(f'Показаны все: {files_word(m.rowCount())}')

    # --- фильтр ---
    def filter_later(self, *_):
        self.ftimer.start(FILTER_MS)

    def apply_filter(self):
        types = {i for i, b in enumerate(self.type_boxes) if b.isChecked()}
        # текст поиска - как набран: пробелы по краям тоже ищутся (имена папок с пробелом, этап 16)
        self.model.set_filter(types, self.folder_edit.text(), self.name_edit.text(),
                              min_size=self.size_box.value() * 1024)
        self.show_totals()
        self.update_buttons()

    # --- выделение ---
    def selected_rows(self):
        return [self.model.row(ix.row()) for ix in self.view.selectionModel().selectedRows()]

    def count_selected(self):
        """Подпись «Пересканировать папки выделенных (N папок, M файлов)…»: M - по таблице folders, в фоне."""
        if self.closed:
            return
        rows = self.selected_rows()
        disks = {r[R_DISK] for r in rows}
        folders = collapse(r[R_FOLDER] for r in rows if r[R_FOLDER])
        self.sel_folders = folders
        self.sel_files = None
        if not rows:
            self.rescan_btn.setText('Пересканировать папки выделенных…')
            self.update_buttons()
            return
        if len(disks) > 1 or not folders:
            self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок)…')
            self.update_buttons()
            return
        disk = next(iter(disks))
        self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок, считаю файлы…)…')

        def show(res):
            if self.closed or folders != self.sel_folders or res[0] != 'ok':
                return
            self.sel_files = sum(res[1].values())
            self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок, '
                                    f'{files_word(sum(res[1].values()))})…')
        self.win.bg.run(lambda: _safe(sv.folders_files, disk, folders), ok=show, quiet=True)
        self.update_buttons()

    def update_buttons(self):
        has = self.data is not None
        self.open_btn.setEnabled(has and bool(self.view.selectionModel().selectedRows()))
        self.excel_btn.setEnabled(has and self.model.rowCount() > 0)
        self.rescan_btn.setEnabled(has and bool(self.view.selectionModel().selectedRows())
                                   and bool(getattr(self, 'sel_folders', None)))

    # --- действия ---
    def current(self):
        ix = self.view.currentIndex()
        rows = self.view.selectionModel().selectedRows()
        if ix.isValid() and any(r.row() == ix.row() for r in rows):
            return self.model.row(ix.row())
        return self.model.row(rows[0].row()) if rows else None

    def open_explorer(self):
        r = self.current()
        if r is None:
            QMessageBox.information(self, TITLE, 'Выделите файл в списке.')
            return
        disk, folder, name = r[R_DISK], r[R_FOLDER], r[R_NAME]

        def show(res):
            if self.closed:
                return
            kind, val = res
            if kind != 'ok':
                QMessageBox.information(self, TITLE, (val if kind == 'refused' else _last_line(val)) +
                                        f'\n\nПапка в базе: {disk}\\{folder}')
                return
            open_in_explorer(self, val, folder, name)
        self.win.bg.run(lambda: _safe(sv.disk_letter, disk), ok=show, quiet=True)

    def save_excel(self):
        m = self.model
        n = m.rowCount()
        if not n:
            return
        base = f'{self.disk} - {KIND_TITLE.get(self.kind, "список")}'.replace(':', '')
        csv_mode = n > XLSX_MAX
        if csv_mode and QMessageBox.question(
                self, TITLE, f'Строк {n_text(n)} — больше, чем помещается на лист Excel ({n_text(XLSX_MAX)}).\n\n'
                             'Сохранить файл CSV? Excel откроет его (все строки - в Excel только первые '
                             f'{n_text(XLSX_MAX)}; уточните фильтр, если нужно всё на одном листе).') != QMessageBox.Yes:
            return
        ext, flt = ('.csv', 'CSV (*.csv)') if csv_mode else ('.xlsx', 'Excel (*.xlsx)')
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить список', os.path.join(os.path.expanduser('~'), 'Documents',
                                                                                     base + ext), flt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        heads = [head(self.kind, c) for c in m.cols]
        snap = (m.rows, list(m.idx), list(m.cols), dict(m.letters))            # строки готовятся в фоне (510 тыс. - 2,7 с)
        self.state.setText(f'Сохраняю {files_word(len(snap[1]))}…')
        self.excel_btn.setEnabled(False)

        def done(res):
            if self.closed:
                return
            self.excel_btn.setEnabled(True)
            kind, val = res
            if kind == 'ok':
                self.state.setText(f'Сохранено: {val}')
            else:
                self.state.setText('Не сохранено: ' + (val if kind == 'refused' else _last_line(val)))
        self.win.bg.run(lambda: _safe(lambda: save_table(path, heads, export_values(*snap))), ok=done, quiet=True)

    def rescan(self):
        rows = self.selected_rows()
        if not rows:
            QMessageBox.information(self, TITLE, 'Выделите файлы: пересканируются их папки.')
            return
        disks = sorted({r[R_DISK] for r in rows})
        if len(disks) > 1:
            QMessageBox.information(self, TITLE, f'Выделены файлы разных дисков ({", ".join(disks)}). Пересканировать '
                                    'можно папки одного диска за раз - выделите файлы одного диска.')
            return
        disk = disks[0]
        root = sum(1 for r in rows if not r[R_FOLDER])
        folders = collapse(r[R_FOLDER] for r in rows if r[R_FOLDER])
        if not folders:
            QMessageBox.information(self, TITLE, f'Выделены только файлы в корне {disk}: их пересканирует только полная '
                                    'опись диска (программа «Сканер дисков»).')
            return
        try:                                              # число уже посчитано в фоне при выделении - не считать заново
            files = self.sel_files if folders == self.sel_folders and self.sel_files is not None else \
                sum(sv.folders_files(disk, folders).values())
        except Exception as e:                                    # noqa: BLE001
            files = None
            log_error(str(e))
        shown = '\n'.join(f'  {disk}\\{f}' for f in folders[:15]) + (f'\n  … и ещё {len(folders) - 15}' if len(folders) > 15 else '')
        q = (f'Пересканировать {len(folders)} папок {disk}' + (f' — {files_word(files)} по базе' if files is not None else '')
             + f'?\n\n{shown}\n\n' + (f'Файлы прямо в корне ({root}) не войдут: их пересканирует только полная опись.\n\n'
                                      if root else '') +
             'Дальше откроется окно пересканирования: там выберите типы файлов и посмотрите предпросмотр.')
        if QMessageBox.question(self, TITLE, q) != QMessageBox.Yes:
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and getattr(running, 'running', False):
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        import rescan_dialog
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.finished.connect(lambda *_: (not self.closed) and self.stale.show())
        self.win.rescan.show()

    def closeEvent(self, e):                                      # noqa: N802
        self.closed = True
        self.reload_timer.stop()
        if self.page is not None:
            for sig, slot in ((self.page.marks_changed, self.on_marks), (self.page.saving_changed, self.on_saving)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        lists = getattr(self.win, 'file_lists', None)
        if lists is not None and self in lists:
            lists.remove(self)
        super().closeEvent(e)


def open_in_explorer(parent, letter, folder, name):
    """Папка файла в Проводнике с выделенным файлом; файла нет - папка; папки нет - сообщение."""
    base = letter.rstrip(SEP) + SEP
    folder_path = base + folder if folder else base
    full = folder_path.rstrip(SEP) + SEP + name if folder else base + name
    if os.path.exists(full):
        subprocess.Popen(f'explorer /select,"{full}"')
        return 'file'
    if os.path.isdir(folder_path):
        os.startfile(folder_path)
        QMessageBox.information(parent, TITLE, f'Файла «{name}» в папке нет (его переместили или удалили?) - открыта '
                                               'папка. Пересканируйте её, чтобы база узнала.')
        return 'folder'
    QMessageBox.information(parent, TITLE, f'Папки «{folder_path}» на диске нет (её переименовали или переместили?). '
                                           'Пересканируйте носитель.')
    return None


def open_list(win, page=None, **spec):
    """Открыть окно «Список файлов» (из «Разбора носителя» и «Дисков и папок»). -> окно."""
    w = FileListWindow(win, page=page, **spec)
    if not hasattr(win, 'file_lists'):
        win.file_lists = []
    win.file_lists.append(w)
    w.show()
    return w


def _safe(fn, *a):
    """('ok', ответ) / ('refused', текст отказа) / ('error', трассировка) - ответ фоновой задачи."""
    import traceback
    try:
        return 'ok', fn(*a)
    except sv.Refused as e:
        return 'refused', str(e)
    except Exception:                                             # noqa: BLE001
        text = traceback.format_exc()
        log_error(text)
        return 'error', text


def _last_line(text):
    t = (text or '').strip()
    return t.splitlines()[-1] if t else text


def _esc(x):
    import html
    return html.escape(str(x))
