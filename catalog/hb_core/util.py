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
    """Папка на носителе после переноса (логика v3): «Скопировано на Семейный архив (45 и 77)»; у направления, чьё
    имя уже кончается РОВНО номерами его дисков, скобок нет: «Семейный архив 45» (диск 45) -> «Скопировано на
    Семейный архив 45» (этап 13)."""
    return COPIED_PREFIX + copied_tail(name, disks)


NUMS_TAIL = re.compile(r'^(.*?\S) (\d+(?:, \d+)* и \d+|\d+)$')      # «<основа> 45», «<основа> 45 и 77», «… 45, 77 и 80»
COPIED_NAME_MAX = 120                                             # длиннее - второй проход отказывает (путь на носителе)


def copied_tail(name, disks):
    """Имя после «Скопировано на »: «<имя> (<номера>)» или само имя, если его хвост - ровно список номеров дисков
    направления (сравнение целым списком: «Архив 2045» при диске 45 и «Семейный архив 45 и 77» при диске 77 - со
    скобками)."""
    if not disks:
        raise ValueError('у направления нет дисков')
    nums = disk_nums(disks)
    m = NUMS_TAIL.match(name or '')
    if m and m.group(2) == nums:
        return name
    return f'{name} ({nums})'


def _tail_group(tail):
    """Часть имени -> (основа, [числа]) для «<основа> <список чисел>» или (часть, None) - неделимая часть."""
    m = NUMS_TAIL.match(tail)
    if m:
        return m.group(1), re.findall(r'\d+', m.group(2))
    return tail, None


def _and_list(items):
    return items[0] if len(items) == 1 else ', '.join(items[:-1]) + ' и ' + items[-1]


def copied_join(parts):
    """Имя папки после второго (третьего…) прохода по частям - хвостам направлений (этап 13): части «<основа> <числа>»
    с одной основой сливаются, числа по возрастанию; группы - по алфавиту. «Семейный архив 45» + «Семейный архив 77» ->
    «Скопировано на Семейный архив 45 и 77» (порядок проходов не важен); разные основы - через « и », а если внутри
    группы уже есть « и » - через запятую: «Семейный архив 45 и 77, Фильмы (55)»."""
    groups, order = {}, []
    for t in parts:
        stem, nums = _tail_group(t.strip())
        key = (stem.casefold(), nums is None)
        if key not in groups:
            groups[key] = (stem, set())
            order.append(key)
        if nums:
            groups[key][1].update(nums)
    texts = []
    for key in sorted(order, key=lambda k: (k[0], k[1])):
        stem, nums = groups[key]
        texts.append(f'{stem} {_and_list(sorted(nums, key=int))}' if nums else stem)
    if len(texts) > 1 and any(' и ' in x for x in texts):
        return COPIED_PREFIX + ', '.join(texts)
    return COPIED_PREFIX + _and_list(texts)


def copied_parts(root):
    """Части имени служебной папки, если записей о них нет: «Скопировано на Семейный архив 45 и 77» -> [«Семейный
    архив 45 и 77»] (copied_join сам делит числа); составное имя «A, B» - по запятой. -> [хвосты]."""
    tail = root[len(COPIED_PREFIX):] if root.startswith(COPIED_PREFIX) else root
    return [x.strip() for x in tail.split(', ')] if ', ' in tail and not NUMS_TAIL.match(tail) else [tail]


def move_dest(folder, name, disks, parts=None):
    """Куда переедет папка разбора folder направления name с дисками disks (для показа; решает mvlist): обычная папка -
    «Скопировано на <направление>»; внутри «Скопировано на A» - «Скопировано на A и B» (этап 13; parts - части A по
    записям переносов, None - по имени)."""
    r1, _rest = copied_inside(folder or '')
    if r1 is None:
        return copied_folder(name, disks)
    return copied_join(list(parts if parts else copied_parts(r1)) + [copied_tail(name, disks)])


def copied_inside(path):
    """Путь внутри служебной папки «Скопировано на …» (первая часть пути) -> (служебная папка, остаток) или (None, path).
    Только по имени: служебная ли папка на самом деле, решает база (moved_roots)."""
    head, _, tail = (path or '').partition(SEP)
    return (head, tail) if head.startswith(COPIED_PREFIX) else (None, path)


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


def original_path(path, roots=None):
    """Путь файла до перемещения на источнике: «ПЕРЕНЕСЕНО → только 77\\A\\1.jpg» -> «A\\1.jpg».
    roots - служебные папки «Скопировано на …» этого носителя из журнала перемещения (таблица moved_roots, логика v3):
    только они снимаются; папка, которую владелец сам назвал «Скопировано на …», остаётся частью пути."""
    head, _, tail = path.partition(SEP)
    return tail if tail and (is_moved_dir(head) or (roots and head in roots)) else path


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
            # этап 13, второй проход: «<корень>\Скопировано на A\rel» -> «<корень>\Скопировано на A и B\rel»
            if rel and part.startswith(COPIED_PREFIX) and src.startswith(root + SEP + COPIED_PREFIX):
                head, _, tail = src[len(root) + 1:].partition(SEP)
                if tail == rel and head != part:
                    return head + SEP + rel, part + SEP + rel
    return None, None
