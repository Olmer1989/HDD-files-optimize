"""«Диски и папки»: дерево папок - ленивая загрузка, строка папки, раскрытие, обход всех строк (часть-«примесь» класса
DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import service as sv
from overview_page import gb_ru, n_ru

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QTreeWidgetItem

from .texts_tree import TYPE_NAMES, type_text
from .common import DISK_ROLE, MARK_ROLE, SIZE_ROLE, TYPES_ROLE, T_CHECK, T_DEC, T_FILES, T_GB, T_NAME, T_TYPE0


class TreeView:
    """Часть DisksPage: дерево папок."""

    def load(self, item):
        disk, path = item.data(T_NAME, DISK_ROLE), item.data(T_NAME, Qt.UserRole)

        def fill(rows):
            item.takeChildren()
            self.tree.blockSignals(True)
            for r in rows:
                ch = self.folder_item(disk, r['path'], r['name'], r['files'], r['gib'], r['types'], r.get('mark'))
                ch.addChild(QTreeWidgetItem())            # раскрывается лениво
                item.addChild(ch)
            self.tree.blockSignals(False)
        item.setData(T_FILES, Qt.UserRole, True)
        self.win.bg.run(sv.folder_children, disk, path, ok=fill)

    def folder_item(self, disk, path, name, files, gib_, types=None, mark=None):
        ch = QTreeWidgetItem()
        ch.setText(T_NAME, name)
        ch.setToolTip(T_NAME, f'{disk}\\{path}')
        ch.setData(T_NAME, Qt.UserRole, path)
        ch.setData(T_NAME, DISK_ROLE, disk)
        ch.setData(T_NAME, SIZE_ROLE, (files, gib_))
        ch.setFlags(ch.flags() | Qt.ItemIsUserCheckable)
        ch.setCheckState(T_CHECK, Qt.Unchecked)
        ch.setText(T_FILES, n_ru(files))
        ch.setText(T_GB, gb_ru(gib_))
        f = QFont(self.tree.font())                     # шрифт дерева (масштаб Windows), только жирный
        f.setBold(True)
        ch.setFont(T_GB, f)
        if types is not None:
            ch.setData(T_NAME, TYPES_ROLE, list(types))
            ch.setToolTip(T_NAME, f'{disk}\\{path}\n' + ', '.join(f'{n} {gb_ru(x)} ГБ' for n, x in zip(TYPE_NAMES, types)))
            for k, x in enumerate(types):
                ch.setText(T_TYPE0 + k, type_text(x).replace('.', ','))
                if x < 0.05:
                    ch.setForeground(T_TYPE0 + k, QColor('#bdbdbd'))
        for k in range(T_FILES, T_DEC):
            ch.setTextAlignment(k, Qt.AlignRight | Qt.AlignVCenter)
        self.nohash_cell(ch)
        if mark and mark.get('text'):
            ch.setData(T_DEC, MARK_ROLE, mark)
            ch.setToolTip(T_DEC, mark['text'] + ('' if mark.get('own') else f' (от «{mark.get("src")}»)')
                          + '. Сохранённые отметки «Разбора носителя».')
        else:
            ch.setText(T_DEC, '—')
            ch.setForeground(T_DEC, QColor('#bdbdbd'))
            ch.setTextAlignment(T_DEC, Qt.AlignCenter)
        return ch

    def expand(self, item):
        if not item.data(T_FILES, Qt.UserRole) and item.data(T_NAME, DISK_ROLE):
            self.load(item)

    def all_items(self):
        out = []

        def walk(it):
            out.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out
