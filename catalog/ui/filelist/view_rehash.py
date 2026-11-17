"""FileListWindow, кнопка «Досчитать хеш у выбранных…» (только список «без хеша», 18.11.2026, задача владельца).

Папки выделенных файлов (вложенные - вместе с верхней, корень - не входит) -> готовое окно пересканирования
(rescan_dialog.RescanDialog) с начальными галочками типов ВЫДЕЛЕННЫХ файлов (в окне их можно поменять). Сканер
работает по папкам: сохранённые хеши берёт, с диска читает только файлы выбранных типов без хеша. Носитель не
подключён - кнопка неактивна («Подключите диск»)."""
from PySide6.QtWidgets import QMessageBox

from hb_core import api as hb

from .common import R_DISK, R_FOLDER, R_K, TITLE
from .model_rows import collapse

REHASH_TIP = ('Сканер работает по папкам: пересканирует папки этих файлов, с диска прочитает только файлы выбранных '
              'типов без хеша; сколько — видно в окне до запуска.')


def rehash_cats(rows):
    """Типы выделенных файлов для галочек окна пересканирования (hb.COPY_CATS, по порядку); неизвестных нет - None."""
    have = {hb.CAT_OF_TYPE.get(r[R_K]) for r in rows} - {None}
    return [c for c in hb.COPY_CATS if c in have] or None


class RehashView:
    """Часть FileListWindow (кнопка «Досчитать хеш у выбранных…»); атрибуты - у FileListWindow."""

    def rehash_plan(self):
        """-> (диск, папки, типы, причина неактивности или '')."""
        rows = self.selected_rows() if self.data is not None else []
        disks = sorted({r[R_DISK] for r in rows})
        folders = collapse(r[R_FOLDER] for r in rows if r[R_FOLDER])
        disk = disks[0] if len(disks) == 1 else None
        if not rows:
            why = 'Выделите файлы в списке.'
        elif disk is None:
            why = 'Выделены файлы разных дисков - выделите файлы одного диска.'
        elif not self.model.letters.get(disk):
            why = 'Подключите диск'
        elif not folders:
            why = 'Файлы прямо в корне диска пересканирует только полная опись («Сканер дисков»).'
        else:
            why = ''
        return disk, folders, rehash_cats(rows), why

    def update_rehash_btn(self):
        if self.kind != 'nohash':
            self.rehash_btn.hide()
            return
        _disk, folders, _cats, why = self.rehash_plan()
        self.rehash_btn.setEnabled(not why)
        self.rehash_btn.setToolTip(why if why == 'Подключите диск' else REHASH_TIP + (f'\n{why}' if why else ''))
        self.rehash_btn.setText(f'Досчитать хеш у выбранных ({len(folders)} папок)…' if folders and not why else
                                'Досчитать хеш у выбранных…')

    def rehash_selected(self):
        disk, folders, cats, why = self.rehash_plan()
        if why:
            QMessageBox.information(self, TITLE, why if why != 'Подключите диск' else
                                    f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and getattr(running, 'running', False):
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        import rescan_dialog
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders, cats=cats)
        self.win.rescan.finished.connect(lambda *_: (not self.closed) and self.stale.show())
        self.win.rescan.show()
