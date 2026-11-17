"""«Задания на копирование»: TasksPage - сборка экрана (__init__: раскладка и связи сигналов) из частей view_* и flow_*.

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os

from ui_common import StepsBar

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QScrollArea, QTableWidget, QToolButton, QVBoxLayout, QWidget)

from .texts_words import INTRO, MOVE_NOTE, RUN_NOTE
from .widgets import _small
from .view_table import TableView
from .view_done import DoneView
from .view_offers import OffersView
from .view_ask import AskView
from .flow_run import RunFlow


class TasksPage(TableView, DoneView, OffersView, AskView, RunFlow, QWidget):
    HEAD = ['', 'Что и куда', 'Состояние', 'Сделано', 'Ошибки']
    DONE_HEAD = ['Задание', 'Файлов', 'ГБ', 'Ошибок и пропусков', 'Дата']

    def __init__(self, win):
        super().__init__()
        self.win, self.rows, self.trows, self.checked, self.queue = win, [], [], set(), []
        self.dlist = []
        self.start_file = os.startfile                    # тесты подменяют: окно PowerShell не открывается
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.head = QLabel('Копирование')
        f = QFont()
        f.setPointSize(14)
        f.setBold(True)
        self.head.setFont(f)
        top.addWidget(self.head)
        top.addStretch()
        self.refresh_btn = QPushButton('Обновить')
        self.refresh_btn.clicked.connect(self.refresh)
        top.addWidget(self.refresh_btn)
        lay.addLayout(top)
        self.steps = StepsBar(win, 2)                     # шаги работы: «3. Копирование» (этап 11)
        lay.addWidget(self.steps)
        self.chips_lay = QHBoxLayout()
        self.chips = []
        lay.addLayout(self.chips_lay)
        self.sub = QLabel(INTRO)
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet('color:#37474f')
        lay.addWidget(self.sub)
        cap = QLabel('Задания')
        cap.setStyleSheet('font-weight:bold; margin-top:6px')
        lay.addWidget(cap)
        self.t = QTableWidget(0, len(self.HEAD))
        self.t.setHorizontalHeaderLabels(self.HEAD)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.verticalHeader().setVisible(False)
        hh = self.t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Interactive)      # ширина - по самой длинной строке «Что и куда»
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.setWordWrap(False)
        self.t.itemChanged.connect(self.on_check)
        lay.addWidget(self.t)
        bar = QHBoxLayout()
        self.run_btn = QPushButton('Запустить отмеченные (0)')
        self.run_btn.setStyleSheet('font-weight:bold')
        self.run_btn.clicked.connect(lambda: self.launch_checked())
        self.all_btn = QPushButton('Запустить все по очереди')
        self.all_btn.setToolTip('Все задания, которые ждут запуска или прерваны, — друг за другом в одном окне.')
        self.all_btn.clicked.connect(self.launch_all)
        self.log_btn = QPushButton('Открыть журнал')
        self.log_btn.clicked.connect(self.open_log)
        self.dir_btn = QPushButton('Открыть папку задания')
        self.dir_btn.clicked.connect(self.open_dir)
        for b in (self.run_btn, self.all_btn):
            bar.addWidget(b)
        bar.addStretch()
        for b in (self.log_btn, self.dir_btn):
            bar.addWidget(b)
        lay.addLayout(bar)
        lay.addWidget(_small(RUN_NOTE, '#37474f'))
        # ниже - блок перемещения и «Готово» (в прокрутке: список «Готово» может быть длинным)
        self.offers, self.done_items, self.groups = [], [], []
        self.blocks = QScrollArea()
        self.blocks.setWidgetResizable(True)
        self.blocks.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        bl = QVBoxLayout(inner)
        bl.setContentsMargins(0, 0, 0, 0)
        self.offer_box = QGroupBox('Скопировано — можно переместить папку на носителе')
        self.offer_lay = QVBoxLayout(self.offer_box)
        bl.addWidget(self.offer_box)
        self.move_note = _small(MOVE_NOTE)
        bl.addWidget(self.move_note)
        self.done_btn = QToolButton()
        self.done_btn.setCheckable(True)
        self.done_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.done_btn.setStyleSheet('QToolButton{border:none; font-weight:bold; padding:4px 0}')
        self.done_btn.toggled.connect(self.on_done_toggle)
        bl.addWidget(self.done_btn)
        self.done_t = QTableWidget(0, len(self.DONE_HEAD))
        self.done_t.setHorizontalHeaderLabels(self.DONE_HEAD)
        self.done_t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.done_t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.done_t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.done_t.verticalHeader().setVisible(False)
        self.done_t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.done_t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.done_t.setMinimumHeight(170)
        self.done_t.setVisible(False)
        self.done_t.cellDoubleClicked.connect(self.on_done_double)
        bl.addWidget(self.done_t)
        bl.addStretch()
        self.blocks.setWidget(inner)
        lay.addWidget(self.blocks, 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.t.itemSelectionChanged.connect(lambda: self._only_one(self.t, self.done_t))
        self.done_t.itemSelectionChanged.connect(lambda: self._only_one(self.done_t, self.t))
        self._done_title(0)
