"""Секция «Направления» вверху раздела «Обзор» (логика v3, этап 4, 15.11.2026).

Пожелание владельца: назначить диски для конечного копирования (45 и 77 - «Семейный архив», у других направлений -
свои диски), у каждого направления описание «что собирается на этих дисках», галочки «для этих направлений пишем
команды копирования» и кнопка «Перейти к написанию команды на копирование →» (экран «Разбор носителя»).

Таблицу направлений пишет только service (direction_save_preview -> direction_save: предпросмотр, затем под замком
та же проверка и одна строка; копия таблицы - в архив). Этап 5 (15.11.2026): в диалоге нет «Проверить» - «Сохранить»
сразу; переспрос (текст предпросмотра) - только при смене или удалении диска у направления, у которого есть задания или
данные на убираемом диске (service: confirm). «Что копировать» - галочки категорий (hb_core.directions.parse_kind).
Цвета дисков: оранжевый - назначен направлению, зелёный - подключён и свободен, серый - не подключён (disk_ui). Галочки - выбор окна, а не таблица владельца: файл
«_БАЗА\\окно - выбор направлений.json». Экран «Разбор носителя» читает выбор через chosen() (один контракт).
Второй круг замечаний (16.11.2026): «Изменить…» - только карточка (имя, «что собирается», «что копировать»), диски не
показываются и не меняются; смены диска в окне нет - диск выбирается при создании направления или один раз
(«Назначить диск…») у направления без диска; в таблице диски зелёные, оранжевые - только у отмеченных галочкой.
Документ - «Логика_v3_разбор_носителя.md», разделы «Этап 4», «Этап 5», «Этап 7».
"""
import json
import os
import shutil
import time

from hb_core import api as hb
import service as sv
import disk_ui

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser,
                               QVBoxLayout, QWidget)

CHOICE_NAME = 'окно - выбор направлений.json'
RAZBOR_PAGE = 'Разбор носителя'
KINDS = (hb.KIND_MEDIA, hb.KIND_ALL)
# галочки «Что копировать»: категория ядра -> подпись окна
CAT_LABELS = ((hb.CAT_PHOTO, 'Фото'), (hb.CAT_VIDEO, 'Видео'), (hb.CAT_DOC, 'Документы (Word, Excel, PDF, тексты)'),
              (hb.CAT_ARCH, 'Архивы'), (hb.CAT_PROJ, 'Проекты монтажа и графики'), (hb.CAT_MUSIC, 'Музыка'),
              (hb.CAT_OTHER, 'Другие'))
NEAR_TEXT = 'Документы — только рядом с фото и видео'
NEAR_TIP = ('«Рядом» — в той же папке или в её подпапках есть хотя бы одно фото или видео, которое идёт в это же '
            'направление (подпапки с другой отметкой и корень носителя не считаются).')
NEVER_TEXT = ('Программы, системные и временные файлы (exe, dll, msi, ini, tmp, Thumbs.db и т. п.) не копируются никогда. '
              '«Все файлы» — все, кроме них.')
GO_TEXT = 'Перейти к написанию команды на копирование →'
HEADERS = ('Пишем команды', 'Направление', 'Что собирается на дисках', 'Диски', 'Свободно', 'Что копировать',
           'Папка на носителе после переноса')
ON, OFF = '#1b5e20', '#8a8a8a'


# ---------- выбор направлений (выбор окна, не таблица владельца) ----------

def choice_path():
    return hb.BASE_DIR / CHOICE_NAME


def load_choice():
    """Номера направлений, отмеченных галочкой (как записаны). Нет файла или он испорчен - пусто."""
    try:
        data = json.loads(choice_path().read_text(encoding='utf-8'))
        return [str(x) for x in data.get('направления', [])]
    except (OSError, ValueError, AttributeError):
        return []


def save_choice(nums):
    """Целиком и заменой файла (читатель видит старое или новое содержимое)."""
    p = choice_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps({'направления': list(nums), 'дата': time.strftime('%d.%m.%Y %H:%M')},
                              ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, p)


def chosen(dirs=None):
    """Для экрана «Разбор носителя»: отмеченные направления, которые есть сейчас и у которых есть диск, по номеру.
    -> [Direction]. Направления читаются заново: выбор хранит только номера."""
    dirs = sv.directions() if dirs is None else dirs
    want = set(load_choice())
    return [d for d in dirs.values() if d.num in want and d.disks]


# ---------- данные секции ----------

def section_data():
    """Направления, носители базы (подключённые - с буквой) и свободное место подключённых дисков направлений."""
    dirs = sv.directions()
    rows = sv.disks()
    by = {r['disk']: r for r in rows}
    free = {}
    for d in {x for v in dirs.values() for x in v.disks}:
        letter = (by.get(d) or {}).get('letter')
        if letter:
            try:
                free[d] = shutil.disk_usage(letter + '\\').free / hb.GIB
            except OSError:
                pass
    return dict(dirs=dirs, disks=rows, by=by, free=free, choice=load_choice())


def gb(x):
    return f'{x:,.0f}'.replace(',', ' ')


def kind_text(kind):
    """«Что копировать» для таблицы: прежние значения и наборы категорий как записаны; нераспознанное - пометкой."""
    cats, near, ok = hb.parse_kind(kind)
    if not ok:
        return f'не распознано («{kind}») — ничего не копируется'
    if cats == hb.ALL_CATS and not near:
        return 'все файлы (кроме программ и временных)'
    return hb.kind_text(cats, near)


# ---------- секция в «Обзоре»: строки-карточки (четвёртый круг, 16.11.2026) ----------

CHECKED_BG, CARD_BG, CARD_BORDER = '#e8f5e9', '#ffffff', '#d0d7de'
TAG_BLUE = ('#e3f2fd', '#1565c0', '#90caf9')          # фон, текст, рамка тега категории
TAG_GRAY = ('#eeeeee', '#424242', '#bdbdbd')
TAG_RED = ('#ffebee', '#c62828', '#ef9a9a')
OFF_BADGE = ('#f3e5d8', '#a1662f', '#d7b899')         # плашка «не подключён» (серо-оранжевая)
# короткие подписи категорий для тегов (порядок - как в диалоге)
TAG_LABELS = ((hb.CAT_PHOTO, 'Фото'), (hb.CAT_VIDEO, 'Видео'), (hb.CAT_DOC, 'Документы'), (hb.CAT_ARCH, 'Архивы'),
              (hb.CAT_PROJ, 'Проекты монтажа и графики'), (hb.CAT_MUSIC, 'Музыка'), (hb.CAT_OTHER, 'Другие'))


def kind_tags(kind):
    """«Что копировать» тегами: -> ([(текст, 'blue'/'gray'/'red')], мелкая приписка)."""
    cats, near, ok = hb.parse_kind(kind)
    if not ok:
        return [(f'не распознано («{kind}») — ничего не копируется', 'red')], ''
    if cats == hb.ALL_CATS and not near:
        return [('Все файлы', 'gray')], 'кроме программ и временных'
    tags = []
    for cat, text in TAG_LABELS:
        if cat in cats:
            tags.append((NEAR_TEXT if cat == hb.CAT_DOC and near else text, 'blue'))
    return tags, ''


def badge_css(colors, bold=False):
    bg, fg, border = colors
    return (f'background:{bg}; color:{fg}; border:1px solid {border}; border-radius:9px; padding:1px 8px;'
            + (' font-weight:bold;' if bold else ''))


class FlowLayout(QLayout):
    """Раскладка «в строку с переносом» (теги): ничего не уходит за правый край."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items, self.gap = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):                                   # noqa: N802
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):                                       # noqa: N802
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):                                       # noqa: N802
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):                             # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):                               # noqa: N802
        return True

    def heightForWidth(self, w):                               # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):                               # noqa: N802
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):                                        # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                                     # noqa: N802
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self.items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self.gap, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line = max(line, hint.height())
        return y + line - rect.y()


def tag_label(text, look):
    lab = QLabel(text)
    lab.setObjectName('tag')
    lab.setProperty('look', look)
    lab.setStyleSheet(badge_css({'blue': TAG_BLUE, 'gray': TAG_GRAY}.get(look, TAG_RED)))
    return lab


def disk_row_html(disk, by, free, writing):
    """Строка диска в карточке: «I: My Book — HDD55 · свободно 421 ГБ» (подключён) или «My Book — HDD55» и плашка
    «не подключён». Цвет: оранжевый - направление отмечено галочкой; зелёный - нет; неподключённый - бледнее."""
    r = by.get(disk) or {'disk': disk, 'label': '', 'letter': ''}
    on = bool(r.get('letter'))
    color, bold = disk_ui.dir_disk_color(on, writing)
    label = disk_ui.disk_name(r)
    text = html_esc(' — '.join(x for x in (disk_ui.disk_place(r) if label else r.get('letter'), disk) if x))
    w = 'bold' if bold else 'normal'
    out = f'<span style="color:{color}; font-weight:{w}">{text}</span>'
    if on:
        out += f' <span style="color:#555">· свободно {gb(free[disk])} ГБ</span>' if disk in free else ''
    else:
        bg, fg, _ = OFF_BADGE
        out += f' &nbsp;<span style="background:{bg}; color:{fg}">&nbsp;не подключён&nbsp;</span>'
    return out


class DirectionCard(QFrame):
    """Одна строка-карточка направления: галочка · имя, описание, диски, «Что копировать:» тегами, папка на носителе ·
    кнопка «Изменить» / «Назначить диск»."""

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
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.name = QLabel(f'<b>{html_esc(d.num)} {html_esc(d.name)}</b>')
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
        folder = d.folder()
        self.folder = None
        if folder:
            self.folder = QLabel(f'📁 На носителе: «{folder}»')
            self.folder.setStyleSheet('color:#37474f; background:#f5f7fa; border:1px solid #b0bec5; border-radius:4px; '
                                      'padding:2px 8px')
            self.folder.setToolTip('Так называется папка на носителе, куда переносятся уже скопированные папки.')
            row = QHBoxLayout()
            row.addWidget(self.folder)
            row.addStretch()
            mid.addLayout(row)
        lay.addLayout(mid, 1)
        self.btn = QPushButton('Изменить' if d.disks else 'Назначить диск')
        self.btn.setToolTip('Имя, описание и «что копировать». Диски здесь не меняются.' if d.disks else
                            'Диск выбирается один раз — при первом назначении.')
        self.btn.clicked.connect(lambda: section.edit(self.num) if self.d.disks else section.assign(self.num))
        lay.addWidget(self.btn, 0, Qt.AlignTop)

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
            self.disks.setText('<br>'.join(disk_row_html(x, data['by'], data['free'], writing) for x in self.d.disks))


class DirectionsSection(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.data, self.filling, self.note = win, None, False, ''
        self.cards = {}                    # номер направления -> DirectionCard
        self.on_choice = None              # «Обзор»: перерисовать нижнюю таблицу дисков (щелчок галочки, перечитывание)
        self.on_saved = None               # «Обзор»: после сохранения в диалоге перечитать всё
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QLabel('<b>Направления</b> — куда собираются файлы с носителей: у каждого направления свои диски. '
                      'Галочкой отметьте направления, для которых сейчас пишем команды копирования.')
        head.setWordWrap(True)
        lay.addWidget(head)
        legend = QLabel(f'Диски: <b style="color:{disk_ui.ASSIGNED_ON}">оранжевый</b> — у отмеченного направления '
                        f'(для него пишем команды), <b style="color:{disk_ui.DIR_ON}">зелёный</b> — у остальных; '
                        f'<span style="color:{disk_ui.DIR_OFF}">бледный</span> — не подключён.')
        legend.setStyleSheet('color:#555')
        legend.setWordWrap(True)
        lay.addWidget(legend)
        self.list = QVBoxLayout()
        self.list.setSpacing(6)
        lay.addLayout(self.list)
        bar = QHBoxLayout()
        self.b_add = QPushButton('Добавить направление…')
        self.b_add.clicked.connect(self.add)
        bar.addWidget(self.b_add, 0, Qt.AlignTop)
        bar.addSpacing(16)
        self.hint = QLabel('')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color:#555')
        bar.addWidget(self.hint, 1)
        self.b_go = QPushButton(GO_TEXT)
        f = self.b_go.font()
        f.setBold(True)
        self.b_go.setFont(f)
        self.b_go.clicked.connect(self.go)
        bar.addWidget(self.b_go, 0, Qt.AlignTop)
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
            self.b_go.setToolTip('Отметьте галочкой хотя бы одно направление.')
        else:
            self.b_go.setEnabled(True)
            self.b_go.setToolTip('Откроется экран «Разбор носителя» для отмеченных направлений.')
        if self.data:
            dirs = self.data['dirs']
            if nums:
                text = 'Пишем команды для: <b>' + html_esc('; '.join(dirs[n].label() for n in nums if n in dirs)) + '</b>'
            else:
                text = 'Галочки не стоят: отметьте направления, для которых пишем команды копирования.'
            if not self.has_razbor():
                text += ' Экран «Разбор носителя» ещё не готов — кнопка перехода неактивна.'
            if self.note:
                text = html_esc(self.note) + '<br>' + text
            self.hint.setText(text)

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


def _safe(fn, **kw):
    """Отказ сервиса - ответ, а не ошибка окна: (True, результат) или (False, текст отказа)."""
    try:
        return True, fn(**kw)
    except sv.Refused as e:
        return False, str(e)


class ConfirmDialog(QDialog):
    """Переспрос перед сохранением: текст предпросмотра сервиса и, если убирается диск с заданиями, галочка «Понимаю…»."""

    def __init__(self, parent, lines, needs_ack):
        super().__init__(parent)
        self.setWindowTitle('Сохранить направление?')
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel('<b>Меняются диски направления, у которого уже есть задания или скопированные файлы. '
                             'Что будет:</b>'))
        view = QTextBrowser()
        view.setHtml('<ul>' + ''.join(f'<li>{html_esc(x)}</li>' for x in lines) + '</ul>')
        lay.addWidget(view, 1)
        self.ack = QCheckBox(ACK_TEXT)
        self.ack.setVisible(bool(needs_ack))
        lay.addWidget(self.ack)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton('Сохранить', QDialogButtonBox.AcceptRole)
        self.buttons.addButton('Отмена', QDialogButtonBox.RejectRole)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.ack.toggled.connect(lambda on: self.ok.setEnabled(on or not needs_ack))
        self.ok.setEnabled(not needs_ack)
        self.text = view


ACK_TEXT = ('Понимаю: убранный диск перестаёт быть диском направления; скопированное на нём остаётся, но направлению '
            'больше не засчитывается («уже есть» — только по новым дискам); старые задания по-прежнему требуют его')


def html_esc(x):
    import html
    return html.escape(str(x))


NEW, CARD, ASSIGN = 'новое', 'карточка', 'назначить диск'
DISKS_LEGEND = (f'Диски назначения. <span style="background:{disk_ui.SELECTED_BG}">&nbsp;Голубой фон&nbsp;</span> — '
                'выбран сейчас (запишется при «Сохранить»); '
                f'<span style="color:{disk_ui.ASSIGNED_ON}"><b>оранжевый</b></span> — уже у другого направления '
                f'(выбрать нельзя); <span style="color:{disk_ui.ON_COLOR.name()}"><b>зелёный</b></span> — подключён и '
                f'свободен; <span style="color:{disk_ui.OFF_COLOR.name()}">серый</span> — не подключён. Один диск — '
                'одному направлению; у «Семейного архива» два диска — две копии. Сменить диск потом нельзя:')


class DirectionDialog(QDialog):
    """Три вида (второй круг, 16.11.2026):
    NEW - новое направление: карточка (имя, «что собирается», «что копировать») и диски;
    CARD - «Изменить…»: только карточка; диски не показываются и в сервис идут как None (сервис под замком берёт
           диски из свежей таблицы) - сохранение карточки диски не трогает, переспроса нет;
    ASSIGN - «Назначить диск…» направлению без диска: только список дисков; имя, описание и набор - None (остаются).
    «Сохранить» - предпросмотр сервиса в фоне; переспрос - только если сервис просит подтверждения (смена или удаление
    диска у направления с заданиями или данными - из окна этого больше не бывает, путь оставлен на всякий случай);
    затем запись под замком."""

    def __init__(self, section, data, cur, mode=None):
        super().__init__(section)
        self.mode = mode or (CARD if cur else NEW)
        self.section, self.data, self.cur = section, data, cur
        self.setWindowTitle({NEW: 'Новое направление',
                             CARD: f'Изменить направление {cur.num} «{cur.name}»' if cur else '',
                             ASSIGN: f'Назначить диск направлению {cur.num} «{cur.name}»' if cur else ''}[self.mode])
        self.resize(780, 720 if self.mode == NEW else 520)
        lay = QVBoxLayout(self)
        self.card = QWidget()
        card = QVBoxLayout(self.card)
        card.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.name = QLineEdit(cur.name if cur else '')
        self.name.setMaxLength(hb.DIR_NAME_MAX)
        self.name.setPlaceholderText('до 30 знаков, без \\ / : * ? " < > | ;')
        self.desc = QLineEdit((cur.desc or '') if cur else '')
        self.desc.setMaxLength(sv.DESC_MAX)
        self.desc.setPlaceholderText('что собирается на этих дисках, например: семейные фото и видео всех лет')
        form.addRow('Имя направления:', self.name)
        form.addRow('Что собирается:', self.desc)
        card.addLayout(form)
        # что копировать - галочки
        card.addWidget(QLabel('<b>Что копировать:</b>'))
        grid = QGridLayout()
        self.all_box = QCheckBox('Все файлы')
        f = self.all_box.font()
        f.setBold(True)
        self.all_box.setFont(f)
        self.all_box.setToolTip('Поставить или снять все галочки. Программы, системные и временные файлы - никогда.')
        grid.addWidget(self.all_box, 0, 0)
        self.cat_boxes = {}
        for i, (cat, text) in enumerate(CAT_LABELS, start=1):
            b = QCheckBox(text)
            self.cat_boxes[cat] = b
            grid.addWidget(b, i // 4, i % 4)
        card.addLayout(grid)
        self.near = QCheckBox(NEAR_TEXT)
        self.near.setToolTip(NEAR_TIP)
        card.addWidget(self.near)
        near_hint = QLabel(NEAR_TIP)
        near_hint.setWordWrap(True)
        near_hint.setStyleSheet('color:#555; margin-left:22px')
        card.addWidget(near_hint)
        never = QLabel(NEVER_TEXT)
        never.setWordWrap(True)
        never.setStyleSheet('color:#777; font-size:8pt')
        card.addWidget(never)
        cats, near, ok = hb.parse_kind(cur.kind) if cur else (hb.ALL_CATS, False, True)
        for cat, b in self.cat_boxes.items():
            b.setChecked(cat in cats)
            b.toggled.connect(self.cats_changed)
        self.near.setChecked(near)
        self.all_box.clicked.connect(self.all_clicked)
        lay.addWidget(self.card)
        self.card.setVisible(self.mode != ASSIGN)
        if self.mode == CARD and cur is not None:
            info = QLabel(f'Диски направления: {", ".join(cur.disks)}. Здесь они не меняются.' if cur.disks else
                          'Диск не назначен — назначить его можно кнопкой «Назначить диск…» в «Обзоре».')
            info.setStyleSheet('color:#555')
            lay.addWidget(info)
        # диски - только у нового направления и при первом назначении
        self.disks = None
        if self.mode in (NEW, ASSIGN):
            legend = QLabel(DISKS_LEGEND)
            legend.setWordWrap(True)
            lay.addWidget(legend)
            self.disks = QListWidget()
            owner = {x: d for d in data['dirs'].values() for x in d.disks if not cur or d.num != cur.num}
            for r in disk_ui.ordered(data['disks']):
                d = r['disk']
                it = QListWidgetItem(disk_ui.disk_text(r))
                it.setData(Qt.UserRole, d)
                if d in owner:
                    it.setText(f'{it.text()} — у {owner[d].num} «{owner[d].name}»')
                    it.setFlags(Qt.NoItemFlags)
                else:
                    it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Unchecked)
                disk_ui.style_disk(it.setData, bool(r.get('letter')), d in owner)
                self.disks.addItem(it)
            self.disks.itemChanged.connect(self.disk_toggled)
            lay.addWidget(self.disks, 1)
        else:
            lay.addStretch(1)
        self.view = QTextBrowser()
        self.view.setMaximumHeight(110)
        lay.addWidget(self.view)
        bar = QHBoxLayout()
        self.b_write = QPushButton('Сохранить')
        self.b_close = QPushButton('Закрыть')
        self.b_write.setDefault(True)
        self.b_write.clicked.connect(self.write)
        self.b_close.clicked.connect(self.reject)
        bar.addStretch()
        for b in (self.b_write, self.b_close):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.view.setHtml('<p style="color:gray">' + {
            NEW: 'Таблица направлений только дописывается, прежняя версия сохраняется.',
            CARD: 'Таблица направлений только дописывается, прежняя версия сохраняется. Диски направления не меняются.',
            ASSIGN: 'Отметьте диск (или два — для двух копий). Таблица направлений только дописывается.'}[self.mode]
            + '</p>')
        self.confirm_hook = None          # для тестов: функция (строки, needs_ack) -> (сохранять ли, ack)
        self.busy = False
        self.cats_changed()
        if self.mode == ASSIGN:
            self.disks.setFocus()

    # --- диски ---
    def checked_disks(self):
        if self.disks is None:
            return []
        return [self.disks.item(i).data(Qt.UserRole) for i in range(self.disks.count())
                if self.disks.item(i).flags() & Qt.ItemIsUserCheckable and self.disks.item(i).checkState() == Qt.Checked]

    def disk_toggled(self, it):
        """Галочка у диска - сразу голубой фон строки «выбран сейчас»; снята - фон убирается."""
        if not it.flags() & Qt.ItemIsUserCheckable:
            return
        on = it.checkState() == Qt.Checked
        self.disks.blockSignals(True)
        it.setData(Qt.BackgroundRole, QBrush(QColor(disk_ui.SELECTED_BG)) if on else None)
        self.disks.blockSignals(False)
        self.update_write()

    # --- что копировать ---
    def chosen_cats(self):
        return frozenset(c for c, b in self.cat_boxes.items() if b.isChecked())

    def cats_changed(self, *_):
        cats = self.chosen_cats()
        self.near.setEnabled(hb.CAT_DOC in cats)
        self.all_box.blockSignals(True)
        self.all_box.setTristate(False)
        self.all_box.setCheckState(Qt.Checked if cats == hb.ALL_CATS else
                                   (Qt.PartiallyChecked if cats else Qt.Unchecked))
        self.all_box.blockSignals(False)
        self.update_write()

    def update_write(self):
        """«Сохранить» неактивна, пока идёт сохранение; пока не выбран ни один тип файлов (новое и карточка); пока не
        отмечен ни один диск («Назначить диск»)."""
        if self.mode == ASSIGN:
            why = '' if self.checked_disks() else 'Отметьте диск, который назначить направлению.'
        else:
            why = '' if self.chosen_cats() else 'Выберите хотя бы один тип файлов в «Что копировать».'
        self.b_write.setEnabled(not why and not self.busy)
        self.b_write.setToolTip(why)

    def all_clicked(self, *_):
        on = self.chosen_cats() != hb.ALL_CATS          # не все - поставить все; все - снять все
        for b in self.cat_boxes.values():
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.cats_changed()

    def values(self):
        """Поля для сервиса. Карточка: disks=None - диски не трогаются (сервис берёт их из свежей таблицы).
        Назначить диск: name, kind, desc = None - остаются как есть."""
        num = self.cur.num if self.cur else None
        if self.mode == ASSIGN:
            return dict(num=num, name=None, disks=self.checked_disks(), kind=None, desc=None)
        cats = self.chosen_cats()
        near = self.near.isChecked() and hb.CAT_DOC in cats
        return dict(num=num, name=self.name.text().strip(), disks=None if self.mode == CARD else self.checked_disks(),
                    kind=(cats, near), desc=self.desc.text().strip())

    # --- сохранение ---
    def refused(self, text, word='Не сохранено'):
        self.view.setHtml(f'<p style="color:#c62828"><b>{word}:</b> {html_esc(text)}</p>')
        self.busy = False
        self.update_write()

    def changed_meanwhile(self, vals):
        """Пока считался предпросмотр (или был открыт переспрос), владелец поменял поля: не сохранять то, чего он уже
        не видит."""
        if self.values() == vals:
            return False
        self.view.setHtml('<p style="color:#e65100">Значения изменились, пока программа проверяла — ничего не '
                          'сохранено. Нажмите «Сохранить» ещё раз.</p>')
        self.busy = False
        self.update_write()
        return True

    def ask_confirm(self, lines, needs_ack):
        if self.confirm_hook is not None:
            return self.confirm_hook(lines, needs_ack)
        dlg = ConfirmDialog(self, lines, needs_ack)
        ok = dlg.exec() == QDialog.Accepted
        return ok, dlg.ack.isChecked()

    def write(self):
        vals = self.values()
        if (self.mode == ASSIGN and not vals['disks']) or (self.mode != ASSIGN and not vals['kind'][0]):
            self.update_write()
            return
        self.busy = True
        self.update_write()

        def previewed(res):
            ok, pv = res
            if not ok:
                self.refused(pv, 'Нельзя сохранить')
                return
            if self.changed_meanwhile(vals):
                return
            ack = False
            if pv.get('confirm'):
                go, ack = self.ask_confirm(pv['lines'], pv['needs_ack'])
                if not go:
                    self.view.setHtml('<p style="color:gray">Не сохранено: отменено.</p>')
                    self.busy = False
                    self.update_write()
                    return
                if self.changed_meanwhile(vals):
                    return
            self.section.win.bg.run(lambda: _safe(sv.direction_save, ack=ack, **vals), ok=saved)

        def saved(res):
            ok, pv = res
            if not ok:
                self.refused(pv)
                return
            self.section.note = (f'Сохранено: {pv["direction"].label()} (строка {pv["line"]} таблицы направлений; '
                                 'копия таблицы до записи — в «_БАЗА\\архив таблиц»).')
            self.accept()
            self.section.refresh()
            if self.section.on_saved:
                self.section.on_saved()
        self.section.win.bg.run(lambda: _safe(sv.direction_save_preview, **vals), ok=previewed)
