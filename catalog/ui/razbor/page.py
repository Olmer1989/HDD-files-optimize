"""Страница окна «Разбор носителя» (логика v3, этап 2, 15.11.2026).

Документ - «Проверка Архитектуры сортировки файлов\Логика_v3_разбор_носителя.md» (разделы 1.2-1.6, 2.2, «Этап 2: экран»).
Владелец выбирает носитель и режим («всё - в направление, кроме отмеченных» или «ничего, кроме отмеченных»), ставит
папкам «Куда» (направление, «не копировать», «как у родителя») и сразу видит итог: что будет с каждым файлом (сумма =
опись) и сколько писать на каждый диск. Отметки сохраняются сразу (этап 16; прежде - «Сохранить отметки») через
service.add_marks_batch. «Подготовить задания» - расчёт, показ, создание через service.razbor_tasks, переход в «Задания».

Как устроено:
- Дерево строится по таблице folders (service.razbor_tree - один запрос, ≤ 60 тыс. папок); элементы дерева создаются
  только при раскрытии узла. «Куда» считается в окне по всем папкам одним проходом (Model.routes - те же правила, что в
  ядре: hb_core.razbor.planner, разбор отметок - общий hb_core.directions.MarkSet), после правки обновляются тексты
  уже созданных строк. Своя отметка - чёрным, унаследованная - серым «… — от «папка»», несохранённое - синим с «•».
- Черновик - несохранённые отметки окна: словарь «исходный путь без регистра → отметка». Итог считается с черновиком
  (service.razbor(disk, drafts)), задания - только из сохранённых отметок.
- Итог и «Уже есть» (service.razbor_have) - в фоне, не больше одного расчёта каждого вида; ответ принимается, только если
  с его запуска ничего не менялось (ревизия), иначе считается заново по последнему состоянию.
- Запись: в предпросмотр и запись уходит неизменяемая копия пакета; страница на это время недоступна. После любого
  исхода сохранённые отметки перечитываются, из черновика уходит только то, что совпало с сохранённым.
Подключение в окно: ('Разбор носителя', RazborPage(self)).

Этап 6 (15-16.11.2026, замечания владельца, документ - раздел «Этап 6»): вверху крупно «Куда» (направления, отмеченные
в «Обзоре»); колонки «Куда» в дереве нет - папка подкрашена цветом своего направления (своя отметка - ярко, унаследованная
- бледно, «не копировать» - серым и зачёркнуто), подсказка «Н2 Работа (78) (своя отметка)» / «(от папки …)»; справа -
крупные ячейки направлений и «Не копировать»: папки перетаскиваются в них мышью (та же черновая отметка, что у меню),
ячейка «Снять свою отметку» возвращает папке отметку родителя; полный итог - вкладка «Подробно». В ячейке - вместимость
по каждому диску (service.capacity: только недостающее на этом диске, кластер, запас max(2 ГиБ, 1 %), очередь других
носителей); не помещается - ячейка красная, её кнопка «Подготовить задания» неактивна. Перед созданием заданий - быстрая
сверка оглавления подключённого носителя с описью (service.toc_check); расхождение или носитель не подключён - задания
не создаются, предлагается «Пересканировать эти папки…».

Этап 8 (16.11.2026, макет владельца, документ - раздел «Этап 8»): вверху - выбранный диск назначения («Диск «Фильмы» —
I: My Book (WD 2 ТБ)»); «Выберите носитель»; «Диск назначения» (направление с диском, имя оранжевым) и три режима:
«Только выбранные папки» (корень ≠ D), «Все папки» и «Все, кроме выбранных» (корень = D). Колонка галочек слева -
вид отметок для D (Model.check): включить - Model.include_pairs, исключить - Model.exclude_pairs; несколько выделенных -
одним шагом отмены. Папка другого направления - пустая галочка и серая метка «Н2». Справа две ячейки: «Копировать на
диск …» (единственная цель перетаскивания, бросок = включить в D) и «Остаётся на носителе» (только сведения). Ядро и путь
записи отметок не менялись.

Этап 10 (16.11.2026, решения владельца, раздел «Этап 10»): заголовок «Диск: <буква> <метка>» + плашка «не подключён»;
верх - форма (подписи слева, сведения под полями); режимы - три кнопки, режим выбран всегда; Shift/Ctrl-выделение сразу
ставит галочки (DragTree.multi -> check_selected); «выбрать все» у строки носителя; в «Все, кроме» - красный; надпись
«Идёт пересчёт…» внизу слева; ячейки «Остаётся на носителе» нет. Модель и объём диска не показываются (disk_ui.disk_name).

Этап 12 (16.11.2026, раздел «Этап 12»): шаги - в самом верху; под заголовком ячейки - имя направления оранжевым жирным;
галочка любой выделенной папки (при нескольких выделенных) - у всей группы одним шагом отмены (выделение берётся на
нажатии мыши, DragTree.press_sel). Направление на нескольких дисках (45 и 77, вариант А владельца: отметка одна) - на
экране раздельно: заголовок «Диск: Семейный архив — две копии» и строка на каждый диск, короткий пункт «Диска
назначения», в ячейке - блок с рамкой на каждый диск (Cell.set_blocks, disk_block_html: часть Б ядра для этого диска и
«уже есть» на нём - Model.have_on_disk). Ядро, отметки и задания не менялись.

Этап 16 (16.11.2026, замечания владельца после проверки на настоящих данных, раздел «Этап 16»): кнопок «Сохранить
отметки» и «Отменить все несохранённые» нет - черновик пишется сразу (autosave: тот же service.add_marks_batch, без окна
предпросмотра; пакет в пути - Model.inflight, правки во время записи - следующим пакетом; отказ - сообщение, черновик
пакета забывается); «Отменить последнее» - шаг отмены хранит прежние свои отметки папок и возвращает их новой правкой
(тоже сохраняется). Зелёная плашка - «Диск назначения: H: Бэкап фото и видео — HDD45, 16 ТБ · свободно …» (head_html);
строки «Диск назначения» нет (диск - из «Обзора», шаг 1; список скрыт). В ячейке - «Показать список» у «копировать»,
«уже есть», «не подходит по типу» (окно filelist_window). Внизу - «Пересчитать хеши спорных файлов (N)» (N в фоне,
0 - неактивна), «Показать список», «Файлы только на этом носителе…» и строка «что такое спорные».
Пути папок нигде не обрезаются по пробелам (« Перемещение перед Индонезией - временное»).

Шаг А разбивки (17.11.2026): методы страницы перенесены без правки тел в части view_* и flow_* этого пакета;
карта файлов - docs/СТРУКТУРА_ПРОГРАММЫ.md."""
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout,
                               QWidget)

from ui_common import StepsBar

from .common import (CONTESTED_NOTE, C_CHECK, C_FILES, C_HAVE, C_NAME, C_OTHER, C_PHOTO, C_VIDEO, HEAD,
                     HEAD_BG, MODE_CSS, MODE_TEXT)
from .flow_autosave import AutosaveFlow, CloseGuard
from .flow_contested import ContestedFlow
from .flow_nohash import NohashFlow
from .flow_tasks import TasksFlow
from .texts_cell import BLUE, EVERY, EXCEPT, GRAY, ONLY, ORANGE
from .texts_head import carrier_text, legend_html
from .view_carrier import CarrierView
from .view_cell import Cell, CellView
from .view_checks import ChecksView
from .view_head import HeadView, RichCombo
from .view_list import ListView
from .view_summary import SummaryView
from .view_tree import DragTree, TreeDelegate, TreeView


class RazborPage(CarrierView, TreeView, HeadView, ChecksView, CellView, SummaryView, AutosaveFlow, TasksFlow, ListView,
                 ContestedFlow, NohashFlow, QWidget):
    marks_changed = Signal(int)                           # этап 17: отметки изменились (ревизия) - окну «Список файлов»
    saving_changed = Signal(bool)                         # идёт / закончилась запись отметок
    def __init__(self, win):
        super().__init__()
        self.win, self.model, self.disk, self.disk_rows = win, None, None, []
        self.items = {}                                   # физический путь папки -> элемент дерева
        self.rev = 0                                      # ревизия входов итога (любая правка, носитель, база)
        self.sum_busy = self.sum_pending = False
        self.have_busy = self.have_pending = False
        self.writing = False
        self.plan = None                                  # последний принятый итог: (план, место дисков, очередь, время)
        self.plan_rev = -1                                # его ревизия (равна self.rev - итог актуален)
        self.loading = None                               # носитель, данные которого читаются
        self.want_choice = True                           # поставить в списки направление, отмеченное в «Обзоре»
        self.dest = None                                  # номер направления - диска назначения
        self.mode_pref = {}                               # (носитель, направление) -> выбранный владельцем EVERY/EXCEPT
        self.painting = False                             # окно само ставит галочки - itemChanged не обрабатывать
        lay = QVBoxLayout(self)
        # 0. шаги работы «2. Что копируем» - в самом верху страницы, над заголовком (этап 11; решение владельца 16.11)
        self.steps = StepsBar(win, 1)
        lay.addWidget(self.steps)
        # 1. выбранный диск назначения - крупно; «Обновить» - справа (макет владельца, 16.11.2026)
        head = QHBoxLayout()
        self.where = QLabel('')
        self.where.setWordWrap(True)
        self.where.setTextFormat(Qt.RichText)
        self.where.setStyleSheet(f'font-size:15pt; font-weight:bold; color:#1b5e20; background:{HEAD_BG}; '
                                 'border:1px solid #a5d6a7; border-radius:4px; padding:8px')
        head.addWidget(self.where, 1)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        head.addWidget(b, 0, Qt.AlignTop)
        lay.addLayout(head)
        self.choice_line = self.where                     # прежнее имя (этап 5)
        # 2. форма: подписи слева столбиком, под полями - строки сведений
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(3)
        form.setColumnStretch(1, 1)

        def caption(text):
            lab = QLabel(f'<b>{text}</b>')
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lab
        from commands_page import DiskCombo               # тот же список, что в «Командах»: подключённые сверху
        self.disk_box = DiskCombo(optional=False, text_fn=carrier_text)
        self.disk_box.setMinimumHeight(QFontMetrics(self.disk_box.font()).height() + 16)
        self.disk_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.disk_box.currentIndexChanged.connect(self.disk_changed)
        form.addWidget(caption('Выберите носитель'), 0, 0)
        form.addWidget(self.disk_box, 0, 1)
        self.info = QLabel('')
        self.info.setTextFormat(Qt.RichText)
        self.info.setStyleSheet(f'color:{GRAY}')
        self.info.setWordWrap(True)
        form.addWidget(self.info, 1, 1)
        form.setRowMinimumHeight(1, 22)
        # этап 16 (решение владельца): строки «Диск назначения» под плашкой нет - диск выбирается в «Обзоре», шаг 1.
        # Список остаётся невидимым (set_dest - переходы и тесты), сведения о диске - в зелёной плашке вверху.
        self.dest_box = RichCombo()
        self.dest_box.activated.connect(self.dest_changed)
        self.dest_box.setParent(self)
        self.dest_box.hide()
        self.dest_info = QLabel('')
        self.dest_info.setParent(self)
        self.dest_info.hide()
        # «Что копировать с носителя»: три отдельные кнопки с промежутками (вариант 1), на ширину поля
        modes = QWidget()
        ml = QHBoxLayout(modes)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(12)
        self.mode_only = QPushButton(MODE_TEXT[ONLY])
        self.mode_every = QPushButton(MODE_TEXT[EVERY])
        self.mode_except = QPushButton(MODE_TEXT[EXCEPT])
        self.mode_only.setToolTip('Копируются только папки с галочкой. Остальное остаётся на носителе (или идёт туда, '
                                  'куда отмечен весь носитель).')
        self.mode_every.setToolTip('Весь носитель - на этот диск. Исключения («не копировать») снимаются; папки, '
                                   'отмеченные для другого диска, остаются за ним (метка «Н2»).')
        self.mode_except.setToolTip('Весь носитель - на этот диск, кроме папок с галочкой: галочка здесь значит '
                                    '«не копировать» (такие папки - красным).')
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_btn = {ONLY: self.mode_only, EVERY: self.mode_every, EXCEPT: self.mode_except}
        for k, w in self.mode_btn.items():
            w.setCheckable(True)
            w.setMinimumHeight(QFontMetrics(w.font()).height() + 16)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.setStyleSheet(MODE_CSS)
            self.mode_group.addButton(w)
            w.toggled.connect(lambda on, k=k: on and self.mode_changed(k))
            ml.addWidget(w, 1)
        self.mode_only.setChecked(True)                   # режим выбран всегда; по умолчанию «Только выбранные»
        form.addWidget(caption('Что копировать с носителя'), 4, 0)
        form.addWidget(modes, 4, 1)
        note = QHBoxLayout()
        self.mode_note = QLabel('')                       # строка пояснения выбранного режима
        self.mode_note.setWordWrap(True)
        self.mode_note.setTextFormat(Qt.RichText)
        self.mode_note.setStyleSheet('color:#37474f')
        note.addWidget(self.mode_note, 1)
        self.mode_hint = QLabel('')
        self.mode_hint.setStyleSheet(f'color:{BLUE}')
        note.addWidget(self.mode_hint)
        form.addLayout(note, 5, 1)
        lay.addLayout(form)
        self.banner = QLabel('')
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f'background:#fff3e0; color:{ORANGE}; padding:6px; border:1px solid #ffcc80')
        self.banner.hide()
        lay.addWidget(self.banner)
        # 4. дерево слева, ячейки справа
        split = QSplitter(Qt.Horizontal)
        g2 = QWidget()
        l2 = QVBoxLayout(g2)
        l2.setContentsMargins(0, 0, 0, 0)
        self.tree_hint = QLabel('Поставьте галочки у нужных папок или перетащите папки в ячейку справа. Shift/Ctrl — '
                                'несколько папок сразу: выделенным галочки ставятся сами; галочка у любой выделенной '
                                'меняется у всех выделенных.')
        self.tree_hint.setWordWrap(True)
        l2.addWidget(self.tree_hint)
        self.tree = DragTree(self)
        self.tree.setHeaderLabels(HEAD)
        self.tree.setTreePosition(C_NAME)                 # галочки - ровной колонкой слева, ветви дерева - у имени
        self.tree.setItemDelegate(TreeDelegate(self.tree))
        hd = self.tree.header()
        hd.setSectionResizeMode(QHeaderView.Interactive)
        hd.setStretchLastSection(False)
        self.tree.setColumnWidth(C_CHECK, 30)
        hd.setSectionResizeMode(C_NAME, QHeaderView.Stretch)   # имя - на остаток ширины: числа видны без прокрутки
        for c in range(C_FILES, C_HAVE + 1):                 # числа - по ширине (строк немного: дерево ленивое)
            hd.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        tips = {C_CHECK: 'Галочка - папка выбрана для диска назначения (в режиме «Все, кроме выбранных» - исключена).',
                C_NAME: 'Зелёный фон - выбранные папки. Наведите мышь на папку - подсказка. Перетащите папку в ячейку '
                        '«Копировать на диск» справа.',
                C_PHOTO: 'Число фото в папке с подпапками', C_VIDEO: 'Число видео в папке с подпапками',
                C_OTHER: 'Документы, прочие файлы и мусор (Thumbs.db и т. п.)',
                C_HAVE: 'Файлов с хешем, которые уже лежат на ВСЕХ дисках своего направления (по базе): их копировать '
                        'не нужно. «—» - направления с диском нет.'}
        for c, t in tips.items():
            self.tree.headerItem().setToolTip(c, t)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemClicked.connect(self.more_clicked)       # «ещё N папок — показать» (этап 17)
        self.tree.itemChanged.connect(self.item_changed)
        l2.addWidget(self.tree, 1)
        legend = QLabel(legend_html(ONLY))
        self.tree_legend = legend
        legend.setWordWrap(True)
        legend.setStyleSheet('font-size:8pt; color:#616161')
        l2.addWidget(legend)
        split.addWidget(g2)
        right = QWidget()
        l3 = QVBoxLayout(right)
        l3.setContentsMargins(0, 0, 0, 0)
        self.sum_state = QLabel('')
        self.sum_state.setWordWrap(True)
        l3.addWidget(self.sum_state)
        self.tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cells_box = QWidget()
        self.cells_lay = QVBoxLayout(self.cells_box)
        self.copy_cell = Cell(self, True)
        self.cells_lay.addWidget(self.copy_cell)           # ячейку «Остаётся на носителе» владелец убрал (16.11)
        self.cells_lay.addStretch()
        self.cells = {'copy': self.copy_cell}
        scroll.setWidget(self.cells_box)
        self.tabs.addTab(scroll, 'Копирование')
        self.summary = QTextBrowser()
        self.tabs.addTab(self.summary, 'Подробно (что с каждым файлом)')
        l3.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([820, 540])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        # кнопки
        bar = QHBoxLayout()
        self.busy_lab = self.copy_cell.busy                # этап 17: плашка - в ячейке «Копировать на диск …»
        self.blink = QTimer(self)
        self.blink.setInterval(500)
        self.blink.timeout.connect(self.blink_busy)
        self.views = {}                                    # этап 17: показанный вид строки дерева (путь -> кортеж)
        # этап 16: «Сохранить отметки» и «Отменить все несохранённые» убраны - отметки сохраняются сразу
        self.undo_btn = QPushButton('Отменить последнее')
        self.undo_btn.setToolTip('Вернуть отметки, какими они были до последнего действия (это тоже сохраняется сразу).')
        self.undo_btn.clicked.connect(self.undo)
        # 17.11.2026: не главное место - «без хеша» того, что пойдёт на диск, теперь в ячейке; здесь - весь носитель
        self.contested_btn = QPushButton('Спорные по всему носителю…')
        self.contested_btn.setFlat(True)
        self.contested_btn.setStyleSheet('QPushButton { color:#1565c0; text-decoration:underline; border:none; }')
        self.contested_btn.setToolTip('Где лежат файлы без хеша и неподтверждённые копии выделенной папки (или всего '
                                      'носителя, со всеми служебными файлами); подключённые диски - пересканировать с '
                                      'хешем всех файлов.')
        self.contested_btn.clicked.connect(self.contested)
        self.contested_list_btn = QPushButton('Показать список')
        self.contested_list_btn.setToolTip('Спорные файлы поштучно: папка, имя, тип, размер, дата, на каком диске и '
                                           'почему спорный.')
        self.contested_list_btn.clicked.connect(lambda: self.show_list('contested'))
        self.unique_btn = QPushButton('Файлы только на этом носителе…')
        self.unique_btn.setToolTip('Файлы выделенной папки (или всего носителя), подтверждённая копия которых по SHA-256 '
                                   'есть только здесь.')
        self.unique_btn.clicked.connect(lambda: self.show_list('unique'))
        self.tasks_btn = self.copy_cell.btn                # «Подготовить задания» - в ячейке «Копировать на диск»
        bar.addWidget(self.undo_btn)
        bar.addStretch()
        for w in (self.unique_btn, self.contested_btn, self.contested_list_btn):
            bar.addWidget(w)
        self.contested_note = QLabel(CONTESTED_NOTE)
        self.contested_note.setWordWrap(True)
        self.contested_note.setAlignment(Qt.AlignRight)
        self.contested_note.setStyleSheet(f'font-size:8pt; color:{GRAY}')
        lay.addWidget(self.contested_note)
        lay.addLayout(bar)
        self.saving = False                               # идёт автосохранение отметок (этап 16)
        self.save_failed = False                          # запись упала ошибкой - ждём следующей правки (этап 17)
        self.save_job = None                              # идущая запись: событие окончания и её ответ (этап 17)
        self.save_then = []                               # что сделать после записи (подготовка заданий)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.autosave)
        self.root_before = {}                             # (носитель, D) -> отметка всего носителя до «Все папки»
        self.nh = None                                    # «без хеша»: ключ (носитель, ревизия, направление) и ответ
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.run_summary)
        self.guard = CloseGuard(self)
        win.installEventFilter(self.guard)
        self.update_buttons()
