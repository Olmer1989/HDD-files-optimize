"""Направления: диалоги «Сохранить направление?» и «Направление». Вынесено из directions_page.py без изменений кода."""
from hb_core import api as hb
import service as sv
import disk_ui

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from directions_look import CAT_LABELS, NEAR_TEXT, NEAR_TIP, NEVER_TEXT, html_esc


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
                          'Диск не назначен — назначить его можно кнопкой «Назначить диск…» на вкладке «Назначить Архивный диск».')
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
