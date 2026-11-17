"""Страница окна «Я сделал в Проводнике» (вместо форм manual и fix-manual раздела «Команды»).

Вкладка «Что изменилось на диске»: окно само сравнивает базу с оглавлением подключённого диска
(explorer_diff, содержимое файлов не читается), владелец отмечает галочками, что записать. Диск не подключён -
папки из каталога базы с галочками и действие.
Вкладка «Записанные действия»: все строки «ручные операции.tsv» словами; «Редактировать» - через service.fix_manual.
Запись - только через service (единый путь записи). Подключение в окно: ('Я сделал в Проводнике', ExplorerPage(self)).
"""
import threading

from PySide6.QtCore import QDate, QDateTime, QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStackedWidget, QStyle,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import explorer_diff as ed
import service as sv
from explorer_common import TITLE, ROLE, GROUPS, RESCAN_HINT, today, num, SpaceToggles, checkable  # noqa: F401
from explorer_changes import ChangesTab
from explorer_records import FixDialog, RecordsTab  # noqa: F401


# ---------- страница ----------

class ExplorerPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lay = QVBoxLayout(self)
        head = QLabel('<b>Я сделал в Проводнике</b> - отметьте, что вы скопировали, переместили или удалили сами, '
                      'чтобы база знала, что где лежит.')
        head.setWordWrap(True)
        lay.addWidget(head)
        self.tabs = QTabWidget()
        self.changes, self.records = ChangesTab(win), RecordsTab(win)
        self.tabs.addTab(self.changes, 'Что изменилось на диске')
        self.tabs.addTab(self.records, 'Записанные действия')
        self.tabs.currentChanged.connect(lambda *_: self.refresh())
        lay.addWidget(self.tabs, 1)

    def refresh(self):
        (self.changes if self.tabs.currentIndex() == 0 else self.records).refresh()

    def can_close(self):
        """Окно не закрывать во время записи или исправления."""
        return not self.changes.busy and not self.records.busy
