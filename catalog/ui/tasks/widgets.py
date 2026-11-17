"""«Задания на копирование»: мелкие части окна - ячейка таблицы, мелкая подпись, стиль плашки, TextDialog (весь ответ
команды и кнопки).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHeaderView, QLabel, QPlainTextEdit,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from .common import GREY, RED


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


def _cell(text, right=False, color=None, tip=''):
    it = QTableWidgetItem(str(text))
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    if tip:
        it.setToolTip(tip)
    return it


class TextDialog(QDialog):
    """Весь ответ команды и кнопки: «ok» - согласие (например, «Создать задание перемещения»)."""

    def __init__(self, parent, title, text, ok=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        f = QFont('Consolas')
        f.setPointSize(10)
        view.setFont(f)
        lay.addWidget(view)
        box = QDialogButtonBox()
        if ok:
            box.addButton(ok, QDialogButtonBox.AcceptRole)
        box.addButton('Закрыть', QDialogButtonBox.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)


def _small(text, color=GREY):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f'color:{color}; font-size:9pt')
    return lab


def _chip_style(color):
    if color == RED:
        return f'QLabel{{color:{RED}; background:#ffebee; border:1px solid #ef9a9a; border-radius:10px; ' \
               'padding:3px 12px; font-weight:bold}'
    return (f'QLabel{{color:{color or "#37474f"}; background:#f5f7f8; border:1px solid #cfd8dc; border-radius:10px; '
            'padding:3px 12px}')
