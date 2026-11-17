"""Общие постоянные «Разбора носителя» (роли дерева, задержки, цвета, стили) и мелкие помощники.

Шаг А разбивки (17.11.2026): перенесено из razbor_page.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import json
import traceback

from PySide6.QtCore import QMimeData, Qt

from hb_core import api as hb

import service as sv

from .texts_cell import EVERY, EXCEPT, ONLY


TITLE = 'Архив дисков'


SEP = '\\'


ROLE = Qt.UserRole


FILLED = Qt.UserRole + 1                                  # дети узла созданы (дерево ленивое)


TAG_ROLE = Qt.UserRole + 2                                # «Н2» - папка отмечена для другого направления


GRAY_ROLE = Qt.UserRole + 3                               # бледная галочка: выбрана вместе с родителем


MORE_ROLE = Qt.UserRole + 4                               # строка «ещё N папок — показать»: (папка-родитель, с какой)


PART_ROLE = Qt.UserRole + 5                               # показана частичная галочка (внутри есть исключения)


CHUNK = 500                                               # этап 17: дети большой папки - порциями


FLUSH_WAIT_MS = 5000                                      # перед закрытием: идущую запись ждём не дольше


C_CHECK, C_NAME, C_FILES, C_GB, C_PHOTO, C_VIDEO, C_OTHER, C_HAVE = range(8)


HEAD = ['', 'Папка', 'Файлов', 'ГБ', 'Фото', 'Видео', 'Прочее', 'Уже есть']


MODE_TEXT = {ONLY: 'Только выбранные папки', EVERY: 'Все папки', EXCEPT: 'Все, кроме выбранных'}


SEL_BG, PALE = '#c8e6c9', '#9e9e9e'                        # один зелёный фон для выбранных; бледный текст унаследованных
NONE_BG = '#fde7ea'                                       # 18.11.2026: папка с галочкой, в которой копировать нечего


HEAD_BG = '#e8f5e9'


JOURNAL = 'по журналу сканирования дисков'


INHERIT, SKIP = hb.MARK_INHERIT, hb.MARK_SKIP


DEBOUNCE_MS = 600


UNDO_MAX = 50


AUTOSAVE_MS = 0                                           # этап 16: отметка пишется сразу (правки одного щелчка - пакетом)


CONTESTED_MS = 700                                        # число спорных - после того, как выделение устоялось


CONTESTED_NOTE = ('Спорные — файлы, чью копию нельзя проверить по SHA-256: без хеша на этом носителе, тёзки без хеша '
                  '(то же имя и размер) и непроверенные копии на 45 и 77. Пересчёт хешей снимает сомнение.')


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


def folders_mime(folders):
    md = QMimeData()
    md.setData(MIME, json.dumps(list(folders), ensure_ascii=False).encode('utf-8'))
    return md


def mime_folders(md):
    try:
        return [str(x) for x in json.loads(bytes(md.data(MIME)).decode('utf-8'))] if md.hasFormat(MIME) else []
    except ValueError:
        return []


def sv_log(text):
    try:
        import app
        app.log_error(text)
    except Exception:                                     # noqa: BLE001
        pass
