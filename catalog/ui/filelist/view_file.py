"""FileListWindow, строка носителя, строка «Файл: / Копия:» и выбранные строки таблицы.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import disk_ui

from .common import _esc, R_WHERE
from .model_rows import file_path


class FileView:
    """Часть FileListWindow (строка носителя, строка «Файл: / Копия:» и выбранные строки таблицы);
    атрибуты - у FileListWindow."""

    # --- дерево папок списка (этап 17) ---
    def carrier_text(self):
        """«Носитель: HDD09 «SN850» — сейчас подключён как F:» / «… — не подключён» (буква - по серийному номеру тома из
        описи, как у «Открыть в Проводнике»)."""
        r = next((x for x in self.disk_rows if x['disk'] == self.disk), None) or {'disk': self.disk, 'label': '',
                                                                                   'letter': ''}
        name = disk_ui.disk_name(r)
        head = f'Носитель: <b>{_esc(self.disk)}</b>' + (f' «{_esc(name)}»' if name else '')
        if r.get('letter'):
            return head + f' — <span style="color:#2e7d32">сейчас подключён как <b>{_esc(r["letter"])}</b></span>'
        return head + ' — <span style="color:#e65100">не подключён</span> (пути — от номера носителя)'

    def show_file_line(self):
        """Строка под таблицей: «Файл: <полный путь>» и (у списка «уже есть») «Копия: <полный путь>» - текущей строки;
        текст выделяется мышью."""
        ix = self.view.currentIndex()
        if not ix.isValid() or ix.row() >= self.model.rowCount() or not self.view.selectionModel().isSelected(ix):
            self.file_line.setText('')
            return
        r = self.model.row(ix.row())
        lines = ['Файл: ' + file_path(r, self.model.letters)]
        if r[R_WHERE]:
            lines.append('Копия: ' + r[R_WHERE])
        self.file_line.setText('\n'.join(lines))

    # --- выделение ---
    def selected_rows(self):
        return [self.model.row(ix.row()) for ix in self.view.selectionModel().selectedRows()]

    # --- действия ---
    def current(self):
        ix = self.view.currentIndex()
        rows = self.view.selectionModel().selectedRows()
        if ix.isValid() and any(r.row() == ix.row() for r in rows):
            return self.model.row(ix.row())
        return self.model.row(rows[0].row()) if rows else None
