"""RazborPage, окно «Список файлов» (этап 16): какой список открыть по ссылке ячейки.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""


class ListView:
    """Часть RazborPage (окно «Список файлов» (этап 16)); атрибуты - у RazborPage."""

    def scope_folder(self):
        """Папка для списков «спорные» и «уникальные»: одна выделенная или весь носитель ('')."""
        fs = self.selected_folders()
        return fs[0] if len(fs) == 1 else ''

    def show_list(self, href):
        """«Показать список» ячейки (copy:<диск> / have / type) и кнопки «спорные» / «уникальные»."""
        import filelist_window
        m = self.model
        if m is None or not self.disk:
            return None
        kind, _, target = str(href).partition(':')
        if kind in ('copy', 'have', 'type'):
            if not self.dest:
                return None
            return filelist_window.open_list(self.win, kind=kind, disk=self.disk, num=self.dest, target=target or None,
                                             drafts=m.draft_rows(), page=self)
        return filelist_window.open_list(self.win, kind=kind, disk=self.disk, folder=self.scope_folder())
