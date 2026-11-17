"""Окно «Список файлов»: FileListWindow - сборка окна (__init__, раскладка, связи сигналов) из частей view_*; open_list.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QSplitter, QTableView, QTreeWidget, QVBoxLayout, QWidget)

import service as sv

from .texts_list import KIND_TITLE
from .common import MARK_KINDS
from .model_table import FileModel
from .view_table import TableView
from .view_tree import TreeView
from .view_file import FileView
from .view_buttons import ButtonsView
from .view_sync import SyncView
from .view_rehash import REHASH_TIP, RehashView


class FileListWindow(TableView, TreeView, FileView, ButtonsView, SyncView, RehashView, QWidget):
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
        self.rehash_btn = QPushButton('Досчитать хеш у выбранных…')        # 18.11.2026: только список «без хеша»
        self.rehash_btn.setToolTip(REHASH_TIP)
        self.rehash_btn.clicked.connect(self.rehash_selected)
        self.rehash_btn.setVisible(self.kind == 'nohash')
        self.refresh_btn = QPushButton('Обновить')
        self.refresh_btn.clicked.connect(self.load)
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close)
        for w in (self.open_btn, self.excel_btn, self.rescan_btn, self.rehash_btn):
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


def open_list(win, page=None, **spec):
    """Открыть окно «Список файлов» (из «Разбора носителя» и «Дисков и папок»). -> окно."""
    w = FileListWindow(win, page=page, **spec)
    if not hasattr(win, 'file_lists'):
        win.file_lists = []
    win.file_lists.append(w)
    w.show()
    return w
