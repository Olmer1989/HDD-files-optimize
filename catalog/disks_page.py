"""Страница «Диски и папки» окна «Архив дисков» (вынесено из app.py 16.11.2026)."""
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
from overview_page import *  # noqa: E402,F401,F403  (HtmlLabel, card, gb_ru, n_ru …)


# ---------- Диски и папки ----------

SCAN_RU = {'complete': 'полное', 'complete_with_inventory_errors': 'полное, есть нечитаемые места',
           'complete_with_unread_files': 'полное, часть файлов не прочитана', 'running': 'не закончено',
           'interrupted': 'прервано, не закончено', 'stopped': 'остановлено, не закончено', 'failed': 'не удалось',
           'error': 'не удалось'}
# состав папки: фото, видео, тексты, прочие, мусор (таблица folders, b0..b4)
TYPE_NAMES = ('фото', 'видео', 'тексты', 'прочие', 'мусор')
TYPE_COLORS = ('#42a5f5', '#ab47bc', '#66bb6a', '#ffa726', '#bdbdbd')
T_CHECK, T_NAME, T_FILES, T_GB, T_TYPE0, T_DEC = 0, 1, 2, 3, 4, 9
DISK_ROLE = Qt.UserRole + 1          # у строки дерева - её носитель (найденные папки - с разных дисков)
TYPES_ROLE = Qt.UserRole + 2         # ГБ по типам - полоска состава под именем
MARK_ROLE = Qt.UserRole + 3          # решение владельца - плашка
SIZE_ROLE = Qt.UserRole + 4          # (файлов, ГиБ) папки
DEC_COLORS = {'dir': ('#fff3e0', '#e65100', '#ffb74d'), 'skip': ('#eeeeee', '#616161', '#bdbdbd'),
              'unset': ('#fffde7', '#8d6e63', '#ffe082'), 'service': ('#eceff1', '#78909c', '#cfd8dc')}
WHY_TEXT = ('Здесь видно, что лежит на каждом носителе по базе: папки, сколько в них фото, видео и прочего, и какое '
            'решение по ним принято. Отсюда же — открыть папку в Проводнике и пересканировать её.')


def scan_text(r):
    """«08.11.2026 · полное · частичных: 2» (сканирование носителя)."""
    st = (r.get('status') or '').strip()
    bits = [r.get('scanned') or 'дата неизвестна', SCAN_RU.get(st, disk_ui.status_text(st))]
    if r.get('partial'):
        bits.append(f'частичных: {r["partial"]}')
    return ' · '.join(b for b in bits if b and b != '—')


def disk_cell(r):
    """«F: — Монтаж - SN850 — HDD09» / «Видеоархив полный — HDD01» / «HDD61» (метки нет)."""
    return ' — '.join(x for x in (r.get('letter'), disk_ui.disk_name(r), r['disk']) if x)


def type_text(x):
    return '—' if x < 0.05 else gib(x)


class FolderDelegate(QStyledItemDelegate):
    """Колонка «Папка» - тонкая цветная полоска состава под именем; «Решение владельца» - плашка."""
    BAR = 4

    def paint(self, painter, option, index):
        if index.column() == T_DEC:
            mark = index.data(MARK_ROLE)
            if mark and mark.get('text'):
                self.initStyleOption(option, index)
                option.text = ''
                st = option.widget.style() if option.widget else None
                if st:
                    st.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
                bg, fg, border = DEC_COLORS.get(mark['kind'], DEC_COLORS['unset'])
                f = QFont(option.font)
                fm = QFontMetrics(f)
                text = mark['text'] + ('' if mark.get('own') else ' ↑')
                w = min(fm.horizontalAdvance(text) + 16, option.rect.width() - 6)
                r = QRectF(option.rect.left() + 3, option.rect.center().y() - fm.height() / 2 - 2, w, fm.height() + 4)
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                c = QColor(bg)
                if not mark.get('own'):
                    c = c.lighter(104)
                painter.setBrush(c)
                painter.setPen(QColor(border))
                painter.drawRoundedRect(r, 8, 8)
                painter.setPen(QColor(fg))
                painter.setFont(f)
                painter.drawText(r.adjusted(8, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                                 fm.elidedText(text, Qt.ElideRight, int(r.width() - 12)))
                painter.restore()
                return
            return super().paint(painter, option, index)
        super().paint(painter, option, index)
        if index.column() != T_NAME:
            return
        types = index.data(TYPES_ROLE)
        total = sum(types) if types else 0
        if not total:
            return
        st = option.widget.style() if option.widget else None
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        tr = st.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget) if st else opt.rect
        x0, width = tr.left() + 2, max(20, min(tr.width() - 8, 260))
        y = option.rect.bottom() - self.BAR - 2
        painter.save()
        x = float(x0)
        for v, color in zip(types, TYPE_COLORS):
            w = width * v / total
            if w > 0:
                painter.fillRect(QRectF(x, y, max(w, 1.0), self.BAR), QColor(color))
            x += w
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        return QSize(s.width() + (30 if index.column() == T_DEC else 0), max(s.height() + self.BAR + 6, 28))


class DisksPage(QWidget):
    """«Диски и папки» (16.11.2026, «всё оставляем, но красиво»): поиск, носители, папки выбранного носителя с составом,
    решением владельца и панелью действий. Действия берут носитель из самой строки (найденные папки - с разных дисков)."""
    HEAD = ['Диск', 'Подключён', 'Свободно', 'Файлов', 'ГБ', 'Сканирование']
    TREE = ['', 'Папка', 'Файлов', 'ГБ', 'фото', 'видео', 'тексты', 'прочие', 'мусор', 'Решение владельца']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.disk, self.found = win, [], None, False   # found - показаны найденные папки
        self.want = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel('Диски и папки')
        f = title.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        f.setBold(True)
        title.setFont(f)
        top.addWidget(title)
        top.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Найти папки на всех дисках по словам, например: Сафари  (Enter)')
        self.search.returnPressed.connect(self.find)
        top.addWidget(self.search, 1)
        b = QPushButton('Найти')
        b.clicked.connect(self.find)
        top.addWidget(b)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        top.addWidget(b)
        lay.addLayout(top)
        why = QLabel(WHY_TEXT)
        why.setWordWrap(True)
        why.setStyleSheet('color:#555')
        lay.addWidget(why)
        split = QSplitter(Qt.Vertical)
        up = QWidget()
        ul = QVBoxLayout(up)
        ul.setContentsMargins(0, 0, 0, 0)
        self.count_lab = QLabel('<b>Носители</b>')
        ul.addWidget(self.count_lab)
        self.t = table(self.HEAD, stretch=0)
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t.itemSelectionChanged.connect(self.pick)
        ul.addWidget(self.t)
        split.addWidget(up)
        low = QWidget()
        ll = QVBoxLayout(low)
        ll.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        self.tree_title = QLabel('')
        tf = self.tree_title.font()
        tf.setPointSizeF(tf.pointSizeF() + 1)
        tf.setBold(True)
        self.tree_title.setFont(tf)
        head.addWidget(self.tree_title)
        head.addStretch()
        self.tree_sum = QLabel('')
        self.tree_sum.setStyleSheet('color:#555')
        head.addWidget(self.tree_sum)
        ll.addLayout(head)
        legend = QLabel('Полоска под именем — состав папки: ' + ' '.join(
            f'<span style="background:{c}">&nbsp;&nbsp;&nbsp;</span>&nbsp;{n}&nbsp;&nbsp;' for n, c in
            zip(TYPE_NAMES, TYPE_COLORS)) + ' · столбцы типов — в ГБ; «↑» у решения — от родительской папки.')
        legend.setStyleSheet('font-size:8pt; color:#616161')
        legend.setWordWrap(True)
        ll.addWidget(legend)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(self.TREE)
        self.tree.setTreePosition(T_NAME)
        self.tree.setItemDelegate(FolderDelegate(self.tree))
        hd = self.tree.header()
        hd.setStretchLastSection(False)
        hd.setSectionResizeMode(QHeaderView.ResizeToContents)
        hd.setSectionResizeMode(T_NAME, QHeaderView.Stretch)
        hd.setSectionResizeMode(T_DEC, QHeaderView.Interactive)
        self.tree.setColumnWidth(T_DEC, 230)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)      # несколько папок - с Ctrl
        self.tree.setAlternatingRowColors(True)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemSelectionChanged.connect(self.selected)
        self.tree.itemChanged.connect(self.item_changed)
        ll.addWidget(self.tree, 1)
        # панель действий - карточкой
        act = QFrame()
        act.setObjectName('card')
        act.setStyleSheet('QFrame#card { background:#f8fafc; border:1px solid #d0d7de; border-radius:6px; }')
        al = QVBoxLayout(act)
        al.setContentsMargins(10, 8, 10, 8)
        row = QHBoxLayout()
        self.sel_lab = QLabel('Выбрано папок: 0')
        sf = self.sel_lab.font()
        sf.setBold(True)
        self.sel_lab.setFont(sf)
        row.addWidget(self.sel_lab)
        row.addStretch()
        self.open_btn = QPushButton('Открыть в Проводнике')
        self.open_btn.clicked.connect(self.open_explorer)
        self.rescan_btn = QPushButton('Пересканировать выбранные…')
        self.rescan_btn.setToolTip('Подключённый диск: заново прочитать только новые и изменённые файлы выбранных папок. '
                                   'Сначала - предпросмотр, затем подтверждение.')
        self.rescan_btn.clicked.connect(self.rescan)
        self.missing_btn = QPushButton('Чего нет на дисках направления')
        self.missing_btn.setToolTip('Каких файлов выбранных папок (по SHA-256) нет на дисках направлений, отмеченных '
                                    'галочкой в «Обзоре».')
        self.missing_btn.clicked.connect(self.presence)
        for w in (self.open_btn, self.rescan_btn, self.missing_btn):
            row.addWidget(w)
        al.addLayout(row)
        self.state = QLabel('')
        al.addWidget(self.state)
        self.dates = QLabel('')                 # «Хеши измерены: …» для выбранной папки
        self.dates.setWordWrap(True)
        self.dates.setStyleSheet('color:#555')
        self.dates.setTextInteractionFlags(Qt.TextSelectableByMouse)
        al.addWidget(self.dates)
        self.info = QLabel('')
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        al.addWidget(self.info)
        ll.addWidget(act)
        split.addWidget(low)
        split.setSizes([260, 560])
        lay.addWidget(split, 1)
        self.update_actions()

    # --- носители ---
    def show_disk(self, disk):
        """Перейти к носителю (ссылка «Пересканировать» из «Обзора»): выбрать его строку и показать папки."""
        self.want = disk
        disks = [r['disk'] for r in self.rows]
        if disk in disks:
            self.want = None
            self.found = False
            self.t.setCurrentCell(disks.index(disk), 0)
            if self.disk != disk:
                self.pick()
            self.info.setText('Отметьте галочками папки и нажмите «Пересканировать выбранные…».')

    def refresh(self):
        """При каждом показе раздела и по «Обновить»: носители и какие из них подключены сейчас."""
        self.win.bg.run(sv.disks, ok=self.render)

    def render(self, rows):
        """Подключённые сейчас - первыми (жирным, зелёным), затем HDD по номеру, флешки в конце.
        Выбор сохраняется; если ничего не выбрано - выбирается первый подключённый и показываются его папки."""
        rows = disk_ui.ordered(rows)
        self.rows = rows
        self.count_lab.setText(f'<b>Носители ({len(rows)})</b> — подключённые сейчас сверху')
        self.t.blockSignals(True)
        self.t.clearSelection()
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            on = bool(r.get('letter'))
            vals = [disk_cell(r), 'да' if on else 'нет',
                    f'{gb_ru(r["free_gib"])} ГБ' if 'free_gib' in r else '—',
                    n_ru(r['files']), gb_ru(r['gib']), scan_text(r)]
            for j, v in enumerate(vals):
                it = cell(v, right=j in (2, 3, 4))
                it.setData(Qt.UserRole, r['disk'])
                if j == 5 and r.get('status'):
                    it.setToolTip(f'В описи: {r["status"]}')
                if on:
                    disk_ui.style_item(it.setData, True)
                elif j in (0, 1):
                    it.setForeground(QColor('#616161'))
                if j == 4:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.t.setItem(i, j, it)
        self.t.blockSignals(False)
        self.t.resizeColumnsToContents()
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        disks = [r['disk'] for r in rows]
        if self.want in disks:          # переход из «Обзора» по ссылке «Пересканировать»
            self.show_disk(self.want)
        elif self.disk in disks:                   # тот же носитель: дерево папок не перестраивать
            self.t.blockSignals(True)
            self.t.setCurrentCell(disks.index(self.disk), 0)
            self.t.blockSignals(False)
            self.update_actions()
        elif not self.found:
            first = next((i for i, r in enumerate(rows) if r.get('letter')), None)
            if first is not None:
                self.t.setCurrentCell(first, 0)  # -> pick(): папки верхнего уровня

    def row_of(self, disk):
        return next((r for r in self.rows if r['disk'] == disk), {'disk': disk, 'label': '', 'letter': ''})

    def pick(self):
        i = self.t.currentRow()
        if 0 <= i < len(self.rows):
            self.found = False
            r = self.rows[i]
            self.disk = r['disk']
            self.tree.clear()
            self.info.setText('')
            self.tree_title.setText(f'Папки диска {disk_cell(r)}')
            self.tree_sum.setText(f'{n_ru(r["files"])} файлов · {gb_ru(r["gib"])} ГБ')
            root = QTreeWidgetItem()
            root.setText(T_NAME, f'{self.disk} (весь диск)')
            root.setData(T_NAME, Qt.UserRole, '')
            root.setData(T_NAME, DISK_ROLE, self.disk)
            self.tree.addTopLevelItem(root)
            self.load(root)
            root.setExpanded(True)
            disk = self.disk
            self.win.bg.run(sv.disk_hash_info, disk, ok=lambda res, d=disk: self.show_hash_info(d, res), quiet=True)
            self.update_actions()

    def show_hash_info(self, disk, res):
        if disk != self.disk or self.found:
            return
        r = self.row_of(disk)
        self.tree_sum.setText(f'{n_ru(r.get("files"))} файлов · {gb_ru(r.get("gib") or 0)} ГБ · {res["text"]}')
        self.tree_sum.setToolTip(res.get('tip', ''))

    def load(self, item):
        disk, path = item.data(T_NAME, DISK_ROLE), item.data(T_NAME, Qt.UserRole)

        def fill(rows):
            item.takeChildren()
            self.tree.blockSignals(True)
            for r in rows:
                ch = self.folder_item(disk, r['path'], r['name'], r['files'], r['gib'], r['types'], r.get('mark'))
                ch.addChild(QTreeWidgetItem())            # раскрывается лениво
                item.addChild(ch)
            self.tree.blockSignals(False)
        item.setData(T_FILES, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, disk, path, ok=fill)

    def folder_item(self, disk, path, name, files, gib_, types=None, mark=None):
        ch = QTreeWidgetItem()
        ch.setText(T_NAME, name)
        ch.setToolTip(T_NAME, f'{disk}\\{path}')
        ch.setData(T_NAME, Qt.UserRole, path)
        ch.setData(T_NAME, DISK_ROLE, disk)
        ch.setData(T_NAME, SIZE_ROLE, (files, gib_))
        ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
        ch.setCheckState(T_CHECK, Qt.Unchecked)
        ch.setText(T_FILES, n_ru(files))
        ch.setText(T_GB, gb_ru(gib_))
        f = QFont(self.tree.font())                     # шрифт дерева (масштаб Windows), только жирный
        f.setBold(True)
        ch.setFont(T_GB, f)
        if types is not None:
            ch.setData(T_NAME, TYPES_ROLE, list(types))
            ch.setToolTip(T_NAME, f'{disk}\\{path}\n' + ', '.join(f'{n} {gb_ru(x)} ГБ' for n, x in zip(TYPE_NAMES, types)))
            for k, x in enumerate(types):
                ch.setText(T_TYPE0 + k, type_text(x).replace('.', ','))
                if x < 0.05:
                    ch.setForeground(T_TYPE0 + k, QColor('#bdbdbd'))
        for k in range(T_FILES, T_DEC):
            ch.setTextAlignment(k, Qt.AlignRight | Qt.AlignVCenter)
        if mark and mark.get('text'):
            ch.setData(T_DEC, MARK_ROLE, mark)
            ch.setToolTip(T_DEC, mark['text'] + ('' if mark.get('own') else f' (от «{mark.get("src")}»)')
                          + '. Сохранённые отметки «Разбора носителя».')
        else:
            ch.setText(T_DEC, '—')
            ch.setForeground(T_DEC, QColor('#bdbdbd'))
            ch.setTextAlignment(T_DEC, Qt.AlignCenter)
        return ch

    def expand(self, item):
        if not item.data(T_FILES, Qt.UserRole) and item.data(T_NAME, DISK_ROLE):
            self.load(item)

    # --- выбор папок ---
    def all_items(self):
        out = []

        def walk(it):
            out.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def targets(self):
        """Папки для действий: с галочкой; галочек нет - выделенные строки. -> [(диск, путь, файлов, ГиБ)]."""
        items = [it for it in self.all_items() if it.data(T_NAME, Qt.UserRole) and
                 it.checkState(T_CHECK) == Qt.Checked]
        if not items:
            items = [it for it in self.tree.selectedItems() if it.data(T_NAME, Qt.UserRole)]
        out = []
        for it in items:
            files, g = it.data(T_NAME, SIZE_ROLE) or (0, 0.0)
            out.append((it.data(T_NAME, DISK_ROLE), it.data(T_NAME, Qt.UserRole), files, g))
        return out

    def item_changed(self, it, col):
        if col == T_CHECK:
            self.update_actions()

    def update_actions(self):
        t = self.targets()
        files, g = sum(x[2] for x in t), sum(x[3] for x in t)
        self.sel_lab.setText(f'Выбрано папок: {len(t)} · файлов {n_ru(files)} · {gb_ru(g)} ГБ' if t else
                             'Выбрано папок: 0 — отметьте папки галочками (или выделите строку)')
        disks = sorted({x[0] for x in t}) or ([self.disk] if self.disk else [])
        off = [d for d in disks if not self.row_of(d).get('letter')]
        if not disks:
            self.state.setText('')
        elif off:
            self.state.setText(f'<span style="color:#e65100">Подключите {", ".join(off)}, чтобы открыть папки в '
                               'Проводнике и пересканировать.</span> Смотреть папки и «чего нет» можно и без него.')
        else:
            self.state.setText(f'<span style="color:#2e7d32">Диск подключён ({", ".join(self.row_of(d)["letter"] for d in disks)}) '
                               '— можно открыть и пересканировать.</span>')
        self.open_btn.setEnabled(bool(t) and not off)
        self.rescan_btn.setEnabled(bool(t) and not off and len(disks) == 1)
        self.missing_btn.setEnabled(bool(t))

    def selected(self):
        """Выбрана одна папка: «когда измерены хеши» - в фоне; ответ для уже сменившейся папки не показывается."""
        self.update_actions()
        items = [it for it in self.tree.selectedItems() if it.data(T_NAME, DISK_ROLE)]
        if len(items) != 1:
            self.dates.setText('')
            return
        disk, path = items[0].data(T_NAME, DISK_ROLE), items[0].data(T_NAME, Qt.UserRole) or ''
        self.dates.setText('Когда измерены хеши: считаю…')

        def show(r):
            cur = self.tree.selectedItems()
            if len(cur) != 1 or cur[0].data(T_NAME, DISK_ROLE) != disk or (cur[0].data(T_NAME, Qt.UserRole) or '') != path:
                return
            self.dates.setText(r['text'] + ' ' + r['hint'])
        self.win.bg.run(sv.hash_dates, disk, path, ok=show, quiet=True)

    # --- действия ---
    def open_explorer(self):
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку).')
            return
        for disk, path, _n, _g in t[:10]:
            letter = self.row_of(disk).get('letter')
            if not letter:
                QMessageBox.information(self, TITLE, f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
                return
            p = letter + '\\' + path
            if os.path.isdir(p):
                os.startfile(p)
            else:
                QMessageBox.information(self, TITLE, f'Папки «{p}» на диске нет (её переименовали или переместили?). '
                                        'Пересканируйте носитель.')
        if len(t) > 10:
            self.info.setText(f'Открыты первые 10 папок из {len(t)}.')

    def presence(self):
        """Чего из выбранных папок нет на дисках направлений, отмеченных в «Обзоре» (по SHA-256)."""
        import directions_page
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку).')
            return
        dirs = directions_page.chosen()
        targets = list(dict.fromkeys(x for d in dirs for x in d.disks))
        if not targets:
            QMessageBox.information(self, TITLE, 'В «Обзоре» не отмечено ни одного направления с диском. Отметьте '
                                    'направления галочками — их диски и проверятся.')
            return
        self.info.setText('Считаю…')

        def job():
            return [(d, p, sv.folder_missing(d, p, targets)) for d, p, _n, _g in t[:30]]

        def show(res):
            import html as h
            lines = []
            for d, p, r in res:
                where = f'{d}\\{p}' if p else f'{d} (весь диск)'
                parts = []
                for x in targets:
                    n, g = r['missing'][x]
                    weak = r.get('weak', {}).get(x, 0)
                    parts.append(f'нет на {x} — <b>{n_ru(n)}</b> файлов, {gb_ru(g)} ГБ' +
                                 (f' (у {n_ru(weak)} из них там есть непроверенная копия)' if weak else '')
                                 if n else f'<span style="color:#2e7d32">на {x} есть всё</span>')
                extra = f'; без хеша (сравнить нельзя) — {n_ru(r["nohash"])}' if r['nohash'] else ''
                if r.get('stale'):
                    extra += f'; хеш устарел — файл изменён после подсчёта (сравнить нельзя) — {n_ru(r["stale"])}'
                lines.append(f'<b>{h.escape(where)}</b>: файлов с хешем {n_ru(r["files"])} ({gb_ru(r["gib"])} ГБ); '
                             + '; '.join(parts) + extra + '.')
            if len(t) > 30:
                lines.append(f'Показаны первые 30 папок из {len(t)}.')
            self.info.setText('<br>'.join(lines))
        self.win.bg.run(job, ok=show)

    def rescan(self):
        """Пересканировать выбранные папки подключённого диска: окно предпросмотра; скан - только по подтверждению."""
        t = self.targets()
        if not t:
            QMessageBox.information(self, TITLE, 'Отметьте папки галочками (или выделите строку). Весь диск целиком - '
                                    'это полное сканирование, его делает сканер дисков.')
            return
        disks = sorted({x[0] for x in t})
        if len(disks) > 1:
            QMessageBox.information(self, TITLE, f'Выбраны папки разных дисков ({", ".join(disks)}). Пересканировать '
                                    'можно папки одного диска за раз.')
            return
        disk = disks[0]
        if not self.row_of(disk).get('letter'):
            QMessageBox.information(self, TITLE, f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, [p for _d, p, _n, _g in t])
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
            self.tree_title.setText(f'Найдено по словам «{" ".join(words)}»')
            self.tree_sum.setText(f'папок: {len(rows)}' + (' (показаны первые 300)' if len(rows) >= 300 else ''))
            self.tree.blockSignals(True)
            for r in rows:
                it = self.folder_item(r['disk'], r['path'], f'{r["disk"]}\\{r["path"]}', r['files'], r['gib'],
                                      r.get('types'), r.get('mark'))         # состав и решение - как в дереве
                self.tree.addTopLevelItem(it)
            self.tree.blockSignals(False)
            self.info.setText(f'Найдено папок: {len(rows)} (вложенные совпадения не показаны). Отметьте нужные '
                              'галочками — действия ниже работают и для найденных папок.')
            self.update_actions()
        self.win.bg.run(sv.find_folders, words, ok=show)
