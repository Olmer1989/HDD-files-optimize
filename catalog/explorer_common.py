"""Общее для страницы «Я сделал в Проводнике»: заголовок, группы, подсказки, помощники."""
from PySide6.QtCore import QDate, QEvent, QObject, Qt



TITLE = 'Я сделал в Проводнике'
ROLE = Qt.UserRole
GROUPS = [
    ('move', 'Я переместил или переименовал внутри этого диска (хеш и подтверждение сохранятся)', True),
    ('gone', 'Исчезли с диска → записать «удалено»', True),
    ('copy', 'Появились, такие же файлы есть на другом диске → «скопировано оттуда» (копия «со слов», не подтверждена)', True),
    ('new', 'Появились, откуда - неизвестно: записать нельзя, пересканируйте папку', False),
]
RESCAN_HINT = ('Чтобы база узнала новые файлы и получила их хеши, пересканируйте эти папки: раздел «Диски и папки» → '
               '«Пересканировать папку». Пересканирование читает сами файлы и считает хеши - это отдельное действие.')


def today():
    return QDate.currentDate().toString('dd.MM.yyyy')


def num(n):
    return f'{n:,}'.replace(',', ' ')


class SpaceToggles(QObject):
    """Пробел отмечает или снимает галочки у ВСЕХ выделенных строк (выделение мышью, Shift, Ctrl)."""

    def __init__(self, view, toggle):
        super().__init__(view)
        self.toggle = toggle
        view.installEventFilter(self)

    def eventFilter(self, obj, ev):                              # noqa: N802
        if ev.type() == QEvent.KeyPress and ev.key() == Qt.Key_Space:
            self.toggle()
            return True
        return False


def checkable(item, on=True):
    if on:
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
    else:
        item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
