"""«Диски и папки»: столбцы дерева папок (T_*) и роли данных строки дерева (*_ROLE).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import Qt


T_CHECK, T_NAME, T_FILES, T_GB, T_NOHASH, T_TYPE0, T_DEC = 0, 1, 2, 3, 4, 5, 10   # «Без хеша» - этап 16
DISK_ROLE = Qt.UserRole + 1          # у строки дерева - её носитель (найденные папки - с разных дисков)
TYPES_ROLE = Qt.UserRole + 2         # ГБ по типам - полоска состава под именем
MARK_ROLE = Qt.UserRole + 3          # решение владельца - плашка
SIZE_ROLE = Qt.UserRole + 4          # (файлов, ГиБ) папки
