"""RazborPage, спорные файлы по всему носителю: окно «Пересчитать хеши спорных файлов» (ссылка «Спорные по всему
носителю…» внизу страницы).

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md). 17.11.2026:
число спорных на кнопке больше не считается (весь носитель - миллионы служебных файлов при каждом выделении); «без
хеша» того, что пойдёт на диск, - в ячейке «Копировать на диск …» (flow_nohash)."""
from PySide6.QtWidgets import QMessageBox

from .common import TITLE
from .dialogs import ContestedDialog


class ContestedFlow:
    """Часть RazborPage (спорные файлы); атрибуты - у RazborPage."""

    def contested(self):
        if self.model is None:
            return
        fs = self.selected_folders()
        if len(fs) > 1:
            QMessageBox.information(self, TITLE, 'Выберите одну папку (или ни одной - тогда весь носитель).')
            return
        self._contested = ContestedDialog(self.win, self.disk, fs[0] if fs else '')
        self._contested.show()
