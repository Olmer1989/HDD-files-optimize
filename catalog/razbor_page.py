"""Страница окна «Разбор носителя» (логика v3, этап 2, 15.11.2026).

Документ - «Проверка Архитектуры сортировки файлов\\Логика_v3_разбор_носителя.md» (разделы 1.2-1.6, 2.2, «Этап 2: экран»).
Владелец выбирает носитель и режим («всё - в направление, кроме отмеченных» или «ничего, кроме отмеченных»), ставит
папкам «Куда» (направление, «не копировать», «как у родителя») и сразу видит итог: что будет с каждым файлом (сумма =
опись) и сколько писать на каждый диск. «Сохранить отметки» - предпросмотр, затем запись одним пакетом через
service.add_marks_batch. «Подготовить задания» - расчёт, показ, создание через service.razbor_tasks, переход в «Задания».

Как устроено:
- Дерево строится по таблице folders (service.razbor_tree - один запрос, ≤ 60 тыс. папок); элементы дерева создаются
  только при раскрытии узла. «Куда» считается в окне по всем папкам одним проходом (Model.routes - те же правила, что в
  ядре: hb_core.razbor.planner, разбор отметок - общий hb_core.directions.MarkSet), после правки обновляются тексты
  уже созданных строк. Своя отметка - чёрным, унаследованная - серым «… — от «папка»», несохранённое - синим с «•».
- Черновик - несохранённые отметки окна: словарь «исходный путь без регистра → отметка». Итог считается с черновиком
  (service.razbor(disk, drafts)), задания - только из сохранённых отметок.
- Итог и «Уже есть» (service.razbor_have) - в фоне, не больше одного расчёта каждого вида; ответ принимается, только если
  с его запуска ничего не менялось (ревизия), иначе считается заново по последнему состоянию.
- Запись: в предпросмотр и запись уходит неизменяемая копия пакета; страница на это время недоступна. После любого
  исхода сохранённые отметки перечитываются, из черновика уходит только то, что совпало с сохранённым.
Подключение в окно: ('Разбор носителя', RazborPage(self)).

Этап 6 (15-16.11.2026, замечания владельца, документ - раздел «Этап 6»): вверху крупно «Куда» (направления, отмеченные
в «Обзоре»); колонки «Куда» в дереве нет - папка подкрашена цветом своего направления (своя отметка - ярко, унаследованная
- бледно, «не копировать» - серым и зачёркнуто), подсказка «Н2 Работа (78) (своя отметка)» / «(от папки …)»; справа -
крупные ячейки направлений и «Не копировать»: папки перетаскиваются в них мышью (та же черновая отметка, что у меню),
ячейка «Снять свою отметку» возвращает папке отметку родителя; полный итог - вкладка «Подробно». В ячейке - вместимость
по каждому диску (service.capacity: только недостающее на этом диске, кластер, запас max(2 ГиБ, 1 %), очередь других
носителей); не помещается - ячейка красная, её кнопка «Подготовить задания» неактивна. Перед созданием заданий - быстрая
сверка оглавления подключённого носителя с описью (service.toc_check); расхождение или носитель не подключён - задания
не создаются, предлагается «Пересканировать эти папки…».

Этап 8 (16.11.2026, макет владельца, документ - раздел «Этап 8»): вверху - выбранный диск назначения («Диск «Фильмы» —
I: My Book (WD 2 ТБ)»); «Выберите носитель»; «Диск назначения» (направление с диском, имя оранжевым) и три режима:
«Только выбранные папки» (корень ≠ D), «Все папки» и «Все, кроме выбранных» (корень = D). Колонка галочек слева -
вид отметок для D (Model.check): включить - Model.include_pairs, исключить - Model.exclude_pairs; несколько выделенных -
одним шагом отмены. Папка другого направления - пустая галочка и серая метка «Н2». Справа две ячейки: «Копировать на
диск …» (единственная цель перетаскивания, бросок = включить в D) и «Остаётся на носителе» (только сведения). Ядро и путь
записи отметок не менялись.

Этап 10 (16.11.2026, решения владельца, раздел «Этап 10»): заголовок «Диск: <буква> <метка>» + плашка «не подключён»;
верх - форма (подписи слева, сведения под полями); режимы - три кнопки, режим выбран всегда; Shift/Ctrl-выделение сразу
ставит галочки (DragTree.multi -> check_selected); «выбрать все» у строки носителя; в «Все, кроме» - красный; надпись
«Идёт пересчёт…» внизу слева; ячейки «Остаётся на носителе» нет. Модель и объём диска не показываются (disk_ui.disk_name).

Этап 12 (16.11.2026, раздел «Этап 12»): шаги - в самом верху; под заголовком ячейки - имя направления оранжевым жирным;
галочка любой выделенной папки (при нескольких выделенных) - у всей группы одним шагом отмены (выделение берётся на
нажатии мыши, DragTree.press_sel). Направление на нескольких дисках (45 и 77, вариант А владельца: отметка одна) - на
экране раздельно: заголовок «Диск: Семейный архив — две копии» и строка на каждый диск, короткий пункт «Диска
назначения», в ячейке - блок с рамкой на каждый диск (Cell.set_blocks, disk_block_html: часть Б ядра для этого диска и
«уже есть» на нём - Model.have_on_disk). Ядро, отметки и задания не менялись.
"""
import collections
import html
import json
import time
import traceback

from PySide6.QtCore import QEvent, QMimeData, QObject, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPalette, QTextDocument
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSplitter,
                               QStyle, QStyledItemDelegate, QStyleOptionComboBox, QStylePainter, QTabWidget,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from hb_core import api as hb
from hb_core import razbor as rz
from hb_core.consts import CAT_OF_TYPE, N_TYPES
from hb_core.directions import R_DIR, R_NONE, R_SKIP, R_UNSET
import directions_page
import disk_ui
from ui_common import StepsBar
import service as sv

TITLE = 'Архив дисков'
SEP = '\\'
ROLE = Qt.UserRole
FILLED = Qt.UserRole + 1                                  # дети узла созданы (дерево ленивое)
TAG_ROLE = Qt.UserRole + 2                                # «Н2» - папка отмечена для другого направления
GRAY_ROLE = Qt.UserRole + 3                               # серая (неактивная) галочка
C_CHECK, C_NAME, C_FILES, C_GB, C_PHOTO, C_VIDEO, C_OTHER, C_HAVE = range(8)
HEAD = ['', 'Папка', 'Файлов', 'ГБ', 'Фото', 'Видео', 'Прочее', 'Уже есть']
ONLY, EVERY, EXCEPT = 'only', 'all', 'except'             # режимы для диска назначения
MODE_TEXT = {ONLY: 'Только выбранные папки', EVERY: 'Все папки', EXCEPT: 'Все, кроме выбранных'}
SEL_BG, PALE = '#c8e6c9', '#9e9e9e'                        # один зелёный фон для выбранных; бледный текст унаследованных
HEAD_BG = '#e8f5e9'
JOURNAL = 'по журналу сканирования дисков'
GRAY, BLUE, BLUE2, ORANGE, RED, GREEN = '#757575', '#1565c0', '#5c6bc0', '#e65100', '#c62828', '#2e7d32'
INHERIT, SKIP = hb.MARK_INHERIT, hb.MARK_SKIP
DEBOUNCE_MS = 600
UNDO_MAX = 50
MIME = 'application/x-arhiv-diskov-folders'               # перетаскивание папок из дерева в ячейки
# Цвет направления - по номеру (Н1 синий, Н2 зелёный, Н3 фиолетовый, …): (своя отметка, унаследованная, рамка ячейки)
PALETTE = [('#90caf9', '#e3f2fd', '#1e88e5'), ('#a5d6a7', '#e8f5e9', '#43a047'), ('#ce93d8', '#f3e5f5', '#8e24aa'),
           ('#80cbc4', '#e0f2f1', '#00897b'), ('#bcaaa4', '#efebe9', '#6d4c41'), ('#f48fb1', '#fce4ec', '#d81b60'),
           ('#e6ee9c', '#f9fbe7', '#9e9d24'), ('#b39ddb', '#ede7f6', '#5e35b1')]
SKIP_OWN, SKIP_INH, UNSET_BG = '#bdbdbd', '#eeeeee', '#ffe0b2'
SHORT_BG, UNKNOWN_BG = '#ffebee', '#fffde7'
# блок диска в ячейке «Копировать на…» (этап 12): (рамка, фон) по состоянию места на этом диске
BLOCK_LOOK = {'short': ('#c62828', '#ffebee'), 'unknown': ('#ffb74d', '#fffde7'), 'ok': ('#43a047', '#f1f8e9'),
              'none': ('#b0bec5', '#fafafa')}
COUNT_WORDS = {2: 'два задания', 3: 'три задания', 4: 'четыре задания'}
DISKS_WORDS = {2: 'два диска', 3: 'три диска', 4: 'четыре диска'}
EXC_BG, EXC_FG = '#ffcdd2', '#b71c1c'                      # «Все, кроме выбранных»: выбранные (не копируются) - красным
MODE_CSS = ('QPushButton { border:1px solid #b0bec5; border-radius:5px; background:#f5f7fa; padding:4px 10px; } '
            'QPushButton:checked { background:#c8e6c9; border:2px solid #43a047; font-weight:bold; color:#1b5e20; } '
            'QPushButton:disabled { color:#9e9e9e; }')
BUSY_CSS = ('QLabel { color:#e65100; font-weight:bold; background:#fff3e0; border:2px solid #ffb74d; border-radius:5px; '
            'padding:5px 12px; }',
            'QLabel { color:#ffffff; font-weight:bold; background:#fb8c00; border:2px solid #ef6c00; border-radius:5px; '
            'padding:5px 12px; }')


def dir_colors(num):
    return PALETTE[(hb.num_key(num) - 1) % len(PALETTE)] if num else PALETTE[0]


def num(n):
    return f'{n or 0:,}'.replace(',', ' ')


def gb(b):
    return f'{(b or 0) / hb.GIB:,.1f}'.replace(',', ' ').replace('.', ',')


def esc(x):
    return html.escape(str(x))


def last(path):
    return path.rsplit(SEP, 1)[-1] if path else ''


def safe(fn, *a):
    """Для фона: всегда ответ («ok», результат) / («refused», причина) / («error», подробности) - окно само решает,
    что показать, и черновик не теряется ни при каком исходе."""
    try:
        return 'ok', fn(*a)
    except sv.Refused as e:
        return 'refused', str(e)
    except Exception:                                      # noqa: BLE001
        return 'error', traceback.format_exc()


def plural(n, one, few, many):
    n = abs(n or 0)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def folders_word(n):
    return f'{num(n)} {plural(n, "папка", "папки", "папок")}'


def files_word(n):
    return f'{num(n)} {plural(n, "файл", "файла", "файлов")}'


# ---------- тексты носителей и дисков назначения (этап 8) ----------

def place(row, disk=''):
    """«F: Монтаж - SN850»; неподключённый - «Монтаж - SN850 (не подключён)»; метки тома нет - номер носителя.
    Модель и объём (устройство подключения) не показываются нигде (решение владельца 16.11.2026, disk_ui.disk_name)."""
    r = disk_ui.as_row(row) if row else {'disk': disk, 'label': '', 'letter': ''}
    name = disk_ui.disk_name(r) or r.get('disk') or disk
    return f'{r["letter"]} {name}' if r.get('letter') else f'{name} (не подключён)'


def carrier_text(row):
    """Строка списка «Выберите носитель»: «F: Монтаж - SN850 — HDD09 (по журналу сканирования дисков)»."""
    r = disk_ui.as_row(row)
    if not disk_ui.disk_name(r):                          # метки нет - номер один раз
        return f'{r["letter"] + " " if r.get("letter") else ""}{r["disk"]}' +             ('' if r.get('letter') else ' (не подключён)') + f' ({JOURNAL})'
    return f'{place(r)} — {r["disk"]} ({JOURNAL})'


def hdds(d):
    return ' и '.join(d.disks)


def dest_places(d, rows):
    by = {r['disk']: r for r in rows}
    return ' и '.join(place(by.get(x), x) for x in d.disks)


COPIES_WORDS = {2: 'две копии', 3: 'три копии', 4: 'четыре копии'}


def copies_word(n):
    return COPIES_WORDS.get(n, f'{n} копий')


def letters(d, rows):
    """«H: и S:» - буквы дисков направления; неподключённый - номером («H: и HDD77»)."""
    by = {r['disk']: r for r in rows}
    return ' и '.join((by.get(x) or {}).get('letter') or x for x in d.disks)


def dest_text(d, rows):
    """Строка списка «Диск назначения»: «I: My Book — Н3 Фильмы — HDD55 (по журналу сканирования дисков)»; у
    направления с несколькими дисками - коротко «Н1 Семейный архив — H: и S: (две копии)» (этап 12)."""
    if len(d.disks) > 1:
        return f'{d.num} {d.name} — {letters(d, rows)} ({copies_word(len(d.disks))})'
    return f'{dest_places(d, rows)} — {d.num} {d.name} — {hdds(d)} ({JOURNAL})'


def dest_html(d, rows):
    """То же с именем направления оранжевым (как отмеченные в «Обзоре»)."""
    name = f'<span style="color:{ORANGE}"><b>{esc(d.num)} {esc(d.name)}</b></span>'
    if len(d.disks) > 1:
        return f'{name} — {esc(letters(d, rows))} <span style="color:{GRAY}">({copies_word(len(d.disks))})</span>'
    return (f'{esc(dest_places(d, rows))} — {name} — '
            f'{esc(hdds(d))} <span style="color:{GRAY}">({JOURNAL})</span>')


OFF_PILL = (f'<span style="background:#ffe0b2; color:{ORANGE}; font-size:11pt">&nbsp;не подключён&nbsp;</span>')


def free_of(x, rows, space=None):
    """Свободно на диске назначения, байт: по последнему расчёту места (space) или по service.disks (free_gib)."""
    if space and x in space:
        return space[x][1]
    r = next((r for r in rows if r['disk'] == x), None)
    return r['free_gib'] * hb.GIB if r and 'free_gib' in r else None


def head_html(d, rows, space=None):
    """Заголовок экрана (макет владельца): «Диск: I: My Book» (+ оранжевая плашка «не подключён») и второй строкой
    «Н3 Фильмы (оранжевым) · HDD55 по журналу сканирования дисков · свободно 421 ГБ» (у двух дисков - оба,
    «два задания»). Модель и объём не показываются."""
    if d is None:
        return (f'<span style="color:{ORANGE}">Диска назначения нет: ни у одного направления не назначен диск.</span> '
                '<span style="font-size:10pt; font-weight:normal">Назначьте диск в «Обзоре» → «Направления».</span>')
    by = {r['disk']: r for r in rows}
    if len(d.disks) > 1:
        # этап 12 (вариант А владельца): диски не сливаются в одну строку - заголовок «Диск: Семейный архив — две
        # копии», под ним направление и по строке на каждый диск
        lines = []
        for x in d.disks:
            r = by.get(x) or {'disk': x, 'label': '', 'letter': ''}
            line = f'{esc(disk_ui.disk_place(r))} — {esc(x)}'
            b = free_of(x, rows, space)
            if b is not None:
                line += f' <span style="color:#33691e">· свободно {gb(b)} ГБ</span>'
            if not r.get('letter'):
                line += ' ' + OFF_PILL.replace('11pt', '9pt')
            lines.append(line)
        sub = (f'<span style="color:{ORANGE}"><b>{esc(d.num)} {esc(d.name)}</b></span> · '
               f'{COUNT_WORDS.get(len(d.disks), f"{len(d.disks)} заданий")} — по одному на каждый диск '
               f'<span style="color:{GRAY}">(номера HDD {JOURNAL})</span>')
        return (f'Диск: {esc(d.name)} — {copies_word(len(d.disks))}<br>'
                f'<span style="font-size:10pt; font-weight:normal; color:#33691e">{sub}</span><br>'
                '<span style="font-size:11pt; font-weight:normal; color:#1b5e20">' + '<br>'.join(lines) + '</span>')
    parts = []
    for x in d.disks:
        r = by.get(x) or {'disk': x, 'label': '', 'letter': ''}
        name = disk_ui.disk_name(r) or x
        parts.append(esc(f'{r["letter"]} {name}' if r.get('letter') else name) + ('' if r.get('letter') else ' ' + OFF_PILL))
    word = 'Диски' if len(d.disks) > 1 else 'Диск'
    free = []
    for x in d.disks:
        b = free_of(x, rows, space)
        if b is not None:
            free.append(f'{x} — {gb(b)} ГБ' if len(d.disks) > 1 else f'{gb(b)} ГБ')
    sub = f'<span style="color:{ORANGE}"><b>{esc(d.num)} {esc(d.name)}</b></span> · {esc(hdds(d))} {JOURNAL}'
    if free:
        sub += ' · свободно ' + esc(', '.join(free))
    if len(d.disks) > 1:
        sub += ' · ' + COUNT_WORDS.get(len(d.disks), f'{len(d.disks)} заданий')
    return (f'{word}: ' + ' и '.join(parts) + '<br>'
            f'<span style="font-size:10pt; font-weight:normal; color:#33691e">{sub}</span>')


MODE_NOTE = {ONLY: 'Копируются только папки с галочкой — остальные остаются на носителе.',
             EVERY: 'Весь носитель копируется на этот диск. Папки, отмеченные для другого диска (метка «Н2»), остаются '
                    'за ним.',
             EXCEPT: 'Весь носитель копируется на этот диск, кроме папок с галочкой — они подсвечены красным и не '
                     'копируются.'}
NO_SPACE = 'Подключите диск, чтобы проверить свободное место. Отмечать папки можно и без него.'


def dest_info_html(d, rows, space=None):
    """Строка под «Диском назначения»: «Свободно 421 ГБ» или «Подключите диск, чтобы проверить свободное место…»."""
    if d is None:
        return ''
    if len(d.disks) > 1:                                  # этап 12: по строке на каждый диск
        by = {r['disk']: r for r in rows}
        out = []
        for i, x in enumerate(d.disks, 1):
            b = free_of(x, rows, space)
            head = f'Копия {i} — {esc(disk_ui.disk_place(by.get(x) or x))} ({esc(x)}): '
            if b is None:
                out.append(f'<span style="color:{ORANGE}">{head}подключите диск, чтобы проверить свободное место.</span>')
            else:
                out.append(f'<span style="color:{GREEN}">{head}свободно {gb(b)} ГБ</span>')
        if any(free_of(x, rows, space) is None for x in d.disks):
            out.append('Отмечать папки можно и без них.')
        return '<br>'.join(out)
    free, off = [], []
    for x in d.disks:
        b = free_of(x, rows, space)
        if b is None:
            off.append(x)
        else:
            free.append(f'{x} — {gb(b)} ГБ' if len(d.disks) > 1 else f'{gb(b)} ГБ')
    out = []
    if free:
        out.append(f'<span style="color:{GREEN}">Свободно {esc(", ".join(free))}</span>')
    if off:
        out.append(f'<span style="color:{ORANGE}">' + (f'{esc(", ".join(off))}: ' if len(d.disks) > 1 else '')
                   + NO_SPACE + '</span>')
    return ' · '.join(out)


def legend_html(mode):
    """Подпись цветов под деревом - по режиму: в «Все, кроме выбранных» зелёного нет, выбранные - красным."""
    if mode == EXCEPT:
        first = (f'<span style="background:{EXC_BG}; color:{EXC_FG}">&nbsp;красный фон&nbsp;</span> — папка с '
                 'галочкой НЕ копируется; ')
    else:
        first = f'<span style="background:{SEL_BG}">&nbsp;зелёный фон&nbsp;</span> — папка выбрана; '
    return (first + f'<span style="color:{PALE}">бледный текст и серая галочка</span> — вместе с родительской папкой; '
            f'<span style="color:{GRAY}">Н2</span> — папка отмечена для другого диска; '
            f'<i style="color:{BLUE}">• курсив</i> — не сохранено.'
            + (' Галочка у строки носителя — выбрать все папки.' if mode == ONLY else ''))


class HtmlDelegate(QStyledItemDelegate):
    """Пункт выпадающего списка «Диск назначения» с HTML (имя направления оранжевым)."""

    def paint(self, painter, option, index):
        html_ = index.data(Qt.UserRole + 5)
        if not html_:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        option.text = ''
        st = option.widget.style() if option.widget else None
        if st:
            st.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(option.font)
        doc.setHtml(html_)
        painter.save()
        painter.translate(option.rect.left() + 6, option.rect.top() + (option.rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter, QRectF(0, 0, option.rect.width() - 8, option.rect.height()))
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        return QSize(s.width(), max(s.height(), QFontMetrics(option.font).height() + 14))   # строки списка - выше


class RichCombo(QComboBox):
    """Выпадающий список, у которого и пункты, и закрытое поле рисуются HTML (Qt.UserRole + 5); текст пункта - простой
    (для поиска и тестов)."""

    def __init__(self):
        super().__init__()
        self.setItemDelegate(HtmlDelegate(self))
        self.setMinimumHeight(QFontMetrics(self.font()).height() + 16)    # поле выше: низ текста не обрезается
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)      # во всю ширину столбца полей

    def add(self, text, html_, data):
        self.addItem(text, data)
        self.setItemData(self.count() - 1, html_, Qt.UserRole + 5)
        need = max(self.html_width(self.itemData(i, Qt.UserRole + 5)) for i in range(self.count())) + 40
        self.view().setMinimumWidth(need)            # выпадающий список - во всю ширину самого длинного пункта
        self.setMinimumWidth(min(need + 30, 520))    # закрытое поле растягивается; «…» только если окно очень узкое

    def html_width(self, html_):
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.font())
        doc.setHtml(html_ or '')
        return int(doc.idealWidth()) + 8

    def current_html(self):
        return self.itemData(self.currentIndex(), Qt.UserRole + 5) if self.currentIndex() >= 0 else ''

    def paintEvent(self, e):                                  # noqa: N802
        html_ = self.current_html()
        if not html_:
            return super().paintEvent(e)
        p = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        opt.currentText = ''
        p.drawComplexControl(QStyle.CC_ComboBox, opt)
        r = self.style().subControlRect(QStyle.CC_ComboBox, opt, QStyle.SC_ComboBoxEditField, self)
        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.font())
        doc.setHtml(html_ if self.isEnabled() else f'<span style="color:{GRAY}">{esc(self.currentText())}</span>')
        if doc.idealWidth() > r.width() - 4:          # не влезает - одной строкой с «…» (весь текст - в подсказке)
            text = QFontMetrics(self.font()).elidedText(self.currentText(), Qt.ElideRight, r.width() - 6)
            doc.setHtml(f'<span style="color:{"#000" if self.isEnabled() else GRAY}">{esc(text)}</span>')
        self.setToolTip(self.currentText())
        p.save()
        p.setClipRect(r)
        p.translate(r.left() + 4, r.top() + (r.height() - doc.size().height()) / 2)
        doc.drawContents(p, QRectF(0, 0, r.width(), r.height()))
        p.restore()


class TreeDelegate(QStyledItemDelegate):
    """Колонка галочек: серая (неактивная) галочка - у папок, выбранных вместе с родителем. Колонка имени: мелкая серая
    метка «Н2» справа от имени - папка отмечена для другого направления."""

    def initStyleOption(self, option, index):                 # noqa: N802
        super().initStyleOption(option, index)
        if index.column() == C_CHECK and index.data(GRAY_ROLE):
            option.state &= ~QStyle.State_Enabled
            option.palette.setColor(QPalette.Text, QColor(PALE))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        tag = index.data(TAG_ROLE) if index.column() == C_NAME else None
        if not tag:
            return
        opt = option.__class__(option)
        self.initStyleOption(opt, index)
        st = opt.widget.style() if opt.widget else None
        r = st.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget) if st else opt.rect
        x = r.left() + QFontMetrics(opt.font).horizontalAdvance(opt.text) + 10
        f = QFont(opt.font)
        f.setPointSizeF(max(6.0, f.pointSizeF() * 0.8))
        painter.save()
        painter.setFont(f)
        painter.setPen(QColor(GRAY))
        painter.drawText(x, r.top(), 60, r.height(), Qt.AlignVCenter | Qt.AlignLeft, tag)
        painter.restore()

    def sizeHint(self, option, index):                       # noqa: N802
        s = super().sizeHint(option, index)
        if index.column() == C_NAME and index.data(TAG_ROLE):
            s.setWidth(s.width() + 40)
        return s


# ---------- модель без Qt: папки, отметки, маршрут, черновик ----------

class Model:
    """Данные одного носителя: папки (folders), служебные папки, направления, сохранённые отметки и черновик."""

    def __init__(self, tree, drafts=None):
        self.disk = tree['disk']
        self.drafts = {}                 # исходный путь (нижний регистр) -> dict(path, phys, verdict, base)
        self.undo_stack = []
        self.have = self.have_disks = None
        self.load(tree)
        if drafts:
            self.drafts = drafts
            self.prune()

    # --- загрузка ---
    def load(self, tree):
        self.tree = tree
        self.folders, self.roots, self.dirs = tree['folders'], set(tree['roots']), tree['dirs']
        self.built, self.sig = tree.get('built'), tree.get('sig')
        self.order = sorted(self.folders, key=lambda f: (f.count(SEP) + 1 if f else 0, f))
        kids = collections.defaultdict(list)
        for f in self.order:
            if f:
                kids[hb.parent_of(f)].append(f)
        self.children = {p: sorted(v, key=lambda f: (-self.folders[f][1], f.lower())) for p, v in kids.items()}
        self.aliases = collections.defaultdict(list)      # исходный путь -> физические папки (в служебной и вне её)
        for f in self.order:
            if not self.is_service(f):
                self.aliases[self.orig(f).lower()].append(f)
        self.saved_ms = hb.MarkSet.build(tree['rows'], self.dirs)
        self.recalc()

    def reload(self, tree):
        """Новые данные носителя (новое поколение базы или запись таблиц): черновик сохраняется, совпавшее с сохранённым
        уходит из него. -> число убранных записей черновика."""
        self.load(tree)
        return self.prune()

    def prune(self):
        gone = [k for k, d in self.drafts.items() if self.equal_saved(k, d['verdict'])]
        for k in gone:
            del self.drafts[k]
        self.recalc()
        return len(gone)

    # --- пути ---
    def is_service(self, f):
        """Сама служебная папка переноса («ПЕРЕНЕСЕНО → …», «Скопировано на …» из журнала): отметить нельзя."""
        return bool(f) and SEP not in f and f in self.roots

    def orig(self, f):
        return rz.original_of(f, self.roots)[0] if f else ''

    def markable(self, f):
        return f in self.folders and not self.is_service(f)

    # --- отметки ---
    def saved_key(self, key):
        m = self.saved_ms.by_key.get(key)
        return None if m is None else (m.kind, m.num)

    def equal_saved(self, key, verdict):
        if verdict == INHERIT:
            return self.saved_ms.by_key.get(key) is None
        return self.saved_key(key) == hb.parse_verdict(verdict, self.dirs)[:2]

    def draft_rows(self):
        return [(d['path'], d['verdict']) for d in self.drafts.values()]

    def ms(self):
        return hb.MarkSet.build(self.tree['rows'], self.dirs, self.draft_rows())

    def routes(self, ms):
        """Действующая отметка каждой папки - как в ядре (hb_core.razbor.planner, раздел «маршрут по папкам»):
        корень - отметка всего носителя; служебная папка переноса - ничего (отметка носителя туда не наследуется);
        внутри неё - только явные отметки исходного пути; иначе - своя отметка или маршрут родителя."""
        route = {}
        for f in self.order:
            if not f:
                m = ms.get('')
                route[f] = rz._mark_route(m, self.dirs) if m else rz.NONE_ROUTE
                continue
            top = f.split(SEP, 1)[0]
            parent = route.get(hb.parent_of(f), rz.NONE_ROUTE)
            if top in self.roots:
                if f == top:
                    route[f] = rz.Route(R_NONE, None, None, True)
                    continue
                m = ms.get(f[len(top) + 1:])
                route[f] = rz._mark_route(m, self.dirs, True) if m else parent
                continue
            m = ms.get(f)
            route[f] = rz._mark_route(m, self.dirs) if m else parent
        return route

    def recalc(self):
        self.full_ms = self.ms()
        self.route = self.routes(self.full_ms)
        self.route_saved = self.routes(self.saved_ms)
        self.have_disk_cache = {}
        self.have_sub = self.have_counts()

    def push_undo(self):
        self.undo_stack.append({k: dict(v) for k, v in self.drafts.items()})
        del self.undo_stack[:-UNDO_MAX]

    def set_mark(self, folders, verdict):
        """Черновая отметка папок (физические пути; '' - весь носитель). -> сколько записей черновика изменилось."""
        return self.set_marks([(f, verdict) for f in folders])

    def set_marks(self, pairs):
        """Несколько черновых отметок одним шагом «Отменить последнее»: [(физический путь, решение)]."""
        self.push_undo()
        changed = 0
        for f, verdict in pairs:
            if f and not self.markable(f):
                continue
            o = self.orig(f)
            key = o.lower()
            cur = self.drafts.get(key)
            if self.equal_saved(key, verdict):
                if cur is not None:
                    del self.drafts[key]
                    changed += 1
                continue
            if cur is None or cur['verdict'] != verdict:
                self.drafts[key] = dict(path=o, phys=f, verdict=verdict,
                                        base=cur['base'] if cur else self.saved_key(key))
                changed += 1
        if not changed:
            self.undo_stack.pop()
        self.recalc()
        return changed

    def undo(self):
        if not self.undo_stack:
            return False
        self.drafts = self.undo_stack.pop()
        self.recalc()
        return True

    def discard(self):
        if self.drafts:
            self.push_undo()
            self.drafts = {}
            self.recalc()

    def own_choice(self, f):
        """Что стоит у папки своё (для выпадающего списка): текст решения или «как у родителя»."""
        m = self.full_ms.get(self.orig(f))
        if m is None:
            return INHERIT
        if m.kind == R_DIR and m.num in self.dirs:
            return self.dirs[m.num].verdict()
        if m.kind == R_SKIP:
            return SKIP
        return None

    # --- галочки диска назначения (этап 8): галочка - вид отметок, не отдельное хранилище ---
    def own_mark(self, f):
        """Своя действующая (с черновиком) отметка папки; '' - отметка всего носителя. None - своей нет."""
        return self.full_ms.get(self.orig(f) if f else '')

    @staticmethod
    def is_dir(r, num):
        return r is not None and r.state == R_DIR and r.num == num

    def ancestors(self, f):
        while f:
            f = hb.parent_of(f)
            yield f

    def parent_is(self, f, num, pending):
        """Идёт ли родитель папки f в направление num с учётом ещё не применённых изменений пакета pending
        {исходный путь (нижний регистр): решение}. Правила - те же, что Model.routes: служебная папка переноса - не
        направление; самая глубокая своя отметка решает."""
        for a in self.ancestors(f):
            if self.is_service(a):
                return False
            key = self.orig(a).lower() if a else ''
            if key in pending:
                v = pending[key]
                if v == INHERIT:
                    continue
                kind, n = hb.parse_verdict(v, self.dirs)[:2]
                return kind == R_DIR and n == num
            if self.full_ms.by_key.get(key) is not None:
                return self.is_dir(self.route.get(a), num)
        return False

    def own_after(self, f, pending):
        """(вид, номер) своей отметки папки с учётом пакета; None - своей нет."""
        key = self.orig(f).lower()
        if key in pending:
            v = pending[key]
            return None if v == INHERIT else hb.parse_verdict(v, self.dirs)[:2]
        m = self.full_ms.by_key.get(key)
        return None if m is None else (m.kind, m.num)

    def include_pairs(self, folders, num, pending=None):
        """«Сделать D» (галочка в «Только выбранные»/«Все папки», бросок в ячейку, снятие исключения): родитель уже
        идёт в D - своя отметка снимается; иначе своя отметка = D. Папки по порядку от мелких путей к глубоким, родитель
        считается с уже сделанными изменениями пакета. -> [(физический путь, решение)]."""
        d = self.dirs.get(num)
        if d is None:
            return []
        pending = {} if pending is None else pending
        out = []
        for f in sorted({f for f in folders if f and self.markable(f)}, key=lambda x: (x.count(SEP), x.lower())):
            key = self.orig(f).lower()
            own = self.own_after(f, pending)
            if self.parent_is(f, num, pending):
                v = None if own is None or own == (R_DIR, num) else INHERIT
            else:
                v = None if own == (R_DIR, num) else d.verdict()
            if v is not None:
                pending[key] = v
                out.append((f, v))
        return out

    def exclude_pairs(self, folders, num, pending=None):
        """«Сделать не D» (снять галочку; галочка в «Все, кроме выбранных»): своя отметка D при родителе не в D -
        снимается («как у родителя»); иначе - «не копировать». Папка и так не идёт в D - ничего."""
        pending = {} if pending is None else pending
        out = []
        for f in sorted({f for f in folders if f and self.markable(f)}, key=lambda x: (x.count(SEP), x.lower())):
            key = self.orig(f).lower()
            own = self.own_after(f, pending)
            par = self.parent_is(f, num, pending)
            cur = own == (R_DIR, num) if own is not None else par
            if not cur:
                continue
            v = INHERIT if own is not None and not par else SKIP
            pending[key] = v
            out.append((f, v))
        return out

    def check(self, f, num, mode):
        """Галочка папки для направления num в режиме mode ('only'/'all'/'except'). -> None (весь носитель, служебная
        папка - галочки нет) или dict(on, gray - унаследовано/менять нельзя, checkable, tag - «Н2» у своей отметки другого
        направления, tip)."""
        if not f or not self.markable(f):
            return None
        r = self.route[f]
        own = self.own_mark(f)
        tag, tip = '', ''
        if own is not None and own.kind == R_DIR and own.num != num:
            d = self.dirs.get(own.num)
            tag = own.num
            tip = f'Папка отмечена для «{own.num} {d.name if d else ""}» ({hb.disk_nums(d.disks) if d and d.disks else "диск не назначен"}).'
        elif r.state == R_DIR and r.num != num:
            d = self.dirs.get(r.num)
            src = 'всего носителя' if r.mark is not None and r.mark.path == '' else f'папки «{r.mark.path}»' if r.mark else ''
            tip = f'Идёт в «{r.num} {d.name if d else ""}» (от {src}).'
        if mode == 'except':
            on = r.state == R_SKIP
            own_skip = own is not None and own.kind == R_SKIP
            gray = on and not own_skip
            checkable = not gray and (self.is_dir(r, num) or own_skip)
            if tag or (r.state == R_DIR and r.num != num):
                tip += (' В режиме «Все, кроме выбранных» галочка значит «исключить»; чтобы копировать эту папку на '
                        'этот диск, перетащите её в ячейку «Копировать на диск» справа.')
            elif gray:
                tip = 'Исключена вместе с родительской папкой.'
        else:
            on = self.is_dir(r, num)
            gray = on and not (own is not None and own.kind == R_DIR and own.num == num)
            checkable = not gray
            if tag:
                tip += ' Поставьте галочку — отметка перейдёт на этот диск назначения.'
            elif gray:
                tip = ('Выбрана вместе с родительской папкой.' if r.mark is not None and r.mark.path
                       else 'Выбрана вместе со всем носителем.')
        return dict(on=on, gray=gray, checkable=checkable, tag=tag, tip=tip.strip())

    def own_skips(self):
        """Свои «не копировать» у папок (без всего носителя): [физический путь]."""
        return [self.aliases[k][0] for k, m in self.full_ms.by_key.items()
                if k and m.kind == R_SKIP and self.aliases.get(k)]

    def skips_back_to(self, num, pending=None):
        """Свои «не копировать», снятие которых вернёт папку в направление num (родительская цепочка - в num, с учётом
        пакета pending, например новой отметки всего носителя). Исключения внутри веток других направлений - нет."""
        pending = dict(pending or {})
        out = []
        for f in sorted(self.own_skips(), key=lambda x: (x.count(SEP), x.lower())):
            if self.parent_is(f, num, pending):
                pending[self.orig(f).lower()] = INHERIT
                out.append(f)
        return out

    def own_excluded(self, num):
        """Сколько папок исключил владелец из num: своя «не копировать» при родителе, идущем в num."""
        return len([f for f in self.own_skips() if self.parent_is(f, num, {})])

    def tops(self, pick):
        """Сколько «верхних» папок с признаком pick(маршрут): у самой признак есть, у родителя - нет (у верхних папок
        носителя родитель - весь носитель, его признак не считается). Служебные и уже перенесённые не считаются."""
        n = 0
        for f in self.order:
            if not f or self.is_service(f) or (self.route[f].moved and self.route[f].state != R_DIR):
                continue
            p = hb.parent_of(f)
            if pick(self.route[f]) and (not p or self.is_service(p) or not pick(self.route[p])):
                n += 1
        return n

    # --- показ ---
    def label(self, r):
        if r.state == R_DIR:
            d = self.dirs.get(r.num)
            t = d.label() if d else str(r.num)
            return t + (' — дополнительная копия (папка уже перенесена)' if r.moved else '')
        if r.state == R_SKIP:
            return 'не копировать' + (f' (старое «{r.mark.label}»)' if r.mark is not None and r.mark.legacy else '')
        if r.state == R_UNSET:
            return hb.mark_text(r.mark, self.dirs)
        return 'уже перенесено' if r.moved else 'не отмечено'

    def mode_text(self, r):
        if r.mark is None:
            return 'режим не выбран — файлы «не отмечены»'
        if r.state == R_DIR:
            return f'всё — в {self.label(r)}, кроме отмеченных'
        if r.state == R_SKIP:
            return 'ничего, кроме отмеченных'
        return self.label(r)

    def cell(self, f, saved=False):
        """Ячейка «Куда»: dict(text, kind 'own'/'inherited'/'none'/'service', dirty None/'own'/'drop'/'inherited', tip)."""
        if self.is_service(f):
            return dict(text='служебная папка: уже перенесено', kind='service', dirty=None,
                        tip='Папка, куда файлы перенесли раньше. Её саму отметить нельзя; папки внутри неё можно '
                            'отметить, чтобы ДОПОЛНИТЕЛЬНО скопировать их в другое направление (второй раз они не '
                            'перемещаются).')
        o = self.orig(f)
        r = (self.route_saved if saved else self.route)[f]
        own = r.mark is not None and r.mark.path.lower() == o.lower()
        tips = []
        if not f:
            text = self.mode_text(r)
            kind = 'own' if r.mark is not None else 'none'
        else:
            text = self.label(r)
            if own:
                kind = 'own'
            elif r.mark is not None:
                kind = 'inherited'
                src = 'режима' if r.mark.path == '' else f'«{last(r.mark.path)}»'
                text += f' — от {src}'
                tips.append('Унаследовано от ' + ('режима всего носителя' if r.mark.path == '' else
                                                  f'папки «{r.mark.path}»') + '.')
            else:
                kind = 'none'
        dirty = None
        if not saved:
            d = self.drafts.get(o.lower())
            rs = self.route_saved[f]
            if d is not None and d['verdict'] == INHERIT:
                dirty = 'drop'
                text = '• снять свою отметку → ' + text
                tips.append('Своя отметка будет снята при сохранении; папка получит отметку родителя.')
            elif d is not None:
                dirty = 'own'
                text = '• ' + text
                tips.append('Своя отметка — НЕ сохранена (кнопка «Сохранить отметки»).')
            elif (r.state, r.num, r.moved) != (rs.state, rs.num, rs.moved):
                dirty = 'inherited'
                text = '• ' + text
                tips.append(f'Изменится после сохранения из-за отметки выше; сейчас сохранено: {self.cell(f, True)["text"]}.')
            elif own:
                tips.append('Своя отметка этой папки (сохранена).')
            if d is not None and d['base'] != self.saved_key(o.lower()):
                tips.append('Пока вы отмечали, отметку этой папки изменили в другом месте.')
        others = [x for x in self.aliases.get(o.lower(), []) if x != f]
        if f and others:
            tips.append('Та же отметка действует и на: ' + '; '.join(f'«{x}»' for x in others[:3]) + '.')
        return dict(text=text, kind=kind, dirty=dirty, tip=' '.join(tips))

    def look(self, f):
        """Как показать папку в дереве (этап 6, вместо колонки «Куда»): dict(kind 'dir'/'skip'/'unset'/'none'/'moved'/
        'service', num, own, dirty, tip, bg - цвет фона или None). Своя отметка - насыщенный цвет направления,
        унаследованная - бледный; «не копировать» - серый (зачёркивание ставит страница)."""
        c = self.cell(f)
        r = self.route[f]
        own = c['kind'] == 'own'
        if c['kind'] == 'service':
            return dict(kind='service', num=None, own=False, dirty=None, tip=c['tip'], bg=None)
        if r.state == R_DIR:
            kind, d = 'dir', self.dirs.get(r.num)
            head = f'{r.num} {d.label() if d else ""}'.strip()
            if r.moved:
                head += ' — дополнительная копия (папка уже перенесена)'
            bg = dir_colors(r.num)[0 if own else 1]
        elif r.state == R_SKIP:
            kind, head, bg = 'skip', self.label(r)[:1].upper() + self.label(r)[1:], SKIP_OWN if own else SKIP_INH
        elif r.state == R_UNSET:
            kind, head, bg = 'unset', self.label(r), UNSET_BG
        elif r.moved:
            kind, head, bg = 'moved', 'Уже перенесено раньше', None
        else:
            kind, head, bg = 'none', 'Не отмечено' + (' — режим не выбран' if r.mark is None else ''), None
        if not f:
            src = ' (режим всего носителя)' if r.mark is not None else ''
        elif own:
            src = ' (своя отметка)'
        elif r.mark is not None:
            src = ' (от режима всего носителя)' if r.mark.path == '' else f' (от папки «{r.mark.path}»)'
        else:
            src = ''
        extra = c['tip'].replace('Своя отметка этой папки (сохранена).', '')
        if r.mark is not None:
            extra = extra.replace('Унаследовано от ' + ('режима всего носителя' if r.mark.path == '' else
                                                        f'папки «{r.mark.path}»') + '.', '')
        tip = head + src + '. ' + extra.strip()
        if c['dirty']:
            tip = '• НЕ СОХРАНЕНО. ' + tip
        return dict(kind=kind, num=r.num if kind == 'dir' else None, own=own, dirty=c['dirty'], tip=tip.strip(), bg=bg)

    def docs_near_map(self):
        """Папки, где документы «рядом с фото и видео» - те же правила, что в ядре (razbor.planner, «документы
        рядом»): фото или видео в самой папке или в подпапках с той же решающей отметкой; корень носителя и сама
        служебная папка - нет. Отметки отдельных файлов (только из командной строки) здесь не учитываются."""
        direct = {}
        for f in self.order:
            n = self.folders[f][2]
            direct[f] = n[0] + n[1]
        for f in self.order:
            if f and hb.parent_of(f) in direct:
                n = self.folders[f][2]
                direct[hb.parent_of(f)] -= n[0] + n[1]
        ident = lambda r: (r.mark.row if r.mark else None, r.moved, r.state, r.num)
        ms = {}
        for f in reversed(self.order):
            k = direct[f]
            for ch in self.children.get(f, ()):
                if ident(self.route[ch]) == ident(self.route[f]):
                    k += ms[ch]
            ms[f] = k
        return {f: bool(f) and not self.is_service(f) and ms[f] > 0 for f in self.order}

    # --- «Уже есть» ---
    def set_have(self, have, disks_):
        self.have, self.have_disks = have, list(disks_)
        self.have_disk_cache = {}
        self.have_sub = self.have_counts()

    def have_counts(self):
        """«Уже есть» по поддереву: у каждой папки - СВОЁ направление для файлов прямо в ней (с хешем, типы, которые
        направление копирует, есть на всех его дисках), затем сумма детей. None - ещё не посчитано."""
        if self.have is None:
            return None
        near = self.docs_near_map()
        own = {}
        for f, masks in self.have.items():
            r = self.route.get(f)
            if r is None or r.state != R_DIR:
                continue
            d = self.dirs.get(r.num)
            if d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
                continue
            need = sum(1 << self.have_disks.index(x) for x in d.disks)
            types = [k for k, cat in CAT_OF_TYPE.items() if cat in d.cats       # что копирует направление;
                     and not (cat == hb.CAT_DOC and d.docs_near and not near.get(f))]  # документы - только «рядом»
            n = b = 0
            for mask, c in masks.items():
                if mask & need == need:
                    n += sum(c[k] for k in types)
                    b += sum(c[N_TYPES + k] for k in types)
            if n:
                own[f] = (n, b)
        sub = collections.defaultdict(lambda: [0, 0])
        for f in reversed(self.order):
            v = own.get(f)
            if v:
                sub[f][0] += v[0]
                sub[f][1] += v[1]
            if f and f in sub:
                p = sub[hb.parent_of(f)]
                p[0] += sub[f][0]
                p[1] += sub[f][1]
        return dict(sub)

    def have_on_disk(self, num_):
        """«Уже есть на диске» по КАЖДОМУ диску направления num_ (этап 12, 45 и 77 раздельно): файлы с хешем, которые
        направление копирует (те же папки, типы и «документы рядом», что у колонки «Уже есть» и в ядре), и у которых
        на этом диске уже есть подтверждённая копия с тем же SHA-256 (razbor_have: маска по дискам). Ядро не менялось:
        у него «уже есть» - только на всех дисках сразу. -> {диск: (файлов, байт)} или None (ещё не посчитано).
        Ответ запоминается до правки отметок или нового «Уже есть» (recalc / set_have): ячейка перерисовывается часто.
        Замер на настоящей базе без кэша: HDD45 (25 тыс. папок) - 0,06 с, HDD09 - 0,03 с."""
        cache = getattr(self, 'have_disk_cache', None)
        if cache is None:
            cache = self.have_disk_cache = {}
        if num_ not in cache:
            cache[num_] = self._have_on_disk(num_)
        return cache[num_]

    def _have_on_disk(self, num_):
        d = self.dirs.get(num_)
        if self.have is None or d is None or not d.disks or any(x not in self.have_disks for x in d.disks):
            return None
        near = self.docs_near_map()
        types_all = [k for k, cat in CAT_OF_TYPE.items() if cat in d.cats]
        types_far = [k for k in types_all if not (CAT_OF_TYPE[k] == hb.CAT_DOC and d.docs_near)]
        res = {x: [0, 0] for x in d.disks}
        bits = {x: 1 << self.have_disks.index(x) for x in d.disks}
        for f, masks in self.have.items():
            r = self.route.get(f)
            if r is None or r.state != R_DIR or r.num != num_:
                continue
            types = types_all if near.get(f) else types_far
            full = sum(bits.values())
            for mask, c in masks.items():
                if r.moved and mask & full == full:
                    continue                              # перенесено и есть везде - в «отмечено» не входит (ядро)
                n = sum(c[k] for k in types)
                if not n:
                    continue
                b = sum(c[N_TYPES + k] for k in types)
                for x, bit in bits.items():
                    if mask & bit:
                        res[x][0] += n
                        res[x][1] += b
        return {x: tuple(v) for x, v in res.items()}

    # --- предпросмотр записи ---
    def batch(self):
        """Неизменяемая копия пакета для записи: [(физический путь, решение)] и ключи."""
        return [(d['phys'], d['verdict']) for d in self.drafts.values()], {k: d['verdict'] for k, d in self.drafts.items()}

    def change_lines(self):
        """«было → станет» по каждой записи черновика, вложенные папки, отметки, изменённые в другом месте."""
        lines, conflicts = [], []
        for k, d in sorted(self.drafts.items(), key=lambda kv: kv[1]['path'].lower()):
            f = d['phys']
            where = f'{self.disk}\\{f}' if f else f'{self.disk} (весь носитель)'
            before, after = self.cell(f, True)['text'], self.cell(f)['text'].lstrip('• ')
            lines.append(f'{where}: было «{before}» → станет «{after}»')
            if d['base'] != self.saved_key(k):
                conflicts.append(f'{where}: отметку изменили в другом месте, пока вы отмечали; ваша отметка заменит её.')
        paths = sorted(d['path'].lower() for d in self.drafts.values() if d['path'])
        nested = any(b.startswith(a + SEP) for a in paths for b in paths if a != b) or ('' in self.drafts and paths)
        return lines, conflicts, bool(nested)


# ---------- перетаскивание: дерево (источник) и ячейки (приёмники) ----------

def folders_mime(folders):
    md = QMimeData()
    md.setData(MIME, json.dumps(list(folders), ensure_ascii=False).encode('utf-8'))
    return md


def mime_folders(md):
    try:
        return [str(x) for x in json.loads(bytes(md.data(MIME)).decode('utf-8'))] if md.hasFormat(MIME) else []
    except ValueError:
        return []


class DragTree(QTreeWidget):
    """Дерево папок: выделенные папки перетаскиваются в ячейки справа. Весь носитель и служебные папки не тащатся
    (у них нет флага перетаскивания). Сброс на само дерево ничего не делает: случайное движение мыши отметку не снимает."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.press_sel = None                             # выделенные папки в момент нажатия мыши (до смены выделения)

    def mousePressEvent(self, e):                             # noqa: N802
        """Выделение запоминается ДО того, как Qt его поменяет: щелчок по галочке невыделенной папки выделяет её на
        нажатии, а галочка меняется на отпускании - групповое действие решается по выделению до щелчка (этап 12)."""
        self.press_sel = self.page.selected_folders()
        super().mousePressEvent(e)
        self.multi(e)

    def mouseReleaseEvent(self, e):                           # noqa: N802
        """Qt у уже выделенной строки меняет выделение при отпускании - проверяем и здесь."""
        try:
            super().mouseReleaseEvent(e)
            self.multi(e)
        finally:
            self.press_sel = None

    def multi(self, e):
        """Решение владельца 16.11: выделение нескольких папок (Shift/Ctrl-щелчок) СРАЗУ ставит им галочки; щелчок по
        галочке любой выделенной ставит и снимает галочки у всей группы (этап 12), невыделенной - только у неё."""
        if self.indexAt(e.position().toPoint()).column() == C_CHECK:
            return                                    # щелчок по галочке: группу меняет item_changed (этап 12)
        if e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier) and len(self.selectedItems()) > 1:
            QTimer.singleShot(0, self.page.check_selected)

    def mimeTypes(self):                                      # noqa: N802
        return [MIME]

    def mimeData(self, items):                                # noqa: N802
        m = self.page.model
        return folders_mime([f for f in (it.data(C_NAME, ROLE) for it in items) if f and m and m.markable(f)])

    def supportedDropActions(self):                           # noqa: N802
        return Qt.CopyAction


class Cell(QFrame):
    """Ячейка справа (этап 8): «Копировать на диск …» (drop=True - единственная цель перетаскивания: бросок = включить
    папки в диск назначения, page.drop) или «Остаётся на носителе» (drop=False - только сведения)."""

    def __init__(self, page, drop):
        super().__init__()
        self.page, self.drop_ok = page, drop
        self.setAcceptDrops(drop)
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(180 if drop else 90)
        lay = QVBoxLayout(self)
        self.title = QLabel('')
        f = QFont()
        f.setPointSize(13)
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        self.sub = QLabel('')                             # «Фильмы, HDD55»: имя направления оранжевым жирным (этап 12)
        self.sub.setTextFormat(Qt.RichText)
        f2 = QFont()
        f2.setPointSize(11)
        self.sub.setFont(f2)
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        self.body = QLabel('')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        lay.addWidget(self.body)
        # направление на нескольких дисках: по блоку с рамкой на каждый диск («Копия 1 — H: …», этап 12)
        self.blocks_box = QWidget()
        self.blocks_lay = QVBoxLayout(self.blocks_box)
        self.blocks_lay.setContentsMargins(0, 4, 0, 0)
        self.blocks_lay.setSpacing(8)
        self.blocks = []                                  # [[диск, QFrame, QLabel, состояние]]
        self.blocks_box.hide()
        lay.addWidget(self.blocks_box)
        lay.addStretch(1)
        self.btn = None
        if drop:
            self.btn = QPushButton('Подготовить задания…')
            self.btn.clicked.connect(lambda: page.prepare())
            lay.addWidget(self.btn, 0, Qt.AlignRight)
        self.state = 'normal'

    def paint(self, border, bg, state='normal'):
        self.state = state
        self.setStyleSheet(f'Cell {{ border: 2px solid {border}; border-radius: 6px; background: {bg}; }}')

    def set_blocks(self, items):
        """Блоки дисков: items = [(диск, html, состояние)]; пусто - блоков нет (направление на один диск)."""
        if [x for x, _, _ in items] != [b[0] for b in self.blocks]:
            for b in self.blocks:
                b[1].setParent(None)
                b[1].deleteLater()
            self.blocks = []
            for x, _, _ in items:
                fr = QFrame()
                fr.setObjectName('diskblock')
                fl = QVBoxLayout(fr)
                fl.setContentsMargins(10, 8, 10, 8)
                lab = QLabel('')
                lab.setTextFormat(Qt.RichText)
                lab.setWordWrap(True)
                fl.addWidget(lab)
                self.blocks_lay.addWidget(fr)
                self.blocks.append([x, fr, lab, None])
        for blk, (x, html_, state) in zip(self.blocks, items):
            blk[2].setText(html_)
            blk[3] = state
            border, bg = BLOCK_LOOK.get(state, BLOCK_LOOK['none'])
            blk[1].setStyleSheet(f'QFrame#diskblock {{ border:1px solid {border}; border-radius:5px; background:{bg}; }}'
                                 'QFrame#diskblock QLabel { border:none; background:transparent; }')
        self.blocks_box.setVisible(bool(items))

    def block_texts(self):
        """Тексты блоков дисков (для тестов): {диск: html}."""
        return {b[0]: b[2].text() for b in self.blocks}

    def block_states(self):
        return {b[0]: b[3] for b in self.blocks}

    def dragEnterEvent(self, e):                              # noqa: N802
        if self.drop_ok and e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):                               # noqa: N802
        self.dragEnterEvent(e)

    def dropEvent(self, e):                                   # noqa: N802
        folders = mime_folders(e.mimeData()) if self.drop_ok else []
        if folders:
            e.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.drop_folders(folders))
        else:
            e.ignore()

    def drop_folders(self, folders):
        """Обработчик сброса (вызывается и из тестов напрямую)."""
        return self.page.drop(folders) if self.drop_ok else 0


class CloseGuard(QObject):
    """Фильтр событий ГЛАВНОГО окна: закрытие при несохранённых отметках - только с согласия; во время записи - нельзя."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def eventFilter(self, obj, ev):                          # noqa: N802
        if ev.type() != QEvent.Close:
            return False
        p = self.page
        if p.writing:
            QMessageBox.information(p.win, TITLE, 'Идёт запись отметок или создание заданий («Разбор носителя»). '
                                    'Дождитесь окончания.')
            ev.ignore()
            return True
        n = len(p.model.drafts) if p.model else 0
        if n and QMessageBox.question(p.win, TITLE, f'На странице «Разбор носителя» есть несохранённые отметки ({n}).\n\n'
                                      'Закрыть окно без сохранения? Они пропадут.') != QMessageBox.Yes:
            ev.ignore()
            return True
        return False


class TextDialog(QDialog):
    """Окно с текстом (HTML) и кнопками: ok_text - главная кнопка (None - только «Закрыть»); extra - (текст, действие)
    дополнительной кнопки слева (окно при её нажатии закрывается)."""

    def __init__(self, parent, title, body, ok_text=None, cancel_text='Отмена', width=900, height=600, extra=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(width, height)
        lay = QVBoxLayout(self)
        self.text = QTextBrowser()
        self.text.setHtml(body)
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        self.extra = None
        if extra:
            self.extra = QPushButton(extra[0])
            self.extra.clicked.connect(lambda: (self.reject(), extra[1]()))
            row.addWidget(self.extra)
        row.addStretch()
        self.ok = None
        if ok_text:
            self.ok = QPushButton(ok_text)
            self.ok.setDefault(True)
            self.ok.clicked.connect(self.accept)
            row.addWidget(self.ok)
        b = QPushButton(cancel_text if ok_text else 'Закрыть')
        b.clicked.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)


# ---------- «Пересчитать хеши спорных файлов» (разбор и «Команды» после «НЕТ / НЕДОСТАТОЧНО») ----------

class ContestedDialog(QDialog):
    """По service.contested: на каких дисках и в каких папках спорные файлы; подключённый диск - открыть «Пересканировать
    папки» с этими папками (хеш у всех файлов там всегда включён); неподключённый - какой диск подключить."""

    def __init__(self, win, disk, folder=''):
        super().__init__(win)
        self.win, self.disk, self.folder = win, disk, (folder or '').strip(SEP)
        self.rows = None
        self.setWindowTitle(f'Пересчитать хеши спорных файлов - {disk}')
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        where = f'{disk}\\{self.folder}' if self.folder else f'{disk} (весь носитель)'
        lay.addWidget(QLabel(f'<b>{esc(where)}</b>: где лежат файлы без хеша и '
                             'неподтверждённые копии, из-за которых ответ «можно ли удалить» - «НЕТ» или «НЕДОСТАТОЧНО».'
                             ' Пересканирование посчитает хеш у всех файлов этих папок.'))
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)
        self.buttons = QVBoxLayout()
        lay.addLayout(self.buttons)
        row = QHBoxLayout()
        again = QPushButton('Проверить заново')
        again.clicked.connect(self.load)
        row.addWidget(again)
        row.addStretch()
        close = QPushButton('Закрыть')
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.load()

    def load(self):
        self.text.setHtml('<p>Ищу спорные файлы по базе (диски не читаются)…</p>')
        while self.buttons.count():
            w = self.buttons.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        self.win.bg.run(safe, sv.contested, self.disk, self.folder, ok=self.show_rows, quiet=True)

    def show_rows(self, res):
        kind, val = res
        if kind != 'ok':
            self.text.setHtml(f'<p style="color:{RED}">Не получилось: {esc(val.strip().splitlines()[-1] if val.strip() else val)}</p>')
            return
        self.rows = val
        if not val:
            self.text.setHtml('<p>Спорных файлов нет: пересчитывать хеши незачем.</p>')
            return
        h = []
        for d, letter, folders in val:
            total = sum(n for _, n in folders)
            state = (f'<b style="color:{GREEN}">подключён ({esc(letter)})</b>' if letter else
                     f'<b style="color:{ORANGE}">не подключён — подключите его и нажмите «Проверить заново»</b>')
            h.append(f'<p><b>{esc(d)}</b>: {state}; папок {len(folders)}, спорных файлов {num(total)}</p><ul>')
            for f, n in folders[:30]:
                if f == '':
                    h.append(f'<li>весь носитель — {num(n)} спорных файлов, часть лежит прямо в корне, поэтому папками '
                             f'не обойтись: запустите полное сканирование {esc(d)} в программе «Сканер дисков»</li>')
                else:
                    h.append(f'<li>{esc(f)} — {num(n)}</li>')
            if len(folders) > 30:
                h.append(f'<li>… и ещё {len(folders) - 30} папок (все войдут в пересканирование)</li>')
            h.append('</ul>')
            sub = [f for f, _ in folders if f]
            if letter and sub:
                b = QPushButton(f'Пересканировать эти папки на {d} ({letter})…  — {len(sub)} папок')
                b.clicked.connect(lambda _=False, d=d, sub=sub: self.rescan(d, sub))
                self.buttons.addWidget(b)
        self.text.setHtml(''.join(h))

    def rescan(self, disk, folders):
        import rescan_dialog
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.show()


# ---------- страница ----------

class RazborPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win, self.model, self.disk, self.disk_rows = win, None, None, []
        self.items = {}                                   # физический путь папки -> элемент дерева
        self.rev = 0                                      # ревизия входов итога (любая правка, носитель, база)
        self.sum_busy = self.sum_pending = False
        self.have_busy = self.have_pending = False
        self.writing = False
        self.plan = None                                  # последний принятый итог: (план, место дисков, очередь, время)
        self.plan_rev = -1                                # его ревизия (равна self.rev - итог актуален)
        self.loading = None                               # носитель, данные которого читаются
        self.want_choice = True                           # поставить в списки направление, отмеченное в «Обзоре»
        self.dest = None                                  # номер направления - диска назначения
        self.mode_pref = {}                               # (носитель, направление) -> выбранный владельцем EVERY/EXCEPT
        self.painting = False                             # окно само ставит галочки - itemChanged не обрабатывать
        lay = QVBoxLayout(self)
        # 0. шаги работы «2. Что копируем» - в самом верху страницы, над заголовком (этап 11; решение владельца 16.11)
        self.steps = StepsBar(win, 1)
        lay.addWidget(self.steps)
        # 1. выбранный диск назначения - крупно; «Обновить» - справа (макет владельца, 16.11.2026)
        head = QHBoxLayout()
        self.where = QLabel('')
        self.where.setWordWrap(True)
        self.where.setTextFormat(Qt.RichText)
        self.where.setStyleSheet(f'font-size:15pt; font-weight:bold; color:#1b5e20; background:{HEAD_BG}; '
                                 'border:1px solid #a5d6a7; border-radius:4px; padding:8px')
        head.addWidget(self.where, 1)
        b = QPushButton('Обновить')
        b.clicked.connect(self.refresh)
        head.addWidget(b, 0, Qt.AlignTop)
        lay.addLayout(head)
        self.choice_line = self.where                     # прежнее имя (этап 5)
        # 2. форма: подписи слева столбиком, под полями - строки сведений
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(3)
        form.setColumnStretch(1, 1)

        def caption(text):
            lab = QLabel(f'<b>{text}</b>')
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lab
        from commands_page import DiskCombo               # тот же список, что в «Командах»: подключённые сверху
        self.disk_box = DiskCombo(optional=False, text_fn=carrier_text)
        self.disk_box.setMinimumHeight(QFontMetrics(self.disk_box.font()).height() + 16)
        self.disk_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.disk_box.currentIndexChanged.connect(self.disk_changed)
        form.addWidget(caption('Выберите носитель'), 0, 0)
        form.addWidget(self.disk_box, 0, 1)
        self.info = QLabel('')
        self.info.setTextFormat(Qt.RichText)
        self.info.setStyleSheet(f'color:{GRAY}')
        self.info.setWordWrap(True)
        form.addWidget(self.info, 1, 1)
        form.setRowMinimumHeight(1, 22)
        self.dest_box = RichCombo()
        self.dest_box.activated.connect(self.dest_changed)
        form.addWidget(caption('Диск назначения'), 2, 0)
        form.addWidget(self.dest_box, 2, 1)
        self.dest_info = QLabel('')
        self.dest_info.setTextFormat(Qt.RichText)
        self.dest_info.setWordWrap(True)
        self.dest_info.setStyleSheet(f'color:{GRAY}')
        form.addWidget(self.dest_info, 3, 1)
        form.setRowMinimumHeight(3, 22)
        # «Что копировать с носителя»: три отдельные кнопки с промежутками (вариант 1), на ширину поля
        modes = QWidget()
        ml = QHBoxLayout(modes)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(12)
        self.mode_only = QPushButton(MODE_TEXT[ONLY])
        self.mode_every = QPushButton(MODE_TEXT[EVERY])
        self.mode_except = QPushButton(MODE_TEXT[EXCEPT])
        self.mode_only.setToolTip('Копируются только папки с галочкой. Остальное остаётся на носителе (или идёт туда, '
                                  'куда отмечен весь носитель).')
        self.mode_every.setToolTip('Весь носитель - на этот диск. Исключения («не копировать») снимаются; папки, '
                                   'отмеченные для другого диска, остаются за ним (метка «Н2»).')
        self.mode_except.setToolTip('Весь носитель - на этот диск, кроме папок с галочкой: галочка здесь значит '
                                    '«не копировать» (такие папки - красным).')
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_btn = {ONLY: self.mode_only, EVERY: self.mode_every, EXCEPT: self.mode_except}
        for k, w in self.mode_btn.items():
            w.setCheckable(True)
            w.setMinimumHeight(QFontMetrics(w.font()).height() + 16)
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            w.setStyleSheet(MODE_CSS)
            self.mode_group.addButton(w)
            w.toggled.connect(lambda on, k=k: on and self.mode_changed(k))
            ml.addWidget(w, 1)
        self.mode_only.setChecked(True)                   # режим выбран всегда; по умолчанию «Только выбранные»
        form.addWidget(caption('Что копировать с носителя'), 4, 0)
        form.addWidget(modes, 4, 1)
        note = QHBoxLayout()
        self.mode_note = QLabel('')                       # строка пояснения выбранного режима
        self.mode_note.setWordWrap(True)
        self.mode_note.setTextFormat(Qt.RichText)
        self.mode_note.setStyleSheet('color:#37474f')
        note.addWidget(self.mode_note, 1)
        self.mode_hint = QLabel('')
        self.mode_hint.setStyleSheet(f'color:{BLUE}')
        note.addWidget(self.mode_hint)
        form.addLayout(note, 5, 1)
        lay.addLayout(form)
        self.banner = QLabel('')
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(f'background:#fff3e0; color:{ORANGE}; padding:6px; border:1px solid #ffcc80')
        self.banner.hide()
        lay.addWidget(self.banner)
        # 4. дерево слева, ячейки справа
        split = QSplitter(Qt.Horizontal)
        g2 = QWidget()
        l2 = QVBoxLayout(g2)
        l2.setContentsMargins(0, 0, 0, 0)
        self.tree_hint = QLabel('Поставьте галочки у нужных папок или перетащите папки в ячейку справа. Shift/Ctrl — '
                                'несколько папок сразу: выделенным галочки ставятся сами; галочка у любой выделенной '
                                'меняется у всех выделенных.')
        self.tree_hint.setWordWrap(True)
        l2.addWidget(self.tree_hint)
        self.tree = DragTree(self)
        self.tree.setHeaderLabels(HEAD)
        self.tree.setTreePosition(C_NAME)                 # галочки - ровной колонкой слева, ветви дерева - у имени
        self.tree.setItemDelegate(TreeDelegate(self.tree))
        hd = self.tree.header()
        hd.setSectionResizeMode(QHeaderView.Interactive)
        hd.setStretchLastSection(False)
        self.tree.setColumnWidth(C_CHECK, 30)
        hd.setSectionResizeMode(C_NAME, QHeaderView.Stretch)   # имя - на остаток ширины: числа видны без прокрутки
        for c in range(C_FILES, C_HAVE + 1):                 # числа - по ширине (строк немного: дерево ленивое)
            hd.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        tips = {C_CHECK: 'Галочка - папка выбрана для диска назначения (в режиме «Все, кроме выбранных» - исключена).',
                C_NAME: 'Зелёный фон - выбранные папки. Наведите мышь на папку - подсказка. Перетащите папку в ячейку '
                        '«Копировать на диск» справа.',
                C_PHOTO: 'Число фото в папке с подпапками', C_VIDEO: 'Число видео в папке с подпапками',
                C_OTHER: 'Документы, прочие файлы и мусор (Thumbs.db и т. п.)',
                C_HAVE: 'Файлов с хешем, которые уже лежат на ВСЕХ дисках своего направления (по базе): их копировать '
                        'не нужно. «—» - направления с диском нет.'}
        for c, t in tips.items():
            self.tree.headerItem().setToolTip(c, t)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setUniformRowHeights(True)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemChanged.connect(self.item_changed)
        l2.addWidget(self.tree, 1)
        legend = QLabel(legend_html(ONLY))
        self.tree_legend = legend
        legend.setWordWrap(True)
        legend.setStyleSheet('font-size:8pt; color:#616161')
        l2.addWidget(legend)
        split.addWidget(g2)
        right = QWidget()
        l3 = QVBoxLayout(right)
        l3.setContentsMargins(0, 0, 0, 0)
        self.sum_state = QLabel('')
        self.sum_state.setWordWrap(True)
        l3.addWidget(self.sum_state)
        self.tabs = QTabWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cells_box = QWidget()
        self.cells_lay = QVBoxLayout(self.cells_box)
        self.copy_cell = Cell(self, True)
        self.cells_lay.addWidget(self.copy_cell)           # ячейку «Остаётся на носителе» владелец убрал (16.11)
        self.cells_lay.addStretch()
        self.cells = {'copy': self.copy_cell}
        scroll.setWidget(self.cells_box)
        self.tabs.addTab(scroll, 'Копирование')
        self.summary = QTextBrowser()
        self.tabs.addTab(self.summary, 'Подробно (что с каждым файлом)')
        l3.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([820, 540])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        # кнопки
        bar = QHBoxLayout()
        self.busy_lab = QLabel('Идёт пересчёт итога и места на диске…')   # левый нижний угол, в стиле кнопки
        self.busy_lab.setStyleSheet(BUSY_CSS[0])
        self.busy_lab.setToolTip('После изменения отметок итог и место на диске пересчитываются (в фоне, окно не '
                                 'замирает). Цифры справа обновятся, когда надпись исчезнет.')
        self.busy_lab.hide()
        self.blink = QTimer(self)
        self.blink.setInterval(500)
        self.blink.timeout.connect(self.blink_busy)
        bar.addWidget(self.busy_lab)
        self.save_btn = QPushButton('Сохранить отметки')
        self.save_btn.clicked.connect(lambda: self.save())
        self.undo_btn = QPushButton('Отменить последнее')
        self.undo_btn.clicked.connect(self.undo)
        self.discard_btn = QPushButton('Отменить все несохранённые')
        self.discard_btn.clicked.connect(self.discard)
        self.contested_btn = QPushButton('Пересчитать хеши спорных файлов…')
        self.contested_btn.setToolTip('Где лежат файлы без хеша и неподтверждённые копии выделенной папки (или всего '
                                      'носителя); подключённые диски - пересканировать с хешем всех файлов.')
        self.contested_btn.clicked.connect(self.contested)
        self.tasks_btn = self.copy_cell.btn                # «Подготовить задания» - в ячейке «Копировать на диск»
        for w in (self.save_btn, self.undo_btn, self.discard_btn):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(self.contested_btn)
        lay.addLayout(bar)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.run_summary)
        self.guard = CloseGuard(self)
        win.installEventFilter(self.guard)
        self.update_buttons()

    # ---------- носители и данные ----------
    def refresh(self):
        """При показе раздела и после применения новых модулей: список носителей; у выбранного - новые данные, если
        изменились поколение базы или таблицы владельца (черновик сохраняется)."""
        self.win.bg.run(safe, self._probe, ok=self.got_probe, quiet=True)

    @staticmethod
    def _probe():
        return sv.disks(), sv.generation(), sv.snapshot()['sig']

    def got_probe(self, res):
        kind, val = res
        if kind != 'ok':
            return
        rows, gen, sig = val
        self.disk_rows = rows
        self.disk_box.blockSignals(True)
        self.disk_box.fill(rows)
        if self.disk:
            self.disk_box.setCurrentText(self.disk)
        self.disk_box.blockSignals(False)
        if self.disk is None:
            on = [r for r in disk_ui.ordered(rows) if r.get('letter')]
            if on:
                self.disk_box.setCurrentText(on[0]['disk'])       # -> disk_changed
            else:
                self.sum_state.setText('Выберите носитель в списке вверху.')
            return
        m = self.model
        if m is not None and self.loading is None and not self.writing and (gen != m.built or sig != m.sig):
            self.load_disk(self.disk, keep=True)

    def disk_changed(self, _i=None):
        new = self.disk_box.value()
        if not new or new == self.disk:
            return
        n = len(self.model.drafts) if self.model else 0
        if n and QMessageBox.question(self, TITLE, f'У носителя {self.disk} есть несохранённые отметки ({n}).\n\n'
                                      f'Перейти к {new} без сохранения? Они пропадут.') != QMessageBox.Yes:
            self.disk_box.blockSignals(True)
            self.disk_box.setCurrentText(self.disk)
            self.disk_box.blockSignals(False)
            return
        self.choose_disk(new)

    def choose_disk(self, disk):
        """Выбрать носитель (из списка или из теста): дерево, итог и «Уже есть» - заново."""
        self.disk, self.model, self.plan = disk, None, None
        self.disk_box.blockSignals(True)
        self.disk_box.setCurrentText(disk)
        self.disk_box.blockSignals(False)
        self.tree.clear()
        self.items = {}
        self.summary.setHtml('')
        self.banner.hide()
        self.update_buttons()
        self.load_disk(disk, keep=False)

    def load_disk(self, disk, keep):
        self.loading = disk
        self.sum_state.setText('Читаю папки носителя из базы…')
        self.win.bg.run(safe, sv.razbor_tree, disk, ok=lambda res, d=disk, k=keep: self.got_tree(d, k, res), quiet=True)

    def got_tree(self, disk, keep, res):
        if disk != self.disk:
            return
        self.loading = None
        kind, val = res
        if kind != 'ok':
            self.sum_state.setText(f'<span style="color:{RED}">Не получилось прочитать носитель: '
                                   f'{esc(val.strip().splitlines()[-1] if val.strip() else val)}</span>')
            return
        old = self.model
        old_have = (old.have, old.have_disks) if old is not None else None
        if keep and old is not None:
            same_tree = set(old.folders) == set(val['folders']) and old.roots == set(val['roots'])
            gen_changed = old.built != val['built']
            pruned = old.reload(val)
            if pruned:
                self.win.statusBar().showMessage(f'Отметки, которые уже сохранены так же: {pruned} - убраны из '
                                                 'несохранённых.', 6000)
            if same_tree:
                self.update_items()
            else:
                self.rebuild_tree()
        else:
            self.model = Model(val)
            gen_changed = True
            self.rebuild_tree()
        self.show_disk_info()
        self.fill_dest()
        need = self.direction_disks()
        if old_have and old_have[0] is not None and old_have[1] == need:
            self.model.set_have(*old_have)                 # прежние цифры видны, пока считаются новые
            self.update_items()
        if gen_changed or not old_have or old_have[1] != need:
            self.run_have()
        self.changed(debounce=False)

    def direction_disks(self):
        m = self.model
        return sorted({d for x in m.dirs.values() for d in x.disks}) if m else []

    def show_disk_info(self):
        """Строка под полем носителя (макет): плашка «подключён (F:)» / «не подключён» · опись от …, полная · файлов, ГБ."""
        m = self.model
        row = next((r for r in self.disk_rows if r['disk'] == self.disk), {'disk': self.disk, 'label': m.tree['label']})
        sc = m.tree.get('scanned')
        st = disk_ui.status_text(m.tree.get('status'))
        files, size = m.folders.get('', (0, 0, None, None))[:2]
        if row.get('letter'):
            pill = (f'<span style="background:#c8e6c9; color:{GREEN}"><b>&nbsp;подключён ({esc(row["letter"])})&nbsp;</b>'
                    '</span>')
        else:
            pill = f'<span style="background:#ffe0b2; color:{ORANGE}"><b>&nbsp;не подключён&nbsp;</b></span>'
        bits = [(f'опись от {time.strftime("%d.%m.%Y", time.localtime(sc))}' if sc else 'дата описи неизвестна')
                + f', {st}', f'{files_word(files)}, {gb(size)} ГБ']
        if m.tree.get('issues'):
            bits.append(f'непрочитанных мест: {num(m.tree["issues"])}')
        self.info.setText(pill + ' &nbsp;· ' + esc(' · '.join(bits)))
        d = hb.direction_of_disk(m.dirs, self.disk)
        if d:
            self.banner.setText(f'{self.disk} — сам диск направления «{d.name}» ({hb.disk_nums(d.disks)}): копировать с '
                                f'него на остальные диски направления можно, перемещать на нём ничего нельзя.')
            self.banner.show()
        else:
            self.banner.hide()

    # ---------- дерево ----------
    def rebuild_tree(self):
        """Перестроить дерево, сохранив раскрытые узлы, выделение и прокрутку (по путям)."""
        expanded = {p for p, it in self.items.items() if it.isExpanded()}
        selected = {it.data(C_NAME, ROLE) for it in self.tree.selectedItems()}
        scroll = self.tree.verticalScrollBar().value()
        self.tree.clear()
        self.items = {}
        m = self.model
        root = QTreeWidgetItem()
        root.setData(C_NAME, ROLE, '')
        root.setFlags(root.flags() & ~Qt.ItemIsDragEnabled)       # весь носитель - это режим, не перетаскивается
        for c in range(C_FILES, C_HAVE + 1):
            root.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.addTopLevelItem(root)
        self.items[''] = root
        self.set_item(root, '')
        self.fill(root)
        root.setExpanded(True)
        for p in sorted(expanded, key=lambda x: x.count(SEP)):
            it = self.items.get(p)
            if it is not None and p in m.folders:
                it.setExpanded(True)                     # -> expand(): дети создаются
        for p in selected:
            if p in self.items:
                self.items[p].setSelected(True)
        QTimer.singleShot(0, lambda: self.tree.verticalScrollBar().setValue(scroll))

    def fill(self, item):
        """Создать детей узла (лениво: внуки - по раскрытию)."""
        p = item.data(C_NAME, ROLE)
        item.takeChildren()
        item.setData(C_NAME, FILLED, True)               # дети созданы
        for f in self.model.children.get(p, ()):
            ch = QTreeWidgetItem()
            ch.setData(C_NAME, ROLE, f)
            for c in range(C_FILES, C_HAVE + 1):
                ch.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            if not self.model.markable(f):
                ch.setFlags(ch.flags() & ~Qt.ItemIsDragEnabled)
            self.items[f] = ch
            self.set_item(ch, f)
            if self.model.children.get(f):
                ph = QTreeWidgetItem()
                ph.setText(C_NAME, '…')
                ch.addChild(ph)
            item.addChild(ch)

    def expand(self, item):
        if not item.data(C_NAME, FILLED) and item.data(C_NAME, ROLE) is not None:
            self.fill(item)

    def set_item(self, it, f):
        m = self.model
        files, size, n, b = m.folders.get(f, (0, 0, (0,) * 5, (0,) * 5))
        lk = m.look(f)
        mode = self.mode() if self.dest else ONLY
        ck = m.check(f, self.dest, mode) if self.dest else None
        if not f and self.dest and mode == ONLY:
            ck = self.root_check()                        # «выбрать все» - у строки носителя
        name = f'{self.disk} (весь носитель)' if not f else last(f)
        self.painting = True
        try:
            it.setText(C_NAME, ('• ' if lk['dirty'] else '') + name)
            tip = lk['tip']
            if ck and ck['tip']:
                tip = ck['tip'] + ' ' + tip
            it.setToolTip(C_NAME, tip)
            font = QFont()
            font.setItalic(bool(lk['dirty']))
            font.setBold(not f or bool(ck and ck['on'] and not ck['gray']))
            it.setFont(C_NAME, font)
            flags = it.flags()
            if ck is None:
                it.setData(C_CHECK, Qt.CheckStateRole, None)
                it.setFlags(flags & ~Qt.ItemIsUserCheckable)
                it.setData(C_CHECK, GRAY_ROLE, False)
                it.setData(C_NAME, TAG_ROLE, None)
            else:
                it.setFlags((flags | Qt.ItemIsUserCheckable) if ck['checkable'] else (flags & ~Qt.ItemIsUserCheckable))
                it.setCheckState(C_CHECK, ck.get('state', Qt.Checked if ck['on'] else Qt.Unchecked))
                it.setData(C_CHECK, GRAY_ROLE, not ck['checkable'])
                it.setToolTip(C_CHECK, ck['tip'] or ('Снять галочку' if ck['on'] else 'Поставить галочку'))
                it.setData(C_NAME, TAG_ROLE, ck['tag'] or None)
            on = bool(f and ck and ck['on'])
            red = on and mode == EXCEPT                   # «Все, кроме выбранных»: выбранные НЕ копируются - красным
            bg = QBrush(QColor(EXC_BG if red else SEL_BG)) if on else QBrush()
            for c in range(C_CHECK, C_HAVE + 1):
                it.setBackground(c, bg)
            if lk['dirty'] in ('own', 'drop'):
                color = BLUE                              # своя несохранённая отметка
            elif lk['kind'] in ('service', 'moved'):
                color = GRAY
            elif ck and ck['gray']:
                color = PALE                              # выбрана вместе с родителем - бледно (курсив, если не сохранено)
            elif lk['dirty']:
                color = BLUE
            elif red:
                color = EXC_FG
            else:
                color = None
            for c in range(C_NAME, C_HAVE + 1):
                it.setForeground(c, QBrush(QColor(color)) if color and (c == C_NAME or color == PALE) else QBrush())
            it.setText(C_FILES, num(files))
            it.setText(C_GB, gb(size))
            it.setText(C_PHOTO, num(n[0]))
            it.setText(C_VIDEO, num(n[1]))
            it.setText(C_OTHER, num(n[2] + n[3] + n[4]))
            it.setToolTip(C_GB, f'фото {gb(b[0])} ГБ, видео {gb(b[1])} ГБ, документы {gb(b[2])} ГБ, прочие {gb(b[3])} ГБ, '
                                f'мусор {gb(b[4])} ГБ')
            it.setToolTip(C_OTHER, f'документы {num(n[2])}, прочие {num(n[3])}, мусор {num(n[4])}')
            if m.have_sub is None:
                it.setText(C_HAVE, '…')
                it.setToolTip(C_HAVE, 'Считаю, что уже есть на дисках направлений…')
            else:
                v = m.have_sub.get(f)
                r = m.route.get(f)
                with_disk = r is not None and r.state == R_DIR and m.dirs.get(r.num) is not None and m.dirs[r.num].disks
                it.setText(C_HAVE, num(v[0]) if v else ('0' if with_disk else '—'))
                it.setToolTip(C_HAVE, f'{num(v[0])} файлов, {gb(v[1])} ГБ уже есть на всех дисках своего направления '
                                      '(по хешу)' if v else 'Ничего из этой папки на дисках направления по хешу не найдено.')
        finally:
            self.painting = False

    def update_items(self):
        for f, it in self.items.items():
            if self.model and f in self.model.folders:
                self.set_item(it, f)
        self.render_cells()

    # ---------- диск назначения и режим (этап 8) ----------
    def preferred(self):
        """Направления, отмеченные галочкой в «Обзоре» (directions_page.chosen: есть сейчас и с диском), по номеру."""
        if self.model is None:
            return []
        return sorted(directions_page.chosen(self.model.dirs), key=lambda d: hb.num_key(d.num))

    def dest_dirs(self):
        """Направления, у которых есть диск, по номеру: только они могут быть диском назначения."""
        if self.model is None:
            return []
        return sorted((d for d in self.model.dirs.values() if d.disks), key=lambda d: hb.num_key(d.num))

    def default_dest(self):
        """Первое по номеру направление из «Обзора»; иначе направление отметки всего носителя (если у него есть диск);
        иначе первое с диском."""
        pref = self.preferred()
        if pref:
            return pref[0].num
        r = self.model.route.get('', rz.NONE_ROUTE)
        dd = self.dest_dirs()
        if r.state == R_DIR and any(d.num == r.num for d in dd):
            return r.num
        return dd[0].num if dd else None

    def use_choice(self):
        """Переход из «Обзора» («Перейти к написанию команды…»): диск назначения - первое по номеру отмеченное
        направление (отметки носителя не меняются)."""
        self.want_choice = True
        if self.model is not None:
            self.fill_dest()

    def fill_dest(self):
        """Список «Диск назначения»; выбор сохраняется, если такое направление ещё есть."""
        dd = self.dest_dirs()
        nums = [d.num for d in dd]
        if self.want_choice or self.dest not in nums:
            self.dest = self.default_dest()
        self.want_choice = False
        self.dest_box.blockSignals(True)
        self.dest_box.clear()
        for d in dd:
            self.dest_box.add(dest_text(d, self.disk_rows), dest_html(d, self.disk_rows), d.num)
        if self.dest in nums:
            self.dest_box.setCurrentIndex(nums.index(self.dest))
        self.dest_box.blockSignals(False)
        self.sync_mode()
        self.update_items()

    def dest_changed(self, _i=None):
        v = self.dest_box.currentData()
        if v and v != self.dest:
            self.dest = v
            self.sync_mode()
            self.update_items()
            self.show_head()

    def set_dest(self, num_):
        """Выбрать диск назначения (для тестов и перехода)."""
        i = self.dest_box.findData(num_)
        if i >= 0:
            self.dest_box.setCurrentIndex(i)
            self.dest_changed()

    def dest_dir(self):
        return self.model.dirs.get(self.dest) if self.model is not None and self.dest else None

    def root_is_dest(self):
        m = self.model
        return m is not None and self.dest is not None and m.is_dir(m.route.get('', rz.NONE_ROUTE), self.dest)

    def mode(self):
        """Режим из отметки всего носителя: корень ≠ D - «Только выбранные»; корень = D - выбор владельца в окне
        («Все папки» / «Все, кроме выбранных»), без выбора: есть свои исключения - «Все, кроме», иначе «Все папки»."""
        if not self.root_is_dest():
            return ONLY
        pref = self.mode_pref.get((self.disk, self.dest))
        if pref in (EVERY, EXCEPT):
            return pref
        return EXCEPT if self.model.own_skips() else EVERY

    def show_head(self):
        space = self.plan[1] if self.plan else None
        d = self.dest_dir()
        self.where.setText(head_html(d, self.disk_rows, space))
        self.dest_info.setText(dest_info_html(d, self.disk_rows, space))
        m = self.model
        r = m.route.get('', rz.NONE_ROUTE) if m else rz.NONE_ROUTE
        mode = self.mode() if (m is not None and self.dest) else ONLY
        note = MODE_NOTE[mode]
        if m is not None and self.dest and mode == ONLY and r.state == R_DIR and r.num in m.dirs:
            rest = m.dirs[r.num]
            amount = ''
            if self.plan:
                v = [self.plan[0].part_a.get((o, rest.num), (0, 0)) for o in (rz.O_COPY, rz.O_HAVE)]
                amount = f' ({files_word(v[0][0] + v[1][0])}, {gb(v[0][1] + v[1][1])} ГБ)'
            note += (f' <span style="color:{ORANGE}">Весь носитель отмечен «Всё — в {esc(rest.label())}»: папки без '
                     f'галочки идут туда{amount}. «{MODE_TEXT[EVERY]}» или «{MODE_TEXT[EXCEPT]}» заменят эту отметку.'
                     '</span>')
        self.mode_note.setText(note)

    def sync_mode(self):
        """Кнопки режимов - по действующей (с черновиком) отметке всего носителя. Режим выбран всегда: без диска
        назначения кнопки неактивны, но «Только выбранные папки» подсвечена."""
        m = self.model
        if m is None:
            return
        mode = self.mode() if self.dest else ONLY
        for w in self.mode_btn.values():
            w.blockSignals(True)
        for k, w in self.mode_btn.items():
            w.setChecked(k == mode)
            w.setEnabled(bool(self.dest) and not self.writing)
        for w in self.mode_btn.values():
            w.blockSignals(False)
        self.mode_hint.setText('• не сохранено' if '' in m.drafts else '')
        self.tree_legend.setText(legend_html(mode))
        self.show_head()

    def mode_changed(self, k):
        m, d = self.model, self.dest_dir()
        if m is None or d is None or self.writing:
            return
        key = (self.disk, d.num)
        pairs, msg = [], ''
        if k == ONLY:
            self.mode_pref.pop(key, None)
            if self.root_is_dest():
                saved = m.saved_ms.by_key.get('')
                if saved is not None and not m.is_dir(m.route_saved.get(''), d.num):
                    pairs = [('', saved.verdict)]        # вернуть сохранённую отметку всего носителя
                else:
                    pairs = [('', SKIP)]
        else:
            self.mode_pref[key] = k
            if not self.root_is_dest():
                pairs.append(('', d.verdict()))
            skips = m.own_skips()
            if k == EVERY and skips:
                drop = m.skips_back_to(d.num, dict((m.orig(f).lower(), v) for f, v in pairs))
                pairs += [(f, INHERIT) for f in drop]
                if drop:
                    msg = (f'«{MODE_TEXT[EVERY]}»: сняты исключения у {folders_word(len(drop))} («Отменить последнее» '
                           'вернёт). Исключения внутри папок других дисков не тронуты.')
            elif k == EXCEPT and skips and pairs:
                msg = (f'Исключения ({folders_word(len(skips))}) действуют и для этого диска — у них галочка. Снимите '
                       'галочку, если папку тоже нужно копировать.')
        if pairs and m.set_marks(pairs):
            self.after_marks()
        else:
            self.sync_mode()
            self.update_items()
        if msg:
            self.win.statusBar().showMessage(msg, 10000)

    def after_marks(self):
        self.update_items()
        self.sync_mode()
        self.changed()

    # ---------- галочки ----------
    def item_changed(self, it, col):
        if self.painting or col != C_CHECK or self.model is None:
            return
        f = it.data(C_NAME, ROLE)
        on = it.checkState(C_CHECK) == Qt.Checked
        if not f:
            self.select_all(on)
            return
        # этап 12 (решение владельца 16.11): галочка выделенной папки при нескольких выделенных - у всей выделенной
        # группы (одним шагом отмены); невыделенной - только у неё. Выделение - каким оно было до щелчка мышью.
        tree = self.tree
        sel = tree.press_sel if tree.press_sel is not None else self.selected_folders()
        if f in sel and len(sel) > 1:
            group = list(sel)
            if self.toggle(group, on):
                QTimer.singleShot(0, lambda fs=group: self.reselect(fs))
            else:
                self.update_items()
            return
        self.toggle([f], on)

    def check_selected(self):
        """Выделено несколько папок (Shift/Ctrl-щелчок) - всем выделенным сразу ставится галочка одним шагом отмены."""
        sel = self.selected_folders()
        if len(sel) > 1 and self.model is not None and self.dest:
            if self.toggle(sel, True):
                QTimer.singleShot(0, lambda fs=sel: self.reselect(fs))

    def tops(self):
        m = self.model
        return [f for f in m.children.get('', ()) if m.markable(f)] if m else []

    def root_check(self):
        """Галочка «выбрать все» у строки носителя (режим «Только выбранные»): все папки верхнего уровня идут в D -
        отмечена; часть - частично; ни одной - пусто."""
        m, tops = self.model, self.tops()
        if not tops:
            return None
        n = sum(1 for f in tops if m.is_dir(m.route[f], self.dest))
        state = Qt.Checked if n == len(tops) else Qt.PartiallyChecked if n else Qt.Unchecked
        return dict(on=n == len(tops), gray=False, checkable=True, tag='', state=state,
                    tip='Выбрать все папки верхнего уровня (или снять все). Исключения внутри папок не меняются.')

    def select_all(self, on):
        """Щелчок по галочке «выбрать все»: не все выбраны - выбрать все папки верхнего уровня; все - снять."""
        m = self.model
        if m is None or self.writing or not self.dest or self.mode() != ONLY:
            self.update_items()
            return 0
        tops = self.tops()
        pairs = m.include_pairs(tops, self.dest) if on else m.exclude_pairs(tops, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        self.after_marks() if n else self.update_items()
        if n:
            self.win.statusBar().showMessage(('Выбраны все' if on else 'Сняты все') + f' папки верхнего уровня ({len(tops)}). '
                                             'Не сохранено - кнопка «Сохранить отметки».', 8000)
        return n

    def reselect(self, folders):
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        for x in folders:
            if x in self.items:
                self.items[x].setSelected(True)
        self.tree.blockSignals(False)

    def toggle(self, folders, on):
        """Галочка поставлена (on) или снята у папок: в «Только выбранные»/«Все папки» - включить в D / исключить;
        в «Все, кроме выбранных» - наоборот (галочка = исключение). -> число изменённых записей черновика."""
        m = self.model
        if m is None or self.writing or not self.dest:
            return 0
        ok = [f for f in folders if f and m.markable(f) and (m.check(f, self.dest, self.mode()) or {}).get('checkable')]
        include = on != (self.mode() == EXCEPT)
        pairs = m.include_pairs(ok, self.dest) if include else m.exclude_pairs(ok, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        self.after_marks() if n else self.update_items()
        if n:
            self.win.statusBar().showMessage(f'Папок: {len(ok)} — ' + ('галочка поставлена' if on else 'галочка снята') +
                                             '. Не сохранено — кнопка «Сохранить отметки».', 8000)
        return n

    # ---------- ячейки справа (этап 8) ----------
    def plan_cap(self):
        if not self.plan:
            return {}
        P, space, queued = self.plan[0], self.plan[1], self.plan[2]
        return sv.capacity(P.part_b, space, queued, disks=[x for d in P.dirs.values() for x in d.disks])

    def counts(self):
        """Числа папок для ячеек: (выбрано для D, исключено владельцем - свои «не копировать» внутри D, остаётся)."""
        m, n = self.model, self.dest
        sel = m.tops(lambda r: m.is_dir(r, n))
        exc = m.own_excluded(n)
        stay = m.tops(lambda r: r.state != R_DIR)
        return sel, exc, stay

    def render_cells(self):
        m = self.model
        if m is None:
            return
        d = self.dest_dir()
        plan = self.plan[0] if self.plan else None
        cap = self.plan_cap()
        c = self.copy_cell
        sel, exc, stay = self.counts() if d else (0, 0, m.tops(lambda r: r.state != R_DIR))
        if d is None:
            c.title.setText('Копировать на диск')
            c.sub.setText('')
            c.set_blocks([])
            c.body.setText(f'<span style="color:{ORANGE}">Диска назначения нет: назначьте диск направлению в «Обзоре».'
                           '</span>')
            c.paint('#9e9e9e', '#fafafa')
            state = 'none'
        else:
            by = {r['disk']: r for r in self.disk_rows}
            many = len(d.disks) > 1
            if many:                                      # этап 12: по блоку на каждый диск
                c.title.setText(f'Копировать на {DISKS_WORDS.get(len(d.disks), f"{len(d.disks)} дисков")} — '
                                f'{copies_word(len(d.disks))}')
            else:
                c.title.setText('Копировать на диск ' + short_place(by.get(d.disks[0]), d.disks[0]))
            c.sub.setText(f'<span style="color:{ORANGE}"><b>{esc(d.name)}</b></span>, {esc(hdds(d))}')
            html_, state = dest_cell_html(d, plan, cap, self.mode(), sel, exc, lambda x: place(by.get(x), x),
                                          split=many)
            c.body.setText(html_)
            blocks = []
            if many and plan is not None:
                cp = plan.part_a.get((rz.O_COPY, d.num), (0, 0))
                hv = plan.part_a.get((rz.O_HAVE, d.num), (0, 0))
                total = (cp[0] + hv[0], cp[1] + hv[1])
                have = m.have_on_disk(d.num)
                for i, x in enumerate(d.disks, 1):
                    cx = cap.get(x) or dict(state='none', files=0, bytes=0, free=None, queued=[0, 0, 0])
                    blocks.append((x,) + disk_block_html(i, x, cx, plan, total, have and have.get(x),
                                                         disk_ui.disk_place(by.get(x) or x)))
            c.set_blocks(blocks)
            if state == 'short':
                c.paint(RED, SHORT_BG, state)
            elif state == 'unknown':
                c.paint('#43a047', UNKNOWN_BG, state)
            else:
                c.paint('#43a047', HEAD_BG, state)
        can = (d is not None and plan is not None and not plan.errors and state != 'short' and not self.writing
               and any(plan.group_state(g) == rz.G_COPY for g, x in plan.groups.items() if x['num'] == d.num))
        c.btn.setEnabled(can)
        c.btn.setText('Подготовить задания…')
        if d is None:
            tip = ''
        elif state == 'short':
            tip = 'Не помещается: снимите галочки у части папок.'
        elif not can and plan is not None:
            tip = 'Копировать нечего: поставьте галочки у папок (задания строятся по сохранённым отметкам).'
        else:
            tip = (f'Задания на копирование для «{d.num} {d.name}» по сохранённым отметкам; перед созданием - сверка '
                   'оглавления носителя и показ.')
        c.btn.setToolTip(tip)

    def drop(self, folders):
        """Папки сброшены в ячейку «Копировать на диск»: включить их в диск назначения (как галочка в «Только
        выбранные»; в «Все, кроме выбранных» - снять исключение). -> число изменённых записей черновика."""
        m = self.model
        if m is None or self.writing or not self.dest:
            return 0
        ok = [f for f in folders if f and m.markable(f)]
        if not ok:
            self.win.statusBar().showMessage('Эти папки отметить нельзя (весь носитель - это режим вверху; служебные '
                                             'папки переноса не отмечаются).', 6000)
            return 0
        pairs = m.include_pairs(ok, self.dest)
        n = m.set_marks(pairs) if pairs else 0
        if n:
            self.after_marks()
            self.win.statusBar().showMessage(f'Папок: {len(ok)} → на диск {hdds(self.dest_dir())}. Не сохранено - '
                                             'кнопка «Сохранить отметки».', 8000)
        return n

    def selected_folders(self):
        return [it.data(C_NAME, ROLE) for it in self.tree.selectedItems() if it.data(C_NAME, ROLE)]

    def apply(self, folders, verdict):
        """Черновая отметка папок напрямую (весь носитель - ''; для тестов и служебных переходов)."""
        if self.model is None or verdict is None or self.writing:
            return
        if self.model.set_mark(folders, verdict):
            self.after_marks()

    def undo(self):
        if self.model and self.model.undo():
            self.after_marks()

    def discard(self):
        if not self.model or not self.model.drafts:
            return
        if QMessageBox.question(self, TITLE, f'Отменить все несохранённые отметки ({len(self.model.drafts)})?\n\n'
                                '«Отменить последнее» вернёт их обратно.') != QMessageBox.Yes:
            return
        self.model.discard()
        self.after_marks()

    def changed(self, debounce=True):
        """Любая правка входов итога: ревизия растёт сразу, итог помечается устаревшим и считается заново."""
        self.rev += 1
        self.show_busy(True)
        self.update_buttons()
        if self.plan is not None:
            self.sum_state.setText(f'<span style="color:{ORANGE}">Итог устарел — пересчитываю…</span>')
        else:
            self.sum_state.setText('Считаю итог…')
        if debounce:
            self.debounce.start(DEBOUNCE_MS)
        else:
            self.debounce.stop()
            self.run_summary()

    def show_busy(self, on):
        """«Идёт пересчёт…» в левом нижнем углу - с правки до принятия итога этой ревизии; мигает."""
        self.busy_lab.setVisible(on)
        if on and not self.blink.isActive():
            self.blink_on = False
            self.blink.start()
        elif not on:
            self.blink.stop()
            self.busy_lab.setStyleSheet(BUSY_CSS[0])

    def blink_busy(self):
        self.blink_on = not getattr(self, 'blink_on', False)
        self.busy_lab.setStyleSheet(BUSY_CSS[1 if self.blink_on else 0])

    def update_buttons(self):
        n = len(self.model.drafts) if self.model else 0
        busy = self.writing or self.model is None
        self.save_btn.setText(f'Сохранить отметки ({n})' if n else 'Сохранить отметки')
        self.save_btn.setEnabled(bool(n) and not busy)
        self.undo_btn.setEnabled(bool(self.model and self.model.undo_stack) and not busy)
        self.discard_btn.setEnabled(bool(n) and not busy)
        self.contested_btn.setEnabled(not busy)
        if self.model is not None:
            self.render_cells()
        else:
            self.tasks_btn.setEnabled(False)

    # ---------- итог ----------
    def run_summary(self):
        if self.model is None:
            return
        if self.sum_busy:
            self.sum_pending = True
            return
        self.sum_busy = True
        snap = (self.disk, self.rev)
        drafts = list(self.model.draft_rows())

        def job(disk, drafts):
            P = sv.razbor(disk, drafts)
            dd = sorted(set(P.part_b) | {x for d in P.dirs.values() for x in d.disks})
            return P, sv.disk_space(dd), sv.queued_copy(disk), time.strftime('%H:%M:%S')
        self.win.bg.run(safe, job, self.disk, drafts, ok=lambda res, s=snap: self.got_summary(s, res), quiet=True)

    def got_summary(self, snap, res):
        self.sum_busy = False
        if snap[0] == self.disk and snap[1] == self.rev:
            kind, val = res
            if kind == 'ok':
                self.plan, self.plan_rev = val, snap[1]
                self.render_summary(*val)
                self.render_cells()
                self.show_head()
                self.sum_state.setText(f'<span style="color:{GRAY}">Посчитано в {val[3]}, с несохранёнными отметками.'
                                       '</span>')
                self.sum_state.setToolTip('Итог учитывает и несохранённые отметки; задания строятся только из сохранённых.')
                self.show_busy(False)
            else:
                self.show_busy(False)
                self.sum_state.setText(f'<span style="color:{RED}">Итог не посчитан: '
                                       f'{esc(val.strip().splitlines()[-1] if val.strip() else val)}</span>')
            if not self.sum_pending:
                return
        self.sum_pending = False
        if self.model is not None and not self.debounce.isActive():   # иначе его запустит таймер правки
            self.run_summary()

    def disk_name(self, d):
        row = next((r for r in self.disk_rows if r['disk'] == d), None)
        t = disk_ui.disk_title(row) if row else ''
        return f'{d} «{t}»' if t else d

    def render_summary(self, P, space, queued, at):
        h = []
        h.append(f'<p><b>{esc(self.disk_name(P.disk))}</b>: {num(P.total[0])} файлов, {gb(P.total[1])} ГБ. '
                 f'Отметок: {len(P.marks)}' + (f' (несохранённых {len(self.model.drafts)})' if self.model.drafts else '')
                 + '.</p>')
        if P.errors:
            h.append(f'<p style="color:{RED}"><b>ИТОГ НЕВЕРЕН:</b> {esc("; ".join(P.errors))}. Задания не создаются.</p>')
        h.append('<p><b>А. Что будет с каждым файлом носителя</b></p>'
                 '<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                 '<tr><th align="left">Что будет</th><th>Файлов</th><th>ГБ</th></tr>')
        for text, n, b in rz.part_a_rows(P):
            h.append(f'<tr><td>{esc(text)}</td><td align="right">{num(n)}</td><td align="right">{gb(b)}</td></tr>')
        h.append(f'<tr><td><b>Итого = опись носителя</b></td><td align="right"><b>{num(P.total[0])}</b></td>'
                 f'<td align="right"><b>{gb(P.total[1])}</b></td></tr></table>')
        if P.moved_copy[0]:
            h.append(f'<p style="color:{GRAY}">Из «будет скопирован» {num(P.moved_copy[0])} лежат в уже перенесённых '
                     'папках: копируются дополнительно, второй раз не перемещаются.</p>')
        h.append('<p><b>Б. Сколько писать на каждый диск</b></p>')
        if P.part_b:
            h.append('<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                     '<tr><th align="left">Диск</th><th>Файлов</th><th>ГБ</th><th>Свободно</th></tr>')
            cap = sv.capacity(P.part_b, space, queued)
            for d, (n, b) in sorted(P.part_b.items()):
                x = cap[d]
                if d in space:
                    short = x['state'] == 'short'
                    place = (f'<span style="color:{RED if short else GREEN}">{gb(x["free"])} ГБ ({esc(x["letter"])})'
                             + (f' — НЕ ПОМЕЩАЕТСЯ: нужно {gb(x["need"] + x["reserve"])} ГБ с запасом' if short else '')
                             + '</span>')
                else:
                    place = f'<span style="color:{GRAY}">не подключён — место не проверено</span>'
                h.append(f'<tr><td>{esc(self.disk_name(d))}</td><td align="right">{num(n)}</td>'
                         f'<td align="right">{gb(b)}</td><td>{place}</td></tr>')
            h.append(f'</table><p style="color:{GRAY}">Свободное место — на {at}; задания вы запустите позже.</p>')
        else:
            h.append('<p>Писать на диски нечего.</p>')
        groups = list(P.groups.values())
        if groups:
            copy = sum(1 for g in P.groups if P.group_state(g) == rz.G_COPY)
            nod = sorted({g['direction'] for k, g in P.groups.items() if P.group_state(k) == rz.G_NODISK})
            h.append(f'<p>Отмеченных папок (будущих заданий): {len(groups)}; есть что копировать: {copy}.'
                     + (f' Направления без диска (задание не создаётся): {esc(", ".join(nod))}.' if nod else '') + '</p>')
        if P.docs_near:
            h.append(f'<p style="color:{GRAY}">Документы рядом с фото и видео (поедут в «Семейный архив»): '
                     f'{num(sum(x[1] for x in P.docs_near))} в {num(len(P.docs_near))} папках.</p>')
        att = [x for x in rz.attention_lines(P) if not x.startswith(f'{P.disk} - диск направления')]
        if att:
            h.append('<p><b>Нужно внимание</b></p><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in att) + '</ul>')
        self.summary.setHtml(''.join(h))

    # ---------- «Уже есть» ----------
    def run_have(self):
        if self.model is None:
            return
        if self.have_busy:
            self.have_pending = True
            return
        self.have_busy = True
        disks_ = self.direction_disks()
        snap = (self.disk, tuple(disks_))
        self.win.bg.run(safe, sv.razbor_have, self.disk, disks_, ok=lambda res, s=snap: self.got_have(s, res), quiet=True)

    def got_have(self, snap, res):
        self.have_busy = False
        kind, val = res
        if self.model is not None and snap[0] == self.disk and list(snap[1]) == self.direction_disks() and kind == 'ok':
            self.model.set_have(val, list(snap[1]))
            self.update_items()
        if self.have_pending or (self.model is not None and snap[0] != self.disk):
            self.have_pending = False
            self.run_have()

    # ---------- сохранение отметок ----------
    def set_writing(self, on):
        self.writing = on
        self.tree.setEnabled(not on)
        for w in (self.disk_box, self.dest_box):
            w.setEnabled(not on)
        self.update_buttons()
        if self.model is not None:
            self.sync_mode()

    def save(self, then=None):
        """Предпросмотр (service.marks_preview) -> окно «было → станет» -> «Записать» -> add_marks_batch одним пакетом.
        then() - после успешной записи (подготовка заданий)."""
        m = self.model
        if m is None or not m.drafts or self.writing:
            return
        rows, sent = m.batch()
        changes, conflicts, nested = m.change_lines()
        disk = self.disk
        self.set_writing(True)

        def shown(res):
            kind, val = res
            if kind != 'ok':
                self.set_writing(False)
                QMessageBox.warning(self, TITLE, 'Предпросмотр не получился, ничего не записано:\n\n' +
                                    (val if kind == 'refused' else val.strip().splitlines()[-1]))
                return
            h = [f'<p><b>{esc(val["lines"][0])}</b> Папок в списке: {len(rows)}.</p><p><b>Было → станет</b></p><ul>']
            h += [f'<li>{esc(x)}</li>' for x in changes]
            h.append('</ul><p><b>Что проверила программа</b></p><ul>')
            h += [f'<li>{esc(x)}</li>' for x in val['lines'][1:]]
            h.append('</ul>')
            if nested:
                h.append(f'<p style="color:{ORANGE}">Среди папок есть вложенные друг в друга: их размеры пересекаются, '
                         'складывать их нельзя. Действует отметка самой глубокой папки.</p>')
            if conflicts:
                h.append(f'<p style="color:{RED}"><b>Изменено в другом месте:</b></p><ul>' +
                         ''.join(f'<li>{esc(x)}</li>' for x in conflicts) + '</ul>')
            h.append(f'<p style="color:{GRAY}">Запись - одним пакетом в «решения.tsv» (копия таблицы до записи - в '
                     '«_БАЗА\\архив таблиц»). Файлы не копируются: это делают задания.</p>')
            dlg = TextDialog(self, 'Сохранить отметки', ''.join(h), ok_text='Записать')
            if dlg.exec() != QDialog.Accepted:
                self.set_writing(False)
                return
            self.win.bg.run(lambda: (safe(sv.add_marks_batch, disk, rows), safe(sv.razbor_tree, disk)),
                            ok=written, quiet=True)

        def written(res):
            (kind, val), (tkind, tree) = res
            self.set_writing(False)
            if disk != self.disk or self.model is None:
                return
            if tkind == 'ok':
                self.model.reload(tree)
                self.fill_dest()
            left = {k for k in sent if k in self.model.drafts}
            done = len(sent) - len(left)
            if kind == 'ok':
                self.win.statusBar().showMessage(f'Записано отметок: {len(val["fields"])}. Копия таблицы - в «_БАЗА\\'
                                                 'архив таблиц».', 8000)
            elif kind == 'refused':
                QMessageBox.warning(self, TITLE, f'Не записано: {val}\n\nНесохранённые отметки остались на экране.')
            else:
                sv_log(val)
                QMessageBox.warning(self, TITLE, 'Запись прервалась ошибкой. Я перечитал таблицу: сохранено '
                                    f'{done} из {len(sent)}, остальные остались несохранёнными.\n\n'
                                    'Подробно - в «_БАЗА\\ответы\\окно - ошибки.log».')
            self.changed(debounce=False)
            if kind == 'ok' and then:
                then()
        self.win.bg.run(safe, sv.marks_preview, disk, rows, ok=shown, quiet=True)

    # ---------- задания ----------
    def prepare(self, nums=None):
        """«Подготовить задания»: nums - направления (None - диск назначения; кнопка ячейки «Копировать на диск»).
        Сохранённые отметки -> пробный расчёт, место по каждому диску, сверка оглавления носителя (в фоне, по порядку)
        -> окно -> «Создать» -> снова пробный расчёт и место -> создание."""
        m = self.model
        if m is None or self.writing:
            return
        if nums is None:
            nums = [self.dest] if self.dest else []
            if not nums:
                QMessageBox.information(self, TITLE, 'Диска назначения нет: назначьте диск направлению в «Обзоре».')
                return
        nums = list(nums)
        if m.drafts:
            if QMessageBox.question(self, TITLE, f'Есть несохранённые отметки ({len(m.drafts)}). Задания строятся только '
                                    'из сохранённых.\n\nСохранить отметки сейчас (сначала - предпросмотр)?') == QMessageBox.Yes:
                self.save(then=lambda: self.prepare(nums))
            return
        disk = self.disk
        self.set_writing(True)
        self.sum_state.setText('Считаю задания по сохранённым отметкам и сверяю оглавление носителя с описью…')
        self.win.bg.run(safe, tasks_check, disk, nums, ok=lambda res: self.show_tasks(disk, nums, res), quiet=True)

    def show_tasks(self, disk, nums, res, note=''):
        kind, val = res
        self.set_writing(False)
        self.sum_state.setText('')
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не посчитаны: ' + (val if kind == 'refused' else
                                                                       val.strip().splitlines()[-1]))
            return
        body, new = tasks_html(val, self.disk_name, note)
        toc = val.get('toc')
        blocked = toc is not None and (not toc['connected'] or toc['problems'])
        extra = None
        if blocked and toc['connected']:
            sub = [p['folder'] for p in toc['problems'] if p['folder'] is not None]
            if sub:
                extra = (f'Пересканировать эти папки ({len(sub)})…', lambda: self.rescan(disk, sub))
        self.last_tasks = val
        dlg = TextDialog(self, f'Подготовить задания - {disk}', body,
                         ok_text=f'Создать задания ({len(new)})' if new and not blocked else None, width=1000, height=640,
                         extra=extra)
        if dlg.exec() != QDialog.Accepted or not new or blocked:
            return
        if QMessageBox.question(self, TITLE, f'Создать заданий: {len(new)} в «Запускаемые скрипты»?\n\nНичего не '
                                'копируется и не запускается: запускаете задания вы - в разделе «Задания на копирование».') != QMessageBox.Yes:
            return
        self.set_writing(True)
        self.win.bg.run(safe, tasks_create, disk, nums, spec_keys(val['specs']),
                        ok=lambda r: self.tasks_created(disk, nums, r), quiet=True)

    def rescan(self, disk, folders):
        """Готовое окно «Пересканировать папки» (Диски и папки) с папками, где сверка нашла расхождения."""
        import rescan_dialog
        running = getattr(self.win, 'rescan', None)
        if running is not None and running.running:
            QMessageBox.information(self, TITLE, 'Уже идёт пересканирование - дождитесь его или остановите.')
            running.raise_()
            return
        self.win.rescan = rescan_dialog.RescanDialog(self.win, disk, folders)
        self.win.rescan.finished.connect(lambda *_: self.refresh())     # новая опись - дерево и итог заново
        self.win.rescan.show()

    def tasks_created(self, disk, nums, res):
        self.set_writing(False)
        kind, val = res
        if kind != 'ok':
            QMessageBox.warning(self, TITLE, 'Задания не созданы: ' + (val if kind == 'refused' else
                                                                     val.strip().splitlines()[-1]))
            return
        what, data = val
        if what == 'changed':                             # список изменился до создания - показать и спросить снова
            self.show_tasks(disk, nums, ('ok', data), note='Пока вы смотрели, отметки, база, место на дисках или '
                                                           'сам носитель изменились: проверьте окно ещё раз.')
            return
        specs = data['res']['specs']
        made = [s for s in specs if not s.get('exists')]
        diff = data.get('differs')
        msg = (f'Создано заданий: {len(made)}' + (f' (уже были подготовлены раньше: {len(specs) - len(made)})'
                                                   if len(specs) != len(made) else '') + '.')
        if diff:
            msg += '\n\nВНИМАНИЕ: созданный список отличается от подтверждённого (данные изменились в последний момент). ' \
                   'Проверьте их в «Заданиях на копирование» перед запуском.'
        if QMessageBox.question(self, TITLE, msg + '\n\nПерейти в «Задания на копирование»?') == QMessageBox.Yes:
            self.win.open_page(disk_ui.TASKS_PAGE)

    # ---------- спорные файлы ----------
    def contested(self):
        if self.model is None:
            return
        fs = self.selected_folders()
        if len(fs) > 1:
            QMessageBox.information(self, TITLE, 'Выберите одну папку (или ни одной - тогда весь носитель).')
            return
        self._contested = ContestedDialog(self.win, self.disk, fs[0] if fs else '')
        self._contested.show()


def sv_log(text):
    try:
        import app
        app.log_error(text)
    except Exception:                                     # noqa: BLE001
        pass


def spec_keys(specs):
    """Что владелец подтверждает: имя, папка, направление, файлов, байт, диски (без признака «уже было»)."""
    return sorted((s['name'], str(s['folder']), s['num'], s['files'], s['bytes'], tuple(s['targets'])) for s in specs)


def tasks_check(disk, nums, toc=True):
    """Пробный расчёт заданий направлений nums по сохранённым отметкам, место по каждому диску (service.capacity),
    затем - по порядку, не параллельно - сверка оглавления носителя для новых заданий тех направлений, что помещаются.
    Направление, которому не хватает места хотя бы на одном диске, исключается целиком (ни на 45, ни на 77).
    -> dict(res, specs, new, short, cap, nums, at, toc)."""
    nums = list(nums)
    res = sv.razbor_tasks(disk, dry=True, only=nums)
    P = res['plan']
    dd = sorted(set(P.part_b) | {x for n in nums if n in P.dirs for x in P.dirs[n].disks})
    cap = sv.capacity(P.part_b, sv.disk_space(dd), sv.queued_copy(disk), disks=dd)
    short = [n for n in sv.short_directions(P.dirs, cap) if n in nums]
    specs = [s for s in res['specs'] if s['num'] not in short]
    new = [s for s in specs if not s.get('exists')]
    out = dict(res=res, specs=specs, new=new, short=short, cap=cap, nums=nums, at=time.strftime('%H:%M:%S'), toc=None)
    if toc and new:
        folders, root, zones = sv.toc_targets(P, new)
        out['toc'] = sv.toc_check(disk, folders, root, zones)
    return out


def tasks_dry(disk, nums=None):
    """Пробный расчёт без сверки оглавления (nums None - все направления)."""
    if nums is None:
        nums = list(sv.directions())
    return tasks_check(disk, nums, toc=False)


def tasks_create(disk, nums, shown):
    """Непосредственно перед созданием - снова пробный расчёт и место: если список другой, ничего не создаётся
    (показывается новый, со свежей сверкой оглавления). Затем создание только для помещающихся направлений (под замком
    таблиц, ядро) и сверка созданного с подтверждённым."""
    dry = tasks_dry(disk, nums)
    if spec_keys(dry['specs']) != shown:
        return 'changed', tasks_check(disk, nums)
    allowed = [n for n in nums if n not in dry['short']]
    if not allowed:
        return 'changed', tasks_check(disk, nums)
    if dry['new']:                       # носитель мог измениться, пока владелец читал окно: сверка ещё раз
        folders, root, zones = sv.toc_targets(dry['res']['plan'], dry['new'])
        toc = sv.toc_check(disk, folders, root, zones)
        if not toc['connected'] or toc['problems']:
            dry['toc'] = toc
            return 'changed', dry
    res = sv.razbor_tasks(disk, dry=False, only=allowed)
    return 'created', dict(res=res, differs=spec_keys(res['specs']) != shown)


def place_html(x, at=''):
    """Строка места на диске по service.capacity."""
    if x['state'] == 'short':
        return (f'<b style="color:{RED}">не помещается: нужно {gb(x["need"] + x["reserve"])} ГБ (с запасом '
                f'{gb(x["reserve"])}), свободно {gb(x["free"])} ГБ ({esc(x["letter"])})</b>')
    if x['state'] == 'unknown':
        return f'<span style="color:{ORANGE}">диск не подключён — место не проверено</span>'
    if x['state'] == 'none':
        return '' if x['free'] is None else f'свободно {gb(x["free"])} ГБ'
    return f'<span style="color:{GREEN}">помещается: свободно {gb(x["free"])} ГБ ({esc(x["letter"])})' + \
        (f' на {at}' if at else '') + '</span>'


def tasks_html(val, disk_name, note=''):
    """Окно «Подготовить задания»: сверка оглавления, таблица заданий, место по дискам, не помещающиеся направления,
    папки без диска, «копировать нечего», внимание. -> (html, новые задания)."""
    res, cap, at, toc = val['res'], val['cap'], val['at'], val.get('toc')
    P, states = res['plan'], res['states']
    specs, new, short = val['specs'], val['new'], val['short']
    h = []
    if note:
        h.append(f'<p style="color:{RED}"><b>{esc(note)}</b></p>')
    if toc is not None:
        if not toc['connected'] or toc['problems']:
            h.append(f'<p style="color:{RED}"><b>Задания не создаются: оглавление носителя не совпадает с описью'
                     + (' (или его нельзя проверить)' if not toc['connected'] else '') + '.</b></p><ul>')
            h += [f'<li>{esc(x)}</li>' for x in sv.toc_lines(toc)]
            h.append('</ul>')
            if toc['connected']:
                h.append('<p>Что делать: пересканируйте эти папки (кнопка ниже - то же окно, что в «Диски и папки»), '
                         'потом нажмите «Подготовить задания» ещё раз. Файлы прямо в корне носителя папкой не '
                         'пересканировать - для них нужно полное сканирование носителя в «Сканере дисков».</p>')
        else:
            h.append(f'<p style="color:{GREEN}">Сверка оглавления носителя ({esc(toc["letter"])}) с описью: '
                     f'расхождений нет (проверено файлов: {num(toc["checked"])}; только пути, размеры и даты).</p>')
    if P.info.get('is_target'):
        names = ', '.join(P.dirs[n].name for n in P.info['is_target'])
        h.append(f'<p style="color:{ORANGE}"><b>{esc(P.disk)} — сам диск направления «{esc(names)}»:</b> копировать с '
                 'него на остальные диски можно, перемещать на нём ничего нельзя (после копирования «Переместить» '
                 'предложено не будет).</p>')
    for n in short:
        d = P.dirs[n]
        bad = '; '.join(f'на {rz.disk_word(x)}: нужно {gb(cap[x]["need"] + cap[x]["reserve"])} ГБ с запасом, свободно '
                        f'{gb(cap[x]["free"])} ГБ' for x in d.disks if cap.get(x, {}).get('state') == 'short')
        h.append(f'<p style="color:{RED}"><b>{esc(d.num)} {esc(d.name)} не помещается</b> ({esc(bad)}) — заданий для '
                 'него не будет (ни на один его диск). Снимите галочки у части папок.</p>')
    if specs:
        h.append('<table cellpadding="3" cellspacing="0" border="1" style="border-collapse:collapse" width="100%">'
                 '<tr><th align="left">Задание</th><th>Файлов</th><th>ГБ</th><th align="left">На диски</th></tr>')
        for s in specs:
            old = ' <span style="color:gray">(уже подготовлено раньше)</span>' if s.get('exists') else ''
            h.append(f'<tr><td>{esc(s["name"])}{old}</td><td align="right">{num(s["files"])}</td>'
                     f'<td align="right">{gb(s["bytes"])}</td><td>{esc(", ".join(disk_name(d) for d in s["targets"]))}'
                     '</td></tr>')
        h.append('</table>')
        per = sorted({d for s in specs for d in s['targets']})
        if per:
            h.append('<p><b>Место на дисках</b> (всё, чего на диске ещё нет с этого носителя, плюс незапущенные задания '
                     'других носителей):</p><ul>')
            for d in per:
                x = cap.get(d)
                if x:
                    q = (f'; в очереди с других носителей {num(x["queued"][0])} заданий, {gb(x["queued"][1])} ГБ'
                         if x['queued'][0] else '')
                    h.append(f'<li>{esc(disk_name(d))}: копировать {gb(x["bytes"])} ГБ{q}; {place_html(x, at)}</li>')
            h.append('</ul>')
    elif not short:
        h.append('<p>Заданий копирования нет: копировать нечего (или у направлений нет дисков).</p>')
    nod = [g for g in states if g['state'] == rz.G_NODISK]
    if nod:
        h.append(f'<p>Без задания — направление без диска: {len(nod)} папок ('
                 f'{esc(", ".join(sorted({g["direction"] for g in nod})))}). Назначьте диск направлению.</p>')
    have = [g for g in states if g['state'] == rz.G_HAVE]
    if have:
        h.append(f'<p>Копировать нечего (всё уже есть на дисках направления): {len(have)} папок. Это ещё не разрешение '
                 'перемещать — его проверит перемещение по базе.</p>')
    chosen = set(val.get('nums') or P.dirs)                  # только диски выбранных направлений (план - полный)
    other = {x for n, d in P.dirs.items() if n not in chosen for x in d.disks} - \
        {x for n in chosen if n in P.dirs for x in P.dirs[n].disks}
    att = [x for x in rz.attention_lines(P) if not x.startswith(f'{P.disk} - диск направления')
           and not any(o in x for o in other)]
    if att:
        h.append('<p><b>Нужно внимание</b></p><ul>' + ''.join(f'<li>{esc(x)}</li>' for x in att) + '</ul>')
    blocked = toc is not None and (not toc['connected'] or toc['problems'])
    if new and not blocked:
        h.append(f'<p style="color:gray">Будет создано заданий: {len(new)} в «Запускаемые скрипты». Ничего не копируется '
                 'и не запускается; запуск - в разделе «Задания на копирование».</p>')
    elif specs and not new:
        h.append('<p>Все задания уже подготовлены раньше - новых нет.</p>')
    return ''.join(h), new


# ---------- ячейки «Копировать на диск» и «Остаётся на носителе» (этап 8) ----------

def short_place(row, disk):
    """«I: My Book» для заголовка ячейки: буква и метка тома без марки; неподключённый - «My Book (не подключён)»."""
    if not row:
        return f'{disk} (не подключён)'
    title = disk_ui.disk_title(row) or disk
    title = title.rsplit(' (', 1)[0] if title.endswith(')') else title
    return f'{row["letter"]} {title}' if row.get('letter') else f'{title} (не подключён)'


def disk_line(x, c, P, place_fn):
    """«Копировать на диск H: Бэкап… (HDD45): 12,3 ГБ — помещается: свободно …» по service.capacity."""
    head = f'Копировать на диск {esc(place_fn(x))} ({esc(x)})'
    if c['state'] == 'none' and P is not None and x == P.disk:
        return f'{head}: это сам носитель'
    if c['state'] == 'none':
        return f'{head}: копировать нечего'
    amount = f'<b>{gb(c["bytes"])} ГБ</b> <span style="color:{GRAY}">({files_word(c["files"])})</span>'
    where = where_html(c)
    q = (f'<br><span style="color:{GRAY}">&nbsp;&nbsp;в очереди на этот диск ещё {num(c["queued"][0])} незапущенных '
         f'заданий других носителей, {gb(c["queued"][1])} ГБ (учтено)</span>' if c['queued'][0] else '')
    return f'{head}: {amount} — {where}{q}'


def dest_cell_html(d, P, cap, mode, sel, exc, place_fn, split=False):
    """Ячейка «Копировать на диск …»: «Отмечено N папок · M файлов · X ГБ» (N - верхние выбранные папки; файлы и ГБ -
    «копировать» + «уже есть» направления из плана ядра, то есть с наследованием, режимом и «что копировать»), «Уже есть
    на диске», строка места по каждому диску. split=True (направление на нескольких дисках, этап 12) - только общая
    часть: «уже есть» и место - в блоках дисков (disk_block_html). -> (html, состояние 'short' / 'unknown' / 'ok')."""
    if P is None:
        return f'<span style="color:{GRAY}">Считаю…</span>', 'normal'
    cp = P.part_a.get((rz.O_COPY, d.num), (0, 0))
    hv = P.part_a.get((rz.O_HAVE, d.num), (0, 0))
    tp = P.part_a.get((rz.O_TYPE, d.num), (0, 0))
    files, size = cp[0] + hv[0], cp[1] + hv[1]
    if mode == EVERY:
        what = 'Отмечено: весь носитель'
    elif mode == EXCEPT:
        what = 'Отмечено: весь носитель' + (f', кроме {num(exc)} {plural(exc, "папки", "папок", "папок")}' if exc else '')
    else:
        what = f'Отмечено {folders_word(sel)}'
    if mode == ONLY and not sel and not files:
        h = [f'<span style="font-size:12pt"><b>Ничего не отмечено — поставьте галочки у папок</b></span><br>'
             f'<span style="color:{GRAY}">или перетащите папки сюда.</span>']
    else:
        h = [f'<span style="font-size:12pt"><b>{what} · {files_word(files)} · {gb(size)} ГБ</b></span>']
    if size and not split:
        where = 'на диске' if len(d.disks) < 2 else 'на обоих дисках' if len(d.disks) == 2 else 'на всех дисках'
        h.append(f'<br>Уже есть {where}: <b>{gb(hv[1])} ГБ ({round(100 * hv[1] / size)} %)</b> '
                 f'<span style="color:{GRAY}; font-size:8pt">{files_word(hv[0])}</span>')
    if tp[0]:
        h.append(f'<br><span style="color:{GRAY}">Не подходит по «что копировать» (останется на носителе): '
                 f'{gb(tp[1])} ГБ, {files_word(tp[0])}</span>')
    state = 'ok'
    for x in d.disks:
        c = cap.get(x) or dict(state='none', files=0, bytes=0, free=None, queued=[0, 0, 0])
        if not split:
            h.append('<br>' + disk_line(x, c, P, place_fn))
        if c['state'] == 'short':
            state = 'short'
        elif c['state'] == 'unknown' and state != 'short':
            state = 'unknown'
    return ''.join(h), state


def where_html(c):
    """Строка места на диске по service.capacity: помещается / не помещается / место не проверено."""
    if c['state'] == 'short':
        return (f'<b style="color:{RED}">не помещается: нужно {gb(c["need"] + c["reserve"])} ГБ (с запасом '
                f'{gb(c["reserve"])} ГБ), свободно {gb(c["free"])} ГБ</b>')
    if c['state'] == 'unknown':
        return f'<span style="color:{ORANGE}">место не проверено (диск не подключён)</span>'
    return f'<span style="color:{GREEN}">помещается: свободно {gb(c["free"])} ГБ</span>'


def disk_block_html(i, x, c, P, total, have, name):
    """Блок одного диска направления на нескольких дисках (этап 12, вариант А владельца): «Копия 1 — H: Бэкап фото и
    видео (HDD45)»; «Копировать K ГБ (M файлов)» - часть Б ядра для этого диска (service.capacity); «Уже есть на диске
    X ГБ (Y %)» - Model.have_on_disk от «отмечено» (total = копировать + уже есть направления); строка места.
    -> (html, состояние блока 'short' / 'unknown' / 'ok' / 'none')."""
    h = [f'<span style="font-size:11pt"><b>Копия {i} — {esc(name)} ({esc(x)})</b></span>']
    if P is not None and x == P.disk:
        h.append(f'<br><span style="color:{GRAY}">Это сам носитель — на него не копируется.</span>')
        return ''.join(h), 'none'
    if c['state'] == 'none':
        h.append('<br>Копировать нечего' + (' — всё отмеченное уже есть на этом диске' if total[0] else '') +
                 (f' <span style="color:{GREEN}">· свободно {gb(c["free"])} ГБ</span>' if c.get('free') is not None
                  else f' <span style="color:{ORANGE}">· диск не подключён</span>'))
    else:
        h.append(f'<br>Копировать <b>{gb(c["bytes"])} ГБ</b> ({files_word(c["files"])})')
    if total[1]:
        if have is None:
            h.append(f'<br><span style="color:{GRAY}">Уже есть на диске: считаю…</span>')
        else:
            h.append(f'<br>Уже есть на диске: <b>{gb(have[1])} ГБ ({round(100 * have[1] / total[1])} %)</b> '
                     f'<span style="color:{GRAY}; font-size:8pt">{files_word(have[0])}</span>')
    if c['state'] == 'none':
        return ''.join(h), 'none'
    h.append('<br>' + where_html(c))
    if c['queued'][0]:
        h.append(f'<br><span style="color:{GRAY}">в очереди на этот диск ещё {num(c["queued"][0])} незапущенных '
                 f'заданий других носителей, {gb(c["queued"][1])} ГБ (учтено)</span>')
    return ''.join(h), c['state']


STAY_NONE = (rz.O_SKIP, rz.O_UNSET, rz.O_NONE, rz.O_JUNK)     # не копируется никуда (общие категории плана)
STAY_DIR = (rz.O_TYPE, rz.O_NODISK)                            # ... и по направлениям: не по типу, диск не назначен


def stay_numbers(P):
    """Сколько остаётся на носителе (не копируется никуда) по плану ядра: (файлов, байт). Уже перенесённое и идущее в
    другие направления (копировать / уже есть) сюда не входит; каждый файл в плане ровно в одной категории."""
    n = b = 0
    for (o, _num), v in P.part_a.items():
        if o in STAY_NONE or o in STAY_DIR:
            n += v[0]
            b += v[1]
    return n, b
