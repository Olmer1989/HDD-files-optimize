"""«Диски и папки»: «Досчитать хеш» фото и видео (18.11.2026, задача владельца) - кнопка в строке «⚠ Без хеша …» над
деревом и пункт правого щелчка по папке «Досчитать хеш в этой папке…» (часть-«примесь» класса DisksPage).

Открывает готовое окно пересканирования (rescan_dialog.RescanDialog) с галочками типов «Фото» и «Видео»: сканер берёт
сохранённые хеши и читает только файлы без хеша. Сканирование - только по подтверждению в том окне. Диск не подключён -
кнопка и пункт неактивны («Подключите диск»)."""
import rescan_dialog
from hb_core import api as hb
from ui_common import TITLE
from overview_page import n_ru

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu, QMessageBox

from .common import DISK_ROLE, T_NAME, T_NOHASH

MEDIA_CATS = [hb.CAT_PHOTO, hb.CAT_VIDEO]               # типы окна пересканирования - как у «Разбора» (flow_tasks)
OFF_TIP = 'Подключите диск'


class RehashFlow:
    """Часть DisksPage: «Досчитать хеш» фото и видео."""

    def update_rehash(self):
        """Кнопка «Досчитать хеш фото и видео (N)…»: видна, если у выбранного носителя есть фото и видео без хеша."""
        info = self.nohash.get(self.disk) if self.disk and not self.found else None
        n = (info or {}).get('media', 0)
        self.rehash_btn.setVisible(bool(n))
        if not n:
            return
        self.rehash_btn.setText(f'Досчитать хеш фото и видео ({n_ru(n)})…')
        on = bool(self.row_of(self.disk).get('letter'))
        self.rehash_btn.setEnabled(on and bool(info.get('media_folders')))
        if not on:
            self.rehash_btn.setToolTip(OFF_TIP)
        elif not info.get('media_folders'):
            self.rehash_btn.setToolTip('Все такие файлы лежат прямо в корне диска - их пересканирует только полная опись '
                                       '(«Сканер дисков»).')
        else:
            root = info.get('media_root') or 0
            self.rehash_btn.setToolTip(
                f'Окно пересканирования с папками, где есть фото и видео без хеша ({n_ru(len(info["media_folders"]))}), '
                'и типами «Фото» и «Видео». Сохранённые хеши берутся, читаются только файлы без хеша. Сначала - '
                'предпросмотр, затем подтверждение.' + (f' Файлы прямо в корне ({n_ru(root)}) не войдут.' if root else ''))

    def rehash_media(self):
        """Кнопка над деревом: все папки носителя с фото и видео без хеша."""
        info = self.nohash.get(self.disk) or {}
        if self.disk and info.get('media_folders'):
            self.open_rehash(self.disk, list(info['media_folders']))

    def rehash_menu(self, it):
        """Меню правого щелчка по папке: «Досчитать хеш в этой папке…». -> QMenu или None (не строка папки)."""
        disk = it.data(T_NAME, DISK_ROLE) if it is not None else None
        if not disk:
            return None
        path = it.data(T_NAME, Qt.UserRole) or ''
        menu = QMenu(self.tree)
        menu.setToolTipsVisible(True)
        act = menu.addAction('Досчитать хеш в этой папке…')
        act.triggered.connect(lambda _=False: self.rehash_folder(disk, path))
        n = it.data(T_NOHASH, Qt.UserRole)
        if not self.row_of(disk).get('letter'):
            act.setEnabled(False)
            act.setToolTip(OFF_TIP)
        elif n == 0:
            act.setEnabled(False)
            act.setToolTip('В папке нет файлов без хеша.')
        else:
            act.setToolTip('Окно пересканирования этой папки с типами «Фото» и «Видео»: читаются только файлы без хеша.')
        return menu

    def tree_menu(self, pos):
        menu = self.rehash_menu(self.tree.itemAt(pos))
        if menu is not None:
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rehash_folder(self, disk, path):
        """Пункт меню: эта папка; весь диск (строка «(весь диск)») - папки с фото и видео без хеша, как кнопка."""
        if path:
            self.open_rehash(disk, [path])
            return
        folders = (self.nohash.get(disk) or {}).get('media_folders')
        if folders:
            self.open_rehash(disk, list(folders))
        else:
            QMessageBox.information(self, TITLE, 'Весь диск целиком - это полное сканирование, его делает сканер '
                                    'дисков. Выберите папку.')

    def open_rehash(self, disk, folders):
        if not self.row_of(disk).get('letter'):
            QMessageBox.information(self, TITLE, f'{disk} не подключён. Подключите диск и нажмите «Обновить».')
            return
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders, cats=list(MEDIA_CATS))
        self.win.rescan.finished.connect(lambda *_: self.refresh())     # новая опись - числа «Без хеша» заново
        self.win.rescan.show()
