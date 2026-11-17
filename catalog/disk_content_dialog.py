"""Окно «Содержимое выбранного диска — H: Бэкап фото и видео — HDD45» (решение владельца 18.11.2026): таблица «что на
диске лежит по базе», перенесённая с конца «Обзора». Открывается кнопкой «Подробнее о содержимом диска…» в карточке
направления; показывает только диски этой карточки. Окно немодальное, данные грузятся в фоне."""
import service as sv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from disk_table import DiskTable, disk_rows, todo_html

TITLE_HEAD = 'Содержимое выбранного диска'
LOADING = 'Считаю…'
EMPTY = '<span style="color:#8a8a8a">По этому диску в базе ничего нет.</span>'
DISKS_PAGE = 'Диски и папки'


def window_title(line):
    """«Содержимое выбранного диска — H: Бэкап фото и видео — HDD45»."""
    return f'{TITLE_HEAD} — {line}'


def checked_text(when):
    return f'Числа — по базе; подключён ли диск и свободное место — проверено в {when}.'


class DiskContentDialog(QDialog):
    """Таблица дисков одной карточки: столбцы и подсказки - как были на «Обзоре», под ней строки «что сделать»,
    пояснение «Числа — по базе…», внизу «Пересканировать» (экран «Диски и папки» к этому диску) и «Закрыть».
    Закрыли до конца загрузки - пришедший ответ молча пропускается."""

    def __init__(self, win, disks, line, parent=None):
        super().__init__(parent)
        self.win, self.disks, self.rows, self.gone = win, list(disks), [], False
        self.setWindowTitle(window_title(line))
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(1000, 420)
        lay = QVBoxLayout(self)
        self.wait = QLabel(LOADING)
        self.wait.setStyleSheet('color:#555')
        lay.addWidget(self.wait)
        self.dt = DiskTable(self.rescan)
        self.dt.setVisible(False)
        self.dt_empty = QLabel(EMPTY)
        self.dt_empty.setVisible(False)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(self.dt)
        wl.addWidget(self.dt_empty)
        wl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(wrap)
        lay.addWidget(scroll, 1)
        self.todo = QLabel('')
        self.todo.setWordWrap(True)
        self.todo.setTextFormat(Qt.RichText)
        self.todo.setStyleSheet('color:#333')
        self.todo.setVisible(False)
        self.todo.linkActivated.connect(self.link_text)
        lay.addWidget(self.todo)
        self.checked = QLabel('')
        self.checked.setStyleSheet('color:gray')
        lay.addWidget(self.checked)
        bar = QHBoxLayout()
        bar.addStretch(1)
        self.b_close = QPushButton('Закрыть')
        self.b_close.clicked.connect(self.close)
        bar.addWidget(self.b_close)
        lay.addLayout(bar)
        self.finished.connect(self._gone)

    def load(self):
        """Числа - тем же запросом, что раньше брала таблица «Обзора» (service.overview), только по своим дискам."""
        self.win.bg.run(sv.overview, self.disks, ok=self.render)

    def _gone(self, *_):
        """Закрыто: ответ фона, если придёт, пропускается; само окно Qt удалит позже (не копятся скрытые окна)."""
        self.gone = True
        self.deleteLater()

    def closeEvent(self, e):                                     # noqa: N802
        self.gone = True
        super().closeEvent(e)

    def render(self, ov):
        if self.gone:
            return
        try:
            info = ov['disks_info']
            self.rows = disk_rows([d for d in self.disks if d in info], info)
            self.wait.setVisible(False)
            self.dt.set_rows(self.rows)
            self.dt.setVisible(bool(self.rows))
            self.dt_empty.setVisible(not self.rows)
            t = todo_html(self.rows)
            self.todo.setText(t)
            self.todo.setVisible(bool(t))
            self.checked.setText(checked_text(ov.get('checked', '')))
        except RuntimeError:                                     # окно уже уничтожено Qt
            return

    def rescan(self, disk):
        """«Пересканировать» / «Перейти»: экран «Диски и папки» с этим диском; окно закрывается."""
        self.win.open_page(DISKS_PAGE)
        page = self.win.page(DISKS_PAGE) if hasattr(self.win, 'page') else None
        if page is not None:
            page.show_disk(disk)
        self.close()

    def link_text(self, s):
        if s.startswith('rescan:'):
            self.rescan(s[7:])
