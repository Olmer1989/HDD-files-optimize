"""Окно «Список файлов»: подписи списков и столбцов, тексты чисел, размеров, дат и итога (без Qt).

Шаг А разбивки (17.11.2026): перенесено из filelist_window.py без правки тел (docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import time
import unicodedata

import service as sv


KIND_TITLE = {'copy': 'к копированию на', 'have': 'уже есть на', 'type': 'не подходит по типу для',
              'nohash': 'без хеша', 'contested': 'спорные файлы', 'unique': 'только на этом носителе'}

# столбцы: ключ -> заголовок
C_DISK, C_FOLDER, C_NAME, C_TYPE, C_SIZE, C_DATE, C_HASH, C_WHY, C_WHERE = (
    'disk', 'folder', 'name', 'type', 'size', 'date', 'hash', 'why', 'where')

HEAD = {C_DISK: 'На каком диске', C_FOLDER: 'Где лежит', C_NAME: 'Имя', C_TYPE: 'Тип', C_SIZE: 'Размер', C_DATE: 'Дата',
        C_HASH: 'Хеш', C_WHY: 'Почему', C_WHERE: 'Где копия'}


def columns(kind):
    """Столбцы списка: общие + «На каком диске» и «Почему спорный» у спорных, «Где копия» у «уже есть»."""
    cols = [C_FOLDER, C_NAME, C_TYPE, C_SIZE, C_DATE, C_HASH]
    if kind == 'contested':
        cols = [C_DISK] + cols + [C_WHY]
    elif kind == 'have':
        cols = cols + [C_WHERE]
    else:
        cols = cols + [C_WHY]
    return cols


def head(kind, col):
    if col == C_WHY:
        return sv.WHY_HEAD.get(kind, 'Почему')
    return HEAD[col]


def norm(text):
    """Строка для поиска «содержит»: единая форма Unicode и нижний регистр; пробелы НЕ обрезаются (этап 16)."""
    return unicodedata.normalize('NFC', text or '').lower()


def size_text(b):
    if b is None:
        return '—'
    if b >= 1024 ** 3:
        return f'{b / 1024 ** 3:.2f} ГБ'.replace('.', ',')
    if b >= 1024 ** 2:
        return f'{b / 1024 ** 2:.1f} МБ'.replace('.', ',')
    if b >= 1024:
        return f'{b / 1024:.0f} КБ'
    return f'{b} Б'


def gb_text(b):
    return f'{(b or 0) / 1024 ** 3:.1f}'.replace('.', ',')


def n_text(n):
    return f'{n or 0:,}'.replace(',', ' ')


def date_ok(mt):
    return mt is not None and mt > 0


def date_text(mt):
    return time.strftime('%d.%m.%Y %H:%M', time.localtime(mt)) if date_ok(mt) else '—'


def files_word(n):
    n10, n100 = n % 10, n % 100
    w = 'файл' if n10 == 1 and n100 != 11 else 'файла' if n10 in (2, 3, 4) and n100 not in (12, 13, 14) else 'файлов'
    return f'{n_text(n)} {w}'


def totals_line(t):
    n, b, nt, _bt = t
    return (f'<b>{files_word(n)} · {gb_text(b)} ГБ</b> — ' +
            ' · '.join(f'{w} {n_text(x)}' for w, x in zip(sv.TYPE5, nt)))
