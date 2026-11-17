"""RazborPage, блок «дерево папок»: ленивое дерево, строки «ещё N папок», перетаскивание (DragTree).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPalette
from PySide6.QtWidgets import QAbstractItemView, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem

from hb_core.directions import R_DIR

from ui_common import timed

from .common import (CHUNK, C_CHECK, C_FILES, C_GB, C_HAVE, C_NAME, C_OTHER, C_PHOTO, C_VIDEO, EXC_BG, EXC_FG, FILLED,
                     GRAY_ROLE, MIME, MORE_ROLE, PALE, PART_ROLE, ROLE, SEL_BG, SEP, TAG_ROLE, folders_mime, last)
from .texts_cell import BLUE, EXCEPT, GRAY, ONLY, gb, num, plural


class TreeDelegate(QStyledItemDelegate):
    """Колонка галочек: серая (неактивная) галочка - у папок, выбранных вместе с родителем. Колонка имени: мелкая серая
    метка «Н2» справа от имени - папка отмечена для другого направления."""

    def initStyleOption(self, option, index):                 # noqa: N802
        super().initStyleOption(option, index)
        if index.column() == C_CHECK and index.data(GRAY_ROLE):
            option.state &= ~QStyle.State_Enabled
            option.palette.setColor(QPalette.Text, QColor(PALE))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        tag = index.data(TAG_ROLE) if index.column() == C_NAME else None
        if not tag:
            return
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        st = opt.widget.style() if opt.widget else None
        r = st.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget) if st else opt.rect
        x = r.left() + QFontMetrics(opt.font).horizontalAdvance(opt.text) + 10
        f = QFont(opt.font)
        f.setPointSizeF(max(6.0, f.pointSizeF() * 0.8))
        painter.save()
        painter.setFont(f)
        painter.setPen(QColor(GRAY))
        painter.drawText(x, r.top(), 60, r.height(), Qt.AlignVCenter | Qt.AlignLeft, tag)
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        if index.column() == C_NAME and index.data(TAG_ROLE):
            s.setWidth(s.width() + 40)
        return s


class DragTree(QTreeWidget):
    """Дерево папок: выделенные папки перетаскиваются в ячейки справа. Весь носитель и служебные папки не тащатся
    (у них нет флага перетаскивания). Сброс на само дерево ничего не делает: случайное движение мыши отметку не снимает."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.press_sel = None                             # выделенные папки в момент нажатия мыши (до смены выделения)

    def mousePressEvent(self, e):                             # noqa: N802
        """Выделение запоминается ДО того, как Qt его поменяет: щелчок по галочке невыделенной папки выделяет её на
        нажатии, а галочка меняется на отпускании - групповое действие решается по выделению до щелчка (этап 12)."""
        self.press_sel = self.page.selected_folders()
        super().mousePressEvent(e)
        self.multi(e)

    def mouseReleaseEvent(self, e):                           # noqa: N802
        """Qt у уже выделенной строки меняет выделение при отпускании - проверяем и здесь."""
        try:
            super().mouseReleaseEvent(e)
            self.multi(e)
        finally:
            self.press_sel = None

    def multi(self, e):
        """Решение владельца 16.11: выделение нескольких папок (Shift/Ctrl-щелчок) СРАЗУ ставит им галочки; щелчок по
        галочке любой выделенной ставит и снимает галочки у всей группы (этап 12), невыделенной - только у неё."""
        if self.indexAt(e.position().toPoint()).column() == C_CHECK:
            return                                    # щелчок по галочке: группу меняет item_changed (этап 12)
        if e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier) and len(self.selectedItems()) > 1:
            QTimer.singleShot(0, self.page.check_selected)

    def mimeTypes(self):                                      # noqa: N802
        return [MIME]

    def mimeData(self, items):                                # noqa: N802
        m = self.page.model
        return folders_mime([f for f in (it.data(C_NAME, ROLE) for it in items) if f and m and m.markable(f)])

    def supportedDropActions(self):                           # noqa: N802
        return Qt.CopyAction


class TreeView:
    """Часть RazborPage (блок «дерево папок»); атрибуты - у RazborPage."""

    @timed('Разбор: rebuild_tree')
    def rebuild_tree(self):
        """Перестроить дерево, сохранив раскрытые узлы, выделение и прокрутку (по путям). Только при смене носителя или
        состава папок (после записи отметок - обновление на месте, update_items)."""
        expanded = {p for p, it in self.items.items() if it.isExpanded()}
        selected = {it.data(C_NAME, ROLE) for it in self.tree.selectedItems()}
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self.items = {}
        self.views = {}
        m = self.model
        root = QTreeWidgetItem()
        root.setData(C_NAME, ROLE, '')
        root.setFlags(root.flags() & ~Qt.ItemIsDragEnabled)       # весь носитель - это режим, не перетаскивается
        for c in range(C_FILES, C_HAVE + 1):
            root.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.addTopLevelItem(root)
        self.items[''] = root
        self.set_item(root, '')
        self.fill(root)
        root.setExpanded(True)
        for p in sorted(expanded, key=lambda x: x.count(SEP)):
            it = self.items.get(p)
            if it is not None and p in m.folders:
                it.setExpanded(True)                     # -> expand(): дети создаются
        for p in selected:
            if p in self.items:
                self.items[p].setSelected(True)
        QTimer.singleShot(0, lambda: self.tree.verticalScrollBar().setValue(scroll))

    @timed('Разбор: fill')
    def fill(self, item, start=0):
        """Создать детей узла (лениво: внуки - по раскрытию). Этап 17: не больше CHUNK за раз, дальше - строка «ещё N
        папок — показать» (у winsxs HDD37 13 361 подпапка: 13 тыс. строк создавались 1,3 с и обновлялись по 0,8 с)."""
        p = item.data(C_NAME, ROLE)
        kids = self.model.children.get(p, ())
        self.tree.blockSignals(True)
        try:
            if start == 0:
                for ch in item.takeChildren():
                    self.forget(ch)
            else:
                for i in reversed(range(item.childCount())):           # прежняя строка «ещё …»
                    if item.child(i).data(C_NAME, MORE_ROLE) is not None:
                        item.takeChild(i)
            item.setData(C_NAME, FILLED, True)           # дети созданы
            new = []
            for f in kids[start:start + CHUNK]:
                ch = QTreeWidgetItem()
                ch.setData(C_NAME, ROLE, f)
                for c in range(C_FILES, C_HAVE + 1):
                    ch.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                if not self.model.markable(f):
                    ch.setFlags(ch.flags() & ~Qt.ItemIsDragEnabled)
                self.items[f] = ch
                self.views.pop(f, None)
                self.set_item(ch, f)
                if self.model.children.get(f):
                    ph = QTreeWidgetItem()
                    ph.setText(C_NAME, '…')
                    ch.addChild(ph)
                new.append(ch)
            rest = len(kids) - start - CHUNK
            if rest > 0:
                more = QTreeWidgetItem()
                more.setText(C_NAME, f'ещё {num(rest)} {plural(rest, "папка", "папки", "папок")} — показать '
                                     f'(по {CHUNK})')
                more.setData(C_NAME, MORE_ROLE, (p, start + CHUNK))
                more.setForeground(C_NAME, QBrush(QColor(BLUE)))
                more.setToolTip(C_NAME, 'Большая папка: подпапки показываются порциями, чтобы окно не замирало.')
                more.setFlags(Qt.ItemIsEnabled)
                new.append(more)
            item.addChildren(new)
        finally:
            self.tree.blockSignals(False)

    def forget(self, it):
        """Строка дерева удалена: убрать её и её созданных потомков из словарей строк и видов."""
        stack = [it]
        while stack:
            x = stack.pop()
            f = x.data(C_NAME, ROLE)
            if f is not None and self.items.get(f) is x:
                del self.items[f]
                self.views.pop(f, None)
            stack.extend(x.child(i) for i in range(x.childCount()))

    def more_clicked(self, it, _col=0):
        """Щелчок по «ещё N папок — показать»: следующая порция детей."""
        more = it.data(C_NAME, MORE_ROLE)
        if not more or self.model is None:
            return
        parent = self.items.get(more[0])
        if parent is not None:
            self.fill(parent, more[1])

    def show_more(self, folder):
        """Для тестов и переходов: показать ещё одну порцию детей папки."""
        it = self.items.get(folder)
        if it is not None:
            for i in range(it.childCount()):
                if it.child(i).data(C_NAME, MORE_ROLE) is not None:
                    self.more_clicked(it.child(i))
                    return True
        return False

    def expand(self, item):
        if not item.data(C_NAME, FILLED) and item.data(C_NAME, ROLE) is not None:
            self.fill(item)

    def set_item(self, it, f, mode=None):
        """Показать папку в строке. Этап 17: сначала - кортеж всего показываемого; совпал с прежним (self.views) -
        сеттеры Qt не вызываются (их по ~15 на строку, при 13 тыс. строк - секунда)."""
        m = self.model
        files, size, n, b = m.folders.get(f, (0, 0, (0,) * 5, (0,) * 5))
        lk = m.look(f)
        mode = mode or (self.mode() if self.dest else ONLY)
        ck = m.check(f, self.dest, mode) if self.dest else None
        if not f and self.dest and mode == ONLY:
            ck = self.root_check()                        # «выбрать все» - у строки носителя
        name = f'{self.disk} (весь носитель)' if not f else last(f)
        hv = None if m.have_sub is None else m.have_sub.get(f)
        r_ = m.route.get(f)
        view = (name, mode, tuple(sorted(lk.items())), tuple(sorted(ck.items())) if ck else None, files, size, n, b,
                m.have_sub is None, tuple(hv) if hv else None, (r_.state, r_.num) if r_ is not None else None)
        if self.views.get(f) == view and self.items.get(f) is it:
            return False
        self.views[f] = view
        self.painting = True
        try:
            it.setText(C_NAME, ('• ' if lk['dirty'] else '') + name)
            tip = lk['tip']
            if ck and ck['tip']:
                tip = ck['tip'] + ' ' + tip
            it.setToolTip(C_NAME, tip)
            font = QFont()
            font.setItalic(bool(lk['dirty']))
            font.setBold(not f or bool(ck and ck['on'] and not ck['gray']))
            it.setFont(C_NAME, font)
            flags = it.flags()
            if ck is None:
                it.setData(C_CHECK, Qt.CheckStateRole, None)
                it.setFlags(flags & ~Qt.ItemIsUserCheckable)
                it.setData(C_CHECK, GRAY_ROLE, False)
                it.setData(C_NAME, TAG_ROLE, None)
            else:
                it.setFlags((flags | Qt.ItemIsUserCheckable) if ck['checkable'] else (flags & ~Qt.ItemIsUserCheckable))
                state = ck.get('state', Qt.Checked if ck['on'] else Qt.Unchecked)
                it.setCheckState(C_CHECK, state)
                it.setData(C_CHECK, PART_ROLE, ck.get('click') if f else None)   # что делает щелчок по частичной
                it.setData(C_CHECK, GRAY_ROLE, not ck['checkable'] or bool(ck['gray']))
                it.setToolTip(C_CHECK, ck['tip'] or ('Снять галочку' if ck['on'] else 'Поставить галочку'))
                it.setData(C_NAME, TAG_ROLE, ck['tag'] or None)
            on = bool(f and ck and ck['on'])
            red = on and mode == EXCEPT                   # «Все, кроме выбранных»: выбранные НЕ копируются - красным
            bg = QBrush(QColor(EXC_BG if red else SEL_BG)) if on else QBrush()
            for c in range(C_CHECK, C_HAVE + 1):
                it.setBackground(c, bg)
            if lk['dirty'] in ('own', 'drop'):
                color = BLUE                              # своя несохранённая отметка
            elif lk['kind'] in ('service', 'moved'):
                color = GRAY
            elif ck and ck['gray']:
                color = PALE                              # выбрана вместе с родителем - бледно (курсив, если не сохранено)
            elif lk['dirty']:
                color = BLUE
            elif red:
                color = EXC_FG
            else:
                color = None
            for c in range(C_NAME, C_HAVE + 1):
                it.setForeground(c, QBrush(QColor(color)) if color and (c == C_NAME or color == PALE) else QBrush())
            it.setText(C_FILES, num(files))
            it.setText(C_GB, gb(size))
            it.setText(C_PHOTO, num(n[0]))
            it.setText(C_VIDEO, num(n[1]))
            it.setText(C_OTHER, num(n[2] + n[3] + n[4]))
            it.setToolTip(C_GB, f'фото {gb(b[0])} ГБ, видео {gb(b[1])} ГБ, документы {gb(b[2])} ГБ, прочие {gb(b[3])} ГБ, '
                                f'мусор {gb(b[4])} ГБ')
            it.setToolTip(C_OTHER, f'документы {num(n[2])}, прочие {num(n[3])}, мусор {num(n[4])}')
            if m.have_sub is None:
                it.setText(C_HAVE, '…')
                it.setToolTip(C_HAVE, 'Считаю, что уже есть на дисках направлений…')
            else:
                v = m.have_sub.get(f)
                r = m.route.get(f)
                with_disk = r is not None and r.state == R_DIR and m.dirs.get(r.num) is not None and m.dirs[r.num].disks
                it.setText(C_HAVE, num(v[0]) if v else ('0' if with_disk else '—'))
                it.setToolTip(C_HAVE, f'{num(v[0])} файлов, {gb(v[1])} ГБ уже есть на всех дисках своего направления '
                                      '(по хешу)' if v else 'Ничего из этой папки на дисках направления по хешу не найдено.')
        finally:
            self.painting = False
        return True

    @timed('Разбор: update_items')
    def update_items(self):
        """Обновить созданные строки на месте (этап 17: только изменившиеся, без сигналов itemChanged)."""
        if self.model is not None:
            mode = self.mode() if self.dest else ONLY
            folders = self.model.folders
            self.tree.blockSignals(True)
            try:
                for f, it in self.items.items():
                    if f in folders:
                        self.set_item(it, f, mode)
            finally:
                self.tree.blockSignals(False)
        self.render_cells()
