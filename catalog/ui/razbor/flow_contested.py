"""RazborPage, спорные файлы: число спорных в фоне и окно «Пересчитать хеши спорных файлов».

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtWidgets import QMessageBox

import service as sv

from .common import TITLE, last, safe
from .dialogs import ContestedDialog
from .texts_cell import num


class ContestedFlow:
    """Часть RazborPage (спорные файлы); атрибуты - у RazborPage."""

    def run_contested_count(self):
        """Число на кнопке «Пересчитать хеши спорных файлов (N)» - для выделенной папки или всего носителя, в фоне;
        пока считается и при 0 - кнопка неактивна; ответ для сменившегося выбора не показывается."""
        if self.model is None or not self.disk:
            return
        self.cont_req += 1
        req, disk, folder = self.cont_req, self.disk, self.scope_folder()
        self.cont_n = None
        self.contested_btn.setText('Пересчитать хеши спорных файлов (считаю…)')
        self.update_buttons()

        def show(res):
            if req != self.cont_req:
                return
            kind, val = res
            if kind != 'ok':
                # число не получено: без ложного числа; кнопки активны - окно и список ищут спорные сами
                self.contested_btn.setText('Пересчитать хеши спорных файлов (число не посчитано)…')
                self.contested_btn.setToolTip('Посчитать спорные файлы не удалось: '
                                              + (val if kind == 'refused' else val.strip().splitlines()[-1])
                                              + '. Нажмите «Обновить» или откройте окно - оно ищет само.')
                self.cont_n = -1                          # «неизвестно» (не 0 и не число)
            else:
                self.cont_n = val['total']
                where = f'«{last(folder)}»' if folder else 'носителя'
                self.contested_btn.setText(f'Пересчитать хеши спорных файлов ({num(val["total"])})…')
                self.contested_btn.setToolTip(f'Спорных у {where}: {num(val["total"])} — на этом носителе '
                                              f'{num(val["carrier"])}, на 45 и 77 {num(val["copies"])}. Окно покажет '
                                              'папки и подключённые диски, их можно пересканировать с хешем.')
            self.update_buttons()
        self.win.bg.run(safe, sv.contested_count, disk, folder, ok=show, quiet=True)

    def contested(self):
        if self.model is None:
            return
        fs = self.selected_folders()
        if len(fs) > 1:
            QMessageBox.information(self, TITLE, 'Выберите одну папку (или ни одной - тогда весь носитель).')
            return
        self._contested = ContestedDialog(self.win, self.disk, fs[0] if fs else '')
        self._contested.show()
