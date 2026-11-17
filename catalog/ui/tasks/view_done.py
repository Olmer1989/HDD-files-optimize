"""«Задания на копирование»: свёрнутый список «Готово (N)» и окно «Что осталось на старом месте» (часть-«примесь» класса
TasksPage).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from hb_core import api as hb

from .common import AMBER, RED
from .texts_words import gb, n
from .model_rules import done_rows
from .widgets import _cell


class DoneView:
    """Часть TasksPage: свёрнутый список «Готово (N)» и окно «Что осталось на старом месте»."""

    # --- «Готово (N)» ---
    def _done_title(self, k):
        self.done_btn.setText(('▾ ' if self.done_btn.isChecked() else '▸ ') + f'Готово ({k})')

    def render_done(self, sel=None):
        self.dlist = done_rows(self.rows, self.done_items)
        t = self.done_t
        t.blockSignals(True)
        t.clearSelection()
        t.setRowCount(len(self.dlist))
        for i, d in enumerate(self.dlist):
            t.setItem(i, 0, _cell(d['task'], tip=d['tip']))
            t.setItem(i, 1, _cell(n(d['files']), right=True))
            t.setItem(i, 2, _cell(d['gb'], right=True))
            if d['left']:
                t.setItem(i, 3, _cell(f'осталось на месте: {n(d["left"])}', color=AMBER,
                                      tip='Двойной щелчок — почему файлы остались на старом месте'))
            else:
                t.setItem(i, 3, _cell(n(d['errors']) if d['errors'] else '0', right=True,
                                      color=RED if d['errors'] else None))
            t.setItem(i, 4, _cell(d['date']))
            if sel and d['task'] == sel['task'] and not t.isHidden():
                t.selectRow(i)
        t.blockSignals(False)
        self._done_title(len(self.dlist))

    def on_done_toggle(self, on):
        self.done_t.setVisible(on)
        if not on:
            self.done_t.clearSelection()
        self._done_title(len(self.dlist))

    def on_done_double(self, row, _col):
        if not (0 <= row < len(self.dlist)):
            return
        d = self.dlist[row]
        if d['left'] and d['item']:
            self.show_left(d['item'])
        else:
            self.start_file(str(hb.TASKS / d['task']))

    def show_left(self, it):
        lines = [f'{why}: {n(v[0])} файлов, {gb(v[1])} ГБ' for why, v in sorted(it.get('reasons', {}).items())]
        self.show_text('Что осталось на старом месте', f'{it["text"]}\n\nПо расчёту перед переносом:\n'
                       + ('\n'.join(lines) or '—') + '\n\nСтроки журнала, кроме «перемещён», — в папке задания '
                       f'«{it["task"]}» («Открыть журнал»).')
