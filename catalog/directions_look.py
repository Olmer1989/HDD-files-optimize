"""Направления: константы, подписи, теги, FlowLayout, строка диска. Вынесено из directions_page.py без изменений кода."""
from hb_core import api as hb
import disk_ui

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLabel, QLayout

RAZBOR_PAGE = 'Разбор носителя'
KINDS = (hb.KIND_MEDIA, hb.KIND_ALL)
# галочки «Что копировать»: категория ядра -> подпись окна
CAT_LABELS = ((hb.CAT_PHOTO, 'Фото'), (hb.CAT_VIDEO, 'Видео'), (hb.CAT_DOC, 'Документы (Word, Excel, PDF, тексты)'),
              (hb.CAT_ARCH, 'Архивы'), (hb.CAT_PROJ, 'Проекты монтажа и графики'), (hb.CAT_MUSIC, 'Музыка'),
              (hb.CAT_OTHER, 'Другие'))
NEAR_TEXT = 'Документы — только рядом с фото и видео'
NEAR_TIP = ('«Рядом» — в той же папке или в её подпапках есть хотя бы одно фото или видео, которое идёт в это же '
            'направление (подпапки с другой отметкой и корень носителя не считаются).')
NEVER_TEXT = ('Программы, системные и временные файлы (exe, dll, msi, ini, tmp, Thumbs.db и т. п.) не копируются никогда. '
              '«Все файлы» — все, кроме них.')
GO_TEXT = 'Дальше: выбрать папки на носителе →'
HEADERS = ('Пишем команды', 'Направление', 'Что собирается на дисках', 'Диски', 'Свободно', 'Что копировать',
           'Папка на носителе после переноса')
ON, OFF = '#1b5e20', '#8a8a8a'


def gb(x):
    return f'{x:,.0f}'.replace(',', ' ')


def kind_text(kind):
    """«Что копировать» для таблицы: прежние значения и наборы категорий как записаны; нераспознанное - пометкой."""
    cats, near, ok = hb.parse_kind(kind)
    if not ok:
        return f'не распознано («{kind}») — ничего не копируется'
    if cats == hb.ALL_CATS and not near:
        return 'все файлы (кроме программ и временных)'
    return hb.kind_text(cats, near)


# ---------- секция в «Обзоре»: строки-карточки (четвёртый круг, 16.11.2026) ----------

CHECKED_BG, CARD_BG, CARD_BORDER = '#e8f5e9', '#ffffff', '#d0d7de'
TAG_BLUE = ('#e3f2fd', '#1565c0', '#90caf9')          # фон, текст, рамка тега категории
TAG_GRAY = ('#eeeeee', '#424242', '#bdbdbd')
TAG_RED = ('#ffebee', '#c62828', '#ef9a9a')
OFF_BADGE = ('#f3e5d8', '#a1662f', '#d7b899')         # плашка «не подключён» (серо-оранжевая)
# короткие подписи категорий для тегов (порядок - как в диалоге)
TAG_LABELS = ((hb.CAT_PHOTO, 'Фото'), (hb.CAT_VIDEO, 'Видео'), (hb.CAT_DOC, 'Документы'), (hb.CAT_ARCH, 'Архивы'),
              (hb.CAT_PROJ, 'Проекты монтажа и графики'), (hb.CAT_MUSIC, 'Музыка'), (hb.CAT_OTHER, 'Другие'))


def kind_tags(kind):
    """«Что копировать» тегами: -> ([(текст, 'blue'/'gray'/'red')], мелкая приписка)."""
    cats, near, ok = hb.parse_kind(kind)
    if not ok:
        return [(f'не распознано («{kind}») — ничего не копируется', 'red')], ''
    if cats == hb.ALL_CATS and not near:
        return [('Все файлы', 'gray')], 'кроме программ и временных'
    tags = []
    for cat, text in TAG_LABELS:
        if cat in cats:
            tags.append((NEAR_TEXT if cat == hb.CAT_DOC and near else text, 'blue'))
    return tags, ''


def badge_css(colors, bold=False):
    bg, fg, border = colors
    return (f'background:{bg}; color:{fg}; border:1px solid {border}; border-radius:9px; padding:1px 8px;'
            + (' font-weight:bold;' if bold else ''))


class FlowLayout(QLayout):
    """Раскладка «в строку с переносом» (теги): ничего не уходит за правый край."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.items, self.gap = [], spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):                                   # noqa: N802
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):                                       # noqa: N802
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):                                       # noqa: N802
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):                             # noqa: N802
        return Qt.Orientations(0)

    def hasHeightForWidth(self):                               # noqa: N802
        return True

    def heightForWidth(self, w):                               # noqa: N802
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):                               # noqa: N802
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):                                        # noqa: N802
        return self.minimumSize()

    def minimumSize(self):                                     # noqa: N802
        s = QSize()
        for it in self.items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        for it in self.items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + self.gap, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.gap
            line = max(line, hint.height())
        return y + line - rect.y()


def tag_label(text, look):
    lab = QLabel(text)
    lab.setObjectName('tag')
    lab.setProperty('look', look)
    lab.setStyleSheet(badge_css({'blue': TAG_BLUE, 'gray': TAG_GRAY}.get(look, TAG_RED)))
    return lab


def disk_row_html(disk, by, free, writing, copy_no=0):
    """Строка диска в карточке: «I: My Book — HDD55 · свободно 421 ГБ» (подключён) или «My Book — HDD55» и плашка
    «не подключён». Цвет: оранжевый - направление отмечено галочкой; зелёный - нет; неподключённый - бледнее.
    copy_no - номер копии у направления с несколькими дисками (этап 12): «… — HDD45 (копия 1) · свободно …»."""
    r = by.get(disk) or {'disk': disk, 'label': '', 'letter': ''}
    on = bool(r.get('letter'))
    color, bold = disk_ui.dir_disk_color(on, writing)
    label = disk_ui.disk_name(r)
    text = html_esc(' — '.join(x for x in (disk_ui.disk_place(r) if label else r.get('letter'), disk) if x)
                    + (f' (копия {copy_no})' if copy_no else ''))
    w = 'bold' if bold else 'normal'
    out = f'<span style="color:{color}; font-weight:{w}">{text}</span>'
    if on:
        out += f' <span style="color:#555">· свободно {gb(free[disk])} ГБ</span>' if disk in free else ''
    else:
        bg, fg, _ = OFF_BADGE
        out += f' &nbsp;<span style="background:{bg}; color:{fg}">&nbsp;не подключён&nbsp;</span>'
    return out


def html_esc(x):
    import html
    return html.escape(str(x))
