"""Мелкие общие функции: вывод, ГБ, пути, классы файлов, папки «ПЕРЕНЕСЕНО»."""
# Перенесено из hashbase.py механически 15.11.2026 (разбивка на модули); логика не менялась.
import collections
import csv
import hashlib
import io
import os
import re
import unicodedata
from pathlib import Path
import build_pilot as bp
from hb_core.consts import (C_BIGMEDIA, C_EMPTY, C_JUNK, C_MEDIA, C_OTHER, COPIED_PREFIX, EXT_CLASS, GIB, JUNK_NAMES, MAIN,
                            MARK_DIR, MARK_INHERIT, MARK_SKIP, MOVED_PREFIX, SEP, TRASH_DIR)


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


def is_v3_mark(verdict):
    """Отметка разбора v3 («направление: Нх …», «не копировать», «как у родителя»). Старые команды её не видят."""
    v = (verdict or '').strip().lower()
    return v.startswith(MARK_DIR) or v == MARK_SKIP or v == MARK_INHERIT


def disk_nums(disks):
    """Номера дисков для имени папки: {HDD45, HDD77} -> «45 и 77», {HDD78} -> «78», три -> «45, 77 и 78»."""
    ts = sorted(set(disks), key=_disk_order)
    nums = [d[3:] if d.upper().startswith('HDD') and d[3:].isdigit() else d for d in ts]
    if not nums:
        return ''
    return nums[0] if len(nums) == 1 else ', '.join(nums[:-1]) + ' и ' + nums[-1]


def copied_folder(name, disks):
    """Папка на носителе после переноса (логика v3): «Скопировано на Семейный архив (45 и 77)»."""
    if not disks:
        raise ValueError('у направления нет дисков')
    return f'{COPIED_PREFIX}{name} ({disk_nums(disks)})'


def _disk_order(disk):
    m = re.match(r'^(\D*)(\d+)(.*)$', disk)
    return (m.group(1).upper(), int(m.group(2)), m.group(3)) if m else (disk.upper(), 0, '')


def moved_folder(targets):
    """Папка переноса на источнике по набору дисков, где копии подтверждены (15.11.2026, любые цели):
    «ПЕРЕНЕСЕНО → 78», «ПЕРЕНЕСЕНО → 45 и 78», «ПЕРЕНЕСЕНО → 45, 77 и 78». Номер - имя диска без «HDD»
    (Flash05 - как есть). Прежние имена сохранены: {45, 77} - «45 и 77», {45} - «только 45», {77} - «только 77».
    Метка диска в имя не входит: она меняется, а у одного набора целей папка должна быть одна."""
    ts = sorted(set(targets), key=_disk_order)
    if not ts:
        raise ValueError('нет дисков-целей')
    if ts == list(MAIN):
        return MOVED_PREFIX + '45 и 77'
    if len(ts) == 1 and ts[0] in MAIN:
        return MOVED_PREFIX + 'только ' + ts[0][3:]
    nums = [d[3:] if d.upper().startswith('HDD') and d[3:].isdigit() else d for d in ts]
    return MOVED_PREFIX + (nums[0] if len(nums) == 1 else ', '.join(nums[:-1]) + ' и ' + nums[-1])


def original_path(path):
    """Путь файла до перемещения на источнике: «ПЕРЕНЕСЕНО → только 77\\A\\1.jpg» -> «A\\1.jpg»."""
    head, _, tail = path.partition(SEP)
    return tail if tail and is_moved_dir(head) else path


def moved_rel(src, dst):
    """Строка журнала перемещения -> (путь от корня до, путь от корня после). Корень находится по папке
    «ПЕРЕНЕСЕНО → …», «МУСОР» или (логика v3) «Скопировано на …» в пути назначения, поэтому годится любая буква
    диска и тестовая папка. «Скопировано на …» принимается только здесь - в строке журнала перемещения."""
    parts = dst.split(SEP)
    for i, part in enumerate(parts):
        if is_moved_dir(part) or part.startswith(COPIED_PREFIX):
            root = SEP.join(parts[:i])
            rel = SEP.join(parts[i + 1:])
            if rel and src == root + SEP + rel:
                return rel, part + SEP + rel
    return None, None
