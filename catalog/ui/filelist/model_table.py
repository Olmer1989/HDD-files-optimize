"""Окно «Список файлов»: FileModel - весь список в памяти, сортировка и фильтр номерами строк; выгрузка.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

import disk_ui
import service as sv

from .texts_list import (C_DATE, C_DISK, C_FOLDER, C_HASH, C_NAME, C_SIZE, C_TYPE, C_WHERE, C_WHY, columns, date_ok,
                         date_text, head, n_text, norm, size_text)
from .common import (EV_ORDER, R_DISK, R_EV, R_FLC, R_FOLDER, R_K, R_MTIME, R_NAME, R_NLC, R_SIZE, R_T5, R_WHERE,
                     R_WHY, SEP)
from .model_rows import Busy, file_path, place_of


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
