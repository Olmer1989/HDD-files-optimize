"""«Задания на копирование»: блок «Скопировано — можно переместить папку на носителе»: строки и кнопки (часть-«примесь»
класса TasksPage).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from .texts_words import MOVE_EMPTY
from .model_move import move_items
from .widgets import _small


class OffersView:
    """Часть TasksPage: блок «Скопировано — можно переместить папку на носителе»: строки и кнопки."""

    # --- логика v3: блок «Скопировано — можно переместить папку на носителе» ---
    def render_blocks(self):
        self.offers, self.done_items = move_items(self.rows, self.groups)
        lay = self.offer_lay
        while lay.count():
            w = lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.offer_buttons = []
        for it in self.offers:
            row = QFrame()
            row.setStyleSheet('QFrame{background:#f3f8ee; border-radius:4px}' if not it.get('disabled') else
                              'QFrame{background:#f5f5f5; border-radius:4px}')
            h = QHBoxLayout(row)
            col = QVBoxLayout()
            lab = QLabel(it.get('line') or it['text'])
            lab.setWordWrap(True)
            lab.setToolTip(it['text'])
            col.addWidget(lab)
            if it.get('small'):
                col.addWidget(_small(it['small']))
            h.addLayout(col, 1)
            for i, word in enumerate(it['buttons']):
                b = QPushButton(word)
                if i == 0:
                    b.setStyleSheet('font-weight:bold')
                if it.get('disabled'):
                    b.setEnabled(False)
                    b.setToolTip('Станет доступна, когда копии будут на всех дисках направления.')
                b.clicked.connect(lambda _=False, it=it, word=word: self.on_offer(it, word))
                h.addWidget(b)
                self.offer_buttons.append((it, b))
            row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            lay.addWidget(row)
        if not self.offers:
            lay.addWidget(_small(MOVE_EMPTY, '#37474f'))

    def on_offer(self, it, word):
        if it.get('disabled'):
            return
        if word.startswith('Переместить'):
            self.move_v3(it)
        elif word == 'Повторить копирование':
            self.retry_copy(it)
        else:
            self.run_move(it['move_task'])
