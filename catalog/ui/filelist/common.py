"""Окно «Список файлов»: общие постоянные (задержки, роли дерева, ширины и индексы столбцов) и помощники фоновых задач.

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
from PySide6.QtCore import Qt

import service as sv
from ui_common import log_error

from .texts_list import C_DATE, C_DISK, C_FOLDER, C_HASH, C_NAME, C_SIZE, C_TYPE, C_WHERE, C_WHY


TITLE = 'Архив дисков'

SEP = '\\'

XLSX_MAX = 1_048_575                 # строк данных на листе Excel (плюс строка заголовка)

FILTER_MS = 300

TREE_CHUNK = 500                     # этап 17: дети папки в дереве окна - порциями

SMALL_KB = 10                        # «мелкие картинки» - фото до 10 КБ (замечание владельца: 1–10 КБ)

RELOAD_MS = 400                      # после правки отметок - перечитать список (несколько правок - одно чтение)

F_ROLE, F_MORE, F_PART = Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3   # роли дерева окна

MARK_KINDS = ('copy', 'have', 'type')

WIDTH = {C_DISK: 90, C_FOLDER: 330, C_NAME: 220, C_TYPE: 110, C_SIZE: 80, C_DATE: 115, C_HASH: 150, C_WHY: 330,
         C_WHERE: 420}

EV_ORDER = {'S': 0, 'C': 1, 'Z': 2, 'U': 3, 'X': 4}

# строка модели
R_DISK, R_FOLDER, R_NAME, R_K, R_T5, R_SIZE, R_MTIME, R_EV, R_WHY, R_WHERE, R_FLC, R_NLC = range(12)


def _safe(fn, *a):
    """('ok', ответ) / ('refused', текст отказа) / ('error', трассировка) - ответ фоновой задачи."""
    import traceback
    try:
        return 'ok', fn(*a)
    except sv.Refused as e:
        return 'refused', str(e)
    except Exception:                                             # noqa: BLE001
        text = traceback.format_exc()
        log_error(text)
        return 'error', text


def _last_line(text):
    t = (text or '').strip()
    return t.splitlines()[-1] if t else text


def _esc(x):
    import html
    return html.escape(str(x))
