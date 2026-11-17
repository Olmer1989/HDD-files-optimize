"""RazborPage, блок «галочки»: галочка у папки, у выделенных, «выбрать все».

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QTimer, Qt

from .common import C_CHECK, C_NAME, PART_ROLE, ROLE
from .texts_cell import EXCEPT, ONLY


class ChecksView:
    """Часть RazborPage (блок «галочки»); атрибуты - у RazborPage."""

    def item_changed(self, it, col):
        if self.painting or col != C_CHECK or self.model is None:
            return
        f = it.data(C_NAME, ROLE)
        on = it.checkState(C_CHECK) == Qt.Checked
        part = it.data(C_CHECK, PART_ROLE)
        if part:                                          # частичная: 'off' - снять всю (этап 17), 'on' - выбрать всю (18)
            on = part == 'on'
        if not f:
            self.select_all(on)
            return
        # этап 12 (решение владельца 16.11): галочка выделенной папки при нескольких выделенных - у всей выделенной
        # группы (одним шагом отмены); невыделенной - только у неё. Выделение - каким оно было до щелчка мышью.
        tree = self.tree
        sel = tree.press_sel if tree.press_sel is not None else self.selected_folders()
        if f in sel and len(sel) > 1:
            group = list(sel)
            if self.toggle(group, on):
                QTimer.singleShot(0, lambda fs=group: self.reselect(fs))
            else:
                self.update_items()
            return
        self.toggle([f], on)

    def check_selected(self):
        """Выделено несколько папок (Shift/Ctrl-щелчок) - всем выделенным сразу ставится галочка одним шагом отмены."""
        sel = self.selected_folders()
        if len(sel) > 1 and self.model is not None and self.dest:
            if self.toggle(sel, True):
                QTimer.singleShot(0, lambda fs=sel: self.reselect(fs))

    def tops(self):
        m = self.model
        return [f for f in m.children.get('', ()) if m.markable(f)] if m else []

    def root_check(self):
        """Галочка «выбрать все» у строки носителя (режим «Только выбранные»): все папки верхнего уровня идут в D -
        отмечена; часть - частично; ни одной - пусто."""
        m, tops = self.model, self.tops()
        if not tops:
            return None
        n = sum(1 for f in tops if m.is_dir(m.route[f], self.dest))
        state = Qt.Checked if n == len(tops) else Qt.PartiallyChecked if n else Qt.Unchecked
        return dict(on=n == len(tops), gray=False, checkable=True, tag='', state=state,
                    tip='Выбрать все папки верхнего уровня (или снять все). Исключения внутри папок не меняются.')

    def select_all(self, on):
        """Щелчок по галочке «выбрать все»: не все выбраны - выбрать все папки верхнего уровня; все - снять."""
        m = self.model
        if m is None or self.writing or not self.dest or self.mode() != ONLY:
            self.update_items()
            return 0
        tops = self.tops()
        pairs = m.include_pairs(tops, self.dest) if on else m.exclude_pairs(tops, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        self.after_marks() if n else self.update_items()
        if n:
            self.win.statusBar().showMessage(('Выбраны все' if on else 'Сняты все') + f' папки верхнего уровня ({len(tops)}). '
                                             'Сохраняется сразу.', 8000)
        return n

    def reselect(self, folders):
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        for x in folders:
            if x in self.items:
                self.items[x].setSelected(True)
        self.tree.blockSignals(False)

    def toggle(self, folders, on):
        """Галочка поставлена (on) или снята у папок: в «Только выбранные»/«Все папки» - включить в D / исключить;
        в «Все, кроме выбранных» - наоборот (галочка = исключение). -> число изменённых записей черновика."""
        m = self.model
        if m is None or self.writing or not self.dest:
            return 0
        ok = [f for f in folders if f and m.markable(f) and (m.check(f, self.dest, self.mode()) or {}).get('checkable')]
        include = on != (self.mode() == EXCEPT)
        pairs = m.include_pairs(ok, self.dest) if include else m.exclude_pairs(ok, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        self.after_marks() if n else self.update_items()
        if n:
            self.win.statusBar().showMessage(f'Папок: {len(ok)} — ' + ('галочка поставлена' if on else 'галочка снята') +
                                             '. Сохраняется сразу.', 8000)
        return n
