"""FileListWindow, галочки дерева = отметки «Разбора носителя», синхронизация с ним.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import QTimer, Qt

from .common import F_PART, F_ROLE, RELOAD_MS


class SyncView:
    """Часть FileListWindow (галочки дерева = отметки «Разбора носителя», синхронизация с ним);
    атрибуты - у FileListWindow."""

    def can_mark(self):
        """Галочки дерева = отметки страницы «Разбор»: только для её носителя и диска назначения, не во время записи."""
        p = self.page
        return bool(p is not None and p.model is not None and p.disk == self.disk and p.dest == self.spec.get('num')
                    and not p.writing and not p.saving)

    def refresh_checks(self):
        """Галочки дерева по маршруту «Разбора»: папка идёт в диск назначения - отмечена (с исключениями внутри -
        частично), иначе - нет. Пока «Разбор» пишет или выбран другой носитель / диск - неактивны."""
        p = self.page
        if p is None or self.closed:
            return
        ok = self.can_mark()
        m = p.model if p.model is not None and p.disk == self.disk else None
        num = self.spec.get('num')
        if p.saving or p.writing:
            self.marks_note.setText('Идёт запись отметок в «Разборе носителя» — галочки ненадолго неактивны.')
        elif not ok:
            self.marks_note.setText('Галочки неактивны: в «Разборе носителя» сейчас другой носитель или диск назначения.')
        else:
            self.marks_note.setText('Галочка снята — папка не копируется (сохраняется сразу; «Отменить последнее» — в '
                                    '«Разборе носителя»). Щелчок по имени — показать файлы папки.')
        part = m.partial(num) if m is not None else {}
        self.painting = True
        was = self.ftree.signalsBlocked()
        self.ftree.blockSignals(True)
        try:
            for f, it in self.f_items.items():
                if not f or m is None or not m.markable(f):
                    it.setData(0, Qt.CheckStateRole, None)
                    continue
                on = m.is_dir(m.route.get(f), num)
                pm = part.get(f)
                st = Qt.PartiallyChecked if (on and pm == 'off') or (not on and pm == 'on') else \
                    (Qt.Checked if on else Qt.Unchecked)
                fl = it.flags()
                it.setFlags((fl | Qt.ItemIsUserCheckable) if ok else (fl & ~Qt.ItemIsUserCheckable))
                it.setCheckState(0, st)
                it.setData(1, F_PART, pm if st == Qt.PartiallyChecked else None)   # что делает щелчок
        finally:
            self.ftree.blockSignals(was)
            self.painting = False

    def on_saving(self, _on=False):
        self.refresh_checks()

    def f_changed(self, item, col):
        if self.painting or col != 0:
            return
        self.check_click = True                     # тот же щелчок придёт и в itemClicked - он не фильтр
        QTimer.singleShot(0, lambda: setattr(self, 'check_click', False))   # только для этого щелчка
        f = item.data(0, F_ROLE)
        if not f or not self.can_mark():
            self.refresh_checks()
            return
        part = item.data(1, F_PART)                    # частичная: 'off' - снять всю, 'on' - выбрать всю
        on = (part == 'on') if part else item.checkState(0) == Qt.Checked
        self.keep.add(f)
        if not self.page.set_in_dest([f], on):
            self.refresh_checks()

    def on_marks(self, _rev=0):
        """Отметки в «Разборе» изменились: галочки - сразу, список - перечитать (ответ старого запроса отбросится)."""
        if self.closed:
            return
        self.refresh_checks()
        self.reload_timer.start(RELOAD_MS)
