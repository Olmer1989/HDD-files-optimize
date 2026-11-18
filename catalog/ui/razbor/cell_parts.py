"""Части ячейки «Копировать на диск …» (макет владельца 18.11.2026): строка «Что копировать:» с плашками типов и
кнопкой «Изменить…» (KindsRow) и рамка «Перед копированием» с шагами (PrepBox). Тексты - texts_cell; что делают
кнопки и ссылки - у страницы (page.edit_kinds, page.scan_nohash, page.nohash_link)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from directions_look import FlowLayout, kind_tags, tag_label

from .texts_cell import EDIT_TEXT, PREP_TITLE, kinds_note

PREP_CSS = ('QFrame#prep { border:1px solid #d0d7de; border-radius:5px; background:#ffffff; }'
            'QFrame#prep QLabel { border:none; background:transparent; }')


def rich(on_link=None):
    lab = QLabel('')
    lab.setTextFormat(Qt.RichText)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.LinksAccessibleByMouse)
    if on_link is not None:
        lab.linkActivated.connect(on_link)
    return lab


class KindsRow(QWidget):
    """«Что копировать:» + голубые плашки типов (как в карточке «Назначить Архивный диск») + «Изменить…»; ниже мелко
    серым - «Настройка А1 — общая для всех носителей; …»."""

    def __init__(self, on_edit):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        self.flow_box = QWidget()
        self.flow = FlowLayout(self.flow_box)
        lay.addWidget(self.flow_box)
        self.edit_btn = QPushButton(EDIT_TEXT)
        self.edit_btn.setStyleSheet('QPushButton { padding:1px 8px; font-size:8pt; }')
        self.edit_btn.setToolTip('То же окно, что «Изменить» в карточке на вкладке «Назначить Архивный диск»: имя, '
                                 'описание и «что копировать». После «Сохранить» ячейка пересчитается.')
        self.edit_btn.clicked.connect(lambda: on_edit())
        self.note = QLabel('')
        self.note.setWordWrap(True)
        self.note.setStyleSheet('color:#757575; font-size:8pt')
        lay.addWidget(self.note)
        self.kind, self.tags = None, []

    def show_kind(self, kind, a):
        """Плашки по «что копировать» направления (kind - как в таблице направлений), a - «А1»."""
        if kind != self.kind:
            self.kind = kind
            while self.flow.count():
                w = self.flow.takeAt(0).widget()
                if w is not None and w is not self.edit_btn:
                    w.setParent(None)
                    w.deleteLater()
            what = QLabel('Что копировать:')
            what.setStyleSheet('color:#555')
            self.flow.addWidget(what)
            tags, small = kind_tags(kind)
            self.tags = [t for t, _ in tags]
            for text, look in tags:
                self.flow.addWidget(tag_label(text, look))
            if small:
                s = QLabel(small)
                s.setStyleSheet('color:#777; font-size:8pt')
                self.flow.addWidget(s)
            self.flow.addWidget(self.edit_btn)
            self.flow_box.updateGeometry()
        self.note.setText(kinds_note(a))


class PrepBox(QFrame):
    """Рамка «Перед копированием»: шаг 1 (step1 + кнопка scan_btn «Посчитать (N)»), шаги 2… по дискам назначения
    (подпись + кнопка «Посчитать хеш на H: (K)»), ниже - строка «не прочитаны» (extra)."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setObjectName('prep')
        self.setStyleSheet(PREP_CSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)
        self.title = QLabel(f'<b>{PREP_TITLE}</b>')
        lay.addWidget(self.title)
        row = QHBoxLayout()
        self.step1 = rich(page.nohash_link)
        row.addWidget(self.step1, 1)
        self.scan_btn = QPushButton('Посчитать')
        self.scan_btn.clicked.connect(lambda: page.scan_nohash())
        self.scan_btn.hide()
        row.addWidget(self.scan_btn, 0, Qt.AlignTop)
        lay.addLayout(row)
        self.steps_box = QWidget()
        self.steps_lay = QVBoxLayout(self.steps_box)
        self.steps_lay.setContentsMargins(0, 0, 0, 0)
        self.steps_lay.setSpacing(8)
        self.steps = []                                   # [[диск, QWidget, QLabel, QPushButton]]
        lay.addWidget(self.steps_box)
        self.extra = rich(page.nohash_link)
        self.extra.hide()
        lay.addWidget(self.extra)

    def set_steps(self, items):
        """Шаги «по желанию»: items = [(диск, html, текст кнопки, можно нажать, подсказка)]."""
        if [x[0] for x in items] != [s[0] for s in self.steps]:
            for s in self.steps:
                s[1].setParent(None)
                s[1].deleteLater()
            self.steps = []
            for x, *_ in items:
                w = QWidget()
                hl = QHBoxLayout(w)
                hl.setContentsMargins(0, 0, 0, 0)
                lab = rich(self.page.nohash_link)
                hl.addWidget(lab, 1)
                btn = QPushButton('')
                btn.clicked.connect(lambda _=False, d=x: self.page.nohash_link(f'nh-copies:{d}'))
                hl.addWidget(btn, 0, Qt.AlignTop)
                self.steps_lay.addWidget(w)
                self.steps.append([x, w, lab, btn])
        for s, (_x, html_, text, on, tip) in zip(self.steps, items):
            s[2].setText(html_)
            s[3].setText(text)
            s[3].setEnabled(on)
            s[3].setToolTip(tip)
        self.steps_box.setVisible(bool(items))

    def step_texts(self):
        """Для тестов: {диск: (html, текст кнопки)}."""
        return {s[0]: (s[2].text(), s[3].text()) for s in self.steps}
