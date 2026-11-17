"""FileListWindow, кнопки: Проводник, Excel, пересканирование.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os
import subprocess

from PySide6.QtWidgets import QFileDialog, QMessageBox

import service as sv
from ui_common import log_error

from .texts_list import files_word, head, KIND_TITLE, n_text
from .common import _last_line, R_DISK, R_FOLDER, R_NAME, _safe, SEP, TITLE, XLSX_MAX
from .model_rows import collapse, save_table
from .model_table import export_values


class ButtonsView:
    """Часть FileListWindow (кнопки: Проводник, Excel, пересканирование);
    атрибуты - у FileListWindow."""

    def count_selected(self):
        """Подпись «Пересканировать папки выделенных (N папок, M файлов)…»: M - по таблице folders, в фоне."""
        if self.closed:
            return
        rows = self.selected_rows()
        disks = {r[R_DISK] for r in rows}
        folders = collapse(r[R_FOLDER] for r in rows if r[R_FOLDER])
        self.sel_folders = folders
        self.sel_files = None
        if not rows:
            self.rescan_btn.setText('Пересканировать папки выделенных…')
            self.update_buttons()
            return
        if len(disks) > 1 or not folders:
            self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок)…')
            self.update_buttons()
            return
        disk = next(iter(disks))
        self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок, считаю файлы…)…')

        def show(res):
            if self.closed or folders != self.sel_folders or res[0] != 'ok':
                return
            self.sel_files = sum(res[1].values())
            self.rescan_btn.setText(f'Пересканировать папки выделенных ({len(folders)} папок, '
                                    f'{files_word(sum(res[1].values()))})…')
        self.win.bg.run(lambda: _safe(sv.folders_files, disk, folders), ok=show, quiet=True)
        self.update_buttons()

    def update_buttons(self):
        has = self.data is not None
        self.open_btn.setEnabled(has and bool(self.view.selectionModel().selectedRows()))
        self.excel_btn.setEnabled(has and self.model.rowCount() > 0)
        self.rescan_btn.setEnabled(has and bool(self.view.selectionModel().selectedRows())
                                   and bool(getattr(self, 'sel_folders', None)))

    def open_explorer(self):
        r = self.current()
        if r is None:
            QMessageBox.information(self, TITLE, 'Выделите файл в списке.')
            return
        disk, folder, name = r[R_DISK], r[R_FOLDER], r[R_NAME]

        def show(res):
            if self.closed:
                return
            kind, val = res
            if kind != 'ok':
                QMessageBox.information(self, TITLE, (val if kind == 'refused' else _last_line(val)) +
                                        f'\n\nПапка в базе: {disk}\\{folder}')
                return
            open_in_explorer(self, val, folder, name)
        self.win.bg.run(lambda: _safe(sv.disk_letter, disk), ok=show, quiet=True)

    def save_excel(self):
        m = self.model
        n = m.rowCount()
        if not n:
            return
        base = f'{self.disk} - {KIND_TITLE.get(self.kind, "список")}'.replace(':', '')
        csv_mode = n > XLSX_MAX
        if csv_mode and QMessageBox.question(
                self, TITLE, f'Строк {n_text(n)} — больше, чем помещается на лист Excel ({n_text(XLSX_MAX)}).\n\n'
                             'Сохранить файл CSV? Excel откроет его (все строки - в Excel только первые '
                             f'{n_text(XLSX_MAX)}; уточните фильтр, если нужно всё на одном листе).') != QMessageBox.Yes:
            return
        ext, flt = ('.csv', 'CSV (*.csv)') if csv_mode else ('.xlsx', 'Excel (*.xlsx)')
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить список', os.path.join(os.path.expanduser('~'), 'Documents',
                                                                                     base + ext), flt)
        if not path:
            return
        if not path.lower().endswith(ext):
            path += ext
        heads = [head(self.kind, c) for c in m.cols]
        snap = (m.rows, list(m.idx), list(m.cols), dict(m.letters))            # строки готовятся в фоне (510 тыс. - 2,7 с)
        self.state.setText(f'Сохраняю {files_word(len(snap[1]))}…')
        self.excel_btn.setEnabled(False)

        def done(res):
            if self.closed:
                return
            self.excel_btn.setEnabled(True)
            kind, val = res
            if kind == 'ok':
                self.state.setText(f'Сохранено: {val}')
            else:
                self.state.setText('Не сохранено: ' + (val if kind == 'refused' else _last_line(val)))
        self.win.bg.run(lambda: _safe(lambda: save_table(path, heads, export_values(*snap))), ok=done, quiet=True)

    def rescan(self):
        rows = self.selected_rows()
        if not rows:
            QMessageBox.information(self, TITLE, 'Выделите файлы: пересканируются их папки.')
            return
        disks = sorted({r[R_DISK] for r in rows})
        if len(disks) > 1:
            QMessageBox.information(self, TITLE, f'Выделены файлы разных дисков ({", ".join(disks)}). Пересканировать '
                                    'можно папки одного диска за раз - выделите файлы одного диска.')
            return
        disk = disks[0]
        root = sum(1 for r in rows if not r[R_FOLDER])
        folders = collapse(r[R_FOLDER] for r in rows if r[R_FOLDER])
        if not folders:
            QMessageBox.information(self, TITLE, f'Выделены только файлы в корне {disk}: их пересканирует только полная '
                                    'опись диска (программа «Сканер дисков»).')
            return
        try:                                              # число уже посчитано в фоне при выделении - не считать заново
            files = self.sel_files if folders == self.sel_folders and self.sel_files is not None else \
                sum(sv.folders_files(disk, folders).values())
        except Exception as e:                                    # noqa: BLE001
            files = None
            log_error(str(e))
        shown = '\n'.join(f'  {disk}\\{f}' for f in folders[:15]) + (f'\n  … и ещё {len(folders) - 15}' if len(folders) > 15 else '')
        q = (f'Пересканировать {len(folders)} папок {disk}' + (f' — {files_word(files)} по базе' if files is not None else '')
             + f'?\n\n{shown}\n\n' + (f'Файлы прямо в корне ({root}) не войдут: их пересканирует только полная опись.\n\n'
                                      if root else '') +
             'Дальше откроется окно пересканирования: там выберите типы файлов и посмотрите предпросмотр.')
        if QMessageBox.question(self, TITLE, q) != QMessageBox.Yes:
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and getattr(running, 'running', False):
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        import rescan_dialog
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.finished.connect(lambda *_: (not self.closed) and self.stale.show())
        self.win.rescan.show()


def open_in_explorer(parent, letter, folder, name):
    """Папка файла в Проводнике с выделенным файлом; файла нет - папка; папки нет - сообщение."""
    base = letter.rstrip(SEP) + SEP
    folder_path = base + folder if folder else base
    full = folder_path.rstrip(SEP) + SEP + name if folder else base + name
    if os.path.exists(full):
        subprocess.Popen(f'explorer /select,"{full}"')
        return 'file'
    if os.path.isdir(folder_path):
        os.startfile(folder_path)
        QMessageBox.information(parent, TITLE, f'Файла «{name}» в папке нет (его переместили или удалили?) - открыта '
                                               'папка. Пересканируйте её, чтобы база узнала.')
        return 'folder'
    QMessageBox.information(parent, TITLE, f'Папки «{folder_path}» на диске нет (её переименовали или переместили?). '
                                           'Пересканируйте носитель.')
    return None
