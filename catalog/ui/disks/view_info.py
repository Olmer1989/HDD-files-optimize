"""«Диски и папки»: строка сведений над деревом («Хеш есть у всех … · Без хеша: N … · Показать») и столбец «Без хеша»
(часть-«примесь» класса DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import service as sv
from overview_page import gb_ru, n_ru

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from .texts_info import nohash_html
from .common import DISK_ROLE, T_NAME, T_NOHASH


class InfoView:
    """Часть DisksPage: строка сведений над деревом и столбец «Без хеша»."""

    def show_hash_info(self, disk, res):
        if res.get('nohash') is not None:
            self.nohash[disk] = res['nohash']
            self.fill_nohash(disk)
        if disk != self.disk or self.found:
            return
        r = self.row_of(disk)
        self.tree_sum.setText(f'{n_ru(r.get("files"))} файлов · {gb_ru(r.get("gib") or 0)} ГБ · {res["text"]}')
        self.tree_sum.setToolTip(res.get('tip', ''))
        self.hash_lab.setText(nohash_html(res))

    # --- «Без хеша» (этап 16) ---
    def need_nohash(self, disk):
        """Число «без хеша» по папкам носителя - один проход в фоне на носитель (нужно для найденных папок)."""
        if disk in self.nohash or disk in self.nohash_busy:
            return
        self.nohash_busy.add(disk)

        def got(res):
            self.nohash_busy.discard(disk)
            self.nohash[disk] = res
            self.fill_nohash(disk)
        self.win.bg.run(sv.nohash_info, disk, ok=got, quiet=True)

    def nohash_cell(self, it):
        disk, path = it.data(T_NAME, DISK_ROLE), it.data(T_NAME, Qt.UserRole) or ''
        info = self.nohash.get(disk)
        if info is None:
            it.setText(T_NOHASH, '…')
            return
        n = info['folders'].get(path, 0)
        it.setData(T_NOHASH, Qt.UserRole, n)
        it.setTextAlignment(T_NOHASH, Qt.AlignRight | Qt.AlignVCenter)
        if n:
            it.setText(T_NOHASH, n_ru(n))
            it.setForeground(T_NOHASH, QColor('#1565c0'))
            f = QFont(self.tree.font())
            f.setUnderline(True)
            it.setFont(T_NOHASH, f)
            it.setToolTip(T_NOHASH, f'{n_ru(n)} файлов без хеша - щелчок: их список')
        else:
            it.setText(T_NOHASH, '—')                     # ноль - серый прочерк, не ссылка
            it.setForeground(T_NOHASH, QColor('#bdbdbd'))

    def fill_nohash(self, disk):
        self.tree.blockSignals(True)
        for it in self.all_items():
            if it.data(T_NAME, DISK_ROLE) == disk:
                self.nohash_cell(it)
        self.tree.blockSignals(False)

    def item_clicked(self, it, col):
        if col == T_NOHASH and it.data(T_NOHASH, Qt.UserRole):
            self.show_nohash(it.data(T_NAME, DISK_ROLE), it.data(T_NAME, Qt.UserRole) or '')

    def show_nohash(self, disk, path):
        """Окно «Список файлов» - файлы без хеша папки (весь носитель - '')."""
        if not disk:
            return None
        from ui.filelist import page as filelist_window
        return filelist_window.open_list(self.win, kind='nohash', disk=disk, folder=path)
