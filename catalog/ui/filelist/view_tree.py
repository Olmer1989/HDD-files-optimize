"""FileListWindow, дерево папок слева: построение, порции, щелчок, «мелкие картинки».

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTreeWidgetItem

from .texts_list import files_word, n_text
from .common import F_MORE, F_ROLE, R_FOLDER, R_SIZE, R_T5, SEP, SMALL_KB, TREE_CHUNK


class TreeView:
    """Часть FileListWindow (дерево папок слева: построение, порции, щелчок, «мелкие картинки»);
    атрибуты - у FileListWindow."""

    def expand_marked(self):
        """Этап 18 (правка владельца): папки дерева, которые идут в диск назначения, а родитель - нет (верхние
        отмеченные, как 4 подпапки «Алтай 2022 …» на HDD09), видны сразу: их предки раскрываются."""
        p = self.page
        if p is None or p.model is None or p.disk != self.disk:
            return
        m, num = p.model, self.spec.get('num')
        tops = [f for f in self.f_count if f and m.is_dir(m.route.get(f), num)
                and not m.is_dir(m.route.get(f.rsplit(SEP, 1)[0] if SEP in f else ''), num)]
        for f in sorted(tops, key=lambda x: x.count(SEP)):
            chain, a = [], f
            while SEP in a:
                a = a.rsplit(SEP, 1)[0]
                chain.append(a)
            for a in reversed(chain):
                it = self.f_items.get(a)
                if it is None:
                    break
                if not it.data(1, F_ROLE):
                    self.f_fill(it)
                it.setExpanded(True)

    def build_tree(self):
        """Папки с файлами списка и их предки (+ снятые в этом окне - с 0 файлов); число - файлов в папке с вложенными.
        Дети создаются по раскрытию, порциями по TREE_CHUNK. Раскрытые узлы сохраняются по путям."""
        rows = self.model.rows
        direct = {}
        for r in rows:
            direct[r[R_FOLDER]] = direct.get(r[R_FOLDER], 0) + 1
        small = {}
        for r in rows:
            if r[R_T5] == 0 and r[R_SIZE] is not None and 0 < r[R_SIZE] <= SMALL_KB * 1024:
                small[r[R_FOLDER]] = small.get(r[R_FOLDER], 0) + 1
        self.small_folders = set(small)
        n_small = sum(small.values())
        if n_small:
            link = 'все папки' if self.only is not None else 'показать эти папки'
            self.small.setText(f'Мелкие картинки до {SMALL_KB} КБ: <b>{n_text(n_small)}</b> {files_word(n_small).split()[-1]}'
                               f' в {n_text(len(small))} папках — <a href="small" style="color:#1565c0">{link}</a>')
        else:
            self.small.setText('')
            self.only = None
        base = set(direct) if self.only is None else set(self.only) & set(direct)
        count, kids = {}, {}
        for f in base | self.keep:
            n = direct.get(f, 0)
            a = f
            while True:
                count[a] = count.get(a, 0) + n
                if not a:
                    break
                p = a.rsplit(SEP, 1)[0] if SEP in a else ''
                kids.setdefault(p, set()).add(a)
                a = p
        count.setdefault('', 0)
        self.f_count = count
        self.f_kids = {p: sorted(v, key=lambda x: x.lower()) for p, v in kids.items()}
        opened = {f for f, it in self.f_items.items() if it.isExpanded()}
        self.painting = True
        self.ftree.blockSignals(True)
        try:
            self.ftree.clear()
            self.f_items = {}
            root = QTreeWidgetItem([f'весь список ({n_text(count.get("", 0))})', ''])
            root.setData(0, F_ROLE, '')
            root.setToolTip(0, 'Щелчок - показать файлы всех папок (сбросить фильтр по папке).')
            self.ftree.addTopLevelItem(root)
            self.f_items[''] = root
            self.f_fill(root)
            root.setExpanded(True)
            for f in sorted(opened, key=lambda x: x.count(SEP)):
                it = self.f_items.get(f)
                if it is not None and f:
                    if not it.data(1, F_ROLE):
                        self.f_fill(it)
                    it.setExpanded(True)
        finally:
            self.ftree.blockSignals(False)
            self.painting = False
        self.refresh_checks()
        self.expand_marked()                                # каждый f_fill сам обновляет галочки

    def f_fill(self, item, start=0):
        p = item.data(0, F_ROLE)
        kids = self.f_kids.get(p, [])
        was = self.ftree.signalsBlocked()
        self.ftree.blockSignals(True)
        try:
            if start == 0:
                item.takeChildren()
            else:
                for i in reversed(range(item.childCount())):
                    if item.child(i).data(0, F_MORE) is not None:
                        item.takeChild(i)
            item.setData(1, F_ROLE, True)                         # дети созданы
            new = []
            for f in kids[start:start + TREE_CHUNK]:
                ch = QTreeWidgetItem([f.rsplit(SEP, 1)[-1], n_text(self.f_count.get(f, 0))])
                ch.setData(0, F_ROLE, f)
                ch.setToolTip(0, f'{self.disk}\\{f}')
                ch.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                if self.f_kids.get(f):
                    ch.addChild(QTreeWidgetItem(['…', '']))
                self.f_items[f] = ch
                new.append(ch)
            rest = len(kids) - start - TREE_CHUNK
            if rest > 0:
                more = QTreeWidgetItem([f'ещё {n_text(rest)} папок — показать', ''])
                more.setData(0, F_MORE, (p, start + TREE_CHUNK))
                more.setForeground(0, QColor('#1565c0'))
                new.append(more)
            item.addChildren(new)
        finally:
            self.ftree.blockSignals(was)
        self.refresh_checks()

    def f_expand(self, item):
        if not item.data(1, F_ROLE) and item.data(0, F_ROLE) is not None:
            self.f_fill(item)

    def f_clicked(self, item, col=0):
        if getattr(self, 'check_click', False):     # щелчок по галочке, а не по имени: фильтр не трогаем
            self.check_click = False
            return
        more = item.data(0, F_MORE)
        if more is not None:
            parent = self.f_items.get(more[0])
            if parent is not None:
                self.f_fill(parent, more[1])
            return
        f = item.data(0, F_ROLE)
        if f is None:
            return
        self.model.set_filter(folder_prefix=f)                     # И с остальными фильтрами; корень - сброс
        self.show_totals()
        self.update_buttons()

    def toggle_small(self, _href=''):
        """«показать эти папки» (только папки с мелкими картинками) / «все папки»."""
        self.only = None if self.only is not None else set(self.small_folders)
        self.build_tree()
