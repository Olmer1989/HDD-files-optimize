"""«Диски и папки»: DisksPage - сборка экрана (__init__: раскладка и связи сигналов) из частей view_* и flow_folder.

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from ui_common import table

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSplitter, QTreeWidget, QVBoxLayout, QWidget)

from .texts_disks import WHY_TEXT
from .texts_tree import TYPE_COLORS, TYPE_NAMES
from .common import T_DEC, T_NAME, T_NOHASH
from .view_delegate import FolderDelegate
from .view_disks import DisksView
from .view_info import InfoView
from .view_tree import TreeView
from .view_select import SelectView
from .flow_folder import FolderFlow
from .flow_rehash import RehashFlow
from .view_search import SearchView


class DisksPage(DisksView, InfoView, TreeView, SelectView, FolderFlow, RehashFlow, SearchView, QWidget):
    """«Диски и папки» (16.11.2026, «всё оставляем, но красиво»): поиск, носители, папки выбранного носителя с составом,
    решением владельца и панелью действий. Действия берут носитель из самой строки (найденные папки - с разных дисков)."""
    HEAD = ['Диск', 'Подключён', 'Свободно', 'Файлов', 'ГБ', 'Сканирование']
    TREE = ['', 'Папка', 'Файлов', 'ГБ', 'Без хеша', 'фото', 'видео', 'тексты', 'прочие', 'мусор', 'Решение владельца']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.disk, self.found = win, [], None, False   # found - показаны найденные папки
        self.want = None
        self.nohash = {}                # этап 16: носитель -> nohash_info (столбец «Без хеша»), до новой сборки базы
        self.nohash_busy = set()
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
        self.hash_lab = QLabel('')                      # этап 16: «Хеш есть у всех фото и видео · Без хеша: N … · Показать»
        self.hash_lab.setTextFormat(Qt.RichText)
        self.hash_lab.setWordWrap(True)
        self.hash_lab.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
        self.hash_lab.linkActivated.connect(lambda _h: self.show_nohash(self.disk, ''))
        hl = QHBoxLayout()
        hl.addWidget(self.hash_lab, 1)
        self.rehash_btn = QPushButton('Досчитать хеш фото и видео…')    # 18.11.2026: окно пересканирования, «Фото»+«Видео»
        self.rehash_btn.clicked.connect(self.rehash_media)
        self.rehash_btn.hide()
        hl.addWidget(self.rehash_btn, 0, Qt.AlignTop)
        ll.addLayout(hl)
        legend = QLabel('Полоска под именем — состав папки: ' + ' '.join(
            f'<span style="background:{c}">&nbsp;&nbsp;&nbsp;</span>&nbsp;{n}&nbsp;&nbsp;' for n, c in
            zip(TYPE_NAMES, TYPE_COLORS)) + ' · столбцы типов — в ГБ; «Без хеша» — файлов без SHA-256 (щелчок по '
            'числу — их список); «↑» у решения — от родительской папки.')
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
        self.tree.itemClicked.connect(self.item_clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)               # правый щелчок: «Досчитать хеш в этой папке…»
        self.tree.customContextMenuRequested.connect(self.tree_menu)
        self.tree.headerItem().setToolTip(T_NOHASH, 'Файлов без хеша (SHA-256) в папке вместе с подпапками (размер больше '
                                                    'нуля). Щелчок по числу - их список.')
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
                                    'галочкой на вкладке «Назначить Архивный диск».')
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
