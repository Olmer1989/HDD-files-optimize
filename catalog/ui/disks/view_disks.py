"""«Диски и папки»: таблица «Носители» - обновление, порядок, выбор носителя, переход из «Обзора» (часть-«примесь»
класса DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import disk_ui
import service as sv
from ui_common import cell
from overview_page import gb_ru, n_ru

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QTreeWidgetItem

from .texts_disks import disk_cell, scan_text
from .common import DISK_ROLE, T_NAME


class DisksView:
    """Часть DisksPage: таблица «Носители»."""

    def show_disk(self, disk):
        """Перейти к носителю (ссылка «Пересканировать» из «Обзора»): выбрать его строку и показать папки."""
        self.want = disk
        disks = [r['disk'] for r in self.rows]
        if disk in disks:
            self.want = None
            self.found = False
            self.t.setCurrentCell(disks.index(disk), 0)
            if self.disk != disk:
                self.pick()
            self.info.setText('Отметьте галочками папки и нажмите «Пересканировать выбранные…».')

    def refresh(self):
        """При каждом показе раздела и по «Обновить»: носители и какие из них подключены сейчас. Новая сборка базы -
        числа «Без хеша» считаются заново."""
        gen = None
        try:
            gen = sv.generation()
        except Exception:                                 # noqa: BLE001 - базы ещё нет
            pass
        if gen != getattr(self, 'nohash_gen', None):
            self.nohash, self.nohash_gen = {}, gen
        self.win.bg.run(sv.disks, ok=self.render)

    def render(self, rows):
        """Подключённые сейчас - первыми (жирным, зелёным), затем HDD по номеру, флешки в конце.
        Выбор сохраняется; если ничего не выбрано - выбирается первый подключённый и показываются его папки."""
        rows = disk_ui.ordered(rows)
        self.rows = rows
        self.count_lab.setText(f'<b>Носители ({len(rows)})</b> — подключённые сейчас сверху')
        self.t.blockSignals(True)
        self.t.clearSelection()
        self.t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            on = bool(r.get('letter'))
            vals = [disk_cell(r), 'да' if on else 'нет',
                    f'{gb_ru(r["free_gib"])} ГБ' if 'free_gib' in r else '—',
                    n_ru(r['files']), gb_ru(r['gib']), scan_text(r)]
            for j, v in enumerate(vals):
                it = cell(v, right=j in (2, 3, 4))
                it.setData(Qt.UserRole, r['disk'])
                if j == 5 and r.get('status'):
                    it.setToolTip(f'В описи: {r["status"]}')
                if on:
                    disk_ui.style_item(it.setData, True)
                elif j in (0, 1):
                    it.setForeground(QColor('#616161'))
                if j == 4:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.t.setItem(i, j, it)
        self.t.blockSignals(False)
        self.t.resizeColumnsToContents()
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        disks = [r['disk'] for r in rows]
        if self.want in disks:          # переход из «Обзора» по ссылке «Пересканировать»
            self.show_disk(self.want)
        elif self.disk in disks:                   # тот же носитель: дерево папок не перестраивать
            self.t.blockSignals(True)
            self.t.setCurrentCell(disks.index(self.disk), 0)
            self.t.blockSignals(False)
            self.update_actions()
        elif not self.found:
            first = next((i for i, r in enumerate(rows) if r.get('letter')), None)
            if first is not None:
                self.t.setCurrentCell(first, 0)  # -> pick(): папки верхнего уровня

    def row_of(self, disk):
        return next((r for r in self.rows if r['disk'] == disk), {'disk': disk, 'label': '', 'letter': ''})

    def pick(self):
        i = self.t.currentRow()
        if 0 <= i < len(self.rows):
            self.found = False
            r = self.rows[i]
            self.disk = r['disk']
            self.tree.clear()
            self.info.setText('')
            self.hash_lab.setText('Без хеша: считаю…')
            self.tree_title.setText(f'Папки диска {disk_cell(r)}')
            self.tree_sum.setText(f'{n_ru(r["files"])} файлов · {gb_ru(r["gib"])} ГБ')
            root = QTreeWidgetItem()
            root.setText(T_NAME, f'{self.disk} (весь диск)')
            root.setData(T_NAME, Qt.UserRole, '')
            root.setData(T_NAME, DISK_ROLE, self.disk)
            self.nohash_cell(root)
            self.tree.addTopLevelItem(root)
            self.load(root)
            root.setExpanded(True)
            disk = self.disk
            self.win.bg.run(sv.disk_hash_info, disk, ok=lambda res, d=disk: self.show_hash_info(d, res), quiet=True)
            self.update_actions()
