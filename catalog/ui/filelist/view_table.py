"""FileListWindow, загрузка списка, итоги, фильтры.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import disk_ui
import service as sv

from .texts_list import files_word, KIND_TITLE, totals_line
from .common import _esc, FILTER_MS, _last_line, _safe, WIDTH
from .model_rows import prepare


class TableView:
    """Часть FileListWindow (загрузка списка, итоги, фильтры);
    атрибуты - у FileListWindow."""

    # --- загрузка ---
    def load(self):
        self.req += 1
        req = self.req
        self.busy(True)
        self.total.setText('Загружаю список из базы (диски не читаются)…')
        spec = dict(self.spec)
        if self.page is not None and self.can_mark():
            spec['drafts'] = self.page.model.draft_rows()   # тот же черновик, что у «Разбора»

        def job():
            data = prepare(sv.file_list(**spec))
            try:
                data['disk_rows'] = sv.disks()
            except Exception:                                     # noqa: BLE001 - подписи дисков не обязательны
                data['disk_rows'] = []
            return data

        self.win.bg.run(lambda: _safe(job), ok=lambda res: self.got(req, res), quiet=True)

    def got(self, req, res):
        if self.closed or req != self.req:
            return                                               # окно закрыто или ответ устарел
        self.busy(False)
        kind, val = res
        if kind != 'ok':
            self.total.setText(f'<span style="color:#c62828">Список не получен: {_esc(_last_line(val))}</span>')
            return
        self.data = val
        self.disk_rows = val.get('disk_rows') or []
        self.model.letters = {r['disk']: r['letter'] for r in self.disk_rows if r.get('letter')}
        self.model.set_rows(self.kind, val['model_rows'])
        self.carrier.setText(self.carrier_text())
        self.set_widths()
        self.stale.hide()
        self.title.setText(self.title_text())
        self.sub.setText(f'Папка: <b>{_esc(val["scope"])}</b> и вложенные. Почему эти файлы: {_esc(val["why"])}.')
        notes = val.get('notes') or []
        self.notes.setText('\n'.join(notes))
        bad = any(x.startswith(('ИТОГ НЕВЕРЕН', 'ВНИМАНИЕ')) for x in notes)
        self.notes.setStyleSheet('color:#c62828; font-weight:bold' if bad else 'color:#5d4037')
        self.notes.setVisible(bool(val.get('notes')))
        self.build_tree()
        self.show_totals()
        self.update_buttons()

    def busy(self, on):
        for w in (self.open_btn, self.excel_btn, self.rescan_btn, self.refresh_btn):
            w.setEnabled(not on)

    def set_widths(self):
        for j, col in enumerate(self.model.cols):
            self.view.setColumnWidth(j, WIDTH.get(col, 120))

    def place(self, disk):
        r = next((x for x in self.disk_rows if x['disk'] == disk), None)
        name = disk_ui.disk_place(r) if r else ''
        return f'{name} ({disk})' if name and name != disk else disk

    def title_text(self):
        d = self.data or {}
        what = KIND_TITLE.get(self.kind, '')
        if self.kind == 'copy':
            return f'{self.disk} · {what} {self.place(d.get("target"))}'
        if self.kind == 'have':
            return f'{self.disk} · {what} ' + ' и '.join(self.place(x) for x in d.get('targets') or [])
        if self.kind == 'type':
            return f'{self.disk} · {what} «{d.get("direction", "")}»'
        return f'{self.disk} · {what}'

    def show_totals(self):
        m = self.model
        self.total.setText('Всего: ' + totals_line(m.totals(visible=False)))
        if m.filtered():
            self.shown.setText('Показаны по фильтру: ' + totals_line(m.totals()))
        else:
            self.shown.setText(f'Показаны все: {files_word(m.rowCount())}')

    # --- фильтр ---
    def filter_later(self, *_):
        self.ftimer.start(FILTER_MS)

    def apply_filter(self):
        types = {i for i, b in enumerate(self.type_boxes) if b.isChecked()}
        # текст поиска - как набран: пробелы по краям тоже ищутся (имена папок с пробелом, этап 16)
        self.model.set_filter(types, self.folder_edit.text(), self.name_edit.text(),
                              min_size=self.size_box.value() * 1024)
        self.show_totals()
        self.update_buttons()
