"""Раздел окна «Диски и папки» - переходник (шаг А разбивки, 17.11.2026).

Код перенесён без правки тел в пакет ui/disks (карта файлов и правила слоёв - docs/СТРУКТУРА_ПРОГРАММЫ.md):
тексты - texts_disks, texts_tree, texts_info, столбцы и роли дерева - common, FolderDelegate - view_delegate, части
DisksPage - view_disks (носители), view_info (строка сведений, «Без хеша»), view_tree (дерево), view_select (выбор
папок), flow_folder (действия с папкой), view_search (поиск), сборка DisksPage - page. Здесь только прежние имена
(в том числе всё, что модуль раньше отдавал звёздочкой из ui_common и overview_page).
Новый код импортирует из ui.disks напрямую (app.py - ui.disks.page.DisksPage). Подменять в тестах имена этого модуля
(mock.patch.object(disks_page, 'X')) нельзя - код их отсюда не берёт: подменяйте там, где имя используется.
"""
import os                                               # noqa: F401
import sys                                              # noqa: F401
import time                                             # noqa: F401
import traceback                                        # noqa: F401
from pathlib import Path                                # noqa: F401

from hb_core import api as hb                           # noqa: F401
import service as sv                                    # noqa: F401
import commands_page                                    # noqa: F401
import disk_ui                                          # noqa: F401
import rescan_dialog                                    # noqa: F401
import explorer_page                                    # noqa: F401

from PySide6.QtCore import QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal   # noqa: F401
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QTextDocument                     # noqa: F401
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel,  # noqa: F401
                               QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ui_common import *                                 # noqa: F401,F403 - прежние звёздочные имена
from ui_common import _Signals                          # noqa: F401
from overview_page import *                             # noqa: F401,F403 - прежние звёздочные имена

from ui.disks.texts_disks import *                      # noqa: F401,F403
from ui.disks.texts_tree import *                       # noqa: F401,F403
from ui.disks.texts_info import *                       # noqa: F401,F403 - files_word, html_esc - свои, как раньше
from ui.disks.common import *                           # noqa: F401,F403
from ui.disks.view_delegate import *                    # noqa: F401,F403
from ui.disks.page import DisksPage                     # noqa: F401 - главное имя
