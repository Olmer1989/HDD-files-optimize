"""Общее для применения модулей: запись строки файла, строка описи, замена файла базы."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import os
import time
from hb_core.consts import EV_NONE, EV_SCAN, EV_STALE
from hb_core.util import name_key


def put_row(c, disk, path, size, sha, mtime, ev, sha_exp, origin):
    c.execute('insert or replace into files(disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp) '
              'values (?,?,?,?,?,?,?,?,?)', (disk, path, size, sha, origin, name_key(path), mtime, ev, sha_exp))


def replace_file(src, dst):
    """Атомарная замена файла; несколько попыток, если его на секунду занял антивирус."""
    for attempt in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(1.5)


def scan_row(disk, p, size, mt, got, origin, keep_empty=False):
    """Строка таблицы files по записи описи и хешу сканера (та же логика, что в снимке описей)."""
    mt_s = '' if mt is None else str(mt)
    try:
        mt_i = int(mt) // 1000000000 if mt else None
    except (TypeError, ValueError):
        mt_i = None
    if not got or (not size and not keep_empty):  # пустому файлу хеш не нужен: терять нечего
        return disk, p, size or 0, None, origin, name_key(p), mt_i, EV_NONE, None
    if got[0] == size and (not got[1] or not mt_s or got[1] == mt_s):
        return disk, p, size or 0, got[2], origin, name_key(p), mt_i, EV_SCAN, None
    return disk, p, size or 0, None, origin, name_key(p), mt_i, EV_STALE, got[2]   # файл изменился после хеша
