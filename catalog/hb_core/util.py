"""Мелкие общие функции: вывод, ГБ, пути, классы файлов, папки «ПЕРЕНЕСЕНО»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import csv
import hashlib
import io
import os
import unicodedata
from pathlib import Path
import build_pilot as bp
from hb_core.consts import C_BIGMEDIA, C_EMPTY, C_JUNK, C_MEDIA, C_OTHER, EXT_CLASS, GIB, JUNK_NAMES, MOVED_PREFIX, SEP, TRASH_DIR


def name_key(path):
    """Имя файла для сравнения: без пути, нижний регистр, единая форма Unicode."""
    return unicodedata.normalize('NFC', path.rsplit(SEP, 1)[-1]).lower()


def class_of(path, name_lc, size):
    if not size:
        return C_EMPTY
    if name_lc in JUNK_NAMES or name_lc.startswith('~$') or bp.CACHE_RE.search(path.lower()):
        return C_JUNK
    ext = os.path.splitext(name_lc)[1]
    if ext in EXT_CLASS:
        return EXT_CLASS[ext]
    if ext in bp.EXT_TYPE:
        return C_MEDIA if size < 1048576 else C_BIGMEDIA     # крупное фото/видео без хеша - значимое
    return C_OTHER


def out(*a):
    print(*a)


def gb(n):
    return f'{(n or 0) / GIB:.2f}'


def rel_of(full):
    """'K:\\папка\\файл' -> ('K:', 'папка\\файл')."""
    if len(full) > 2 and full[1] == ':':
        return full[:2].upper(), full[3:]
    return '', full


def prefix_cond(col, prefix):
    """SQL-условие «файл prefix или всё внутри папки prefix»."""
    if not prefix:
        return '1=1', []
    p = prefix.rstrip(SEP)
    return f'({col} = ? or ({col} >= ? and {col} < ?))', [p, p + SEP, p + ']']


def inside(path, folders):
    """Папка из списка, внутри которой лежит путь (или None)."""
    for f in folders:
        if path == f or path.startswith(f + SEP):
            return f
    return None


class Seen:
    """Когда что описано последний раз: полная опись носителя или более новый частичный скан его папки.
    Операция (журнал, ручная) действует на место, только если она НОВЕЕ этого времени."""

    def __init__(self, full):
        self.full = dict(full)
        self.parts = collections.defaultdict(list)

    def add(self, disk, folder, t):
        self.parts[disk].append((folder, t))

    def at(self, disk, path=None):
        t = self.full.get(disk, 0)
        if path is not None:
            for f, pt in self.parts.get(disk, ()):
                if pt > t and (path == f or path.startswith(f + SEP)):
                    t = pt
        return t


def parent_of(path):
    i = path.rfind(SEP)
    return path[:i] if i >= 0 else ''


def sha1(b):
    return hashlib.sha1(b).hexdigest()


def stat_sig(p):
    st = Path(p).stat()
    return st.st_size, st.st_mtime_ns


def complete_lines(data):
    """Только целые строки: журнал, который скрипт ещё пишет, учитывается до последнего перевода строки."""
    return data[:data.rfind(b'\n') + 1]


def tsv_rows(data):
    text = data.decode('utf-8-sig', errors='replace')
    return [r for r in csv.reader(io.StringIO(text, newline=''), delimiter='\t', quoting=csv.QUOTE_NONE)
            if r and any(x.strip() for x in r)]


def is_drop(verdict):
    """Единственное решение, которое разрешает не сохранять файл. Раздел и отсрочка этого не разрешают."""
    return bool(verdict) and verdict.strip().lower().startswith('не нужно')


def is_moved_dir(part):
    return part.startswith(MOVED_PREFIX) or part == TRASH_DIR


def original_path(path):
    """Путь файла до перемещения на источнике: «ПЕРЕНЕСЕНО → только 77\\A\\1.jpg» -> «A\\1.jpg»."""
    head, _, tail = path.partition(SEP)
    return tail if tail and is_moved_dir(head) else path


def moved_rel(src, dst):
    """Строка журнала перемещения -> (путь от корня до, путь от корня после). Корень находится по папке
    «ПЕРЕНЕСЕНО → …» или «МУСОР» в пути назначения, поэтому годится любая буква диска и тестовая папка."""
    parts = dst.split(SEP)
    for i, part in enumerate(parts):
        if is_moved_dir(part):
            root = SEP.join(parts[:i])
            rel = SEP.join(parts[i + 1:])
            if rel and src == root + SEP + rel:
                return rel, part + SEP + rel
    return None, None
