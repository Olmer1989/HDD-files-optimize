"""«Диски и папки»: выбор папок - галочки и выделение, строка «Выбрано папок: …», состояние диска и доступность кнопок,
«Когда измерены хеши» (часть-«примесь» класса DisksPage).

Шаг А разбивки (17.11.2026): перенесено из disks_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import service as sv
from overview_page import gb_ru, n_ru

from PySide6.QtCore import Qt

from .common import DISK_ROLE, SIZE_ROLE, T_CHECK, T_NAME


class SelectView:
    """Часть DisksPage: выбор папок и панель «Выбрано папок»."""

    def targets(self):
        """Папки для действий: с галочкой; галочек нет - выделенные строки. -> [(диск, путь, файлов, ГиБ)]."""
        items = [it for it in self.all_items() if it.data(T_NAME, Qt.UserRole) and
                 it.checkState(T_CHECK) == Qt.Checked]
        if not items:
            items = [it for it in self.tree.selectedItems() if it.data(T_NAME, Qt.UserRole)]
        out = []
        for it in items:
            files, g = it.data(T_NAME, SIZE_ROLE) or (0, 0.0)
            out.append((it.data(T_NAME, DISK_ROLE), it.data(T_NAME, Qt.UserRole), files, g))
        return out

    def item_changed(self, it, col):
        if col == T_CHECK:
            self.update_actions()

    def update_actions(self):
        t = self.targets()
        files, g = sum(x[2] for x in t), sum(x[3] for x in t)
        self.sel_lab.setText(f'Выбрано папок: {len(t)} · файлов {n_ru(files)} · {gb_ru(g)} ГБ' if t else
                             'Выбрано папок: 0 — отметьте папки галочками (или выделите строку)')
        disks = sorted({x[0] for x in t}) or ([self.disk] if self.disk else [])
        off = [d for d in disks if not self.row_of(d).get('letter')]
        if not disks:
            self.state.setText('')
        elif off:
            self.state.setText(f'<span style="color:#e65100">Подключите {", ".join(off)}, чтобы открыть папки в '
                               'Проводнике и пересканировать.</span> Смотреть папки и «чего нет» можно и без него.')
        else:
            self.state.setText(f'<span style="color:#2e7d32">Диск подключён ({", ".join(self.row_of(d)["letter"] for d in disks)}) '
                               '— можно открыть и пересканировать.</span>')
        self.open_btn.setEnabled(bool(t) and not off)
        self.rescan_btn.setEnabled(bool(t) and not off and len(disks) == 1)
        self.missing_btn.setEnabled(bool(t))
        self.update_rehash()                              # «Досчитать хеш фото и видео» - по подключению носителя

    def selected(self):
        """Выбрана одна папка: «когда измерены хеши» - в фоне; ответ для уже сменившейся папки не показывается."""
        self.update_actions()
        items = [it for it in self.tree.selectedItems() if it.data(T_NAME, DISK_ROLE)]
        if len(items) != 1:
            self.dates.setText('')
            return
        disk, path = items[0].data(T_NAME, DISK_ROLE), items[0].data(T_NAME, Qt.UserRole) or ''
        self.dates.setText('Когда измерены хеши: считаю…')

        def show(r):
            cur = self.tree.selectedItems()
            if len(cur) != 1 or cur[0].data(T_NAME, DISK_ROLE) != disk or (cur[0].data(T_NAME, Qt.UserRole) or '') != path:
                return
            self.dates.setText(r['text'] + ' ' + r['hint'])
        self.win.bg.run(sv.hash_dates, disk, path, ok=show, quiet=True)
