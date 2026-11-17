"""Направления: секция в «Обзоре» и строка-карточка направления. Вынесено из directions_page.py без изменений кода."""
import disk_ui

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from hb_core.razbor_base import COPY_ROOT

from directions_choice import save_choice, section_data
from directions_look import (CARD_BG, CARD_BORDER, CHECKED_BG, GO_TEXT, OFF, OFF_BADGE, ON, RAZBOR_PAGE, FlowLayout,
                             disk_row_html, html_esc, kind_tags, show_num, tag_label)
from directions_dialog import ASSIGN, CARD, DirectionDialog


class DirectionCard(QFrame):
    """Одна строка-карточка направления: галочка · имя, описание, диски, «Что копировать:» тегами, плашки «📁 Файлы
    будут скопированы в папку …» (по одной на диск) · кнопка «Изменить» / «Назначить диск»."""

    def __init__(self, section, d):
        super().__init__()
        self.section, self.d, self.num = section, d, d.num
        self.setObjectName('dircard')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)
        self.box = QCheckBox()
        self.box.setEnabled(bool(d.disks))
        self.box.setToolTip('Отметить: для этого направления пишем команды копирования' if d.disks else
                            'Сначала назначьте направлению диск («Назначить диск»)')
        lay.addWidget(self.box, 0, Qt.AlignTop)
        if d.disks:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip('Щелчок по строке — отметить или снять направление.')
        else:
            self.setToolTip('Сначала назначьте направлению диск («Назначить диск»).')
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.name = QLabel(f'<b>{html_esc(show_num(d.num))} {html_esc(d.name)}</b>')
        self.name.setWordWrap(True)
        f = self.name.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.name.setFont(f)
        if d.former:
            self.name.setToolTip('Прежние имена: ' + ', '.join(d.former))
        mid.addWidget(self.name)
        self.desc = QLabel(d.desc or '')
        self.desc.setWordWrap(True)
        self.desc.setStyleSheet('color:#555')
        self.desc.setVisible(bool(d.desc))
        mid.addWidget(self.desc)
        self.disks = QLabel('')
        self.disks.setTextFormat(Qt.RichText)
        self.disks.setWordWrap(True)
        mid.addWidget(self.disks)
        kinds = QWidget()
        kl = FlowLayout(kinds)
        what = QLabel('Что копировать:')
        what.setStyleSheet('color:#555')
        kl.addWidget(what)
        tags, small = kind_tags(d.kind)
        self.tags = [t for t, _ in tags]
        self.small = small
        for text, look in tags:
            kl.addWidget(tag_label(text, look))
        if small:
            s = QLabel(small)
            s.setStyleSheet('color:#777; font-size:8pt')
            kl.addWidget(s)
        mid.addWidget(kinds)
        self.folders = []                  # плашка на каждый диск направления; текст - в paint() (нужна буква диска)
        for _ in d.disks:
            lab = QLabel('')
            lab.setStyleSheet(FOLDER_CSS)
            lab.setToolTip('Сюда на архивном диске попадут файлы; внутри — папка с именем носителя')
            self.folders.append(lab)
            row = QHBoxLayout()
            row.addWidget(lab)
            row.addStretch()
            mid.addLayout(row)
        lay.addLayout(mid, 1)
        self.btn = QPushButton('Изменить' if d.disks else 'Назначить диск')
        self.btn.setToolTip('Имя, описание и «что копировать». Диски здесь не меняются.' if d.disks else
                            'Диск выбирается один раз — при первом назначении.')
        self.btn.clicked.connect(lambda: section.edit(self.num) if self.d.disks else section.assign(self.num))
        lay.addWidget(self.btn, 0, Qt.AlignTop)

    def mousePressEvent(self, e):                              # noqa: N802
        """Щелчок по строке целиком (надписи без ссылок пропускают щелчок сюда; кнопка забирает его себе) - галочка."""
        if e.button() == Qt.LeftButton and self.box.isEnabled():
            self.box.toggle()
            e.accept()
            return
        super().mousePressEvent(e)

    def paint(self, writing):
        """Отмеченная - светло-зелёный фон; диски - оранжевым у отмеченной, зелёным у остальных."""
        self.writing = writing
        bg = CHECKED_BG if writing else CARD_BG
        border = '#81c784' if writing else CARD_BORDER
        self.setStyleSheet(f'QFrame#dircard {{ background:{bg}; border:1px solid {border}; border-radius:6px; }}')
        data = self.section.data
        if not self.d.disks:
            self.disks.setText('<span style="color:#c62828">диск не назначен</span>')
        else:
            many = len(self.d.disks) > 1                    # «(копия 1/2)» - только у направления на нескольких дисках
            self.disks.setText('<br>'.join(disk_row_html(x, data['by'], data['free'], writing, i if many else 0)
                                           for i, x in enumerate(self.d.disks, 1)))
        for i, (x, lab) in enumerate(zip(self.d.disks, self.folders), 1):
            lab.setText(folder_text(x, data['by'], i if len(self.d.disks) > 1 else 0))


FOLDER_CSS = 'color:#37474f; background:#f5f7fa; border:1px solid #b0bec5; border-radius:4px; padding:2px 8px'


def folder_text(disk, by, copy_no=0):
    """Плашка под дисками: подключён - «📁 Файлы будут скопированы в папку H:\\ПЕРЕНОС с других дисков»; не подключён -
    «… на диск HDD78 в папку «ПЕРЕНОС с других дисков»». copy_no - «(копия N)» у направления на нескольких дисках."""
    letter = ((by.get(disk) or {}).get('letter') or '').rstrip('\\').rstrip(':')
    tail = f' (копия {copy_no})' if copy_no else ''
    if letter:
        return f'📁 Файлы будут скопированы в папку {letter}:\\{COPY_ROOT}{tail}'
    return f'📁 Файлы будут скопированы на диск {disk} в папку «{COPY_ROOT}»{tail}'


TITLE_TEXT = 'Выберите Архивный диск для наполнения его файлами'
SUB_TEXT = ('Отметьте галочкой одно или несколько направлений. У каждого направления свой диск: туда попадут файлы '
            'с носителя.')                 # 17.11.2026: с экрана убрано; имя оставлено для прежних импортов
ADD_TEXT = '+ Добавить архивный диск…'
ADD_CSS = ('QPushButton { background:#e3f2fd; border:1px solid #1e88e5; color:#0d47a1; font-weight:bold; '
           'border-radius:6px; padding:2px 12px; } QPushButton:hover { background:#bbdefb; }')
NONE_TEXT = 'Диск не выбран'
SECTION_CSS = 'QFrame#dirsection { background:#fbfcfd; border:1px solid #c5ced8; border-radius:8px; }'


def add_height():
    """Высота кнопки «+ Добавить архивный диск…» - в 1,5 раза больше прежней мелкой (8pt, поля 2px 8px): замер на месте,
    чтобы на любом экране и шрифте соотношение было тем же."""
    old = QPushButton('+ Добавить направление…')
    old.setStyleSheet('QPushButton { font-size:8pt; color:#37474f; padding:2px 8px; }')
    old.ensurePolished()
    h = round(old.sizeHint().height() * 1.5)
    old.deleteLater()
    return h


def legend_html():
    """Легенда цветов одной строкой под списком направлений."""
    bg, fg, _ = OFF_BADGE
    return (f'<b style="color:{disk_ui.ASSIGNED_ON}">оранжевый</b> — выбран для копирования &nbsp;·&nbsp; '
            f'<b style="color:{disk_ui.DIR_ON}">зелёный</b> — не выбран &nbsp;·&nbsp; '
            f'<span style="background:{bg}; color:{fg}">&nbsp;не подключён&nbsp;</span> — подключите перед копированием')


class DirectionsSection(QFrame):
    """Карточка «Выберите Архивный диск для наполнения его файлами» (этап 11, 16.11.2026; 17.11.2026 - без пояснения):
    заголовок, справа голубая «+ Добавить архивный диск…»; строки-карточки направлений (щелчок по строке - галочка); легенда цветов под
    списком; внизу «Копируем на: …» / «Диск не выбран» и «Дальше: выбрать папки на носителе →»."""

    def __init__(self, win):
        super().__init__()
        self.win, self.data, self.filling, self.note = win, None, False, ''
        self.cards = {}                    # номер направления -> DirectionCard
        self.on_choice = None              # «Обзор»: перерисовать нижнюю таблицу дисков (щелчок галочки, перечитывание)
        self.on_saved = None               # «Обзор»: после сохранения в диалоге перечитать всё
        self.setObjectName('dirsection')
        self.setStyleSheet(SECTION_CSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel(TITLE_TEXT)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 5)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        self.title.setStyleSheet('color:#1f2933; background:transparent; border:none')
        top.addWidget(self.title, 1)
        self.b_add = QPushButton(ADD_TEXT)
        self.b_add.setToolTip('Новый архивный диск: имя, что собирается, что копировать и диск.')
        self.b_add.setMinimumHeight(add_height())
        self.b_add.setStyleSheet(ADD_CSS)
        self.b_add.clicked.connect(self.add)
        top.addWidget(self.b_add, 0, Qt.AlignTop)
        lay.addLayout(top)
        lay.addSpacing(4)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        lay.addLayout(self.list)
        self.legend = QLabel(legend_html())
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet('color:#555; font-size:9pt; background:transparent; border:none')
        lay.addWidget(self.legend)
        self.hint = QLabel('')                 # «Сохранено: …» после диалога; пусто - скрыта
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color:#555; background:transparent; border:none')
        self.hint.setVisible(False)
        lay.addWidget(self.hint)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet('color:#d0d7de; background:#d0d7de; border:none; max-height:1px')
        lay.addWidget(line)
        bar = QHBoxLayout()
        self.target = QLabel('')
        self.target.setTextFormat(Qt.RichText)
        self.target.setWordWrap(True)
        self.target.setStyleSheet('background:transparent; border:none')
        f = self.target.font()
        f.setPointSizeF(f.pointSizeF() + 1)
        self.target.setFont(f)
        bar.addWidget(self.target, 1)
        self.b_go = QPushButton(GO_TEXT)
        f = self.b_go.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 1)
        self.b_go.setFont(f)
        self.b_go.setMinimumHeight(32)
        self.b_go.setStyleSheet('QPushButton { padding:4px 14px; }')
        self.b_go.clicked.connect(self.go)
        bar.addWidget(self.b_go, 0, Qt.AlignVCenter)
        lay.addLayout(bar)
        self.update_buttons()

    # --- данные ---
    def refresh(self):
        self.win.bg.run(section_data, ok=self.render)

    def render(self, data):
        self.data = data
        choice = set(data['choice'])
        self.filling = True
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.cards = {}
        for d in data['dirs'].values():
            card = DirectionCard(self, d)
            card.box.setChecked(bool(d.disks) and d.num in choice)
            card.box.toggled.connect(self.on_toggled)
            self.cards[d.num] = card
            self.list.addWidget(card)
        self.filling = False
        self.paint_disks()
        self.update_buttons()
        if self.on_choice:
            self.on_choice()

    def paint_disks(self):
        """Щелчок галочки: фон карточки и цвета дисков - без перечитывания базы."""
        if self.data is None:
            return
        on = set(self.checked())
        for num_, card in self.cards.items():
            card.paint(num_ in on)

    # --- выбор ---
    def checked(self):
        return [n for n, c in self.cards.items() if c.d.disks and c.box.isChecked()]

    def set_checked(self, num_, on=True):
        """Поставить/снять галочку направления (как щелчок владельца)."""
        self.cards[num_].box.setChecked(on)

    def on_toggled(self, *_):
        if self.filling:
            return
        nums = self.checked()
        save_choice(nums)
        if self.data is not None:
            self.data['choice'] = nums
        self.paint_disks()
        self.update_buttons()
        if self.on_choice:
            self.on_choice()

    def has_razbor(self):
        return RAZBOR_PAGE in [n for n, _ in getattr(self.win, 'pages', [])]

    def update_buttons(self):
        nums = self.checked()
        if not self.has_razbor():
            self.b_go.setEnabled(False)
            self.b_go.setToolTip('Экран «Разбор носителя» ещё не готов.')
        elif not nums:
            self.b_go.setEnabled(False)
            self.b_go.setToolTip('Сначала отметьте галочкой хотя бы одно направление.')
        else:
            self.b_go.setEnabled(True)
            self.b_go.setToolTip('Откроется «Разбор носителя»: там отмечают папки, которые копировать.')
        dirs = self.data['dirs'] if self.data else {}
        names = [dirs[n].name for n in nums if n in dirs]
        if names:
            self.target.setText(f'<b style="color:{ON}">Копируем на: {html_esc(", ".join(names))}</b>')
        else:
            self.target.setText(f'<span style="color:{OFF}">{NONE_TEXT}</span>')
        self.hint.setText(html_esc(self.note) if self.note else '')
        self.hint.setVisible(bool(self.note))

    def go(self):
        nums = self.checked()
        if not nums or not self.has_razbor():
            return
        save_choice(nums)
        page = self.win.page(RAZBOR_PAGE) if hasattr(self.win, 'page') else None
        if page is not None and hasattr(page, 'use_choice'):
            page.use_choice()                     # экран уже открывался: списки «Куда» - на отмеченное направление
        self.win.open_page(RAZBOR_PAGE)

    # --- запись ---
    def add(self):
        if self.data is None:
            return
        DirectionDialog(self, self.data, None).exec()

    def edit(self, num_):
        """Только карточка: имя, «что собирается», «что копировать». Диски не показываются и не меняются."""
        if self.data is None or num_ not in self.data['dirs']:
            return
        DirectionDialog(self, self.data, self.data['dirs'][num_], mode=CARD).exec()

    def assign(self, num_):
        """Первое назначение диска - только направлению без диска (смены диска в окне нет)."""
        d = self.data['dirs'].get(num_) if self.data else None
        if d is None or d.disks:
            return
        DirectionDialog(self, self.data, d, mode=ASSIGN).exec()
