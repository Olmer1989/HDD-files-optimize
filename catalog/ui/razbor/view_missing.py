"""RazborPage, строка «На HDD09 нет на H: …» над «Что копировать с носителя» и окно «Показать по папкам» (18.11.2026,
решение владельца; числа - Model.not_on_disk, тексты - texts_head.not_on_target_html)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout

from hb_core import api as hb

from .common import SEP
from .texts_cell import num, vol
from .texts_head import not_on_target_html

PATH_ROLE, SORT_ROLE = Qt.UserRole, Qt.UserRole + 1
HEAD = ['Папка', 'В неотмеченных', 'В отмеченных', 'Без хеша']
TIPS = ['Двойной щелчок - показать папку в дереве «Разбора».',
        'Файлы с хешем, которых нет на диске, в папках без галочки: на диск не попадут.',
        'Файлы, которые будут скопированы на диск (столько же, сколько «Копировать на …» в ячейке).',
        'Файлы без хеша в папках без галочки: есть ли они на диске, проверить нельзя.']


class SortItem(QTreeWidgetItem):
    """Строка окна: числа сортируются по байтам (SORT_ROLE), имя - по алфавиту."""

    def __lt__(self, other):
        c = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(c, SORT_ROLE), other.data(c, SORT_ROLE)
        if a is None or b is None:
            return self.text(c).lower() < other.text(c).lower()
        return a < b


class FoldersDialog(QDialog):
    """«Показать по папкам»: дерево папок всех уровней, где есть файлы, которых нет на диске; двойной щелчок -
    выделить папку в дереве «Разбора» и закрыть окно."""

    def __init__(self, page, label, v):
        super().__init__(page)
        self.page, self.picked = page, None
        self.setWindowTitle(f'Нет на {label} — по папкам')
        self.resize(980, 640)
        lay = QVBoxLayout(self)
        note = QLabel(f'Папки носителя {page.disk}, где есть файлы, которых нет на {label}: числа - по папке со всеми '
                      'подпапками. Двойной щелчок - показать папку в дереве «Разбора».')
        note.setWordWrap(True)
        lay.addWidget(note)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(HEAD)
        for c, t in enumerate(TIPS):
            self.tree.headerItem().setToolTip(c, t)
        hd = self.tree.header()
        hd.setSectionResizeMode(0, QHeaderView.Stretch)
        hd.setStretchLastSection(False)
        for c in range(1, len(HEAD)):
            hd.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.items = {}
        sub = v['folders']
        for f in sorted(sub, key=lambda x: (x.count(SEP) + 1 if x else 0, x)):
            it = SortItem()
            it.setText(0, f'{page.disk} (весь носитель)' if not f else f.rsplit(SEP, 1)[-1])
            it.setData(0, PATH_ROLE, f)
            it.setToolTip(0, f or page.disk)
            s = sub[f]
            for c, (n, b) in enumerate(((s[0], s[1]), (s[2], s[3]), (s[4], s[5])), 1):
                it.setText(c, f'{num(n)} · {vol(b)}' if n else '—')
                it.setData(c, SORT_ROLE, b)
                it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            parent = self.items.get(hb.parent_of(f)) if f else None
            if parent is None:
                self.tree.addTopLevelItem(it)
            else:
                parent.addChild(it)
            self.items[f] = it
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.DescendingOrder)    # больше всего «не попадут» - сверху
        if '' in self.items:
            self.items[''].setExpanded(True)
        self.tree.itemDoubleClicked.connect(self.go)
        lay.addWidget(self.tree, 1)

    def go(self, it, _col=0):
        f = it.data(0, PATH_ROLE)
        if f is None:
            return
        self.picked = f
        self.page.reveal(f)
        self.accept()


class MissingView:
    """Часть RazborPage (строка «нет на H:» и окно «по папкам»); атрибуты - у RazborPage."""

    def missing_label(self, x):
        by = {r['disk']: r for r in self.disk_rows}
        return (by.get(x) or {}).get('letter') or x

    def render_missing(self):
        """Строка «нет на H:» - по строке на каждый диск направления (45 и 77 - две); носитель сам диск назначения или
        диска назначения нет - строки нет. Пересчёт - вместе с ячейкой (render_cells)."""
        m = self.model
        d = self.dest_dir() if m is not None else None
        xs = [x for x in d.disks if x != m.disk] if d is not None else []
        if not xs:
            self.missing.hide()
            return
        res = m.not_on_disk(d.num)
        self.missing.setText('<br>'.join(not_on_target_html(m.disk, self.missing_label(x), d,
                                                            None if res is None else res.get(x), x) for x in xs))
        self.missing.show()

    def missing_link(self, href):
        """«Показать по папкам» (nt:<диск>) -> окно (не ждёт закрытия) или None."""
        kind, _, x = str(href).partition(':')
        m = self.model
        res = m.not_on_disk(self.dest) if kind == 'nt' and m is not None and self.dest else None
        if not res or x not in res:
            return None
        self.missing_dlg = FoldersDialog(self, self.missing_label(x), res[x])
        self.missing_dlg.open()
        return self.missing_dlg

    def reveal(self, f):
        """Показать папку в дереве «Разбора»: раскрыть родителей (большие папки - порциями), выделить, прокрутить."""
        parts = f.split(SEP) if f else []
        it = self.items.get('')
        for i in range(1, len(parts) + 1):
            if it is None:
                return False
            it.setExpanded(True)                          # -> expand(): дети создаются
            p, parent = SEP.join(parts[:i]), SEP.join(parts[:i - 1])
            while p not in self.items and self.show_more(parent):
                pass
            it = self.items.get(p)
        if it is None:
            return False
        self.tree.clearSelection()
        it.setSelected(True)
        self.tree.scrollToItem(it)
        return True
