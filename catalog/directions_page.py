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
Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 4».
"""
import json
import os
import shutil
import time

from hb_core import api as hb
import service as sv
import disk_ui

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

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


def disk_line(disk, by, assigned=True):
    """Диск строки направления - назначен (оранжевый; подключённый - жирный, неподключённый - бледно-оранжевый)."""
    r = by.get(disk) or {'disk': disk, 'label': '', 'letter': ''}
    text = disk_ui.disk_text(r)
    color, bold = disk_ui.disk_color(bool(r.get('letter')), assigned)
    if bold:
        return f'<b style="color:{color}">{text}</b>'
    return f'<span style="color:{color}">{text}</span>'


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


# ---------- секция в «Обзоре» ----------

class DirectionsSection(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.data, self.filling, self.note = win, None, False, ''
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel('<b>Направления</b> — куда собираются файлы с носителей: у каждого направления свои диски. '
                             'Галочкой отметьте направления, для которых сейчас пишем команды копирования.'))
        self.t = QTableWidget(0, len(HEADERS))
        self.t.setHorizontalHeaderLabels(HEADERS)
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSelectionMode(QAbstractItemView.SingleSelection)
        self.t.verticalHeader().setVisible(False)
        h = self.t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Interactive)       # описание - с переносом строк, ширину можно тянуть
        self.t.setColumnWidth(2, 230)
        h.setStretchLastSection(True)
        self.t.setWordWrap(True)
        self.t.itemChanged.connect(self.on_item)
        self.t.itemSelectionChanged.connect(self.update_buttons)
        self.t.doubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.t)
        bar = QHBoxLayout()
        self.b_add = QPushButton('Добавить направление…')
        self.b_edit = QPushButton('Изменить…')
        self.b_disk = QPushButton('Назначить диск…')
        self.b_go = QPushButton(GO_TEXT)
        f = self.b_go.font()
        f.setBold(True)
        self.b_go.setFont(f)
        self.b_add.clicked.connect(self.add)
        self.b_edit.clicked.connect(self.edit)
        self.b_disk.clicked.connect(lambda: self.edit(disks_only=True))
        self.b_go.clicked.connect(self.go)
        for b in (self.b_add, self.b_edit, self.b_disk):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.b_go)
        lay.addLayout(bar)
        self.hint = QLabel('')
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet('color:#555')
        lay.addWidget(self.hint)
        self.update_buttons()

    # --- данные ---
    def refresh(self):
        self.win.bg.run(section_data, ok=self.render)

    def render(self, data):
        self.data = data
        dirs, by, free = data['dirs'], data['by'], data['free']
        choice = set(data['choice'])
        sel = self.current()
        self.filling = True
        self.t.setRowCount(0)
        for d in dirs.values():
            i = self.t.rowCount()
            self.t.insertRow(i)
            chk = QTableWidgetItem('')
            if d.disks:
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
                chk.setCheckState(Qt.Checked if d.num in choice else Qt.Unchecked)
                chk.setToolTip('Отметить: для этого направления пишем команды копирования')
            else:
                chk.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                chk.setText('нет диска')
                chk.setForeground(QColor(OFF))
                chk.setToolTip('Сначала назначьте направлению диск («Назначить диск…»)')
            chk.setData(Qt.UserRole, d.num)
            self.t.setItem(i, 0, chk)
            name = QTableWidgetItem(f'{d.num} {d.name}')
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            if d.former:
                name.setToolTip('Прежние имена: ' + ', '.join(d.former))
            self.t.setItem(i, 1, name)
            desc = QTableWidgetItem(d.desc or '')
            if not d.desc:
                desc.setText('— описания нет («Изменить…»)')
                desc.setForeground(QColor(OFF))
            self.t.setItem(i, 2, desc)
            if d.disks:
                disks_html = '<br>'.join(disk_line(x, by) for x in d.disks)
                free_html = '<br>'.join(f'{gb(free[x])} ГБ' if x in free else '—' for x in d.disks)
            else:
                disks_html = f'<span style="color:#c62828">диск не назначен</span>'
                free_html = '—'
            self.t.setItem(i, 3, QTableWidgetItem(''))
            self.t.setItem(i, 4, QTableWidgetItem(''))
            self.t.setCellWidget(i, 3, self._label(disks_html))
            self.t.setCellWidget(i, 4, self._label(free_html, right=True))
            self.t.setItem(i, 5, QTableWidgetItem(kind_text(d.kind)))
            self.t.setItem(i, 6, QTableWidgetItem(d.folder() or '—'))
        self.t.resizeRowsToContents()
        self.filling = False
        h = self.t.horizontalHeader().height() + sum(self.t.rowHeight(i) for i in range(self.t.rowCount())) + 8 \
            + self.t.horizontalScrollBar().sizeHint().height()
        self.t.setFixedHeight(min(max(h, 80), 420))
        if sel:
            self.select(sel)
        self.update_buttons()

    @staticmethod
    def _label(html, right=False):
        lab = QLabel(html)
        lab.setTextFormat(Qt.RichText)
        lab.setContentsMargins(4, 2, 4, 2)
        if right:
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lab

    # --- выбор ---
    def current(self):
        r = self.t.currentRow()
        it = self.t.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def select(self, num):
        for i in range(self.t.rowCount()):
            if self.t.item(i, 0).data(Qt.UserRole) == num:
                self.t.selectRow(i)
                return

    def checked(self):
        return [self.t.item(i, 0).data(Qt.UserRole) for i in range(self.t.rowCount())
                if self.t.item(i, 0).flags() & Qt.ItemIsUserCheckable and self.t.item(i, 0).checkState() == Qt.Checked]

    def on_item(self, it):
        if self.filling or it.column() != 0:
            return
        nums = self.checked()
        save_choice(nums)
        if self.data is not None:
            self.data['choice'] = nums
        self.update_buttons()

    def has_razbor(self):
        return RAZBOR_PAGE in [n for n, _ in getattr(self.win, 'pages', [])]

    def update_buttons(self):
        num = self.current()
        d = self.data['dirs'].get(num) if (self.data and num) else None
        self.b_edit.setEnabled(d is not None)
        self.b_disk.setEnabled(d is not None and not d.disks)
        self.b_disk.setToolTip('' if d is None or not d.disks else 'У направления уже есть диск: сменить или добавить - «Изменить…»')
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
                self.hint.setText('Пишем команды для: ' + '; '.join(dirs[n].label() for n in nums if n in dirs) + '.')
            else:
                self.hint.setText('Галочки не стоят: отметьте направления, для которых пишем команды копирования.')
            if not self.has_razbor():
                self.hint.setText(self.hint.text() + ' Экран «Разбор носителя» ещё не готов — кнопка перехода неактивна.')
            if self.note:
                self.hint.setText(self.note + ' ' + self.hint.text())

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

    def edit(self, disks_only=False):
        num = self.current()
        if self.data is None or not num or num not in self.data['dirs']:
            return
        DirectionDialog(self, self.data, self.data['dirs'][num], disks_only=disks_only).exec()


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


class DirectionDialog(QDialog):
    """Добавить / изменить направление: имя, описание, диски (носители базы, подключённые сверху), что копировать
    (галочки). «Сохранить» - сразу: предпросмотр сервиса в фоне; переспрос - только если сервис просит подтверждения
    (меняются диски у направления с заданиями или данными на убираемом диске); затем запись под замком."""

    def __init__(self, section, data, cur, disks_only=False):
        super().__init__(section)
        self.section, self.data, self.cur = section, data, cur
        self.setWindowTitle(('Назначить диск направлению «%s»' % cur.name) if disks_only and cur else
                            (f'Изменить направление {cur.num} «{cur.name}»' if cur else 'Новое направление'))
        self.resize(780, 720)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(cur.name if cur else '')
        self.name.setMaxLength(hb.DIR_NAME_MAX)
        self.name.setPlaceholderText('до 30 знаков, без \\ / : * ? " < > | ;')
        self.desc = QLineEdit((cur.desc or '') if cur else '')
        self.desc.setMaxLength(sv.DESC_MAX)
        self.desc.setPlaceholderText('что собирается на этих дисках, например: семейные фото и видео всех лет')
        form.addRow('Имя направления:', self.name)
        form.addRow('Что собирается:', self.desc)
        lay.addLayout(form)
        # что копировать - галочки
        lay.addWidget(QLabel('<b>Что копировать:</b>'))
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
        lay.addLayout(grid)
        self.near = QCheckBox(NEAR_TEXT)
        self.near.setToolTip(NEAR_TIP)
        lay.addWidget(self.near)
        near_hint = QLabel(NEAR_TIP)
        near_hint.setWordWrap(True)
        near_hint.setStyleSheet('color:#555; margin-left:22px')
        lay.addWidget(near_hint)
        never = QLabel(NEVER_TEXT)
        never.setWordWrap(True)
        never.setStyleSheet('color:#777; font-size:8pt')
        lay.addWidget(never)
        cats, near, ok = hb.parse_kind(cur.kind) if cur else (hb.ALL_CATS, False, True)
        for cat, b in self.cat_boxes.items():
            b.setChecked(cat in cats)
            b.toggled.connect(self.cats_changed)
        self.near.setChecked(near)
        self.all_box.clicked.connect(self.all_clicked)
        # диски
        lay.addWidget(QLabel('Диски назначения. <span style="color:#e65100"><b>Оранжевый</b></span> — уже назначен '
                             'направлению, <span style="color:#1b5e20"><b>зелёный</b></span> — подключён и свободен, '
                             '<span style="color:#8a8a8a">серый</span> — не подключён. Один диск — одному направлению; '
                             'у «Семейного архива» два диска — две копии:'))
        self.disks = QListWidget()
        owner = {x: d for d in data['dirs'].values() for x in d.disks if not cur or d.num != cur.num}
        mine = list(cur.disks) if cur else []
        for r in disk_ui.ordered(data['disks']):
            d = r['disk']
            it = QListWidgetItem(disk_ui.disk_text(r))
            it.setData(Qt.UserRole, d)
            connected = bool(r.get('letter'))
            if d in owner:
                it.setText(f'{it.text()} — у {owner[d].num} «{owner[d].name}»')
                it.setFlags(Qt.NoItemFlags)
            else:
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if d in mine else Qt.Unchecked)
                if d in mine:
                    it.setText(f'{it.text()} — у этого направления')
            disk_ui.style_disk(it.setData, connected, d in owner or d in mine)
            self.disks.addItem(it)
        lay.addWidget(self.disks, 1)
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
        self.view.setHtml('<p style="color:gray">Таблица направлений только дописывается, прежняя версия сохраняется. '
                          'Если меняются диски у направления, где уже есть задания или скопированные файлы, программа '
                          'покажет, что будет, и спросит ещё раз.</p>')
        self.confirm_hook = None          # для тестов: функция (строки, needs_ack) -> (сохранять ли, ack)
        self.busy = False
        self.cats_changed()
        if disks_only:
            self.disks.setFocus()

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
        """«Сохранить» неактивна, пока не выбран ни один тип файлов или идёт сохранение."""
        empty = not self.chosen_cats()
        self.b_write.setEnabled(not empty and not self.busy)
        self.b_write.setToolTip('Выберите хотя бы один тип файлов в «Что копировать».' if empty else '')

    def all_clicked(self, *_):
        on = self.chosen_cats() != hb.ALL_CATS          # не все - поставить все; все - снять все
        for b in self.cat_boxes.values():
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.cats_changed()

    def values(self):
        checked = [self.disks.item(i).data(Qt.UserRole) for i in range(self.disks.count())
                   if self.disks.item(i).flags() & Qt.ItemIsUserCheckable and self.disks.item(i).checkState() == Qt.Checked]
        mine = [x for x in (self.cur.disks if self.cur else ()) if x in checked]      # прежний порядок дисков
        disks = mine + [x for x in checked if x not in mine]
        cats = self.chosen_cats()
        near = self.near.isChecked() and hb.CAT_DOC in cats
        return dict(num=self.cur.num if self.cur else None, name=self.name.text().strip(), disks=disks,
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
        if not vals['kind'][0]:
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
        self.section.win.bg.run(lambda: _safe(sv.direction_save_preview, **vals), ok=previewed)
