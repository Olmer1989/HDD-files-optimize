"""Общая база хешей: быстрые ответы на типовые вопросы без чтения дисков и без подсчётов в чате.

Одна база SQLite собирается из описей всех носителей (hashes.sqlite) и поправок:
  - журналы скриптов копирования, перемещения и корзины из «Каталог дисков\\<задача>\\Журнал*.tsv»;
  - «Каталог дисков\\_БАЗА\\ручные операции.tsv» - то, что пользователь сделал в Проводнике;
  - «Каталог дисков\\_БАЗА\\решения.tsv» - решения пользователя («не нужно», «раздел: …»).
Рабочая база пересобирается сама, если появился новый журнал или изменились эти таблицы; снимок описей
(все 11,3 млн файлов) собирается один раз и заново только при изменении самих описей.
Фото и видео сравниваются по SHA-256 - точно. Остальные файлы (без хеша) - по имени и размеру:
«копия не найдена» / «вероятная копия»; для ответа «можно удалять» вероятная копия не засчитывается.
Копией считается только ПОДТВЕРЖДЁННАЯ запись: хеш измерен сканером по самому файлу или посчитан скриптом
при копировании. Копия, у которой сверен только размер («уже есть»), и копия со слов пользователя
копией не считаются. Ответ «можно удалять» учитывает все файлы, полноту описи и не считает
сохраняемой копией то, что само удаляется.
Диски программа не читает вообще.

Команды (диск - номер HDDxx / Flashxx; папка - путь от корня диска, можно не указывать):
  py catalog\\hashbase.py missing HDD17 [папка] [--depth 2]   чего с диска нет на 45 и 77, по папкам
  py catalog\\hashbase.py only HDD17 [папка]                  что лежит только на этом диске
  py catalog\\hashbase.py cmp HDD17 "папка A" HDD61 "папка B" одинаковы ли две папки
  py catalog\\hashbase.py where HDD17 "папка или файл"        на каких ещё дисках это лежит
  py catalog\\hashbase.py candel HDD17 "папка"                можно ли удалять (есть ли всё на 45 и на 77)
  py catalog\\hashbase.py mklist HDD17 --to HDD45 HDD77 --name "K - остаток" [--folder "папка"] [--dry]
                                                             папка задачи для единого шаблона копирования
                                                             (--dry - только посчитать, ничего не создавать)
  py catalog\\hashbase.py folders HDD45 [папка] [--depth 2]   сколько занимают папка и подпапки, по типам файлов
  py catalog\\hashbase.py find Сафари [--disk HDD45]          папки со словами в пути, на всех носителях
  py catalog\\hashbase.py build                               применить новые модули и показать сводку
  py catalog\\hashbase.py stats                               что в базе и какие модули учтены
  py catalog\\hashbase.py rebuild                             самопроверка: база с нуля против базы по шагам
Модули (ТЗ v3): описи, частичные сканы («Повторное сканирование»), журналы, строки ручных операций и
исключений («_БАЗА\\исключения.tsv»). Каждая команда применяет только новые модули (таблица applied).
На экран - не больше 20 строк; полный ответ - «_БАЗА\\ответы\\последний ответ.txt», списки - там же.
"""
import argparse
import collections
import csv
import glob
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

import build_pilot as bp

SEP = '\\'
GIB = 1024 ** 3
MAIN = ('HDD45', 'HDD77')


def set_root(out_dir):
    """Где лежат база и таблицы поправок (в тестах - временная папка)."""
    global BASE_DIR, DB, SNAP, MANUAL, DECISIONS, EXCLUSIONS, ANSWERS, TEMPLATE, MOVE_TEMPLATE, TASKS
    BASE_DIR = Path(out_dir) / '_БАЗА'
    DB = BASE_DIR / 'хеши.sqlite'          # рабочая база: снимок описей + поправки
    SNAP = BASE_DIR / 'описи.sqlite'       # снимок описей; пересобирается, только если изменились сами описи
    MANUAL = BASE_DIR / 'ручные операции.tsv'
    DECISIONS = BASE_DIR / 'решения.tsv'
    EXCLUSIONS = BASE_DIR / 'исключения.tsv'   # папки, которые база не учитывает (временные копии владельца)
    ANSWERS = BASE_DIR / 'ответы'
    TEMPLATE = Path(out_dir) / '_ШАБЛОН копирования'
    MOVE_TEMPLATE = Path(out_dir) / '_ШАБЛОН перемещения'
    TASKS = Path(out_dir).parent / 'Запускаемые скрипты'   # готовые задания владельца (правило 13.11.2026)


def journal_paths():
    """Журналы скриптов: в папках задач «Каталог дисков\\<задача>» и «Запускаемые скрипты\\<задание>»."""
    res = []
    for root in (bp.OUT_DIR, TASKS):
        res += glob.glob(str(Path(root) / '*' / 'Журнал*.tsv'))
    return res


set_root(bp.OUT_DIR)
DISK_RE = re.compile(r'^(HDD|Flash)\d+', re.I)
# Старые журналы (до единого шаблона): в них нет имён дисков, только буквы на день запуска.
OLD_LOGS = {
    'Копирование на G - I и J': {'G:': 'HDD45', 'I:': 'HDD55', 'J:': 'HDD51'},
    'Дубли фильмов на I': {'I:': 'HDD55', 'J:': 'HDD51'},
    'K - На HDD77': {'K:': 'HDD59'},
}
# Журналы перемещения целых папок («Время, Результат, Папка»): диск, откуда и куда - из самого скрипта.
FOLDER_MOVES = {
    'Зойкин компьютер - ФОТОГРАФИИ': ('HDD55', 'Зойкин компьютер - перенос', 'Зойкин компьютер - перенос\\ФОТОГРАФИИ'),
}
MANUAL_HEAD = 'дата\tдействие\tдиск\tпуть\tдиск2\tпуть2\tкомментарий'
DECISION_HEAD = 'диск\tпуть\tрешение\tкомментарий'
EXCLUSION_HEAD = 'диск\tпуть\tкомментарий'
PARTIAL_DIR = 'Повторное сканирование'     # частичные сканы папок: <корень сканов>\Повторное сканирование\<носитель>\<задание>

# Степень подтверждения записи «файл лежит на носителе». Колонка sha заполнена ТОЛЬКО у подтверждённых (S и C):
# поэтому всё, что сравнивается по sha, сравнивается по измеренным хешам. У остальных ожидаемый хеш лежит в sha_exp.
EV_SCAN, EV_COPY, EV_SIZE, EV_USER, EV_STALE, EV_NONE = 'S', 'C', 'Z', 'U', 'X', 'N'
EV_NAME = {EV_SCAN: 'хеш измерен сканером по самому файлу',
           EV_COPY: 'скопировано скриптом, хеш прочитанных байтов посчитан',
           EV_SIZE: 'НЕ подтверждено: скрипт сверил только размер или увидел «уже есть»',
           EV_USER: 'НЕ подтверждено: со слов пользователя (Проводник)',
           EV_STALE: 'НЕ подтверждено: файл изменился после подсчёта хеша',
           EV_NONE: 'хеш не считался'}

# Классы файлов без хеша (по расширению). «Значимые» участвуют в поиске уникальных папок.
C_DOC, C_PROJ, C_ARCH, C_MUSIC, C_OTHER = 'документы', 'проекты монтажа и графики', 'архивы и образы', 'музыка и звук', 'прочее'
C_MEDIA, C_PROG, C_JUNK, C_EMPTY = 'мелкие картинки и медиа без хеша', 'программы и системное', 'служебные и временные', 'пустые файлы'
C_BIGMEDIA = 'фото и видео без хеша (от 1 МБ)'
SIGNIFICANT = (C_DOC, C_PROJ, C_ARCH, C_MUSIC, C_BIGMEDIA, C_OTHER)
CLASS_ORDER = SIGNIFICANT + (C_MEDIA, C_PROG, C_JUNK, C_EMPTY)
EXT_CLASS = {}
for _cls, _exts in (
        (C_DOC, 'doc docx docm dot xls xlsx xlsm ppt pptx pps ppsx pdf txt rtf odt ods odp djvu djv fb2 epub csv md wri pub vsd one'),
        (C_PROJ, 'prproj prel aep aepx veg vf psd psb cdr ai indd fla dwg dxf max blend ses sesx ncor xmp cpr als flp sfk drp'),
        (C_ARCH, 'zip rar 7z iso nrg mdf mds tar gz bz2 tgz arj img vhd vhdx'),
        (C_MUSIC, 'mp3 wav flac ogg wma aac m4a ape aiff aif mid midi ac3 mpa cda'),
        (C_PROG, 'exe dll sys msi cab inf ocx drv com bat cmd reg ini dat bin hlp chm manifest cat mui nls ax cpl scr jar '
                 'class js css php asp aspx py pyc lib obj pdb so cfg conf mst msp nfo diz htm html shtml xml json swf dbf '
                 'cdx ntx db mdb sqlite gfr gfa gfd gfo cse pak dmg plist strings nib icns ttf otf fon cur ani ico'),
        (C_JUNK, 'tmp temp lnk url bak log pek cfa pkf mpgindex mpegindex ims xmpses dmp mdmp hdmp old chk sfv md0 thm')):
    for _e in _exts.split():
        EXT_CLASS['.' + _e] = _cls
JUNK_NAMES = {'thumbs.db', 'desktop.ini', '.ds_store', 'ehthumbs.db', 'folder.jpg', 'albumartsmall.jpg', 'pagefile.sys'}


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


# ---------- сборка ----------

def find_partials():
    """Частичные сканы папок (result.json с scan_scope=partial) - и в «Повторное сканирование», и рядом с описями."""
    res, seen = [], set()
    for root in bp.SCAN_ROOTS:
        for pattern in (('*', '*', 'result.json'), (PARTIAL_DIR, '*', '*', 'result.json')):
            for result in sorted(glob.glob(str(Path(root).joinpath(*pattern)))):
                job = Path(result).parent
                if '_Архив' in str(job) or job in seen:
                    continue
                try:
                    info = json.loads(Path(result).read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if not bp.is_partial(info):
                    continue
                seen.add(job)
                inv = job / 'inventory.sqlite'
                res.append(dict(dir=job, name=job.name, disk=info.get('disk_id') or job.name.split('_')[0],
                                folders=[str(f) for f in info.get('folders') or []], status=info.get('status', '?'),
                                info=info, time=os.path.getmtime(inv) if inv.exists() else os.path.getmtime(result)))
    return sorted(res, key=lambda p: (p['time'], p['name']))


def ensure_tables():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ANSWERS.mkdir(exist_ok=True)
    if not MANUAL.exists():
        MANUAL.write_text(MANUAL_HEAD + '\n', encoding='utf-8-sig')
    if not DECISIONS.exists():
        DECISIONS.write_text(DECISION_HEAD + '\n', encoding='utf-8-sig')
    if not EXCLUSIONS.exists():
        EXCLUSIONS.write_text(EXCLUSION_HEAD + '\n', encoding='utf-8-sig')


def read_exclusions():
    """Папки, которые база не учитывает: диск -> [папка]. Строка заголовка необязательна."""
    res = collections.defaultdict(list)
    for f in read_table(EXCLUSIONS):
        f = [x.strip() for x in f] + ['', '']
        if not f[0] or f[0].lower() == 'диск' or not f[1].strip(SEP):
            continue
        res[f[0]].append(f[1].strip(SEP))
    return res


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


def read_tsv(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE) if r and any(x.strip() for x in r)]


def read_table(path):
    """Таблица владельца (ручные операции, решения, исключения): только ЦЕЛЫЕ строки. Строка, которую
    кто-то ещё дописывает (нет перевода строки), не читается: обрезанный путь «Фото» вместо «Фотоархив»
    задел бы чужую ветку."""
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError:
        return []
    return tsv_rows(data[:data.rfind(b'\n') + 1])


def serial_map(jobs):
    m = {}
    for d, j in jobs.items():
        try:
            ser = json.loads((j['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
            m[str(ser).upper()] = d
        except (OSError, ValueError, KeyError):
            pass
    return m


def log_time(log):
    """Когда шёл запуск: время из имени журнала (его ставит скрипт при старте), иначе время файла."""
    m = re.search(r'(\d{4})-(\d\d)-(\d\d) (\d\d)-(\d\d)(?:-(\d\d))?', Path(log).name)
    if m:
        try:
            return time.mktime(tuple(int(x or 0) for x in m.groups()) + (0, 0, -1))
        except (ValueError, OverflowError):
            pass
    return os.path.getmtime(log)


def put_row(c, disk, path, size, sha, mtime, ev, sha_exp, origin):
    c.execute('insert or replace into files(disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp) '
              'values (?,?,?,?,?,?,?,?,?)', (disk, path, size, sha, origin, name_key(path), mtime, ev, sha_exp))


def apply_log(c, log, jobs, serials, report, seen, rows=None, start=0):
    """Журнал скрипта -> поправки. Строка действует на диск, только если запуск был ПОЗЖЕ описи этого диска:
    иначе опись уже отражает результат (или его отсутствие), и старый журнал вернул бы исчезнувший файл.
    rows - уже прочитанные строки журнала; start - сколько строк данных уже учтено (журнал дописывается)."""
    task = Path(log).parent
    rows = read_tsv(log) if rows is None else rows
    if len(rows) < 2 + start:
        return
    head = [h.strip().lower() for h in rows[0]]
    body = rows[1 + start:]
    name = f'{task.name}\\{Path(log).name}'
    when = log_time(log)
    newer = lambda disk, path=None: when > seen.at(disk, path)     # опись диска или частичный скан папки новее
    added = removed = moved = weak = old = 0
    origin = 'журнал: ' + name
    lookup = lambda disk, rel: c.execute('select sha, size, mtime, sha_exp, ev from files where disk=? and path=?',
                                         (disk, rel)).fetchone()

    if 'цель' in head and 'куда' in head:                      # единый шаблон и ночные скрипты 12.11
        names = {}
        tv = task / 'тома.tsv'
        if tv.exists():
            for f in read_tsv(tv):
                if len(f) >= 2:
                    names[f[0].strip()] = serials.get(f[1].strip().upper())
        src_disk = next(iter(names.values()), None) if names else None
        i_t, i_r, i_s, i_src, i_dst = (head.index(x) for x in ('цель', 'результат', 'размер', 'источник', 'куда'))
        i_h = next((i for i, h in enumerate(head) if h.startswith('sha-256')), None)
        for f in body:
            if len(f) <= i_dst or not (f[i_r].startswith('скопирован') or f[i_r] == 'уже есть'):
                continue
            disk = names.get(f[i_t]) or (f[i_t] if f[i_t] in jobs and f[i_t] not in names else None)
            if not disk:
                report['warn'].add(f'{name}: цель «{f[i_t]}» не опознана по тома.tsv - строки пропущены')
                continue
            if not newer(disk, rel_of(f[i_dst])[1]):
                old += 1
                continue
            log_sha = (f[i_h].strip().lower() if i_h is not None and len(f) > i_h else '') or None
            got = lookup(src_disk, rel_of(f[i_src])[1]) if src_disk else None
            src_sha = (got[0] or got[3]) if got else None
            if f[i_r].startswith('скопирован') and log_sha:
                # скрипт сам прочитал и записал эти байты и посчитал их хеш
                put_row(c, disk, rel_of(f[i_dst])[1], int(f[i_s]), log_sha, got[2] if got else None, EV_COPY, None, origin)
            else:
                # «уже есть» или копия, сверенная только по размеру: содержимое приёмника никто не читал
                put_row(c, disk, rel_of(f[i_dst])[1], int(f[i_s]), None, got[2] if got else None, EV_SIZE,
                        log_sha or src_sha, origin)
                weak += 1
            added += 1
    elif task.name in OLD_LOGS and 'откуда' in head and 'куда' in head:
        letters = OLD_LOGS[task.name]
        i_r, i_a, i_b, i_s = (head.index(x) for x in ('результат', 'откуда', 'куда', 'размер'))
        for f in body:
            if len(f) <= max(i_a, i_b, i_s):
                continue
            (la, ra), (lb, rb) = rel_of(f[i_a]), rel_of(f[i_b])
            da, db_ = letters.get(la), letters.get(lb)
            if not da or not db_:
                continue
            got = lookup(da, ra)
            if f[i_r].startswith('скопирован'):
                if not newer(db_, rb):
                    old += 1
                    continue
                put_row(c, db_, rb, int(f[i_s]), None, got[2] if got else None, EV_SIZE,
                        (got[0] or got[3]) if got else None, origin)      # File.Copy + сверка размера
                added += 1; weak += 1
            elif f[i_r].startswith('перемещ'):
                if not newer(da, ra) or not newer(db_, rb):
                    old += 1
                    continue
                if got:                                                   # тот же файл на том же диске
                    c.execute('delete from files where disk=? and path=?', (da, ra))
                    put_row(c, db_, rb, got[1], got[0] if da == db_ else None, got[2],
                            got[4] if da == db_ else EV_SIZE, got[3] if da == db_ else (got[0] or got[3]), origin)
                    moved += 1
    elif task.name in OLD_LOGS and 'в корзину' in head:
        letters = OLD_LOGS[task.name]
        i_r, i_a = head.index('результат'), head.index('в корзину')
        for f in body:
            if len(f) > i_a and f[i_r].startswith('в корзин'):
                l, r = rel_of(f[i_a])
                if l in letters:
                    if not newer(letters[l], r):
                        old += 1
                        continue
                    removed += c.execute('delete from files where disk=? and path=?', (letters[l], r)).rowcount
    elif head[:6] == ['время', 'результат', 'размер', 'sha-256', 'откуда', 'куда']:    # шаблон «Переместить на источнике»
        vols = read_tsv(task / 'тома.tsv') if (task / 'тома.tsv').exists() else []
        disk = serials.get(vols[0][1].strip().upper()) if vols and len(vols[0]) >= 2 else None
        if not disk:
            report['warn'].add(f'{name}: диск-источник не опознан по тома.tsv - журнал перемещения не учтён')
            return
        for f in body:
            if len(f) < 6 or f[1] not in ('перемещён', 'уже перемещён'):
                continue
            ra, rb = moved_rel(f[4], f[5])
            if ra is None:
                continue
            if not newer(disk, ra) or not newer(disk, rb):
                old += 1
                continue
            got = lookup(disk, ra)
            if not got:
                continue                                # уже учтено (повторный запуск) или файла нет в базе
            c.execute('delete from files where disk=? and path=?', (disk, ra))
            put_row(c, disk, rb, got[1], got[0], got[2], got[4], got[3], origin)     # тот же файл на том же диске
            moved += 1
    elif task.name in FOLDER_MOVES and head[:3] == ['время', 'результат', 'папка']:
        disk, src_base, dst_base = FOLDER_MOVES[task.name]
        for f in body:
            if len(f) < 3 or not f[1].startswith('перемещ'):
                continue
            old_path = src_base + SEP + f[2]
            if not newer(disk, old_path) or not newer(disk, dst_base + SEP + f[2]):
                old += 1
                continue
            cond, args = prefix_cond('path', old_path)
            moved += c.execute(f'update files set path = ? || substr(path, ?), origin = ? where disk=? and {cond}',
                               [dst_base + SEP + f[2], len(old_path) + 1, origin, disk] + args).rowcount
    else:
        if name not in report['skipped']:
            report['skipped'].append(name)
        return
    k = report['logs'].setdefault(name, [0, 0, 0, 0])
    for i, v in enumerate((added, moved, removed, weak)):
        k[i] += v
    if old:
        report['old_logs'][name] = report['old_logs'].get(name, 0) + old


def manual_time(date):
    """'12.11.2026' -> конец этого дня; непонятная дата -> сейчас (операция считается свежей)."""
    try:
        d, m, y = (int(x) for x in date.split('.')[:3])
        return time.mktime((y, m, d, 23, 59, 59, 0, 0, -1))
    except (ValueError, OverflowError):
        return time.time()


def manual_rows():
    """Строки таблицы ручных операций: (номер строки в файле, поля)."""
    return [(line_no, [x.strip() for x in f] + [''] * 7) for line_no, f in enumerate(read_table(MANUAL)[1:], 2)]


def apply_manual_row(c, line_no, f, report, seen):
    """Одна ручная операция (то, что пользователь сделал в Проводнике). Копия «со слов» никогда не становится
    подтверждённой. Операция не действует на место, которое ПОЗЖЕ описал частичный скан: скан и есть итог."""
    f = [x.strip() for x in f] + [''] * 7
    date, act, disk, path, disk2, path2 = f[:6]
    act = act.lower()
    when = manual_time(date)
    origin = f'вручную {date}, строка {line_no}'
    cond, args = prefix_cond('path', path)
    label = f'{date} {act} {disk}:{path}' + (f' -> {disk2}:{path2}' if disk2 else '')
    late = 0
    if act.startswith('удал'):
        if when < seen.at(disk):
            report['old'].append(label + ' - не применено: опись диска новее')
            return False
        paths = [r[0] for r in c.execute(f'select path from files where disk=? and {cond}', [disk] + args)]
        keep = [p for p in paths if when < seen.at(disk, p)]
        late = len(keep)
        if late:
            keep = set(keep)
            paths = [p for p in paths if p not in keep]
        c.executemany('delete from files where disk=? and path=?', ((disk, p) for p in paths))
        k = len(paths)
    elif act.startswith(('скопир', 'перемещ')):
        move = act.startswith('перемещ')
        if when < seen.at(disk2) or (move and when < seen.at(disk)):
            report['old'].append(label + ' - не применено: опись диска новее')
            return False
        rows = c.execute(f'select path, size, sha, mtime, ev, sha_exp from files where disk=? and {cond}',
                         [disk] + args).fetchall()
        base = path.rstrip(SEP)
        todo = []
        for p, size, sha, mt, ev, exp in rows:
            tail = p[len(base):].lstrip(SEP)
            newp = (path2.rstrip(SEP) + (SEP + tail if tail else '')) if tail or path2 else p
            if when < seen.at(disk2, newp) or (move and when < seen.at(disk, p)):
                late += 1                         # это место позже описал частичный скан
                continue
            todo.append((p, newp, size, sha, mt, ev, exp))
        if move:                                  # сначала убрать ровно эти записи, потом создать новые
            c.executemany('delete from files where disk=? and path=?', ((disk, r[0]) for r in todo))
        for p, newp, size, sha, mt, ev, exp in todo:
            if move and disk2 == disk:            # тот же файл на том же диске: подтверждение не меняется
                put_row(c, disk2, newp, size, sha, mt, ev, exp, origin)
            else:                                 # содержимое копии никто не проверял
                put_row(c, disk2, newp, size, None, mt, EV_USER, sha or exp, origin)
        k = len(todo)
    else:
        report['warn'].add(f'ручные операции: непонятное действие «{act}»')
        return False
    report['manual'].append(label + f' - {k} файлов')
    if late:
        report['old'].append(label + f' - {late} файлов не применено: это место позже описал частичный скан')
    return True


def apply_manual(c, report, seen):
    return sum(apply_manual_row(c, n, f, report, seen) for n, f in manual_rows())


def event_stream():
    """Все поправки к описям одним потоком по времени: (время, порядок, имя, вид, данные).
    Журнал скрипта - время запуска; частичный скан - время его описи; ручная операция - конец её дня."""
    ev = [(log_time(p), 0, p, 'log', p) for p in journal_paths()]
    ev += [(pj['time'], 1, str(pj['dir']), 'partial', pj) for pj in find_partials()]
    ev += [(manual_time(f[0]), 2, f'{n:09d}', 'manual', (n, f)) for n, f in manual_rows()]
    return sorted(ev, key=lambda e: e[:3])


def apply_event(c, ev, jobs, serials, report, seen, excl):
    kind, data = ev[3], ev[4]
    if kind == 'log':
        apply_log(c, data, jobs, serials, report, seen)
    elif kind == 'partial':
        apply_partial(c, data, seen, excl, report)
    else:
        apply_manual_row(c, data[0], data[1], report, seen)


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


def load_disk(c, d, j):
    """Полная опись одного носителя -> строки files, issues и disks. Возвращает (файлов, с хешем, с устаревшим хешем)."""
    hp, ip = j['dir'] / 'hashes.sqlite', j['dir'] / 'inventory.sqlite'
    hashes = {}
    if hp.exists():
        with bp.ro(hp) as h:
            for p, s, m, x, st in h.execute('select path, size, mtime_ns, lower(sha256), status from hashes'):
                if st == 'verified' and x:
                    hashes[p] = (s, '' if m is None else str(m), x)
                else:
                    c.execute('insert into issues values (?,?,?,?)', (d, p, 'файл не прочитан при подсчёте хеша', st or ''))
    have_inv = ip.exists()
    cnt = collections.Counter()

    def rows():
        if not have_inv:                              # описи нет вовсе: есть только таблица хешей
            for p, (size, m, x) in hashes.items():
                cnt[EV_SCAN] += 1
                yield d, p, size or 0, x, 'опись', name_key(p), None, EV_SCAN, None
            return
        with bp.ro(ip) as inv:
            for p, size, mt in inv.execute('select path, size, mtime_ns from files order by path'):
                r = scan_row(d, p, size, mt, hashes.get(p), 'опись', keep_empty=True)
                cnt[r[7]] += 1
                yield r
        # хеш, для которого в описи нет файла, не переносится: по описи такого файла на диске нет

    c.executemany('insert or replace into files values (?,?,?,?,?,?,?,?,?)', rows())
    total = sum(cnt.values())                       # не total_changes: при сборке по шагам его увеличивают триггеры
    if have_inv:
        try:
            with bp.ro(ip) as inv:
                for p, op, msg in inv.execute('select path, operation, message from errors'):
                    c.execute('insert into issues values (?,?,?,?)',
                              (d, rel_of(p or '')[1].rstrip(SEP), 'папка или файл не прочитаны при описи', f'{op}: {msg}'[:300]))
        except sqlite3.Error:
            pass
    scanned = os.path.getmtime(ip) if have_inv else j.get('mtime', 0)
    c.execute('insert or replace into disks values (?,?,?,?,?,?)',
              (d, j['label'], cnt[EV_SCAN], total, j.get('status') or '?', scanned))
    return total, cnt[EV_SCAN], cnt[EV_STALE]


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


def apply_partial(c, pj, seen, excl, report):
    """Частичный скан папок: строки носителя ВНУТРИ его папок заменяются строками скана (степень S),
    строки вне этих папок не трогаются. Папки из исключений пропускаются. Итог - в report['partial']."""
    disk, label = pj['disk'], f'частичный скан {pj["disk"]} ({pj["name"]})'
    info = pj['info']
    if not str(pj['status']).startswith('complete'):
        report['warn'].add(f'{label}: состояние «{pj["status"]}» - скан не принят')
        return False
    if disk not in seen.full:
        report['warn'].add(f'{label}: полной описи этого носителя нет в базе - скан не принят')
        return False
    if pj['time'] <= seen.full[disk]:
        report['old'].append(f'{label}: не применён - полная опись носителя новее')
        return False
    folders = sorted({f.strip().strip(SEP) for f in pj['folders'] if f.strip().strip(SEP)}, key=lambda f: -len(f))
    if not folders:
        report['warn'].add(f'{label}: в result.json нет списка папок - скан не принят')
        return False
    hp, ip = pj['dir'] / 'hashes.sqlite', pj['dir'] / 'inventory.sqlite'
    hashes, unread = {}, 0
    if hp.exists():
        with bp.ro(hp) as h:
            for p, s, m, x, st in h.execute('select path, size, mtime_ns, lower(sha256), status from hashes'):
                if st == 'verified' and x:
                    hashes[p] = (s, '' if m is None else str(m), x)
                else:
                    unread += 1
    with bp.ro(ip) as inv:
        scan = inv.execute('select path, size, mtime_ns from files').fetchall()
        try:
            errors = inv.execute('select path, operation, message from errors').fetchall()
        except sqlite3.Error:
            errors = []
    ex = excl.get(disk, [])
    origin = f'частичный скан: {pj["name"]}'
    st = {f: collections.Counter() for f in folders}
    prev = {}
    for f in folders:
        cond, args = prefix_cond('path', f)
        for p, sha, exp, ev, size in c.execute(f'select path, sha, sha_exp, ev, size from files where disk=? and {cond}',
                                               [disk] + args):
            prev[p] = (sha or exp, ev, size or 0)
        c.execute(f'delete from files where disk=? and {cond}', [disk] + args)
        c.execute(f'delete from issues where disk=? and {cond}', [disk] + args)
        seen.add(disk, f, pj['time'])
        c.execute('insert or replace into scan_folders values (?,?,?)', (disk, f, pj['time']))
    rows, outside = [], 0
    for p, size, mt in scan:
        f = inside(p, folders)
        if f is None:
            outside += 1
            continue
        k = st[f]
        k['файлов'] += 1; k['байт'] += size or 0
        r = scan_row(disk, p, size, mt, hashes.get(p), origin)
        h = r[3] or r[8]
        if inside(p, ex):
            k['исключено'] += 1; k['исключено байт'] += size or 0
            c.execute('insert or replace into excluded values (?,?,?,?,?,?)', (disk, p, size or 0, h, r[5], origin))
            continue
        rows.append(r)
        old = prev.pop(p, None)
        if old is None:
            k['новые'] += 1; k['новые байт'] += size or 0
        elif old[0] and h and old[0] != h:
            k['хеш не совпал'] += 1
        elif r[7] == EV_SCAN:
            k['было ' + (old[1] or EV_NONE)] += 1
    c.executemany('insert or replace into files values (?,?,?,?,?,?,?,?,?)', rows)
    for p, (h, ev, size) in prev.items():                        # было в базе, в скане нет
        k = st[inside(p, folders)]
        if inside(p, ex):
            k['убрано по исключениям'] += 1
        else:
            k['исчезли'] += 1; k['исчезли байт'] += size
    for p, op, msg in errors:
        c.execute('insert into issues values (?,?,?,?)', (disk, rel_of(p or '')[1].rstrip(SEP),
                                                          'не прочитано при частичном скане', f'{op}: {msg}'[:300]))
    lines = []
    for f in sorted(folders):
        k = st[f]
        conf = ', '.join(f'{e} {k["было " + e]}' for e in (EV_SIZE, EV_COPY, EV_USER, EV_STALE, EV_NONE) if k['было ' + e])
        lines.append(f'{disk}\\{f}: в скане {k["файлов"]} файлов ({gb(k["байт"])} ГБ); стало S: {conf or "0"}'
                     + (f', уже было S {k["было S"]}' if k['было S'] else '')
                     + f'; новые {k["новые"]} ({gb(k["новые байт"])} ГБ); исчезли из базы {k["исчезли"]}'
                     + f'; хеш не совпал {k["хеш не совпал"]}'
                     + (f'; пропущено по исключениям {k["исключено"]} ({gb(k["исключено байт"])} ГБ)' if k['исключено'] else '')
                     + (f'; старых записей убрано по исключениям {k["убрано по исключениям"]}'
                        if k['убрано по исключениям'] else ''))
    report.setdefault('partial', []).extend(lines)
    report.setdefault('partial_stats', {})[pj['name']] = {f: dict(st[f]) for f in folders}
    if outside:
        report['warn'].add(f'{label}: {outside} файлов вне перечисленных папок - не приняты')
    if unread or info.get('damaged_files') or info.get('unread_files') or errors:
        report['warn'].add(f'{label}: не прочитано файлов {unread or info.get("unread_files") or 0}, '
                           f'повреждено {info.get("damaged_files") or 0}, ошибок описи {len(errors)}')
    return True


EXCLUDED_DDL = ('create table if not exists excluded(disk text not null, path text not null, size integer, sha text, '
                'name_lc text, origin text, primary key(disk, path)) without rowid')
NOHASH_VIDEO = ('.m2t', '.dv')    # видео, которому сканер полных описей хеш не считает: копию ищем и по имени и размеру


def apply_exclusions(c, excl, report):
    """Папки из исключений не учитываются вовсе: строки внутри них убираются, откуда бы они ни пришли
    (что убрано - запоминается в таблице excluded, чтобы проверить, не единственные ли это экземпляры)."""
    for disk, folders in excl.items():
        for f in folders:
            cond, args = prefix_cond('path', f)
            c.execute(f'insert or replace into excluded select disk, path, size, coalesce(sha, sha_exp), name_lc, origin '
                      f'from files where disk=? and {cond}', [disk] + args)
            n = c.execute(f'delete from files where disk=? and {cond}', [disk] + args).rowcount
            if n:
                report.setdefault('excluded', []).append(f'{disk}\\{f}: убрано записей {n}')


def excluded_unique(c, report):
    """Фото и видео из исключённых папок, которых нет больше ни на одном носителе в базе (по SHA-256): их нельзя
    потерять при ручном переносе. Список - в «ответы», в отчёт сборки - одна строка на носитель."""
    report['unique'] = {}
    by_disk = collections.defaultdict(list)
    q = '''select e.disk, e.path, e.size, e.sha,
                  exists(select 1 from files g where g.name_lc=e.name_lc and g.size=e.size)
           from excluded e where e.sha is not null
             and not exists(select 1 from files g where g.sha=e.sha)
             and not exists(select 1 from files g where g.sha_exp=e.sha)'''
    for disk, p, size, sha, probable in c.execute(q):
        ext = os.path.splitext(p)[1].lower()
        if ext in bp.EXT_TYPE or ext in NOHASH_VIDEO:
            kind = bp.file_type(p, size or 0) or 'Видео'
            by_disk[disk].append((p, size, kind, 'есть файл с тем же именем и размером' if probable else '', sha))
    for disk, rr in sorted(by_disk.items()):
        path = save(f'исключения - больше нигде нет - {disk}', ('путь', 'размер', 'тип', 'вероятная копия', 'SHA-256'),
                    sorted(rr))
        small = sum(1 for r in rr if r[2] == bp.T_SMALL)
        nohash = sum(1 for r in rr if os.path.splitext(r[0])[1].lower() in NOHASH_VIDEO)
        report['unique'][disk] = (f'в исключённых папках {disk} {len(rr)} фото и видео ({gb(sum(r[1] for r in rr))} ГБ) нет больше '
                           f'ни на одном носителе в базе (из них мелких картинок {small}; видео .m2t/.dv, которым на других '
                           f'дисках хеш не считали, {nohash}) - не потерять при ручном переносе: {path}')


# ---------- сборщик: модули -> одна рабочая база ----------
# Модуль - неизменяемый первоисточник: полная опись носителя, частичный скан папок, журнал скрипта, строка таблицы
# ручных операций, строка таблицы исключений. Таблица applied помнит, какие модули учтены. При каждой команде
# применяются только новые модули (и дописанные строки журналов). Изменился уже учтённый модуль - база
# собирается заново целиком. Команда rebuild собирает базу с нуля и сверяет её с собранной по шагам.

BUILD_VERSION = 5          # правила сборки и устройство базы; изменились - база пересобирается целиком
STATE_KINDS = ('журнал', 'ручная операция', 'частичный скан')     # события, упорядоченные по времени
KIND_ORDER = {'опись': 0, 'исключение': 1, 'журнал': 2, 'частичный скан': 3, 'ручная операция': 4}

SCHEMA = [
    'create table if not exists files(disk text not null, path text not null, size integer, sha text, origin text, '
    'name_lc text, mtime integer, ev text, sha_exp text, primary key(disk, path)) without rowid',
    'create table if not exists meta(key text primary key, value text)',
    'create table if not exists disks(disk text primary key, label text, hashed integer, total integer, status text, scanned real)',
    'create table if not exists issues(disk text, path text, kind text, note text)',
    'create table if not exists applied(module text primary key, kind text, time real, size integer, mtime_ns integer, '
    'checksum text, rows integer, applied_at text, changed integer)',
    'create table if not exists scan_folders(disk text not null, folder text not null, time real, primary key(disk, folder))',
    EXCLUDED_DDL,
]
INDEXES = [
    'create index if not exists files_sha on files(sha, disk) where sha is not null',
    'create index if not exists files_exp on files(sha_exp, disk) where sha_exp is not null',
    'create index if not exists files_name on files(name_lc, size, disk)',
    'create index if not exists issues_disk on issues(disk)',
]
DIGEST_TABLES = {          # что сравнивается при самопроверке rebuild (служебные applied и meta - нет)
    'files': 'disk, path, size, sha, origin, name_lc, mtime, ev, sha_exp',
    'disks': 'disk, label, hashed, total, status, scanned',
    'issues': 'disk, path, kind, note',
    'excluded': 'disk, path, size, sha, name_lc, origin',
    'scan_folders': 'disk, folder, time',
}


# ---------- готовые таблицы для быстрых ответов: presence (по хешу) и folders (по папкам) ----------
# presence: есть ли хеш на 45 и на 77 и с какой степенью, на скольких носителях подтверждён.
# folders: суммы по каждой папке каждого носителя (вместе с подпапками) с разбивкой по типам файлов.
# При сборке по шагам обе таблицы правятся только для затронутых строк (их отмечают временные триггеры).

EV_RANK = "(case ev when 'S' then '1S' when 'C' then '2C' when 'Z' then '3Z' when 'U' then '4U' when 'X' then '5X' else '6' || ev end)"
FOLDER_TYPES = ('фото', 'видео', 'тексты', 'прочие', 'мусор')
F_PHOTO, F_VIDEO, F_TEXT, F_OTHER, F_JUNK = range(5)
DERIVED_SCHEMA = [
    'create table if not exists presence(sha text primary key, e45 text, e77 text, ndisks integer, ncopies integer) without rowid',
    'create table if not exists folders(disk text not null, folder text not null, depth integer, folder_lc text, '
    'files integer, bytes integer, ' + ', '.join(f'n{i} integer, b{i} integer' for i in range(5)) +
    ', primary key(disk, folder)) without rowid',
]
TRIGGERS = [
    'create temp table if not exists touched(sha text primary key) without rowid',
    'create temp table if not exists delta(disk text, path text, size integer, name_lc text, sign integer)',
    '''create temp trigger if not exists t_files_ins after insert on files begin
         insert or ignore into touched select new.sha where new.sha is not null;
         insert or ignore into touched select new.sha_exp where new.sha_exp is not null;
         insert into delta values (new.disk, new.path, new.size, new.name_lc, 1); end''',
    '''create temp trigger if not exists t_files_del after delete on files begin
         insert or ignore into touched select old.sha where old.sha is not null;
         insert or ignore into touched select old.sha_exp where old.sha_exp is not null;
         insert into delta values (old.disk, old.path, old.size, old.name_lc, -1); end''',
    '''create temp trigger if not exists t_files_upd after update on files begin
         insert or ignore into touched select old.sha where old.sha is not null;
         insert or ignore into touched select old.sha_exp where old.sha_exp is not null;
         insert or ignore into touched select new.sha where new.sha is not null;
         insert or ignore into touched select new.sha_exp where new.sha_exp is not null;
         insert into delta values (old.disk, old.path, old.size, old.name_lc, -1);
         insert into delta values (new.disk, new.path, new.size, new.name_lc, 1); end''',
]
DIGEST_TABLES.update({
    'presence': 'sha, e45, e77, ndisks, ncopies',
    'folders': 'disk, folder, depth, folder_lc, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5)),
})


def presence_sql(where_sha, where_exp):
    return f'''insert into presence
        select h, substr(min(case when disk='{MAIN[0]}' then r end), 2), substr(min(case when disk='{MAIN[1]}' then r end), 2),
               count(distinct case when conf=1 then disk end), sum(conf)
        from (select sha h, disk, {EV_RANK} r, 1 conf from files where sha is not null {where_sha}
              union all
              select sha_exp, disk, {EV_RANK}, 0 from files where sha_exp is not null {where_exp})
        group by h'''


def presence_full(c):
    c.execute('delete from presence')
    c.execute(presence_sql('', ''))


def presence_touched(c):
    c.execute('delete from presence where sha in (select sha from temp.touched)')
    c.execute(presence_sql('and sha in (select sha from temp.touched)', 'and sha_exp in (select sha from temp.touched)'))
    c.execute('delete from temp.touched')


def folder_type(path, name_lc, size):
    if not size:
        return F_OTHER
    if class_of(path, name_lc or '', size) == C_JUNK:
        return F_JUNK
    t = bp.EXT_TYPE.get(os.path.splitext(name_lc or '')[1])
    if t:
        return F_VIDEO if t == 'Видео' else F_PHOTO
    return F_TEXT if EXT_CLASS.get(os.path.splitext(name_lc or '')[1]) == C_DOC else F_OTHER


def parent_of(path):
    i = path.rfind(SEP)
    return path[:i] if i >= 0 else ''


def roll_up(agg):
    """Суммы по папкам (прямо в ней) -> суммы вместе со всеми подпапками, для всех папок-предков до корня ''."""
    total = {f: list(v) for f, v in agg.items()}
    for f in list(total):                                   # недостающие промежуточные папки
        while f:
            f = parent_of(f)
            if f in total:
                break
            total[f] = [0] * 12
    for f in sorted(total, key=lambda x: -(x.count(SEP) + 1 if x else 0)):
        if f:
            p, v = total[parent_of(f)], total[f]
            for i in range(12):
                p[i] += v[i]
    return total


def add_file(agg, path, size, name_lc, sign=1):
    a = agg.get(parent_of(path))
    if a is None:
        a = agg[parent_of(path)] = [0] * 12
    k = folder_type(path, name_lc, size)
    size = (size or 0) * sign
    a[0] += sign; a[1] += size; a[2 + 2 * k] += sign; a[3 + 2 * k] += size


def folder_row(d, f, v):
    return (d, f, f.count(SEP) + 1 if f else 0, f.lower(), *v)


def folders_full(c, disks=None):
    disks = disks or [r[0] for r in c.execute('select distinct disk from files')]
    for d in disks:
        c.execute('delete from folders where disk=?', (d,))
        agg = {}
        for path, size, nm in c.execute('select path, size, name_lc from files where disk=?', (d,)):
            add_file(agg, path, size, nm)
        c.executemany(f'insert into folders values ({",".join("?" * 16)})',
                      (folder_row(d, f, v) for f, v in roll_up(agg).items()))


def folders_delta(c):
    """Изменения строк files (из триггеров) -> поправки сумм по папкам."""
    by_disk = collections.defaultdict(dict)
    for d, path, size, nm, sign in c.execute('select disk, path, size, name_lc, sign from temp.delta'):
        add_file(by_disk[d], path, size, nm, sign)
    c.execute('delete from temp.delta')
    upd = ', '.join(f'{x}={x}+excluded.{x}' for x in ['files', 'bytes'] + [f'{p}{i}' for i in range(5) for p in 'nb'])
    for d, agg in by_disk.items():
        rows = [folder_row(d, f, v) for f, v in roll_up(agg).items() if any(v)]
        c.executemany(f'insert into folders values ({",".join("?" * 16)}) on conflict(disk, folder) do update set {upd}', rows)
    c.execute('delete from folders where files <= 0')


def derived_start(c):
    """Включить учёт затронутых строк перед сборкой по шагам."""
    c.execute('pragma recursive_triggers = on')       # «insert or replace» удаляет старую строку - это тоже изменение
    for q in DERIVED_SCHEMA + TRIGGERS:
        c.execute(q)


def derived_finish(c):
    presence_touched(c)
    folders_delta(c)


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


def discover(jobs):
    """Все модули - первоисточники базы: ключ -> dict(kind, time, size, mtime_ns, checksum, data)."""
    mods = {}
    for d, j in jobs.items():
        sig = [str(j['dir'])]
        for fn in ('result.json', 'inventory.sqlite', 'hashes.sqlite'):
            p = j['dir'] / fn
            if p.exists():
                sig.append([fn, *stat_sig(p)])
        ip = j['dir'] / 'inventory.sqlite'
        size, mt = stat_sig(ip) if ip.exists() else (0, 0)
        mods[f'опись: {d}'] = dict(kind='опись', time=os.path.getmtime(ip) if ip.exists() else j.get('mtime', 0),
                                   size=size, mtime_ns=mt, checksum=sha1(json.dumps(sig, ensure_ascii=False).encode()),
                                   data=(d, j))
    for pj in find_partials():
        sig = [str(pj['dir'])] + [[fn, *stat_sig(pj['dir'] / fn)] for fn in ('result.json', 'inventory.sqlite', 'hashes.sqlite')
                                  if (pj['dir'] / fn).exists()]
        mods[f'частичный скан: {pj["dir"].parent.name}\\{pj["name"]}'] = dict(
            kind='частичный скан', time=pj['time'], size=0, mtime_ns=0,
            checksum=sha1(json.dumps(sig, ensure_ascii=False).encode()), data=pj)
    for p in journal_paths():
        size, mt = stat_sig(p)
        mods[f'журнал: {Path(p).parent.name}\\{Path(p).name}'] = dict(kind='журнал', time=log_time(p), size=size,
                                                                      mtime_ns=mt, checksum=None, data=p)
    for n, f in manual_rows():
        mods[f'ручная операция: строка {n:05d}'] = dict(kind='ручная операция', time=manual_time(f[0]), size=0, mtime_ns=0,
                                                       checksum=sha1('\t'.join(f).strip().encode()), data=(n, f))
    for n, f in enumerate(read_table(EXCLUSIONS), 1):
        f = [x.strip() for x in f] + ['', '']
        if f[0] and f[0].lower() != 'диск' and f[1].strip(SEP):
            mods[f'исключение: строка {n:05d}'] = dict(kind='исключение', time=0, size=0, mtime_ns=0,
                                                       checksum=sha1('\t'.join(f).strip().encode()), data=(f[0], f[1].strip(SEP)))
    return mods


def read_log(m, done=None):
    """Журнал: целые строки, их размер в байтах, контрольная сумма. done=(размер, сумма) уже учтённой части:
    если журнал только дописан - возвращает и число уже учтённых строк, иначе None (журнал изменён)."""
    data = complete_lines(Path(m['data']).read_bytes())
    m.update(size=len(data), checksum=sha1(data))
    rows = tsv_rows(data)
    m['rows'] = rows
    if done is None:
        return 0
    size, checksum, n = done
    if len(data) < size or sha1(data[:size]) != checksum:
        return None
    return n


def plan(c, mods):
    """Что применить: (список новых модулей, None) или (None, причина полной пересборки)."""
    applied = {r[0]: r for r in c.execute('select module, kind, time, size, mtime_ns, checksum, rows from applied')}
    gone = [k for k in applied if k not in mods]
    if gone:
        return None, f'пропал уже учтённый модуль «{gone[0]}»'
    last = c.execute(f"select max(time) from applied where kind in ({','.join('?' * len(STATE_KINDS))})",
                     STATE_KINDS).fetchone()[0] or 0
    todo = []
    for key, m in mods.items():
        a = applied.get(key)
        k = m['kind']
        if k == 'журнал':
            if a and (a[3], a[4]) == (m['size'], m['mtime_ns']):
                continue
            start = read_log(m, (a[3], a[5], a[6]) if a else None)
            if start is None:
                return None, f'изменился уже учтённый журнал «{key}» (не дописан, а исправлен)'
            m['start'] = start
            todo.append((key, m))
        elif a:
            if a[5] != m['checksum']:
                if k == 'опись' and m['time'] >= last:
                    todo.append((key, m))                # новая опись носителя: заменить только его строки
                    continue
                return None, f'изменился уже учтённый модуль «{key}»'
        elif k in ('опись', 'частичный скан') and m['time'] < last:
            return None, f'новый модуль «{key}» старше уже учтённых поправок'
        else:
            todo.append((key, m))
    return sorted(todo, key=lambda km: (km[1]['time'], KIND_ORDER[km[1]['kind']], km[0])), None


def load_report(c):
    row = c.execute("select value from meta where key='report'").fetchone()
    rep = json.loads(row[0]) if row else {}
    for k, v in (('logs', {}), ('old_logs', {}), ('skipped', []), ('manual', []), ('old', []), ('warn', []),
                 ('partial', []), ('excluded', []), ('unique', {})):
        rep.setdefault(k, v)
    rep['warn'] = set(rep['warn'])
    return rep


def save_report(c, rep):
    rep = dict(rep, warn=sorted(rep['warn']))
    c.execute('insert or replace into meta values (?,?)', ('report', json.dumps(rep, ensure_ascii=False)))
    c.execute('insert or replace into meta values (?,?)', ('built', time.strftime('%d.%m.%Y %H:%M')))


def load_seen(c):
    seen = Seen(c.execute('select disk, scanned from disks'))
    for d, f, t in c.execute('select disk, folder, time from scan_folders'):
        seen.add(d, f, t)
    return seen


def replace_disk(c, d, j, seen):
    """Новая полная опись носителя: строки только этого носителя удаляются и вставляются заново.
    Триггеры на сотни тысяч строк медленны, поэтому здесь они выключаются: суммы по папкам этого носителя
    считаются заново целиком, а в presence пересчитываются только его хеши (старые и новые)."""
    fast = bool(c.execute("select 1 from sqlite_temp_master where type='trigger' and name='t_files_ins'").fetchone())
    mark = ('insert or ignore into temp.touched select sha from files where disk=? and sha is not null',
            'insert or ignore into temp.touched select sha_exp from files where disk=? and sha_exp is not null')
    if fast:
        for name in ('t_files_ins', 't_files_del', 't_files_upd'):
            c.execute(f'drop trigger if exists temp.{name}')
        for q in mark:
            c.execute(q, (d,))
        c.execute('delete from temp.delta where disk=?', (d,))
    for t in ('files', 'issues', 'disks', 'scan_folders', 'excluded'):
        c.execute(f'delete from {t} where disk=?', (d,))
    load_disk(c, d, j)
    if fast:
        for q in mark:
            c.execute(q, (d,))
        folders_full(c, [d])
        for q in TRIGGERS:
            c.execute(q)
    seen.full[d] = c.execute('select scanned from disks where disk=?', (d,)).fetchone()[0]
    seen.parts.pop(d, None)


def apply_modules(c, todo, jobs, rep, seen, incremental):
    """Применить модули по порядку и записать их в applied. Исключения действуют всегда: после каждого модуля
    строки в исключённых папках убираются, откуда бы они ни пришли."""
    serials = serial_map(jobs)
    excl = read_exclusions()
    stamp = time.strftime('%d.%m.%Y %H:%M')
    count = ((lambda: c.execute('select count(*) from temp.delta').fetchone()[0]) if incremental   # без строк триггеров
             else (lambda: c.total_changes))
    for key, m in todo:
        before = count()
        k = m['kind']
        if k == 'опись':
            if incremental:
                replace_disk(c, *m['data'], seen)
            else:
                load_disk(c, *m['data'])
                seen.full[m['data'][0]] = c.execute('select scanned from disks where disk=?', (m['data'][0],)).fetchone()[0]
        elif k == 'частичный скан':
            apply_partial(c, m['data'], seen, excl, rep)
        elif k == 'журнал':
            if 'rows' not in m:
                read_log(m)
                m['start'] = 0
            apply_log(c, m['data'], jobs, serials, rep, seen, rows=m['rows'], start=m['start'])
        elif k == 'ручная операция':
            apply_manual_row(c, m['data'][0], m['data'][1], rep, seen)
        if k != 'опись' or incremental:
            apply_exclusions(c, excl, rep)
        changed = max(0, count() - before)
        c.execute('insert or replace into applied values (?,?,?,?,?,?,?,?,?)',
                  (key, k, m['time'], m['size'], m['mtime_ns'], m['checksum'],
                   max(0, len(m['rows']) - 1) if k == 'журнал' else 0, stamp, changed))


def rebuild(jobs=None, quiet=False, check=False):
    """Полная пересборка из всех модулей во временный файл; затем он заменяет рабочую базу.
    check=True - самопроверка: сравнить с базой, собранной по шагам."""
    jobs = jobs or bp.find_jobs()
    ensure_tables()
    t0 = time.time()
    tmp = DB.with_name(f'хеши.{os.getpid()}.tmp')
    if tmp.exists():
        tmp.unlink()
    c = sqlite3.connect(tmp)
    c.executescript('pragma journal_mode=off; pragma synchronous=off; pragma cache_size=-400000;')
    for q in SCHEMA:
        c.execute(q)
    mods = discover(jobs)
    rep = load_report(c)
    seen = Seen({})
    todo = sorted(mods.items(), key=lambda km: (KIND_ORDER[km[1]['kind']] if km[1]['kind'] == 'опись' else 1,
                                                km[1]['time'], KIND_ORDER[km[1]['kind']], km[0]))
    disks_first = [km for km in todo if km[1]['kind'] == 'опись']
    apply_modules(c, disks_first, jobs, rep, seen, incremental=False)
    c.commit()
    t_disks = time.time() - t0
    apply_exclusions(c, read_exclusions(), rep)
    rest = sorted((km for km in todo if km[1]['kind'] != 'опись'),
                  key=lambda km: (km[1]['time'], KIND_ORDER[km[1]['kind']], km[0]))
    apply_modules(c, rest, jobs, rep, seen, incremental=False)
    for q in INDEXES + DERIVED_SCHEMA:
        c.execute(q)
    t1 = time.time()
    presence_full(c)
    folders_full(c)
    t_derived = time.time() - t1
    finish(c, rep)
    c.execute('insert or replace into meta values (?,?)', ('version', str(BUILD_VERSION)))
    c.commit()
    result = None
    if check:
        result = compare_with_current(c)
    c.close()
    replace_file(tmp, DB)          # прежняя рабочая база остаётся на месте до этой строки
    if not quiet:
        out(f'База собрана целиком за {time.time() - t0:.0f} с (описи носителей {t_disks:.0f} с, '
            f'таблицы presence и folders {t_derived:.0f} с): '
            f'{len(jobs)} носителей, модулей {len(mods)}.')
    return result


def finish(c, rep):
    """Общий хвост сборки: список единственных экземпляров в исключённых папках."""
    excluded_unique(c, rep)
    save_report(c, rep)


def digest(c, prefix=''):
    """Контрольные суммы отсортированного содержимого таблиц: таблица -> (строк, сумма)."""
    res = {}
    for t, cols in DIGEST_TABLES.items():
        h, n = hashlib.sha256(), 0
        for r in c.execute(f'select {cols} from {prefix}{t} order by {cols}'):
            h.update(repr(r).encode('utf-8', 'surrogatepass'))
            n += 1
        res[t] = (n, h.hexdigest())
    return res


def compare_with_current(c):
    """Самопроверка: та же ли база получилась с нуля, что и собранная по шагам. (совпало, строки отчёта)."""
    if not DB.exists():
        return None, ['прежней базы нет - сравнивать не с чем']
    c.execute('attach ? as cur', (str(DB),))
    try:
        ver = c.execute("select value from cur.meta where key='version'").fetchone()
    except sqlite3.Error:
        ver = None
    if not ver or ver[0] != str(BUILD_VERSION):
        c.execute('detach cur')
        return None, ['прежняя база собрана по другим правилам - сравнивать не с чем']
    new, old = digest(c), digest(c, 'cur.')
    c.execute('detach cur')
    lines = [f'{t}: {"совпала" if new[t] == old[t] else "НЕ СОВПАЛА"} (строк {new[t][0]}'
             + (f', по шагам было {old[t][0]})' if new[t] != old[t] else ')') for t in DIGEST_TABLES]
    return all(new[t] == old[t] for t in DIGEST_TABLES), lines


def db_version():
    if not DB.exists():
        return None
    c = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
    try:
        row = c.execute("select value from meta where key='version'").fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        c.close()


def update(jobs=None, quiet=False):
    """Применить к рабочей базе только новые модули. Нужна полная пересборка - сообщить и собрать целиком."""
    jobs = jobs or bp.find_jobs()
    ensure_tables()
    with BuildLock():
        if db_version() != str(BUILD_VERSION):
            out('(рабочей базы ещё нет или изменились правила сборки - собираю её целиком из модулей, это несколько минут)')
            rebuild(jobs, quiet=quiet)
            return 'rebuild'
        t0 = time.time()
        c = sqlite3.connect(DB)
        try:
            mods = discover(jobs)
            todo, why = plan(c, mods)
            if why:
                c.close()
                out(f'({why} - пересобираю рабочую базу целиком, это несколько минут)')
                rebuild(jobs, quiet=quiet)
                return 'rebuild'
            if not todo:
                return None
            kinds = collections.Counter(m['kind'] for _, m in todo)
            out('(есть новые модули: ' + ', '.join(f'{k} - {n}' for k, n in kinds.items())
                + ' - пересобираю рабочую базу частично: применяю только их)')
            c.execute('pragma cache_size=-200000')
            rep = load_report(c)
            seen = load_seen(c)
            derived_start(c)
            apply_modules(c, todo, jobs, rep, seen, incremental=True)
            derived_finish(c)
            finish(c, rep)
            c.commit()
        finally:
            c.close()
    if not quiet:
        out(f'Новые модули применены за {time.time() - t0:.1f} с.')
    return 'update'


class BuildLock:
    """Одна сборка базы за раз: вторая копия программы ждёт, а не портит временные файлы первой."""

    def __enter__(self):
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(BASE_DIR / 'сборка.lock', 'a+b')
        try:
            import msvcrt
        except ImportError:
            return self
        for _ in range(900):
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.locked = True
                return self
            except OSError:
                time.sleep(1)
        self.f.close()
        sys.exit('Другая копия программы уже 15 минут пересобирает базу. Дождитесь её и повторите команду.')

    def __exit__(self, *exc):
        try:
            if getattr(self, 'locked', False):
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def build(jobs=None, quiet=False):
    """Привести рабочую базу в порядок (только новые модули) и вернуть отчёт сборки."""
    update(jobs, quiet)
    c = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
    try:
        return load_report(c)
    finally:
        c.close()


_last = None      # последнее открытое соединение: закрывается перед пересборкой, иначе Windows не даст заменить файл


def close_last():
    global _last
    if _last is not None:
        try:
            _last.close()
        except sqlite3.Error:
            pass
        _last = None


def connect():
    global _last
    close_last()
    jobs = bp.find_jobs()
    update(jobs, quiet=True)
    _last = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
    return _last, jobs


def is_drop(verdict):
    """Единственное решение, которое разрешает не сохранять файл. Раздел и отсрочка этого не разрешают."""
    return bool(verdict) and verdict.strip().lower().startswith('не нужно')


def decisions_for(disk):
    """Решения по путям для диска (строки с диском «*» действуют на все диски)."""
    res = []
    for f in read_table(DECISIONS)[1:]:
        f = [x.strip() for x in f] + [''] * 4
        if f[0] in (disk, '*') and f[2] and not f[1].lower().startswith('класс:'):
            res.append((f[1].rstrip(SEP), f[2]))
    return res


def class_rules(disk):
    """Решения владельца по целому классу файлов: путь вида «класс: служебные и временные»."""
    res = {}
    for f in read_table(DECISIONS)[1:]:
        f = [x.strip() for x in f] + [''] * 4
        if f[0] in (disk, '*') and f[2] and f[1].lower().startswith('класс:'):
            res[f[1].split(':', 1)[1].strip().lower()] = f[2]
    return res


MOVED_PREFIX = 'ПЕРЕНЕСЕНО → '        # папки на источнике после копирования (логика v2, раздел 5)
TRASH_DIR = 'МУСОР'
MOVED_FOLDER = {frozenset(MAIN): MOVED_PREFIX + '45 и 77', frozenset([MAIN[0]]): MOVED_PREFIX + 'только 45',
                frozenset([MAIN[1]]): MOVED_PREFIX + 'только 77'}


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


def decision_of(path, decs):
    path = original_path(path)                # решения привязаны к исходному пути и действуют после перемещения
    for p, verdict in decs:
        if not p or path == p or path.startswith(p + SEP):
            return verdict
    return None


def check_disk(c, disk):
    if not c.execute('select 1 from disks where disk=?', (disk,)).fetchone():
        known = ', '.join(r[0] for r in c.execute('select disk from disks order by disk'))
        sys.exit(f'Диска {disk} нет в базе. Есть: {known}')


def save(name, head, rows):
    path = ANSWERS / (re.sub(r'[\\/:*?"<>|]', '_', name) + '.tsv')
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_NONE, escapechar=None, quotechar=None)
        w.writerow(head)
        for r in rows:
            w.writerow(r)
    return path


def table(head, rows, limit=10, total=None):
    """Таблица на экран: не больше limit строк; total - итоговая строка, видна всегда."""
    rows = list(rows)
    shown = rows[:limit] + ([total] if total else [])
    widths = [max(len(str(h)), *(len(str(r[i])) for r in shown)) if shown else len(str(h)) for i, h in enumerate(head)]
    line = lambda r: '  '.join(str(x).ljust(w) if i == 0 else str(x).rjust(w) for i, (x, w) in enumerate(zip(r, widths)))
    out(line(head))
    for r in rows[:limit]:
        out(line(r))
    if len(rows) > limit:
        out(f'... ещё {len(rows) - limit} строк - см. файл')
    if total:
        out(line(total))


def presence(c, disk, prefix, exclude=None, weak=False):
    """Каждый файл диска с подтверждённым хешем: (path, size, sha, на45, на77, сколько дисков всего[, слабая45, слабая77]).
    Копией считается только запись с подтверждённым хешем (измерен сканером или сверен скриптом при копировании).
    exclude=(диск, папка) - не считать копиями то, что само собираются удалить.
    weak=True - добавить признаки «на диске лежит неподтверждённая копия» (только размер или со слов)."""
    cond, args = prefix_cond('f.path', prefix)
    if not exclude:                       # обычный вопрос - по готовой таблице presence (быстро)
        conf, weak_ev = "('S','C')", "('Z','U','X')"
        extra = f', coalesce(p.e45 in {weak_ev}, 0), coalesce(p.e77 in {weak_ev}, 0)' if weak else ''
        q = f"""select f.path, f.size, f.sha, coalesce(p.e45 in {conf}, 0), coalesce(p.e77 in {conf}, 0), p.ndisks{extra}
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        return c.execute(q, [disk] + args).fetchall()
    ex_sql, ex_args = '', []
    if exclude:
        ec, ea = prefix_cond('g.path', exclude[1])
        ex_sql, ex_args = f' and not (g.disk=? and {ec})', [exclude[0]] + ea
    cols = [f'exists(select 1 from files g where g.sha=f.sha and g.disk=?{ex_sql})'] * 2
    params = [MAIN[0]] + ex_args + [MAIN[1]] + ex_args
    extra = ''
    if weak:
        extra = (', exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)'
                 ', exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)')
    q = f"""select f.path, f.size, f.sha, {cols[0]}, {cols[1]},
                   (select count(distinct g.disk) from files g where g.sha=f.sha){extra}
            from files f where f.disk=? and f.sha is not null and {cond}"""
    return c.execute(q, params + ([MAIN[0], MAIN[1]] if weak else []) + [disk] + args).fetchall()


def issues_for(c, disk, folder):
    """Места, которые сканер не смог прочитать и которые задевают папку (внутри неё или выше неё)."""
    base = (folder or '').rstrip(SEP)
    res = []
    for p, kind, note in c.execute('select path, kind, note from issues where disk=?', (disk,)):
        p = p or ''
        if not base or not p or p == base or p.startswith(base + SEP) or base.startswith(p + SEP):
            res.append((p, kind, note))
    return res


def evidence_notes(c):
    """Предупреждения сборки, которые обязаны попадать в ответ об удалении."""
    rep = json.loads(c.execute("select value from meta where key='report'").fetchone()[0])
    notes = [f'журнал не прочитан программой: {x}' for x in rep.get('skipped', [])]
    notes += list(rep.get('warn', []))
    return notes


def folder_key(path, prefix, depth):
    tail = path[len(prefix.rstrip(SEP)) + 1:] if prefix else path
    parts = tail.split(SEP)
    if len(parts) == 1:
        return '[файлы прямо в папке]'
    return SEP.join(parts[:min(depth, len(parts) - 1)])


NOHASH_NOTE = ('Сравнение по имени и размеру. «Копия не найдена» - файла с таким именем и размером нет ни на одном\n'
               'другом диске (под другим именем копия может существовать). Совпадение имени и размера - вероятная\n'
               'копия, но не доказательство: для решения «можно удалять» оно не засчитывается.')


def unhashed(c, disk, prefix):
    """Файлы без хеша: (path, size, name_lc, класс, на скольких ДРУГИХ дисках есть файл с тем же именем и размером,
    есть ли второй такой же на этом диске)."""
    cond, args = prefix_cond('f.path', prefix)
    q = f'''select f.path, f.size, f.name_lc,
                   (select count(distinct g.disk) from files g
                     where g.name_lc=f.name_lc and g.size=f.size and g.disk<>f.disk),
                   exists(select 1 from files g
                     where g.name_lc=f.name_lc and g.size=f.size and g.disk=f.disk and g.path<>f.path)
            from files f where f.disk=? and f.sha is null and {cond}'''
    return [(p, s or 0, nm or '', class_of(p, nm or '', s or 0), others, dup)
            for p, s, nm, others, dup in c.execute(q, [disk] + args)]


def namesakes(c, disk, names):
    """Какие из имён встречаются на других дисках (с любым размером) - возможно, другая версия файла."""
    c.execute('create temp table if not exists nm(name text primary key)')
    c.execute('delete from nm')
    c.executemany('insert or ignore into nm values (?)', ((n,) for n in names))
    return {r[0] for r in c.execute(
        'select name from nm where exists(select 1 from files g where g.name_lc=nm.name and g.disk<>?)', (disk,))}


def unhashed_note(c, disk, prefix):
    cond, args = prefix_cond('path', prefix)
    n = c.execute(f'select count(*) from files where disk=? and sha is null and {cond}', [disk] + args).fetchone()[0]
    if n:
        out(f'Файлов без SHA-256 (документы, проекты, архивы, мелочь): {n} - здесь не сравниваются; '
            f'их уникальность показывает команда only.')


def unhashed_report(c, disk, prefix, decs, save_name):
    """Вторая таблица: файлы без хеша по классам и папки, которые есть только на этом диске."""
    rows = unhashed(c, disk, prefix)
    if not rows:
        return
    cls = collections.defaultdict(lambda: [0, 0, 0, 0])            # файлов, байт, не найдено: файлов, байт
    tot, unf, unf_bytes = collections.Counter(), collections.Counter(), collections.Counter()
    detail, decided, root_unf = [], 0, 0
    base = prefix.rstrip(SEP)
    for p, s, nm, k, others, dup in rows:
        if decision_of(p, decs):
            decided += 1
            continue
        a = cls[k]
        a[0] += 1; a[1] += s
        lost = others == 0 and k != C_EMPTY
        if lost:
            a[2] += 1; a[3] += s
        if k not in SIGNIFICANT:
            continue
        parts = p.split(SEP)[:-1]
        for i in range(1, len(parts) + 1):
            d = SEP.join(parts[:i])
            if base and not (d == base or d.startswith(base + SEP)):
                continue
            tot[d] += 1
            if lost:
                unf[d] += 1; unf_bytes[d] += s
        if lost:
            root_unf += not parts
            detail.append([p, s, k, nm, 'есть второй такой же файл на этом диске' if dup else ''])
    other_version = namesakes(c, disk, {d[3] for d in detail}) if detail else set()
    for d in detail:
        if d[3] in other_version:
            d[4] = (d[4] + '; ' if d[4] else '') + 'на других дисках есть файл с тем же именем, но другого размера'
    out('')
    out(f'ОСТАЛЬНЫЕ ФАЙЛЫ (без SHA-256): {sum(v[0] for v in cls.values())}')
    out(NOHASH_NOTE)
    table(('класс', 'файлов', 'ГБ', 'копия не найдена: файлов', 'ГБ'),
          [(k, cls[k][0], gb(cls[k][1]), cls[k][2] if k != C_EMPTY else '-', gb(cls[k][3]) if k != C_EMPTY else '-')
           for k in CLASS_ORDER if k in cls])
    whole = sorted((d for d in tot if unf[d] == tot[d]), key=lambda d: d.count(SEP))
    top = []
    for d in whole:                                   # только самые верхние из целиком уникальных
        if not any(d.startswith(t + SEP) for t in top):
            top.append(d)
    top.sort(key=lambda d: -unf_bytes[d])
    if top:
        out('')
        out('Папки, у которых НИ У ОДНОГО значимого файла копия не найдена (вероятно, есть только на этом диске):')
        table(('папка', 'файлов', 'ГБ'), [(d[-90:], unf[d], gb(unf_bytes[d])) for d in top], limit=20)
    depth = (base.count(SEP) + 1 if base else 0)
    partial = sorted((d for d in tot if d.count(SEP) == depth and unf[d] and unf[d] != tot[d]), key=lambda d: -unf_bytes[d])
    if partial:
        out('')
        out('Папки, где копия не найдена у части значимых файлов:')
        table(('папка', 'значимых файлов', 'не найдено', 'ГБ не найдено'),
              [(d[-70:], tot[d], unf[d], gb(unf_bytes[d])) for d in partial], limit=12)
    if root_unf:
        out(f'Прямо в корне: {root_unf} значимых файлов без найденной копии.')
    n_ver = sum(1 for d in detail if d[3] in other_version)
    if n_ver:
        out(f'Из ненайденных у {n_ver} файлов на других дисках есть тёзка другого размера - возможно, другая версия.')
    if decided:
        out(f'Не показано по решениям пользователя: {decided} файлов.')
    path = save(save_name, ('путь', 'размер', 'класс', 'пометка'), sorted((d[0], d[1], d[2], d[4]) for d in detail))
    out(f'Значимые файлы без найденной копии ({len(detail)}): {path}')


# ---------- команды ----------

def cmd_missing(a, only=False):
    c, jobs = connect()
    check_disk(c, a.disk)
    prefix = (a.folder or '').rstrip(SEP)
    rows = presence(c, a.disk, prefix, weak=True)
    decs = decisions_for(a.disk)
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # файлов, байт, нет45, нет77, нет обоих, только тут
    detail, dropped = [], [0, 0]
    sections = collections.defaultdict(lambda: [0, 0, 0, 0])    # решение: файлов, байт, без копий где-либо: файлов, байт
    weak45 = weak77 = 0
    for path, size, sha, on45, on77, ndisks, w45, w77 in rows:
        v = decision_of(path, decs)
        if is_drop(v):
            dropped[0] += 1; dropped[1] += size
            continue
        if v:                                    # раздел или отсрочка: сохранять НУЖНО, но не на 45 и 77
            s = sections[v]
            s[0] += 1; s[1] += size
            if ndisks == 1:
                s[2] += 1; s[3] += size
            continue
        if only and ndisks > 1:
            continue
        k = agg[folder_key(path, prefix, a.depth)]
        k[0] += 1; k[1] += size
        if not on45: k[2] += size
        if not on77: k[3] += size
        if not on45 and not on77: k[4] += size
        if ndisks == 1: k[5] += size
        weak45 += (not on45) and bool(w45); weak77 += (not on77) and bool(w77)
        if only or not (on45 and on77):
            detail.append((path, size, 'да' if on45 else ('не подтверждено' if w45 else 'нет'),
                           'да' if on77 else ('не подтверждено' if w77 else 'нет'), ndisks - 1, sha))
    title = f'{a.disk}' + (f'\\{prefix}' if prefix else '')
    what = 'только на этом диске' if only else f'чего нет на {MAIN[0]} и {MAIN[1]}'
    out(f'{title}: {what} (ГБ, только файлы с SHA-256; всего таких {len(rows)})')
    out('Копией считается только подтверждённая: хеш измерен сканером или сверен скриптом при копировании.')
    tot = [sum(v[i] for v in agg.values()) for i in range(6)]
    head = ('папка', 'файлов', 'всего', f'нет на {MAIN[0]}', f'нет на {MAIN[1]}', 'нет на обоих', 'больше нигде')
    order = sorted(agg.items(), key=lambda kv: -(kv[1][1] if only else max(kv[1][2], kv[1][3])))
    body = [(k[:60], v[0], gb(v[1]), gb(v[2]), gb(v[3]), gb(v[4]), gb(v[5])) for k, v in order
            if only or v[2] or v[3]]
    table(head, body, total=('ИТОГО', tot[0], gb(tot[1]), gb(tot[2]), gb(tot[3]), gb(tot[4]), gb(tot[5])))
    if weak45 or weak77:
        out(f'Из «нет»: на {MAIN[0]} у {weak45} файлов и на {MAIN[1]} у {weak77} лежит НЕПОДТВЕРЖДЁННАЯ копия '
            f'(сверен только размер или со слов пользователя). Копией она не считается, пока файл не прочитан.')
    if sections:
        out('')
        out('По решениям пользователя (в таблицу выше не входят; сохранять их НУЖНО, место - по решению):')
        table(('решение', 'файлов', 'ГБ', 'без подтверждённой копии где-либо ещё: файлов', 'ГБ'),
              [(k[:50], v[0], gb(v[1]), v[2], gb(v[3])) for k, v in sorted(sections.items(), key=lambda kv: -kv[1][1])])
    if dropped[0]:
        out(f'По решению «не нужно» не показано: {dropped[0]} файлов, {gb(dropped[1])} ГБ')
    iss = issues_for(c, a.disk, prefix)
    if iss:
        out(f'ВНИМАНИЕ: опись неполная - сканер не прочитал {len(iss)} мест в этой области; файлы оттуда программе неизвестны.')
    tag = f'{a.disk} {prefix.replace(SEP, " - ")}'.strip()
    p = save(f'{"только" if only else "нет на 45 и 77"} - {tag}',
             ('путь', 'размер', f'на {MAIN[0]}', f'на {MAIN[1]}', 'на скольких других дисках', 'SHA-256'), sorted(detail))
    out(f'По файлам ({len(detail)}): {p}')
    if only:
        unhashed_report(c, a.disk, prefix, [d for d in decs if is_drop(d[1])], f'только, без хеша - {tag}')
    else:
        unhashed_note(c, a.disk, prefix)


def sha_sizes(c, disk, prefix):
    cond, args = prefix_cond('path', prefix)
    d = {}
    for path, size, sha in c.execute(f'select path, size, sha from files where disk=? and sha is not null and {cond}',
                                     [disk] + args):
        d.setdefault(sha, (path, size))
    return d


def name_sizes(c, disk, prefix):
    """Файлы без хеша в папке: (имя, размер) -> путь; без служебных и пустых."""
    cond, args = prefix_cond('path', prefix)
    d = {}
    for path, size, nm in c.execute(f'select path, size, name_lc from files where disk=? and sha is null and {cond}',
                                    [disk] + args):
        if class_of(path, nm or '', size or 0) not in (C_JUNK, C_EMPTY):
            d.setdefault((nm, size), path)
    return d


def cmd_cmp(a):
    c, _ = connect()
    check_disk(c, a.disk_a); check_disk(c, a.disk_b)
    A, B = sha_sizes(c, a.disk_a, a.folder_a), sha_sizes(c, a.disk_b, a.folder_b)
    both, oa, ob = A.keys() & B.keys(), A.keys() - B.keys(), B.keys() - A.keys()
    s = lambda keys, d: sum(d[k][1] for k in keys)
    NA, NB = name_sizes(c, a.disk_a, a.folder_a), name_sizes(c, a.disk_b, a.folder_b)
    nb, na_, nb_ = NA.keys() & NB.keys(), NA.keys() - NB.keys(), NB.keys() - NA.keys()
    out(f'A = {a.disk_a}\\{a.folder_a}    B = {a.disk_b}\\{a.folder_b}')
    out(f'Файлы с подтверждённым SHA-256 (разных): A {len(A)}, B {len(B)}')
    table(('', 'файлов', 'ГБ'), [('есть в обеих', len(both), gb(s(both, A))), ('только в A', len(oa), gb(s(oa, A))),
                                  ('только в B', len(ob), gb(s(ob, B)))])
    if NA or NB:
        out(f'Файлы без подтверждённого хеша (по имени и размеру, не доказательство): в обеих {len(nb)}, '
            f'только в A {len(na_)}, только в B {len(nb_)}')
    # общий вывод - только после обеих частей
    if not A and not B and not NA and not NB:
        verdict = 'в базе нет файлов по этим путям - сравнивать нечего.'
    elif oa or ob:
        verdict = ('в B есть все файлы с хешем из A.' if not oa else 'в A есть все файлы с хешем из B.' if not ob
                   else 'папки различаются.')
        if na_ or nb_:
            verdict += ' Различаются и файлы без хеша.'
    elif na_ or nb_:
        verdict = ('файлы с хешем совпадают, но РАЗЛИЧАЮТСЯ файлы без хеша: '
                   f'только в A {len(na_)}, только в B {len(nb_)}. Папки не одинаковы.')
    elif NA or NB:
        verdict = ('файлы с хешем совпадают точно; остальные совпали по имени и размеру - это не доказательство. '
                   'Одинаковость папок НЕ подтверждена полностью.')
    else:
        verdict = 'наборы файлов одинаковы по содержимому (SHA-256).'
    out('Вывод: ' + verdict)
    out('Сравнивается набор файлов, а не расположение по подпапкам: структура папок не проверяется.')
    detail = [('только в A', *A[k], k) for k in oa] + [('только в B', *B[k], k) for k in ob]
    detail += [('только в A, без хеша', NA[k], k[1], '') for k in na_] + [('только в B, без хеша', NB[k], k[1], '') for k in nb_]
    p = save(f'сравнение - {a.disk_a} {a.folder_a} и {a.disk_b} {a.folder_b}'.replace(SEP, ' - '),
             ('где', 'путь', 'размер', 'SHA-256'), sorted(detail, key=lambda r: (r[0], r[1])))
    out(f'Различия по файлам ({len(detail)}): {p}')


def where_unhashed(c, disk, path, has_hashed):
    cond, args = prefix_cond('f.path', path)
    mine = {}
    for p, s, nm, mt in c.execute(f'select f.path, f.size, f.name_lc, f.mtime from files f '
                                  f'where f.disk=? and f.sha is null and {cond}', [disk] + args):
        if class_of(p, nm or '', s or 0) not in (C_JUNK, C_EMPTY):
            mine[p] = (s, nm, mt)
    if not mine:
        if not has_hashed:
            out('В базе нет файлов по этому пути (проверьте написание пути и номер диска).')
        return
    found, same_date, sample, hit = collections.defaultdict(set), collections.Counter(), {}, set()
    q = f'''select f.path, g.disk, g.path, g.mtime from files f join files g on g.name_lc=f.name_lc and g.size=f.size
            where f.disk=? and f.sha is null and f.size>0 and {cond} and not (g.disk=f.disk and g.path=f.path)'''
    for p, gd, gp, gmt in c.execute(q, [disk] + args):
        if p not in mine or p in found[gd]:
            continue
        found[gd].add(p); hit.add(p)
        same_date[gd] += bool(gmt and gmt == mine[p][2])
        sample.setdefault(gd, gp)
    out(f'{disk}\\{path}: файлов без SHA-256 (кроме служебных и пустых) {len(mine)}, '
        f'{gb(sum(v[0] for v in mine.values()))} ГБ. Где есть файлы с тем же именем и размером:')
    rows = [(d + (' (тот же диск, другое место)' if d == disk else ''), len(found[d]), f'{100 * len(found[d]) // len(mine)}%',
             same_date[d], sample[d][-70:]) for d in sorted(found, key=lambda d: -len(found[d]))]
    table(('диск', 'файлов', 'доля', 'из них с той же датой', 'пример пути'), rows or [('нигде больше', 0, '0%', 0, '')])
    out(f'Копия не найдена нигде: {len(mine) - len(hit)} файлов. Совпадение имени и размера - вероятная копия, не доказательство.')
    if has_hashed:
        out('')


def cmd_where(a):
    c, _ = connect()
    check_disk(c, a.disk)
    mine = sha_sizes(c, a.disk, a.path)
    where_unhashed(c, a.disk, a.path, bool(mine))
    if not mine:
        return
    cnt, size, sample = collections.Counter(), collections.Counter(), {}
    c.execute('create temp table q(sha text primary key)')
    c.executemany('insert into q values (?)', ((k,) for k in mine))
    seen = set()
    for disk, path, sha in c.execute('select f.disk, f.path, f.sha from files f join q on q.sha=f.sha'):
        if disk == a.disk and mine[sha][0] == path:
            continue
        if (disk, sha) in seen:
            continue
        seen.add((disk, sha))
        cnt[disk] += 1; size[disk] += mine[sha][1]; sample.setdefault(disk, path)
    tot = sum(v[1] for v in mine.values())
    out(f'{a.disk}\\{a.path}: {len(mine)} разных файлов с SHA-256, {gb(tot)} ГБ. Где ещё лежит то же содержимое:')
    rows = [(d + (' (тот же диск, другое место)' if d == a.disk else ''), cnt[d], gb(size[d]), f'{100 * cnt[d] // len(mine)}%',
             sample[d][:70]) for d in sorted(cnt, key=lambda d: -size[d])]
    table(('диск', 'файлов', 'ГБ', 'доля', 'пример пути'), rows or [('нигде больше', 0, '0.00', '0%', '')])
    weak = collections.Counter()
    for disk, sha in c.execute('select f.disk, f.sha_exp from files f join q on q.sha=f.sha_exp'):
        weak[disk] += 1
    if weak:
        out('НЕПОДТВЕРЖДЁННЫЕ копии (сверен только размер, со слов пользователя или файл менялся) - копиями не считаются: '
            + ', '.join(f'{d} - {n}' for d, n in weak.most_common()))


def cmd_candel(a):
    """Можно ли удалять. «ДА» - только когда у КАЖДОГО файла есть подтверждённые копии на обоих главных дисках,
    не считая удаляемого, опись полна и ничего не исключено по умолчанию. Иначе «НЕТ» или «НЕДОСТАТОЧНО»."""
    c, jobs = connect()
    check_disk(c, a.disk)
    folder = (a.folder or '').rstrip(SEP)
    decs, crules = decisions_for(a.disk), class_rules(a.disk)
    rows = presence(c, a.disk, folder, exclude=(a.disk, folder), weak=True)
    rest = unhashed(c, a.disk, folder)
    if not rows and not rest:
        out('В базе нет файлов по этому пути (проверьте написание пути и номер диска).')
        return
    reasons = []
    status = (c.execute('select status from disks where disk=?', (a.disk,)).fetchone() or ['?'])[0] or '?'
    if not status.startswith('complete'):
        reasons.append(f'опись диска не завершена (состояние «{status}»)')
    iss = issues_for(c, a.disk, folder)
    if iss:
        reasons.append(f'опись неполная: сканер не прочитал {len(iss)} мест в этой области (первое: «{iss[0][0] or "корень диска"}»)')
    reasons += evidence_notes(c)

    dropped, lack, weak_only = 0, [], 0
    for p, s, sha, o45, o77, n, w45, w77 in rows:
        if is_drop(decision_of(p, decs)):
            dropped += 1
            continue
        if not (o45 and o77):
            lack.append((p, s, 'да' if o45 else ('не подтверждено' if w45 else 'нет'),
                         'да' if o77 else ('не подтверждено' if w77 else 'нет'), sha))
            weak_only += bool((o45 or w45) and (o77 or w77))
    unconf = collections.defaultdict(lambda: [0, 0, 0])            # класс: файлов, байт, из них копия не найдена нигде
    unconf_rows = []
    for p, s, nm, k, others, dup in rest:
        if k == C_EMPTY:
            continue                                               # пустой файл: терять нечего
        if is_drop(decision_of(p, decs)) or is_drop(crules.get(k.lower())):
            dropped += 1
            continue
        u = unconf[k]
        u[0] += 1; u[1] += s; u[2] += others == 0
        unconf_rows.append((p, s, k, 'копия не найдена нигде' if others == 0 else 'есть вероятная копия (имя и размер)'))
    confirmed = len(rows) - len(lack)

    out(f'{a.disk}\\{folder}: проверка перед удалением')
    out(f'Файлов с подтверждённым SHA-256: {len(rows)}, {gb(sum(r[1] for r in rows))} ГБ')
    out(f'  подтверждённые копии есть и на {MAIN[0]}, и на {MAIN[1]} (не считая удаляемого): {confirmed}')
    out(f'  нет хотя бы на одном: {len(lack)}, {gb(sum(r[1] for r in lack))} ГБ'
        + (f' (у {weak_only} из них копии лежат, но не подтверждены: сверен только размер или со слов)' if weak_only else ''))
    n_unconf = sum(v[0] for v in unconf.values())
    if n_unconf:
        out(f'Файлов БЕЗ подтверждённого хеша: {n_unconf}, {gb(sum(v[1] for v in unconf.values()))} ГБ - их сохранность доказать нечем:')
        table(('класс', 'файлов', 'ГБ', 'копия не найдена нигде'),
              [(k, unconf[k][0], gb(unconf[k][1]), unconf[k][2]) for k in CLASS_ORDER if k in unconf])
    if dropped:
        out(f'Исключено решениями «не нужно»: {dropped} файлов.')
    for r in reasons:
        out('ВНИМАНИЕ: ' + r)
    if lack:
        out(f'ОТВЕТ: НЕТ - у {len(lack)} файлов нет подтверждённой копии на обоих дисках. Удалять нельзя.')
    elif reasons or n_unconf:
        out('ОТВЕТ: НЕДОСТАТОЧНО ПОДТВЕРЖДЕНИЙ - удалять по этому ответу нельзя.')
        if n_unconf:
            out('  Что можно сделать: посчитать этим файлам хеши; либо владелец записывает решение «не нужно» '
                'для папки или для класса (строка «класс: <название>» в решения.tsv).')
    else:
        out(f'ОТВЕТ: ДА - у каждого файла есть подтверждённые копии на {MAIN[0]} и {MAIN[1]}, не считая удаляемого.')
    tag = f'{a.disk} {folder}'.replace(SEP, ' - ')
    if lack:
        out(f'Чего не хватает: {save(f"нельзя удалять - {tag}", ("путь", "размер", "на " + MAIN[0], "на " + MAIN[1], "SHA-256"), sorted(lack))}')
    if unconf_rows:
        out(f'Файлы без подтверждения: {save(f"нельзя удалять, без подтверждения - {tag}", ("путь", "размер", "класс", "что известно"), sorted(unconf_rows))}')
    out('Основание: описи, журналы скриптов, таблицы ручных операций и решений; диски не читались. Удаляет только пользователь.')


def cmd_mklist(a):
    c, jobs = connect()
    check_disk(c, a.disk)
    for t in a.to:
        check_disk(c, t)
    task = (TASKS if getattr(a, 'task_root', None) == 'scripts' else bp.OUT_DIR) / a.name
    if not a.dry and task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задачи уже есть и не пуста: {task}. Выберите другое имя (--name).')
    decs = decisions_for(a.disk)
    want = (getattr(a, 'section', None) or '').strip().lower()
    take_all = getattr(a, 'all', False)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    waiting = collections.defaultdict(lambda: [0, 0])      # раздел/отсрочка: файлов, байт - не идут в этот список
    dropped, weak_there = [0, 0], collections.Counter()
    waiting_seen = set()
    src_folder = (getattr(a, 'source_folder', None) or '').strip(SEP)
    src_name = getattr(a, 'as_name', None) or a.disk
    cut = len(src_folder) + 1 if src_folder else 0
    for prefix in ([src_folder] if src_folder else (a.folder or [''])):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        for t in a.to:
            q = f"""select f.path, f.size, f.sha,
                           exists(select 1 from files g where g.sha_exp=f.sha and g.disk=?)
                    from files f where f.disk=? and f.sha is not null and {cond}
                    and not exists(select 1 from files g where g.sha=f.sha and g.disk=?)"""
            for path, size, sha, weak in c.execute(q, [t, a.disk] + args + [t]):
                v = decision_of(path, decs)
                if is_drop(v):
                    dropped[0] += 1; dropped[1] += size
                    continue
                if want:
                    if not v or v.strip().lower() != want:
                        continue
                elif v and not take_all:                   # раздел или отсрочка: НЕ на эти диски, но и не «не нужно»
                    if path not in waiting_seen:           # один файл считается один раз, а не по разу на каждую цель
                        waiting_seen.add(path)
                        w = waiting[v]
                        w[0] += 1; w[1] += size
                    continue
                if weak:
                    weak_there[t] += 1                     # файл там уже лежит, но не подтверждён: копирование его пропустит
                    continue
                lines.append((t, path[cut:], size, 'фото/видео', sha.upper()))
                stat[t][0] += 1; stat[t][1] += size
    lines = sorted(set(lines))

    def notes():
        for v, w in sorted(waiting.items(), key=lambda kv: -kv[1][1]):
            out(f'  ЖДУТ СВОЕГО ДИСКА, решение «{v}»: {w[0]} файлов, {gb(w[1])} ГБ - в этот список не вошли. '
                f'Собрать их: --section "{v}" --to <диск раздела>')
        for t, n in weak_there.items():
            out(f'  на {t} уже лежит неподтверждённая копия у {n} файлов (сверен только размер или со слов) - '
                f'в список не включены: скрипт их пропустит как «уже есть». Подтвердить можно только чтением.')
        if dropped[0]:
            out(f'  по решению «не нужно» пропущено: {dropped[0]} файлов, {gb(dropped[1])} ГБ')

    if not lines:
        if waiting or weak_there:
            out('В список для указанных дисков ничего не вошло, но это НЕ значит, что всё сохранено:')
        else:
            out('Копировать нечего: у всех файлов с хешем есть подтверждённая копия на указанных дисках.')
        notes()
        return
    if a.dry:
        out('Пробный расчёт (--dry): папка задачи не создаётся.')
        for t in a.to:
            out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ')
        notes()
        return
    serials = {v: k for k, v in serial_map(jobs).items()}
    task.mkdir(parents=True, exist_ok=True)
    with io.open(task / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{src_name}\t{serials.get(a.disk, "НЕТ_СЕРИЙНОГО_НОМЕРА")}' + (f'\t{src_folder}' if src_folder else '') + '\n')
        for d in a.to:
            f.write(f'{d}\t{serials.get(d, "НЕТ_СЕРИЙНОГО_НОМЕРА")}\n')
    for name in ('Копировать.ps1', 'Запустить.cmd'):
        shutil.copy2(TEMPLATE / name, task / name)
    out(f'Папка задачи: {task}')
    for t in a.to:
        out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ -> ПЕРЕНОС с других дисков\\{src_name}\\<тот же путь>'
            + (f' (источник - папка {a.disk}\\{src_folder})' if src_folder else ''))
    notes()
    out('Запуск - пользователем: двойной щелчок по «Запустить.cmd». Свою папку на цели можно задать третьей колонкой в тома.tsv.')


def report_lines(c, rep):
    """Полный отчёт сборки - для файла подробностей."""
    L = []
    L.append('Учтённые журналы скриптов (добавлено, перемещено, убрано, из добавленных без подтверждения содержимого):')
    L += [f'  {k}: {v[0]}, {v[1]}, {v[2]}, {v[3]}' for k, v in sorted(rep['logs'].items())]
    if rep['skipped']:
        L.append('Журналы, которые программа не умеет читать (не учтены):')
        L += ['  ' + x for x in rep['skipped']]
    if rep['old_logs'] or rep['old']:
        L.append('Не применено, потому что опись диска (или частичный скан папки) новее операции:')
        L += [f'  {k}: {n} строк' for k, n in sorted(rep['old_logs'].items())] + ['  ' + x for x in rep['old']]
    if rep['partial']:
        L.append('Частичные сканы папок:')
        L += ['  ' + x for x in rep['partial']]
    L += [f'Исключения ({EXCLUSIONS.name}): {x}' for x in rep['excluded']]
    L.append(f'Ручные операции ({MANUAL.name}): {len(rep["manual"])}')
    L += ['  ' + x for x in rep['manual']]
    L += ['ВНИМАНИЕ: ' + x for x in sorted(rep['warn'])]
    L += ['ВНИМАНИЕ: ' + x for _, x in sorted(rep['unique'].items())]
    L.append('Модули (вид, ключ, время, когда применён, строк изменено):')
    L += [f'  {k}\t{m}\t{time.strftime("%d.%m.%Y %H:%M", time.localtime(t)) if t else "-"}\t{at}\t{n}'
          for m, k, t, at, n in c.execute('select module, kind, time, applied_at, changed from applied order by kind, time, module')]
    return L


def type_cols(r, k=0):
    """ГБ по типам из строки folders, начиная с колонки n0 (k - её номер)."""
    return [gb(r[k + 1 + 2 * i]) for i in range(5)]


def cmd_folders(a):
    """Сколько занимает папка и её подпапки, по типам файлов: по готовой таблице folders, диски не читаются."""
    c, _ = connect()
    check_disk(c, a.disk)
    base = (a.folder or '').strip(SEP)
    depth = (base.count(SEP) + 1 if base else 0) + a.depth
    cols = 'folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5))
    me = c.execute(f'select {cols} from folders where disk=? and folder=?', (a.disk, base)).fetchone()
    if not me:
        out(f'В базе нет файлов в {a.disk}\\{base} (проверьте написание пути).')
        return
    out(f'{a.disk}\\{base}: файлов {me[1]}, {gb(me[2])} ГБ; по типам, ГБ: '
        + ', '.join(f'{t} {v}' for t, v in zip(FOLDER_TYPES, type_cols(me, 3))))
    cond, args = prefix_cond('folder', base)
    rows = c.execute(f'select {cols} from folders where disk=? and depth=? and {cond} order by bytes desc',
                     [a.disk, depth] + args).fetchall()
    head = ('папка', 'файлов', 'ГБ') + FOLDER_TYPES
    body = [(r[0][len(base):].lstrip(SEP)[-60:], r[1], gb(r[2]), *type_cols(r, 3)) for r in rows]
    if body:
        table(head, body, limit=12)
    path = save(f'папки - {a.disk} {base}'.replace(SEP, ' - ').strip(), head, body)
    out(f'Все подпапки ({len(body)}): {path}')


def cmd_find(a):
    """Папки, в пути которых есть все слова: по таблице folders, а не по 11 млн файлов."""
    c, _ = connect()
    words = [w.lower() for w in a.words if w.strip()]
    q = ('select disk, folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5)) + ' from folders where '
         + ' and '.join(['instr(folder_lc, ?) > 0'] * len(words)))
    args = list(words)
    if a.disk:
        check_disk(c, a.disk)
        q += ' and disk=?'
        args.append(a.disk)
    rows = c.execute(q, args).fetchall()
    hits = {(r[0], r[1]) for r in rows}
    top = [r for r in rows if (r[0], parent_of(r[1])) not in hits or not r[1]]   # только верхние совпадения
    top.sort(key=lambda r: -r[3])
    by_disk = collections.defaultdict(lambda: [0, 0, 0])
    for r in top:
        k = by_disk[r[0]]
        k[0] += 1; k[1] += r[2]; k[2] += r[3]
    what = ' '.join(f'«{w}»' for w in a.words)
    if not top:
        out(f'Папок со словами {what} нет' + (f' на {a.disk}.' if a.disk else '.'))
        return
    out(f'Папки со словами {what}: {len(top)} (вложенные совпадения не считаются), файлов {sum(r[2] for r in top)}, '
        f'{gb(sum(r[3] for r in top))} ГБ')
    if not a.disk:
        out('По носителям: ' + '; '.join(f'{d} - {k[0]} папок, {gb(k[2])} ГБ'
                                         for d, k in sorted(by_disk.items(), key=lambda kv: -kv[1][2])[:8])
            + ('; …' if len(by_disk) > 8 else ''))
    head = ('диск', 'папка', 'файлов', 'ГБ') + FOLDER_TYPES
    body = [(r[0], r[1][-70:], r[2], gb(r[3]), *type_cols(r, 4)) for r in top]
    table(head[:4], [b[:4] for b in body], limit=10)
    path = save(f'поиск папок - {" ".join(a.words)}', head, [(r[0], r[1], r[2], gb(r[3]), *type_cols(r, 4)) for r in top])
    out(f'Все найденные папки с разбивкой по типам: {path}')


def copied_from(disk, jobs):
    """Что журналы единого шаблона скопировали С этого диска: путь источника -> {диск-цель: путь назначения}.
    Учитываются строки «скопирован…» и «уже есть»; подтверждена ли копия, решает база (степень S или C)."""
    serials = serial_map(jobs)
    res = collections.defaultdict(dict)
    for log in sorted(journal_paths(), key=log_time):
        task = Path(log).parent
        if not (task / 'тома.tsv').exists():
            continue
        vols = [f for f in read_tsv(task / 'тома.tsv') if len(f) >= 2]
        names = {f[0].strip(): serials.get(f[1].strip().upper()) for f in vols}
        if not vols or names.get(vols[0][0].strip()) != disk:
            continue
        rows = read_tsv(log)
        head = [h.strip().lower() for h in rows[0]] if rows else []
        if not ('цель' in head and 'куда' in head):
            continue
        i_t, i_r, i_src, i_dst = (head.index(x) for x in ('цель', 'результат', 'источник', 'куда'))
        for f in rows[1:]:
            if len(f) <= i_dst or not (f[i_r].startswith('скопирован') or f[i_r] == 'уже есть'):
                continue
            t = names.get(f[i_t]) or (f[i_t] if f[i_t] in jobs else None)
            if t:
                res[rel_of(f[i_src])[1]][t] = rel_of(f[i_dst])[1]
    return res


def cmd_mvlist(a):
    """Задание «Переместить на источнике»: файлы, у которых журнал копирования подтвердил копии, перекладываются
    внутри своего диска в «ПЕРЕНЕСЕНО → 45 и 77 / только 45 / только 77» (логика v2, разделы 4-5)."""
    c, jobs = connect()
    check_disk(c, a.disk)
    copies = copied_from(a.disk, jobs)
    decs = decisions_for(a.disk)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    wait, stay, notyet, other = [0, 0], [0, 0], [0, 0], [0, 0]
    for prefix in (a.folder or ['']):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        q = f"""select f.path, f.size, f.sha, f.mtime, coalesce(p.e45 in ('S','C'), 0), coalesce(p.e77 in ('S','C'), 0)
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        for path, size, sha, mt, on45, on77 in c.execute(q, [a.disk] + args):
            if is_moved_dir(path.split(SEP, 1)[0]) or decision_of(path, decs):
                continue                                  # уже перемещён; раздел, отсрочка или «не нужно» - не здесь
            done = copies.get(path, {})
            to_main = {t for t in done if t in MAIN}
            if not done:
                k = stay if (on45 and on77) else notyet   # на 45 и 77 уже было - остаётся на месте; иначе ещё не копировали
            elif not to_main:
                k = other                                 # копировали только на другие диски - их проход позже
            else:
                ok = all(c.execute("select 1 from files where disk=? and path=? and sha=? and ev in ('S','C')",
                                   (t, done[t], sha)).fetchone() for t in to_main)
                if not (ok and on45 and on77):
                    k = wait                              # копия не подтверждена (размер, «уже есть») или нет второй
                else:
                    folder = MOVED_FOLDER[frozenset(to_main)]
                    lines.append((path, size, mt if mt is not None else '', folder, sha.upper(),
                                  'копия подтверждена: ' + ', '.join(sorted(to_main))))
                    stat[folder][0] += 1; stat[folder][1] += size
                    continue
            k[0] += 1; k[1] += size
    lines.sort()
    out(f'{a.disk}: что переложить внутри диска после копирования (только фото и видео с SHA-256)')
    for folder, (n, b) in sorted(stat.items()):
        out(f'  -> {folder}: {n} файлов, {gb(b)} ГБ')
    if not lines:
        out('  перемещать нечего')
    out(f'Ждут: копия ещё не подтверждена - {wait[0]} файлов ({gb(wait[1])} ГБ); ещё не копировались - {notyet[0]} '
        f'({gb(notyet[1])} ГБ); копировались только на другие диски - {other[0]}.')
    out(f'Остаются на месте (на 45 и 77 уже были): {stay[0]} файлов, {gb(stay[1])} ГБ.')
    if not lines or a.dry:
        if a.dry and lines:
            out('Пробный расчёт (--dry): папка задания не создаётся.')
        return
    task = (TASKS if getattr(a, 'task_root', None) == 'scripts' else bp.OUT_DIR) / a.name
    if task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задания уже есть и не пуста: {task}. Выберите другое имя (--name).')
    task.mkdir(parents=True, exist_ok=True)
    serial = {v: k for k, v in serial_map(jobs).items()}.get(a.disk, 'НЕТ_СЕРИЙНОГО_НОМЕРА')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'{a.disk}\t{serial}\n')
    with io.open(task / 'перемещение.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    for name in ('Переместить.ps1', 'Запустить.cmd'):
        shutil.copy2(MOVE_TEMPLATE / name, task / name)
    (task / 'Как запустить.txt').write_text(
        f'Задание: переложить внутри диска {a.disk} файлы, копии которых подтверждены журналами копирования.\n'
        f'Файлов: {len(lines)}, {gb(sum(r[1] for r in lines))} ГБ. Куда: ' +
        '; '.join(f'{k} - {v[0]} файлов' for k, v in sorted(stat.items())) + '.\n'
        'Ничего не удаляется и не перезаписывается: это переименование внутри того же диска.\n\n'
        f'1. Подключите диск {a.disk} (букву скрипт найдёт сам по серийному номеру).\n'
        '2. Двойной щелчок по «Запустить.cmd», проверьте сводку, введите «да».\n'
        '3. Q - остановиться после текущего файла; повторный запуск продолжит.\n'
        '4. Журнал «Журнал перемещения <дата>.tsv» появится здесь; программа учтёт его сама.\n', encoding='utf-8-sig')
    out(f'Папка задания: {task}')
    out('Запускает владелец: «Запустить.cmd» в этой папке. Перед запуском список можно пересобрать - он всегда по свежей базе.')


def owner_write(preview, write, a):
    """Предпросмотр по умолчанию; запись - только с --yes. Всё - через service (единый путь записи)."""
    import service as sv
    try:
        pv = write() if a.yes else preview()
    except sv.Refused as e:
        out('НЕ ЗАПИСАНО: ' + str(e))
        raise SystemExit(1)
    for x in pv['lines']:
        out(x)
    if a.yes:
        out(f'Записано: строка {pv["line"]}. Копия таблицы до записи - в «_БАЗА\\архив таблиц».')
    else:
        out('Это предпросмотр, ничего не записано. Записать: та же команда с --yes')


def cmd_manual(a):
    import service as sv
    args = (a.date, a.action, a.disk, a.path, a.disk2 or '', a.path2 or '')
    owner_write(lambda: sv.manual_preview(*args), lambda: sv.add_manual(*args, note=a.note or ''), a)


def cmd_decide(a):
    import service as sv
    owner_write(lambda: sv.decision_preview(a.disk, a.path, a.verdict),
                lambda: sv.add_decision(a.disk, a.path, a.verdict, a.note or ''), a)


def cmd_exclude(a):
    import service as sv
    owner_write(lambda: sv.exclusion_preview(a.disk, a.path), lambda: sv.add_exclusion(a.disk, a.path, a.note or ''), a)


def cmd_fix_manual(a):
    import service as sv
    rows = dict(manual_rows())
    if a.line not in rows:
        out(f'Строки {a.line} в «{MANUAL.name}» нет.')
        raise SystemExit(1)
    old = rows[a.line]
    out('Было: ' + ' | '.join(x for x in old[:6] if x))
    new = [a.date, a.action, a.disk, a.path, a.disk2 or '', a.path2 or '', old[6]]
    out('Станет: ' + ' | '.join(x for x in new[:6] if x))
    if not a.yes:
        out('Это предпросмотр. Исправить: та же команда с --yes (база соберётся заново, несколько минут).')
        return
    try:
        sv.fix_manual(a.line, new, a.reason)
    except sv.Refused as e:
        out('НЕ ИСПРАВЛЕНО: ' + str(e))
        raise SystemExit(1)
    out('Исправлено, причина записана в комментарий строки; база собрана заново.')


def cmd_tasks(a):
    import service as sv
    rows = sv.tasks()
    if not rows:
        out(f'Заданий нет в {TASKS}')
        return
    table(('задание', 'вид', 'состояние', 'строк', 'обработано', 'ошибок'),
          [(r['task'][:50], r['kind'], r['state'], r['total'], r['done'], r['errors']) for r in rows], limit=15)


def cmd_stats(a):
    c, jobs = connect()
    n, h = c.execute('select count(*), count(sha) from files').fetchone()
    rep = load_report(c)
    out(f'База собрана {c.execute("select value from meta where key=?", ("built",)).fetchone()[0]}: файлов {n}, '
        f'с подтверждённым SHA-256 {h}; носителей {len(jobs)}')
    for disk in MAIN:
        parts = [f'{ev} {k} ({gb(b)} ГБ)' for ev, k, b in
                 c.execute('select ev, count(*), sum(size) from files where disk=? group by ev order by 2 desc', (disk,))]
        out(f'  {disk}: ' + ', '.join(parts))
    out(f'  степени: S - хеш измерен сканером, C - скопировано скриптом с хешем; Z, U, X - НЕ подтверждено; N - без хеша')
    kinds = collections.Counter(r[0] for r in c.execute('select kind from applied'))
    out('Учтено модулей: ' + ', '.join(f'{k} - {v}' for k, v in sorted(kinds.items())))
    bad = c.execute("select count(*) from disks where status not like 'complete'").fetchone()[0]
    out(f'Описей с замечаниями (не «complete»): {bad}; непрочитанных мест: {c.execute("select count(*) from issues").fetchone()[0]}')
    out('Все найденные журналы учтены.' if not rep['skipped'] else
        f'НЕ УЧТЕНЫ журналы, которые программа не умеет читать: {len(rep["skipped"])}')
    if rep['old_logs'] or rep['old']:
        out(f'Не применено, потому что опись новее операции: строк журналов {sum(rep["old_logs"].values())}, '
            f'других операций {len(rep["old"])} (подробно - в файле ниже)')
    if rep['partial']:
        tot = collections.Counter()
        for folders in rep.get('partial_stats', {}).values():
            for k in folders.values():
                tot.update(k)
        conf = sum(v for k, v in tot.items() if k.startswith('было ') and k != 'было S')
        out(f'Частичные сканы папок: {len(rep["partial"])} папок, файлов {tot["файлов"]}; стало S {conf}, новые {tot["новые"]}, '
            f'исчезли {tot["исчезли"]}, хеш не совпал {tot["хеш не совпал"]}, пропущено по исключениям {tot["исключено"]}')
    out(f'Исключённых папок: {sum(len(v) for v in read_exclusions().values())}; ручных операций: {len(rep["manual"])}; '
        f'решений: {len(read_table(DECISIONS)) - 1}')
    warn = sorted(rep['warn'])
    for x in warn[:3]:
        out('ВНИМАНИЕ: ' + x)
    if len(warn) > 3:
        out(f'... и ещё предупреждений: {len(warn) - 3}')
    for _, x in sorted(rep['unique'].items()):
        out('ВНИМАНИЕ: ' + x)
    path = ANSWERS / 'сборка - подробно.txt'
    path.write_text('\n'.join(report_lines(c, rep)) + '\n', encoding='utf-8-sig')
    out(f'Подробно (журналы, сканы, модули): {path}')


def cmd_rebuild(a):
    """Полная пересборка с нуля и сверка с базой, собранной по шагам."""
    close_last()
    t0 = time.time()
    with BuildLock():
        ok, lines = rebuild(check=True)
    out(f'Пересборка с нуля: {time.time() - t0:.0f} с. Сверка с базой, собранной по шагам:')
    for x in lines:
        out('  ' + x)
    if ok is True:
        out('ИТОГ: совпала - сборка по шагам работает правильно.')
    elif ok is False:
        out('ИТОГ: НЕ СОВПАЛА - сборка по шагам дала другую базу; теперь действует собранная с нуля. Сообщите разработчику.')


def cmd_recovery_plan(a):
    import recovery_plan
    recovery_plan.cmd_recovery_plan(a, sys.modules[__name__])


def cmd_recovery_staging(a):
    import recovery_staging_audit as audit
    if not a.cached:
        audit.main()
    audit.refine_unhashed()


def cmd_family_plan(a):
    import copy_workflow
    copy_workflow.prepare(sys.modules[__name__], a)


def cmd_family_check(a):
    import copy_workflow
    result = copy_workflow.verify(a.task, preflight=a.preflight)
    if not result['ok']:
        raise SystemExit(2)


MAX_LINES = 20            # ответ команды на экран - не больше 20 строк (ТЗ v3, 6.2); остальное - в файл


class ShortAnswer(io.TextIOBase):
    """Поток вывода команды: на экран - первые строки и последние строки ответа (там итог и пути к файлам),
    всё целиком - в «ответы\\последний ответ.txt». Всего на экране не больше MAX_LINES строк."""

    def __init__(self, stream, path, limit=MAX_LINES, tail=6):
        self.stream, self.path, self.head, self.tail = stream, path, limit - tail - 1, tail
        self.lines, self.buf, self.shown, self.last = [], '', 0, collections.deque(maxlen=tail)

    def writable(self):
        return True

    def write(self, s):
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            self.lines.append(line)
            if self.shown < self.head:
                self.emit(line + '\n')
                self.shown += 1
            else:
                self.last.append(line)
        return len(s)

    def emit(self, text=''):
        """На экран; если вывод оборван (окно закрыто, канал закрыт читателем) - молча дальше, полный ответ в файле."""
        try:
            if text:
                self.stream.write(text)
            self.stream.flush()
        except (OSError, ValueError):
            pass

    def flush(self):
        self.emit()

    def close_answer(self):
        if self.buf:
            self.write('\n')
        hidden = len(self.lines) - self.shown - len(self.last)
        if hidden > 0:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text('\n'.join(self.lines) + '\n', encoding='utf-8-sig')
                where = f'полный ответ: {self.path}'
            except OSError:
                where = 'полный ответ сохранить не удалось'
            self.emit(f'... ещё {hidden} строк не показано - {where}\n')
        for line in self.last:
            self.emit(line + '\n')
        self.emit()


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('missing', 'only'):
        p = sub.add_parser(name)
        p.add_argument('disk'); p.add_argument('folder', nargs='?', default='')
        p.add_argument('--depth', type=int, default=1)
    p = sub.add_parser('cmp')
    p.add_argument('disk_a'); p.add_argument('folder_a'); p.add_argument('disk_b'); p.add_argument('folder_b')
    p = sub.add_parser('where'); p.add_argument('disk'); p.add_argument('path')
    p = sub.add_parser('candel'); p.add_argument('disk'); p.add_argument('folder')
    p = sub.add_parser('mklist')
    p.add_argument('disk'); p.add_argument('--to', nargs='+', default=list(MAIN)); p.add_argument('--name', required=True)
    p.add_argument('--folder', action='append')
    p.add_argument('--dry', action='store_true', help='только посчитать, папку задачи не создавать')
    p.add_argument('--section', help='собрать только файлы с этим решением, например "раздел: Оцифрованные источники"')
    p.add_argument('--all', action='store_true', help='не учитывать разделы и отсрочки (решение «не нужно» учитывается всегда)')
    p.add_argument('--source-folder', help='копировать из этой папки диска; путь в списке - от неё (шаблон 2.2)')
    p.add_argument('--as', dest='as_name', help='имя источника в тома.tsv и в папке на цели (по умолчанию - номер диска)')
    p.set_defaults(task_root='scripts')
    p = sub.add_parser('mvlist', help='задание «Переместить на источнике» по подтверждённым копиям на 45 и 77')
    p.add_argument('disk'); p.add_argument('--name', required=True)
    p.add_argument('--folder', action='append')
    p.add_argument('--dry', action='store_true', help='только посчитать, папку задания не создавать')
    p.set_defaults(task_root='scripts')
    for name, hlp in (('manual', 'записать, что владелец сделал в Проводнике'), ('fix-manual', 'исправить ошибочную строку ручных операций')):
        p = sub.add_parser(name, help=hlp)
        if name == 'fix-manual':
            p.add_argument('line', type=int); p.add_argument('--reason', required=True)
        p.add_argument('date'); p.add_argument('action', choices=['удалено', 'скопировано', 'перемещено'])
        p.add_argument('disk'); p.add_argument('path'); p.add_argument('disk2', nargs='?'); p.add_argument('path2', nargs='?')
        p.add_argument('--note'); p.add_argument('--yes', action='store_true', help='записать (без него - только предпросмотр)')
    p = sub.add_parser('decide', help='записать решение владельца по папке')
    p.add_argument('disk'); p.add_argument('path'); p.add_argument('verdict'); p.add_argument('--note')
    p.add_argument('--yes', action='store_true')
    p = sub.add_parser('exclude', help='папка, которую база не учитывает (временная копия)')
    p.add_argument('disk'); p.add_argument('path'); p.add_argument('--note'); p.add_argument('--yes', action='store_true')
    sub.add_parser('tasks', help='задания в «Запускаемые скрипты» и их состояние')
    sub.add_parser('build', help='применить новые модули (журналы, сканы, ручные операции) и показать сводку')
    sub.add_parser('stats', help='что в базе и какие модули учтены')
    p = sub.add_parser('folders', help='сколько занимают папка и её подпапки, по типам файлов')
    p.add_argument('disk'); p.add_argument('folder', nargs='?', default='')
    p.add_argument('--depth', type=int, default=1)
    p = sub.add_parser('find', help='папки, в пути которых есть слова (например «Сафари»)')
    p.add_argument('words', nargs='+'); p.add_argument('--disk')
    sub.add_parser('rebuild', help='самопроверка: собрать базу с нуля и сверить с собранной по шагам (минуты)')
    p = sub.add_parser('family-plan', help='план семейного копирования и проверки HDD51')
    p.add_argument('disk')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--snapshot', type=Path, help='сохранённое оглавление; повторного обхода не будет')
    p.add_argument('--manual-evidence', type=Path, help='конкретные ручные копирования из журнала операций')
    p = sub.add_parser('family-check', help='журнал и фактические пути/размеры двух копий; без хеширования целей')
    p.add_argument('--task', type=Path, required=True)
    p.add_argument('--preflight', action='store_true')
    p = sub.add_parser('recovery-plan', help='разбор оглавления восстановленной папки, без чтения содержимого')
    p.add_argument('disk'); p.add_argument('--root', type=Path, required=True)
    p.add_argument('--cached', action='store_true', help='обновить разметку сохранённого оглавления, без обращения к диску')
    p = sub.add_parser('recovery-staging', help='остаток восстановлений К/Н вне F, 45 и 77; только метаданные')
    p.add_argument('--cached', action='store_true', help='работать только с сохранёнными оглавлениями')
    a = ap.parse_args()
    t0 = time.time()
    real, ans = sys.stdout, ShortAnswer(sys.stdout, ANSWERS / 'последний ответ.txt')
    sys.stdout = ans
    try:
        run_command(a)
        out(f'[{time.time() - t0:.1f} с]')
    finally:
        sys.stdout = real
        ans.close_answer()


def run_command(a):
    if a.cmd == 'build':
        build()
        cmd_stats(a)
    else:
        {'missing': cmd_missing, 'only': lambda x: cmd_missing(x, True), 'cmp': cmd_cmp, 'where': cmd_where,
         'candel': cmd_candel, 'mklist': cmd_mklist, 'stats': cmd_stats, 'rebuild': cmd_rebuild, 'folders': cmd_folders, 'find': cmd_find, 'mvlist': cmd_mvlist, 'manual': cmd_manual, 'fix-manual': cmd_fix_manual, 'decide': cmd_decide, 'exclude': cmd_exclude, 'tasks': cmd_tasks, 'recovery-plan': cmd_recovery_plan,
         'recovery-staging': cmd_recovery_staging, 'family-plan': cmd_family_plan, 'family-check': cmd_family_check}[a.cmd](a)


if __name__ == '__main__':
    main()
