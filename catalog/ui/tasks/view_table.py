"""«Задания на копирование»: таблица заданий: обновление, плашки, галочки, выделение; «Открыть журнал», «Открыть папку
задания» (часть-«примесь» класса TasksPage).

Шаг А разбивки (17.11.2026): перенесено из tasks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import html

from hb_core import api as hb

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem

from .common import GREY, RED
from .texts_words import gb, n
from .texts_rows import errors_tip, state_text, summary, what_where
from .model_rules import checkable
from .model_load import load_all
from .widgets import _cell, _chip_style


class TableView:
    """Часть TasksPage: таблица заданий: обновление, плашки, галочки, выделение; «Открыть журнал», «Открыть папку
    задания»."""

    # --- данные ---
    def refresh(self):
        self.win.bg.run(load_all, ok=lambda res: self.render(*res), quiet=True)

    def render(self, rows, groups=None):
        sel = self.current()
        self.rows = rows
        if groups is not None:
            self.groups = groups
        running = {r['task'] for r in rows if r['state'] == 'идёт'}
        if self.queue and not running and all(r['state'] != 'не запускалось' for r in rows if r['task'] in self.queue):
            self.queue = []
        self.render_chips()
        self.trows = [r for r in rows if r['state'] != 'готово']
        self.checked = {r['task'] for r in self.trows if r['task'] in self.checked and checkable(r)}
        self.t.blockSignals(True)
        self.t.clearSelection()
        self.t.setRowCount(len(self.trows))
        for i, r in enumerate(self.trows):
            box = QTableWidgetItem('')
            if checkable(r):
                box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                box.setCheckState(Qt.Checked if r['task'] in self.checked else Qt.Unchecked)
            else:
                box.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                box.setToolTip('Идёт — запускать нечего' if r['state'] == 'идёт' else
                               'Не удалось узнать, идёт ли задание: нажмите «Обновить»'
                               if r['state'] == 'состояние неизвестно' else
                               'Не скопированное — кнопкой «Повторить копирование» ниже')
            self.t.setItem(i, 0, box)
            l1, l2 = what_where(r)
            it = QTableWidgetItem('')
            it.setData(Qt.UserRole, f'{l1}\n{l2}')
            it.setToolTip(f'Задание: {r["task"]}\n{r.get("disks_long") or r.get("disks", "")}')
            self.t.setItem(i, 1, it)
            lab = QLabel(f'{html.escape(l1)}<br><span style="color:{GREY}; font-size:9pt">{html.escape(l2)}</span>')
            lab.setTextFormat(Qt.RichText)
            lab.setContentsMargins(4, 2, 4, 2)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.t.setCellWidget(i, 1, lab)
            text, color = state_text(r, self.queue)
            self.t.setItem(i, 2, _cell(text, color=color))
            done = _cell(f'{n(r["done"])} из {n(r["total"])}', right=True,
                         tip=f'{gb(r.get("done_b", 0))} из {gb(r.get("total_b", 0))} ГБ' if r['kind'] == 'копирование'
                         else '')
            self.t.setItem(i, 3, done)
            bad = r['errors'] + r['skipped']
            self.t.setItem(i, 4, _cell(n(bad) if bad else '', right=True, color=RED if bad else None, tip=errors_tip(r)))
            self.t.setRowHeight(i, 46)
            if sel and r['task'] == sel['task']:
                self.t.selectRow(i)
        self.t.blockSignals(False)
        widths = [self.t.cellWidget(i, 1).sizeHint().width() for i in range(len(self.trows))]
        self.t.setColumnWidth(1, min(700, max([260] + widths) + 16))
        # таблица - по числу строк (до 8 видно сразу, дальше прокрутка): место ниже - блоку перемещения и «Готово»
        self.t.setFixedHeight(self.t.horizontalHeader().sizeHint().height() + 46 * max(2, min(8, len(self.trows))) + 6)
        self.update_run_btn()
        self.render_blocks()
        self.render_done(sel)
        busy = bool(running) or bool(self.queue)
        if busy and not self.timer.isActive():
            self.timer.start(5000)
        elif not busy and self.timer.isActive():
            self.timer.stop()

    def render_chips(self):
        while self.chips_lay.count():                       # плашки и растяжка - убираются из ряда сразу
            item = self.chips_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.chips = []
        for text, color in summary(self.rows, self.queue):
            lab = QLabel(text)
            lab.setStyleSheet(_chip_style(color))
            self.chips_lay.addWidget(lab)
            self.chips.append(lab)
        self.chips_lay.addStretch(1)

    def update_run_btn(self):
        self.run_btn.setText(f'Запустить отмеченные ({len(self.checked)})')

    def on_check(self, it):
        if it.column() != 0 or not (0 <= it.row() < len(self.trows)):
            return
        r = self.trows[it.row()]
        if not checkable(r):
            return
        (self.checked.add if it.checkState() == Qt.Checked else self.checked.discard)(r['task'])
        self.update_run_btn()

    def _only_one(self, a, b):
        if a.selectionModel().selectedRows():
            b.blockSignals(True)
            b.clearSelection()
            b.blockSignals(False)

    def current(self):
        for t, lst in ((self.t, self.trows), (self.done_t, self.dlist)):
            rows = t.selectionModel().selectedRows() if not t.isHidden() else []
            if rows and 0 <= rows[0].row() < len(lst):
                name = lst[rows[0].row()]['task']
                return next((r for r in self.rows if r['task'] == name), None)
        return None

    def need(self):
        r = self.current()
        if not r:
            self.say('Сначала выберите задание в таблице (щелчок по строке).')
        return r

    # --- прочее ---
    def open_dir(self):
        r = self.need()
        if r:
            self.start_file(str(hb.TASKS / r['task']))

    def open_log(self):
        r = self.need()
        if r and r['journal']:
            self.start_file(r['journal'])
        elif r:
            self.say('Журнала ещё нет: задание не запускалось.')
