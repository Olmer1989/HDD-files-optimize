"""Сервис над hashbase: единственный путь записи в таблицы владельца и данные для окна программы.

Записи владельца (ручные операции, решения, исключения) делают ТОЛЬКО эти функции - из окна, из командной
строки и из чата (через команды hashbase.py manual / decide / exclude). Каждая запись:
  1. проверяет формат и смысл (диск есть в базе, путь есть в базе, такой же строки ещё нет);
  2. показывает предпросмотр: сколько файлов базы затронет и примеры путей;
  3. под замком таблиц кладёт копию таблицы в «_БАЗА\\архив таблиц» и дописывает ОДНУ целую строку;
  4. сразу применяет её к базе (сборщик берёт только новые строки; если программа упадёт между шагами 3 и 4,
     следующая команда применит строку сама - строка уже является модулем).
Строку, записанную по ошибке, исправляет fix_manual: старая строка заменяется, причина пишется в комментарий,
база собирается заново целиком (изменённый модуль) - так ошибка не остаётся в учёте навсегда.
"""
import collections
import io
import os
import re
import shutil
import sqlite3
import stat as stat_mod
import subprocess
import sys
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

SEP = '\\'
ACTIONS = ('удалено', 'скопировано', 'перемещено')
VERDICT_RE = re.compile(r'^(не нужно|раздел: .+|пока не трогаем)$')
DATE_RE = re.compile(r'^\d\d\.\d\d\.\d{4}$')
BACKUPS_KEEP = 200


class Refused(Exception):
    """Запись не сделана: причина понятна владельцу."""


# ---------- замок, копия, дописывание ----------

class TableLock:
    """Одна запись в таблицы владельца за раз (окно, командная строка, чат)."""

    def __enter__(self):
        hb.BASE_DIR.mkdir(parents=True, exist_ok=True)
        self.f = open(hb.BASE_DIR / 'таблицы.lock', 'a+b')
        try:
            import msvcrt
        except ImportError:
            return self
        for _ in range(120):
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                self.locked = True
                return self
            except OSError:
                time.sleep(0.5)
        self.f.close()
        raise Refused('Таблицы сейчас записывает другая программа дольше минуты. Повторите позже.')

    def __exit__(self, *exc):
        try:
            if getattr(self, 'locked', False):
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self.f.close()


def backup(path):
    """Копия таблицы перед записью: «_БАЗА\\архив таблиц\\<имя> <время>.tsv», хранятся последние 200."""
    path = Path(path)
    if not path.exists():
        return None
    arch = hb.BASE_DIR / 'архив таблиц'
    arch.mkdir(exist_ok=True)
    dst = arch / f'{path.stem} {time.strftime("%Y-%m-%d %H-%M-%S")}-{time.perf_counter_ns() % 1000000:06d}{path.suffix}'
    shutil.copy2(path, dst)
    old = sorted(arch.glob(f'{path.stem} *{path.suffix}'))
    for p in old[:-BACKUPS_KEEP]:
        p.unlink()
    return dst


def append_rows(path, rows):
    """Дописать целые строки ОДНОЙ записью на диск (write + fsync). Номер первой новой строки в файле - в ответе.
    Проверки - до записи: при отказе файл не тронут."""
    for fields in rows:
        for x in fields:
            if '\t' in x or '\n' in x or '\r' in x:
                raise Refused('В тексте не должно быть табуляции и переводов строки.')
    data = Path(path).read_bytes() if Path(path).exists() else b''
    if data and not data.endswith(b'\n'):
        raise Refused(f'Последняя строка {Path(path).name} не закончена (её кто-то пишет или файл испорчен). '
                      'Запись остановлена, файл не тронут.')
    eol = '\r\n' if b'\r\n' in data[-400:] else '\n'
    block = ''.join('\t'.join(fields) + eol for fields in rows).encode('utf-8')
    with open(path, 'ab') as f:
        f.write(block)
        f.flush()
        os.fsync(f.fileno())
    return len([x for x in data.decode('utf-8-sig', errors='replace').splitlines() if x.strip()]) + 1


def append_row(path, fields):
    """Дописать одну целую строку (одной записью на диск). Номер новой строки в файле - в ответе."""
    return append_rows(path, [fields])


# ---------- проверки ----------

def check_rel(path, what='путь'):
    p = (path or '').strip().strip(SEP)
    if not p or ':' in p or '/' in p or (SEP + p + SEP).find(SEP + '..' + SEP) >= 0:
        raise Refused(f'Недопустимый {what} «{path}»: нужен путь от корня диска без буквы, например «Фото\\2014».')
    return p


def db():
    return hb.connect()[0]


def check_disk(c, disk):
    if not c.execute('select 1 from disks where disk=?', (disk,)).fetchone():
        raise Refused(f'Носителя {disk} нет в базе.')


def files_under(c, disk, path, limit=3):
    """Сколько записей базы лежит по пути (сам файл или всё внутри папки - не соседние имена) и примеры."""
    cond, args = hb.prefix_cond('path', path)
    n, size = c.execute(f'select count(*), coalesce(sum(size), 0) from files where disk=? and {cond}', [disk] + args).fetchone()
    sample = [r[0] for r in c.execute(f'select path from files where disk=? and {cond} limit ?', [disk] + args + [limit])]
    return n, size, sample


# ---------- записи владельца ----------

def manual_preview(date, act, disk, path, disk2='', path2='', c=None):
    """Что изменит ручная операция. Исключение Refused - если записывать нельзя. c - уже открытое соединение
    (пакетная запись проверяет все строки по одной базе)."""
    act = (act or '').strip().lower()
    if act not in ACTIONS:
        raise Refused(f'Действие должно быть одним из: {", ".join(ACTIONS)}.')
    if not DATE_RE.match(date or ''):
        raise Refused('Дата - в виде ДД.ММ.ГГГГ, например 14.11.2026.')
    c = c or db()
    check_disk(c, disk)
    path = check_rel(path)
    if act != 'удалено':
        check_disk(c, disk2)
        path2 = check_rel(path2, 'путь назначения')
    else:
        disk2 = path2 = ''
    n, size, sample = files_under(c, disk, path)
    if not n:
        raise Refused(f'В базе нет файлов по пути {disk}\\{path}. Проверьте номер диска и путь (папку можно '
                      'выбрать и на отключённом диске - из каталога базы).')
    for ln, f in hb.manual_rows():
        if [x.strip() for x in f[:6]] == [date, act, disk, path, disk2, path2]:
            raise Refused(f'Такая операция уже записана (строка {ln}). Повторно не записываю.')
    lines = [f'{date} {act}: {disk}\\{path}' + (f' -> {disk2}\\{path2}' if disk2 else ''),
             f'Затронет записей базы: {n}, {hb.gb(size)} ГБ. Например: ' + '; '.join(sample)]
    if disk2:
        m, _, _ = files_under(c, disk2, path2)
        if m:
            lines.append(f'ВНИМАНИЕ: в {disk2}\\{path2} в базе уже есть {m} записей - одинаковые пути будут заменены.')
        lines.append('Копия «со слов» получает степень U (не подтверждена): удалять оригинал по ней нельзя.'
                     if act == 'скопировано' or disk2 != disk else 'Перемещение внутри диска: хеш и степень сохраняются.')
    return dict(fields=[date, act, disk, path, disk2, path2], lines=lines, files=n)


def add_manual(date, act, disk, path, disk2='', path2='', note='', apply=True):
    with TableLock():
        pv = manual_preview(date, act, disk, path, disk2, path2)
        hb.ensure_tables()
        backup(hb.MANUAL)
        ln = append_row(hb.MANUAL, pv['fields'] + [note or ''])
    pv['line'] = ln
    if apply:
        hb.close_last()
        hb.update(quiet=True)
    return pv


def add_manual_batch(date, rows, note='', apply=True):
    """Пакетная запись ручных операций (окно «Я сделал в Проводнике»): rows - [(действие, диск, путь, диск2, путь2)].
    Всё или ничего: под одним замком таблиц все строки проверяются заранее (как manual_preview каждой, плюс нет
    повторов внутри пакета), затем одна копия таблицы в архив, все строки - одной записью на диск, одно применение к
    базе. При любой ошибке не пишется ничего. Ответ: [(поля, номер строки в файле)]."""
    rows = [tuple((list(r) + [''] * 5)[:5]) for r in rows]
    if not rows:
        raise Refused('Ничего не отмечено.')
    with TableLock():
        c = db()
        fields, seen = [], set()
        for r in rows:
            try:
                pv = manual_preview(date, *r, c=c)
            except Refused as e:
                raise Refused(f'{r[1]}{SEP}{r[2]}: {e} Ничего не записано.')
            key = tuple(pv['fields'])
            if key in seen:
                raise Refused(f'{r[1]}{SEP}{r[2]}: эта операция в пакете дважды. Ничего не записано.')
            seen.add(key)
            fields.append(pv['fields'] + [note or ''])
        hb.ensure_tables()
        hb.close_last()
        backup(hb.MANUAL)
        first = append_rows(hb.MANUAL, fields)
    if apply:
        hb.close_last()
        hb.update(quiet=True)
    return [(f, first + i) for i, f in enumerate(fields)]


def fix_manual(line_no, fields, reason):
    """Исправить ошибочно записанную строку: заменить её, причину - в комментарий; база соберётся заново."""
    if not reason:
        raise Refused('Нужна причина исправления.')
    with TableLock():
        lines = hb.MANUAL.read_bytes().decode('utf-8-sig').split('\n')
        idx = [i for i, x in enumerate(lines) if x.strip()]
        if line_no < 2 or line_no > len(idx):
            raise Refused(f'Строки {line_no} нет.')
        backup(hb.MANUAL)
        i = idx[line_no - 1]
        eol = '\r' if lines[i].endswith('\r') else ''
        old = lines[i].rstrip('\r').split('\t')
        note = (fields[6] if len(fields) > 6 else '') + f' | исправлено {time.strftime("%d.%m.%Y")}: {reason}; было: {" / ".join(old[:6])}'
        lines[i] = '\t'.join(fields[:6] + [note]) + eol
        data = '\n'.join(lines).encode('utf-8-sig')
        hb.MANUAL.write_bytes(data)
    hb.close_last()
    hb.update(quiet=True)


def decision_preview(disk, path, verdict):
    verdict = (verdict or '').strip()
    if hb.is_v3_mark(verdict):                    # отметки разбора v3 - та же проверка, что у пакета отметок
        pv = marks_preview(disk, [(path, verdict)])
        return dict(fields=pv['fields'][0], lines=pv['lines'])
    if not VERDICT_RE.match(verdict):
        raise Refused('Решение: «не нужно», «раздел: <название>», «пока не трогаем» или (разбор v3) '
                      '«направление: <номер или имя>», «не копировать», «как у родителя».')
    c = db()
    if disk != '*':
        check_disk(c, disk)
    if path.lower().startswith('класс:'):
        n, size, sample = 0, 0, []
    else:
        path = check_rel(path)
        n, size, sample = files_under(c, disk, path) if disk != '*' else (0, 0, [])
        if disk != '*' and not n:
            raise Refused(f'В базе нет файлов по пути {disk}\\{path}.')
    for f in hb.read_table(hb.DECISIONS)[1:]:
        f = [x.strip() for x in f] + ['', '', '']
        if f[:3] == [disk, path, verdict]:
            raise Refused('Такое решение уже записано.')
    return dict(fields=[disk, path, verdict],
                lines=[f'{disk}\\{path}: {verdict}', f'Под решение попадает записей базы: {n}, {hb.gb(size)} ГБ'])


def add_decision(disk, path, verdict, note=''):
    if hb.is_v3_mark(verdict):
        pv = add_marks_batch(disk, [(path, verdict)], note)
        pv['fields'] = pv['fields'][0]
        return pv
    with TableLock():
        pv = decision_preview(disk, path, verdict)
        hb.ensure_tables()
        backup(hb.DECISIONS)
        pv['line'] = append_row(hb.DECISIONS, pv['fields'] + [note or ''])
    return pv                       # решения читаются при каждом ответе - применять к базе нечего


def exclusion_preview(disk, path):
    c = db()
    check_disk(c, disk)
    path = check_rel(path)
    for d, folders in hb.read_exclusions().items():
        if d == disk and path in folders:
            raise Refused('Эта папка уже в исключениях.')
    n, size, sample = files_under(c, disk, path)
    return dict(fields=[disk, path], lines=[f'Исключить {disk}\\{path}: база перестанет учитывать {n} записей, '
                                            f'{hb.gb(size)} ГБ (их список сохранится в таблице excluded).'])


def add_exclusion(disk, path, note=''):
    with TableLock():
        pv = exclusion_preview(disk, path)
        hb.ensure_tables()
        backup(hb.EXCLUSIONS)
        pv['line'] = append_row(hb.EXCLUSIONS, pv['fields'] + [note or ''])
    hb.close_last()
    hb.update(quiet=True)
    return pv


# ---------- чтение для окна: каждое обращение - своё соединение только для чтения ----------

def ro():
    """Соединение только для чтения на один запрос. Окно не держит базу открытой: пересборке ничто не мешает."""
    if not hb.DB.exists():
        raise Refused('База ещё собирается - подождите.')
    return sqlite3.connect(f'file:{hb.DB.as_posix()}?mode=ro', uri=True, timeout=30)


def generation():
    """Поколение базы - время её сборки; меняется после каждого применения модулей."""
    if not hb.DB.exists():
        return None
    c = ro()
    try:
        r = c.execute("select value from meta where key='built'").fetchone()
        return r[0] if r else None
    finally:
        c.close()


def volumes():
    """Подключённые сейчас тома: серийный номер -> буква. Сетевые диски пропускаются, диски не читаются."""
    import ctypes
    k32 = ctypes.windll.kernel32
    res = {}
    mask = k32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f'{chr(65 + i)}:\\'
        if k32.GetDriveTypeW(root) in (0, 1, 4):          # неизвестный, нет корня, сетевой
            continue
        ser = ctypes.c_ulong()
        if k32.GetVolumeInformationW(root, None, 0, ctypes.byref(ser), None, None, None, 0):
            res[f'{ser.value:08X}'] = root[:2]
    return res


def disks():
    """Таблица носителей: номер, метка, подключён ли (буква), файлов, ГБ, опись от, состояние, частичных сканов."""
    jobs = bp.find_jobs()
    serial_of = {v: k for k, v in hb.serial_map(jobs).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    c = ro()
    try:
        rows = []
        size = dict(c.execute("select disk, bytes from folders where folder=''"))
        parts = collections.Counter(r[0] for r in c.execute('select disk from scan_folders'))
        for d, label, total, status, scanned in c.execute('select disk, label, total, status, scanned from disks order by disk'):
            rows.append(dict(disk=d, label=label.split(' - ', 1)[-1] if label else '', letter=vols.get(serial_of.get(d, '?'), ''),
                             files=total, gib=(size.get(d) or 0) / hb.GIB, status=status,
                             scanned=time.strftime('%d.%m.%Y', time.localtime(scanned)) if scanned else '',
                             partial=parts.get(d, 0)))
        return rows
    finally:
        c.close()


EV_COLS = (hb.EV_SCAN, hb.EV_COPY, hb.EV_SIZE, hb.EV_USER, hb.EV_STALE)
TASK_ATTENTION = ('готово с ошибками', 'прервано', 'состояние неизвестно')     # «идёт» - не ошибка


def direction_disks(dirs=None):
    """Диски всех направлений, у которых есть диск, по порядку направлений (без повторов)."""
    dirs = directions() if dirs is None else dirs
    return list(dict.fromkeys(x for d in dirs.values() for x in d.disks))


def _unique_from_list(disk):
    """База собрана до 16.11.2026 (в отчёте нет unique_info): числа - из того же файла списка, колонки по заголовку."""
    import csv
    path = hb.ANSWERS / (re.sub(r'[\\/:*?"<>|]', '_', f'исключения - больше нигде нет - {disk}') + '.tsv')
    if not path.exists():
        return dict(disk=disk, missing=True)
    try:
        with open(path, encoding='utf-8-sig', newline='') as f:
            rows = list(csv.reader(f, delimiter='\t'))
    except OSError:
        return dict(disk=disk, missing=True)
    head = rows[0] if rows else []
    if 'путь' not in head or 'размер' not in head:
        return dict(disk=disk, list=str(path), files=None)
    i_p, i_s, i_t = head.index('путь'), head.index('размер'), head.index('тип') if 'тип' in head else None
    body = [r for r in rows[1:] if len(r) > max(i_p, i_s)]
    size = sum(int(r[i_s]) for r in body if r[i_s].isdigit())
    small = sum(1 for r in body if i_t is not None and len(r) > i_t and r[i_t] == bp.T_SMALL)
    nohash = sum(1 for r in body if os.path.splitext(r[i_p])[1].lower() in hb.NOHASH_VIDEO)
    return dict(disk=disk, files=len(body), bytes=size, small=small, nohash=nohash, list=str(path))


def overview(disks=None):
    """Сводка для экрана «Обзор» (второй круг, 16.11.2026).
    disks_info - по каждому диску направлений (все направления с диском; окно само отбирает отмеченные): буква («»),
    свободно (ГиБ, если подключён), объём файлов (ГиБ), есть ли в базе, ev - число записей по степеням S/C/Z/U/X.
    Один запрос по files на все диски (первичный ключ disk, path - читается только диапазон этих дисков).
    unique - «файлы, которых больше нигде нет»: [dict(disk, files, bytes, small, nohash, list)] (list - путь к файлу
    списка; нет файла - missing=True); skipped - журналы, которые программа не прочитала; warn - прочие предупреждения."""
    disks = direction_disks() if disks is None else list(disks)
    c = ro()
    try:
        rep = hb.load_report(c)
        res = dict(built=c.execute("select value from meta where key='built'").fetchone()[0],
                   files=c.execute("select sum(total) from disks").fetchone()[0], disks=c.execute('select count(*) from disks').fetchone()[0],
                   warn=sorted(rep['warn']), skipped=list(rep['skipped']), disks_info={})
        info = {d: dict(ev={}, gib=0.0, in_base=False, letter='') for d in disks}
        if disks:
            q = ','.join('?' * len(disks))
            for d, in c.execute(f'select disk from disks where disk in ({q})', disks):
                info[d]['in_base'] = True
            for d, ev, n in c.execute(f'select disk, ev, count(*) from files where disk in ({q}) group by disk, ev', disks):
                info[d]['ev'][ev] = n
            for d, b in c.execute(f"select disk, bytes from folders where folder='' and disk in ({q})", disks):
                info[d]['gib'] = (b or 0) / hb.GIB
        res['disks_info'] = info
        uinfo = rep.get('unique_info') or {}
        res['unique'] = [dict(uinfo[d], disk=d) if d in uinfo else _unique_from_list(d) for d in sorted(rep['unique'])]
    finally:
        c.close()
    jobs = bp.find_jobs()
    serial_of = {v: k for k, v in hb.serial_map(jobs).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    for d, m in res['disks_info'].items():
        letter = vols.get(serial_of.get(d, '?'))
        m['letter'] = letter or ''
        if letter:
            try:
                m['free_gib'] = shutil.disk_usage(letter + '\\').free / hb.GIB
            except OSError:
                pass
    res['checked'] = time.strftime('%H:%M:%S')
    return res


def attention(ov, tasks):
    """«Требует внимания» по видам; пустые группы не включаются. -> [dict(key, title, items)]."""
    groups = []
    bad = [dict(task=t['task'], state=t['state'], done=t['done'], total=t['total'], errors=t['errors'])
           for t in tasks if t['state'] in TASK_ATTENTION or (t['errors'] and t['state'] != 'не запускалось')]
    for key, title, items in (('tasks', 'Задания с ошибками или прерванные', bad),
                              ('logs', 'Журналы, которые программа не смогла прочитать', list(ov.get('skipped') or [])),
                              ('unique', 'Файлы, которых больше нигде нет', list(ov.get('unique') or [])),
                              ('warn', 'Прочие предупреждения базы', list(ov.get('warn') or []))):
        if items:
            groups.append(dict(key=key, title=title, items=items))
    return groups


def folder_children(disk, folder=''):
    """Подпапки папки (по готовой таблице folders): имя, путь, файлов, ГБ, ГБ по типам, решение владельца."""
    folder = (folder or '').strip(SEP)
    depth = (folder.count(SEP) + 1 if folder else 0) + 1
    cond, args = hb.prefix_cond('folder', folder)
    decs = hb.decisions_for(disk)
    c = ro()
    try:
        q = (f'select folder, files, bytes, ' + ', '.join(f'b{i}' for i in range(5)) +
             f' from folders where disk=? and depth=? and {cond} order by bytes desc')
        res = []
        for r in c.execute(q, [disk, depth] + args):
            res.append(dict(path=r[0], name=r[0].rsplit(SEP, 1)[-1], files=r[1], gib=r[2] / hb.GIB,
                            types=[x / hb.GIB for x in r[3:8]], decision=hb.decision_of(r[0], decs) or ''))
        return res
    finally:
        c.close()


def folder_presence(disk, folder):
    """Чего из папки нет на 45 и 77 (файлы с SHA-256 любого типа, по таблице presence; решения не учитываются)."""
    cond, args = hb.prefix_cond('f.path', (folder or '').strip(SEP))
    c = ro()
    try:
        q = f"""select count(*), coalesce(sum(f.size),0),
                       coalesce(sum(case when not coalesce(p.e45 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when not coalesce(p.e77 in ('S','C'),0) then f.size end),0),
                       coalesce(sum(case when p.ndisks=1 then f.size end),0)
                from files f join presence p on p.sha=f.sha where f.disk=? and f.sha is not null and {cond}"""
        n, b, no45, no77, only = c.execute(q, [disk] + args).fetchone()
        nohash = c.execute(f"select count(*) from files f where f.disk=? and f.sha is null and {cond}", [disk] + args).fetchone()[0]
        return dict(files=n, gib=b / hb.GIB, no45=no45 / hb.GIB, no77=no77 / hb.GIB, only=only / hb.GIB, nohash=nohash)
    finally:
        c.close()


def _day(t):
    return time.strftime('%d.%m.%Y', time.localtime(t)) if t else 'дата неизвестна'


def _log_day(name):
    m = re.search(r'(\d{4})-(\d\d)-(\d\d)', name or '')
    return f'{m.group(3)}.{m.group(2)}.{m.group(1)}' if m else 'дата неизвестна'


_n = lambda n: f'{n:,}'.replace(',', ' ')

HASH_HINT = 'Сомневаетесь? «Пересканировать папку…» с галочкой «Перечитать всё».'


def hash_dates(disk, folder):
    """Когда измерены хеши файлов папки - по происхождению строк базы (origin) и, для частичных сканов, по таблице
    hash_info их hashes.sqlite. Считается при ответе, база не меняется. Дата частичного скана - время его описи;
    «взято из прежнего скана» - хеш не перечитывался (правило доверия), «измерены не раньше» - начало задания,
    которое действительно прочитало файл (bound_ns). Нет сведений - «дата неизвестна».
    -> dict(text=одна строка, hint=подсказка, parts=[...], nohash=число)."""
    folder = (folder or '').strip(SEP)
    cond, args = hb.prefix_cond('path', folder)
    c = ro()
    try:
        groups = c.execute(f'select origin, count(*), count(sha) from files where disk=? and {cond} group by origin',
                           [disk] + args).fetchall()
        scanned = (c.execute('select scanned from disks where disk=?', (disk,)).fetchone() or [None])[0]
    finally:
        c.close()
    nohash = sum(n - h for _, n, h in groups)
    partials = {pj['name']: pj for pj in hb.find_partials()} if any((o or '').startswith('частичный скан') for o, _, _ in groups) else {}
    parts, logs, manual = [], [0, set()], 0
    for origin, n, h in sorted(groups, key=lambda g: g[0] or ''):
        origin = origin or ''
        if not h:
            continue
        if origin == 'опись':
            parts.append((scanned or 0, f'{_day(scanned)} - полная опись ({_n(h)} файлов)'))
        elif origin.startswith('частичный скан: '):
            name = origin.split(': ', 1)[1]
            pj = partials.get(name)
            reused, bounds = None, []
            if pj and (pj['dir'] / 'hashes.sqlite').exists():
                try:
                    hc = sqlite3.connect(f'file:{(pj["dir"] / "hashes.sqlite").as_posix()}?mode=ro', uri=True)
                    try:
                        if hc.execute("select 1 from sqlite_master where name='hash_info'").fetchone():
                            hcond, hargs = hb.prefix_cond('path', folder)
                            reused, b0, b1 = hc.execute(
                                f"select count(*), min(bound_ns), max(bound_ns) from hash_info where how='reused' and {hcond}",
                                hargs).fetchone()
                            bounds = [x for x in (b0, b1) if x]
                    finally:
                        hc.close()
                except sqlite3.Error:
                    reused = None
            extra = ''
            if reused is None:
                extra = ', сколько взято из прежнего скана - неизвестно'
            elif reused:
                days = sorted({_day(b / 1e9) for b in bounds}, key=lambda d: d[6:] + d[3:5] + d[:2])
                extra = (f', из них взято из прежнего скана {_n(reused)}'
                         + (f' (измерены не раньше {"–".join(days)})' if days else ''))
            parts.append((pj['time'] if pj else 0,
                          f'{_day(pj["time"]) if pj else "дата неизвестна"} - пересканирование ({_n(h)} файлов'
                          + extra + ')'))
        elif origin.startswith('журнал: '):
            logs[0] += h
            logs[1].add(_log_day(origin))
        else:
            manual += h
    if logs[0]:
        days = sorted(logs[1], key=lambda d: d[6:] + d[3:5] + d[:2])
        parts.append((1e12, f'{", ".join(days[:3])}{"…" if len(days) > 3 else ""} - копирование шаблоном '
                      f'(хеш прочитанных байтов, {_n(logs[0])} файлов)'))
    if manual:
        parts.append((2e12, f'другие записи ({manual} файлов)'))
    parts.sort(key=lambda x: x[0])
    text = ('Хеши измерены: ' + '; '.join(p for _, p in parts) + '.') if parts else 'Хешей у файлов этой папки нет.'
    if nohash:
        text += f' Без хеша: {_n(nohash)} файлов.'
    return dict(text=text, hint=HASH_HINT, parts=[p for _, p in parts], nohash=nohash)


def find_folders(words, disk=None, limit=300):
    """Папки, в пути которых есть все слова (только верхние совпадения), по таблице folders."""
    words = [w.lower() for w in words if w.strip()]
    if not words:
        return []
    q = 'select disk, folder, files, bytes from folders where ' + ' and '.join(['instr(folder_lc, ?) > 0'] * len(words))
    args = list(words)
    if disk:
        q += ' and disk=?'
        args.append(disk)
    c = ro()
    try:
        rows = c.execute(q, args).fetchall()
    finally:
        c.close()
    hits = {(r[0], r[1]) for r in rows}
    top = [r for r in rows if r[1] and (r[0], hb.parent_of(r[1])) not in hits]
    top.sort(key=lambda r: -r[3])
    return [dict(disk=d, path=f, files=n, gib=b / hb.GIB) for d, f, n, b in top[:limit]]


def sources_signature():
    """Быстрая подпись первоисточников (размеры и время таблиц, журналов, описей) - чтобы окно знало,
    что пора применить новые модули. Диски не читаются."""
    sig = []
    for p in [hb.MANUAL, hb.DECISIONS, hb.EXCLUSIONS] + [Path(x) for x in hb.journal_paths()]:
        try:
            st = Path(p).stat()
            sig.append((str(p), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for j in bp.find_jobs().values():
        try:
            st = (j['dir'] / 'inventory.sqlite').stat()
            sig.append((str(j['dir']), st.st_size, st.st_mtime_ns))
        except OSError:
            pass
    for pj in hb.find_partials():
        sig.append((str(pj['dir']), pj['time']))
    return hash(tuple(sorted(sig)))


# ---------- пересканирование выбранных папок (сканер 1.4.0) ----------

SCANNER = Path(__file__).resolve().parent.parent / 'scanner'


def _scanner():
    """Модули сканера (rescan - правило доверия прежнему хешу, inventory - сведения о томе)."""
    if str(SCANNER) not in sys.path:
        sys.path.insert(0, str(SCANNER))
    import rescan
    import inventory
    return rescan, inventory


def disk_letter(disk):
    """Буква подключённого носителя - по серийному номеру тома из его полной описи. Диск не читается."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    if disk not in serial_of:
        raise Refused(f'У {disk} нет полной описи - пересканировать папки нельзя.')
    try:
        letter = volumes().get(serial_of[disk])
    except (OSError, AttributeError):
        letter = None
    if not letter:
        raise Refused(f'{disk} не подключён: подключите диск (буква найдётся сама по серийному номеру тома).')
    return letter


def rescan_plan(disk, folders, rehash_all=False):
    """Предпросмотр пересканирования по оглавлению диска: сколько файлов прочитать, сколько хешей взять из
    прежней описи, сколько исчезло. Содержимое файлов не читается."""
    letter = disk_letter(disk)
    rescan, inventory = _scanner()
    try:
        fs = inventory.volume(letter + '\\')[2]
        plan = rescan.plan(letter + '\\', disk, list(folders), bp.SCAN_ROOTS, rehash_all, fs)
    except (ValueError, OSError) as e:
        raise Refused(str(e))
    plan.update(letter=letter, filesystem=fs, lines=rescan.plan_text(plan))
    if fs.upper() != 'NTFS':
        plan['lines'].insert(1, f'Файловая система {fs}: прежним хешам не доверяем, читается всё.')
    return plan


def rescan_files(disk):
    """Файлы хода и остановки сканирования - в «_БАЗА\\пересканирование»."""
    d = hb.BASE_DIR / 'пересканирование'
    d.mkdir(parents=True, exist_ok=True)
    return d / f'{disk} ход.json', d / f'{disk} стоп.txt', d / f'{disk} вывод.txt'


def scanner_python():
    exe = Path(sys.executable)
    return str(exe.with_name('python.exe')) if exe.name.lower() == 'pythonw.exe' and exe.with_name('python.exe').exists() else str(exe)


def rescan_argv(disk, letter, folders, rehash_all=False, job=None):
    """Командная строка сканера (то же можно запустить вручную в консоли). job - продолжить это задание."""
    progress, stop, _ = rescan_files(disk)
    argv = [scanner_python(), '-X', 'utf8', '-u', str(SCANNER / 'portable.py'), '--progress-file', str(progress),
            '--stop-file', str(stop)]
    if job:
        return argv + ['resume', str(job)]
    argv += ['start', '--disk', disk, '--letter', letter.rstrip(':\\')]
    for f in folders:
        argv += ['--folder', f]
    argv += ['--output', str(Path(bp.SCAN_ROOTS[0]) / hb.PARTIAL_DIR), '--yes']
    for r in bp.SCAN_ROOTS:
        argv += ['--prior-root', str(r)]
    return argv + ['--hash-all-types'] + (['--rehash-all'] if rehash_all else [])     # хеш у всех файлов - явно


def rescan_start(disk, letter, folders, rehash_all=False, job=None):
    """Запуск сканера отдельным процессом без консоли - ТОЛЬКО по кнопке владельца после подтверждения."""
    progress, stop, log = rescan_files(disk)
    for p in (progress, stop):
        if p.exists():
            p.unlink()
    out = open(log, 'a' if job else 'w', encoding='utf-8')
    env = os.environ.copy()
    env.update(PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
    proc = subprocess.Popen(rescan_argv(disk, letter, folders, rehash_all, job), cwd=str(SCANNER), env=env,
                            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    out.close()
    return proc


def read_progress(disk):
    try:
        import json
        return json.loads(rescan_files(disk)[0].read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def partial_outcome(job_name):
    """Итог приёма частичного скана базой: по каждой папке - в скане, стало S, новые, исчезли, хеш не совпал."""
    c = ro()
    try:
        rep = hb.load_report(c)
    finally:
        c.close()
    stats = (rep.get('partial_stats') or {}).get(job_name)
    warn = sorted(w for w in rep['warn'] if job_name in w) + [x for x in rep['old'] if job_name in x]
    lines = []
    pj = next((x for x in hb.find_partials() if x['name'] == job_name), None)
    if pj:                                    # итог сканера: прочитано заново / взято из прежнего скана (с даты)
        lines.append(_scanner()[0].summary_text(pj['info']))
    for f, k in (stats or {}).items():
        became = sum(v for key, v in k.items() if key.startswith('было ') and key != 'было S')
        lines.append(f'{f}: в скане {k.get("файлов", 0)} файлов ({hb.gb(k.get("байт", 0))} ГБ); стало S {became}'
                     f' (уже было S {k.get("было S", 0)}); '
                     f'новые {k.get("новые", 0)}; исчезли из базы {k.get("исчезли", 0)}; хеш не совпал {k.get("хеш не совпал", 0)}')
    return dict(accepted=stats is not None, lines=lines, warn=warn)


# ---------- задания: честное состояние ----------

def running_scripts():
    """Командные строки запущенных PowerShell (чтобы понять, идёт ли задание). None - узнать не удалось."""
    try:
        r = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | ForEach-Object CommandLine"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return [x for x in r.stdout.decode('utf-8', errors='replace').splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        return None


def task_state(task, running='спросить'):
    """Состояние папки задания по её списку и журналам. Только то, что можно доказать:
    «не запускалось», «идёт», «прервано», «готово», «готово с ошибками», «состояние неизвестно»."""
    task = Path(task)
    kind = 'копирование' if (task / 'список.tsv').exists() else 'перемещение' if (task / 'перемещение.tsv').exists() else None
    if not kind:
        return None
    lst = task / ('список.tsv' if kind == 'копирование' else 'перемещение.tsv')
    total = len([x for x in hb.read_tsv(lst) if x])
    ok_words = ('скопирован', 'уже есть') if kind == 'копирование' else ('перемещён', 'уже перемещён')
    logs = sorted(task.glob(('Журнал копирования' if kind == 'копирование' else 'Журнал перемещения') + ' *.tsv'))
    done, errors, skipped, last = {}, 0, 0, None
    for log in logs:
        rows = hb.read_tsv(log)[1:]
        for f in rows:
            if kind == 'копирование' and len(f) >= 7:
                key, res = (f[1], f[5]), f[2]
            elif kind == 'перемещение' and len(f) >= 6:
                key, res = f[4], f[1]
            else:
                continue
            done[key] = res
        last = log
    good = sum(1 for r in done.values() if r.startswith(ok_words))
    errors = sum(1 for r in done.values() if r.startswith('ОШИБКА') or r.startswith('КОНФЛИКТ'))
    skipped = len(done) - good - errors
    if running == 'спросить':
        running = running_scripts()            # None - узнать не удалось
    is_running = None if running is None else any(str(task).lower() in x.lower() for x in running)
    if is_running:
        state = 'идёт'
    elif not logs:
        state = 'не запускалось'
    elif len(done) >= total:
        state = 'готово' if not errors and not skipped else 'готово с ошибками'
    elif is_running is None:
        state = 'состояние неизвестно'
    else:
        state = 'прервано'
    return dict(task=task.name, kind=kind, state=state, total=total, done=len(done), good=good, errors=errors,
                skipped=skipped, journal=str(last) if last else '')


def tasks(root=None):
    root = Path(root or hb.TASKS)
    running = running_scripts()
    res = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        st = task_state(d, running)
        if st:
            res.append(st)
    return res


MOVE_MARK = 'после копирования.json'


def mark_task_move(task, disk, folders=None):
    """Пометка в папке задания копирования (окно, «Подготовить копирование» с галочкой «разложить»): после
    копирования разложить файлы на источнике по «ПЕРЕНЕСЕНО → …» (команда mvlist). Сама ничего не перемещает.
    Файл «после копирования.json»: {"разложить_на_источнике": true, "диск": "HDDxx", "папки": [...] или null,
    "создано": "ДД.ММ.ГГГГ ЧЧ:ММ"}; null - весь диск."""
    import json
    task = Path(task)
    if not task.is_dir():
        raise Refused(f'Нет папки задания: {task}')
    data = {'разложить_на_источнике': True, 'диск': disk, 'папки': list(folders) if folders else None,
            'создано': time.strftime('%d.%m.%Y %H:%M')}
    path = task / MOVE_MARK
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


# ---------- логика v3: направления, отметки разбора, задания по отметкам (15.11.2026) ----------
# Документ - «Проверка Архитектуры сортировки файлов\Логика_v3_разбор_носителя.md». Направления - «_БАЗА\направления.tsv»
# (только дописывание, действует последняя строка номера), отметки - строки «решения.tsv» новых видов. Расчёт - ядро
# (hb_core/razbor.py), здесь - снимок входов под замком, проверки, запись и публикация заданий.

KIND_WORDS = {'фото': hb.KIND_MEDIA, 'фото, видео и документы рядом': hb.KIND_MEDIA, 'медиа': hb.KIND_MEDIA,
              'все': hb.KIND_ALL, 'все файлы': hb.KIND_ALL}
DEFAULT_DIRECTIONS = [    # ответы владельца 15.11.2026 (В4, В5): у «Семейного архива» 45 и 77, у остальных - свой диск
    dict(name='Семейный архив', disks=['HDD45', 'HDD77'], kind=hb.KIND_MEDIA, former=[],
         note='две копии; фото, видео и документы рядом'),
    dict(name='Работа и Сафари', disks=['HDD78'], kind=hb.KIND_ALL, former=['Сафари', 'Работа'],
         note='диск 78 «Работа Сафари 6ТБ»; одно направление (В4)'),
    dict(name='Фильмы', disks=['HDD55'], kind=hb.KIND_ALL, former=[], note='диск 55 My Book 2 ТБ (В5)'),
    dict(name='Оцифрованные источники', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
    dict(name='Саша, Таня, Наташа', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
    dict(name='Разные', disks=[], kind=hb.KIND_ALL, former=[], note='диск пока не назначен (В5)'),
]


def _read_snapshot():
    """Обе таблицы целиком в память; подпись - по тем же байтам (спор с GPT, раунд 2, п. 4). Без замка."""
    dec, dirs = hb.table_bytes(hb.DECISIONS), hb.table_bytes(hb.DIRECTIONS)
    return dict(decisions=dec, directions=dirs, sig=hb.signature(dec, dirs))


def snapshot():
    """Согласованный снимок таблиц владельца: читается под замком таблиц (никто не пишет в это время)."""
    with TableLock():
        return _read_snapshot()


def directions(snap=None):
    return hb.parse_directions((snap or _read_snapshot())['directions'])


def _ensure_directions():
    hb.BASE_DIR.mkdir(parents=True, exist_ok=True)
    if not hb.DIRECTIONS.exists():
        hb.DIRECTIONS.write_text(hb.DIRECTION_HEAD + '\n', encoding='utf-8-sig')


def _norm_kind(kind):
    """«Что копировать» -> текст колонки. Принимает старые слова («фото», «все» …), текст набора категорий («фото,
    видео, документы рядом, архивы») или (набор, рядом). Пустой набор и неизвестное слово - отказ (этап 5)."""
    if isinstance(kind, (tuple, list)) and len(kind) == 2 and not isinstance(kind[0], str):
        cats, near = kind
        if not cats:
            raise Refused('Что копировать: отметьте хотя бы одну категорию файлов.')
        bad = set(cats) - set(hb.COPY_CATS)
        if bad:
            raise Refused('Что копировать: неизвестная категория ' + ', '.join(sorted(bad)) + '.')
        return hb.kind_text(cats, near)
    k = ' '.join((kind or '').split()).lower()
    if k in KIND_WORDS:
        return KIND_WORDS[k]
    cats, near, ok = hb.parse_kind(k)
    if not k or not ok:
        raise Refused('Что копировать: «фото» (фото, видео и документы рядом), «все» (все файлы, кроме программ, '
                      'системных и временных) или категории через запятую: ' + ', '.join(hb.COPY_CATS) +
                      f' («{hb.DOCS_NEAR_WORD}» - документы только рядом с фото и видео).')
    return hb.kind_text(cats, near)


def direction_preview(num=None, name=None, disks=None, add_disks=(), kind=None, former=(), note=None, dirs=None, c=None):
    """Новое направление (num=None) или новая версия направления num. Проверки - логика v3, 1.1 и 2.1.
    disks - заменить список дисков (None - оставить); add_disks - добавить. -> dict(fields, lines, direction)."""
    dirs = directions() if dirs is None else dirs
    cur = None
    if num:
        n = hb.norm_num(num)
        cur = dirs.get(n) or hb.find_direction(dirs, num)
        if not cur:
            raise Refused(f'Нет направления «{num}». Есть: ' + (', '.join(f'{d.num} {d.name}' for d in dirs.values()) or 'никаких'))
        num = cur.num
    else:
        if not (name or '').strip():
            raise Refused('Нужно имя нового направления.')
        num = f'Н{max([hb.num_key(x) for x in dirs] + [0]) + 1}'
    new_name = (name or (cur.name if cur else '')).strip()
    err = hb.check_name(new_name)
    if err:
        raise Refused(err)
    for d in dirs.values():
        if d.num != num and new_name.casefold() in {x.casefold() for x in (d.name,) + d.former}:
            raise Refused(f'Имя «{new_name}» уже занято направлением {d.num} «{d.name}» (как имя или прежнее имя).')
    fm = list(cur.former) if cur else []
    for x in list(former) + ([cur.name] if cur and cur.name != new_name else []):
        x = x.strip()
        if x and x.casefold() != new_name.casefold() and x.casefold() not in {y.casefold() for y in fm}:
            for d in dirs.values():
                if d.num != num and x.casefold() in {y.casefold() for y in (d.name,) + d.former}:
                    raise Refused(f'Прежнее имя «{x}» уже у направления {d.num} «{d.name}».')
            fm.append(x)
    dl = list(cur.disks) if (cur and disks is None) else list(disks or [])
    for x in add_disks or ():
        if x not in dl:
            dl.append(x)
    dl = list(dict.fromkeys(x.strip() for x in dl if x.strip()))
    c = c or db()
    for x in dl:
        check_disk(c, x)
        other = hb.direction_of_disk({k: v for k, v in dirs.items() if k != num}, x)
        if other:
            raise Refused(f'Диск {x} уже у направления {other.num} «{other.name}»: один диск - одному направлению.')
    k = _norm_kind(kind) if kind else (cur.kind if cur else hb.KIND_ALL)
    nd = hb.Direction(num, new_name, tuple(fm), tuple(dl), k, (note if note is not None else (cur.note if cur else '')).strip())
    if cur and nd == cur:
        raise Refused('Ничего не меняется.')
    lines = [f'{"Изменить" if cur else "Новое направление"} {num} «{nd.name}»: диски {", ".join(nd.disks) or "не назначены"}; '
             f'что копировать: {nd.kind}.',
             f'Папка на носителе после переноса: «{nd.folder()}».' if nd.disks else
             'Без диска: отмечать папки можно, задания не создаются, пока не назначен диск.']
    if nd.former:
        lines.append('Прежние имена (старые «раздел: …» с ними сразу относятся к этому направлению): ' + ', '.join(nd.former))
    if cur and set(cur.disks) != set(nd.disks):
        lines.append('Смена дисков касается только НОВЫХ заданий; уже созданные требуют свои прежние диски.')
    return dict(fields=hb.direction_row(nd), lines=lines, direction=nd)


def add_direction(note=None, **kw):
    with TableLock():
        snap = _read_snapshot()
        pv = direction_preview(note=note, dirs=hb.parse_directions(snap['directions']), **kw)
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_row(hb.DIRECTIONS, pv['fields'])
    return pv


def directions_batch_preview(items, dirs=None):
    """Несколько направлений одним пакетом: всё или ничего (directions-default)."""
    dirs = dict(directions() if dirs is None else dirs)
    c = db()
    res, lines = [], []
    for it in items:
        cur = hb.find_direction(dirs, it['name'], by_num=False)
        if cur and cur.name == it['name'] and set(cur.disks) >= set(it['disks']):
            lines.append(f'{cur.num} «{cur.name}» уже есть - пропускаю.')
            continue
        pv = direction_preview(num=cur.num if cur else None, name=it['name'], disks=it['disks'] if not cur else None,
                               add_disks=it['disks'] if cur else (), kind=it['kind'], former=it.get('former', ()),
                               note=it.get('note', ''), dirs=dirs, c=c)
        dirs[pv['direction'].num] = pv['direction']
        res.append(pv['fields'])
        lines += pv['lines']
    if not res:
        raise Refused('Все направления по умолчанию уже заведены - записывать нечего.')
    return dict(fields=res, lines=lines)


def add_directions_batch(items):
    with TableLock():
        snap = _read_snapshot()
        pv = directions_batch_preview(items, hb.parse_directions(snap['directions']))
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_rows(hb.DIRECTIONS, pv['fields'])
    return pv


def mark_verdict(text, dirs):
    """Текст отметки владельца -> (решение для решения.tsv, направление или None)."""
    t = (text or '').strip()
    low = t.lower()
    if low == hb.MARK_SKIP:
        return hb.MARK_SKIP, None
    if low == hb.MARK_INHERIT:
        return hb.MARK_INHERIT, None
    if low.startswith(hb.MARK_DIR):
        t = t.split(':', 1)[1].strip()
    d = hb.find_direction(dirs, t)
    if not d:
        raise Refused(f'Нет направления «{t}». Есть: ' + (', '.join(f'{x.num} {x.name}' for x in dirs.values()) or
                                                          'никаких (заведите: directions-default или direction-add)')
                      + '; или «не копировать», «как у родителя».')
    return d.verdict(), d


def _real_path(c, disk, path, roots=()):
    """Путь как в базе: точный, иначе - папка без учёта регистра (folders.folder_lc), иначе - тот же исходный путь
    внутри служебной папки переноса (папка уже перенесена, владелец назвал её исходный путь)."""
    for cand in [path] + [r + SEP + path for r in sorted(roots)]:
        if files_under(c, disk, cand, 1)[0]:
            return cand
        r = c.execute('select folder from folders where disk=? and folder_lc=?', (disk, cand.lower())).fetchone()
        if r:
            return r[0]
    raise Refused(f'В базе нет файлов по пути {disk}\\{path}. Проверьте путь (папку можно выбрать по дереву базы).')


def marks_preview(disk, rows, c=None, snap=None):
    """Отметки разбора одним пакетом: rows - [(путь, отметка)], путь '' - весь носитель (режим разбора).
    Отметка: направление (номер или имя), «не копировать», «как у родителя». Путь проверяется физически (есть в базе),
    затем пишется ИСХОДНЫМ (без «ПЕРЕНЕСЕНО → …» / «Скопировано на …»). Совпадает с действующей - пропускается."""
    c = c or db()
    check_disk(c, disk)
    snap = snap or _read_snapshot()
    dirs = hb.parse_directions(snap['directions'])
    ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs)
    roots = hb.moved_roots(c, disk)
    fields, lines, skipped, seen = [], [], [], set()
    for path, text in rows:
        path = (path or '').strip().strip(SEP)
        if path:
            real = _real_path(c, disk, check_rel(path), roots)
            orig, inside = hb.original_of(real, roots)
            if not orig:
                raise Refused(f'«{real}» - служебная папка переноса; отметьте папки внутри неё.')
        else:
            real, orig, inside = '', '', False
        verdict, d = mark_verdict(text, dirs)
        if orig.lower() in seen:
            raise Refused(f'{disk}\\{orig or "(весь носитель)"}: отмечено в пакете дважды. Ничего не записано.')
        seen.add(orig.lower())
        cur = ms.get(orig)
        where = f'{disk}\\{orig}' if orig else f'{disk} (весь носитель)'
        if verdict == hb.MARK_INHERIT:
            if cur is None:
                skipped.append(f'{where}: своей отметки нет - уже «как у родителя»')
                continue
        elif cur is not None and hb.parse_verdict(verdict, dirs)[:2] == (cur.kind, cur.num):
            skipped.append(f'{where}: уже отмечено так ({hb.mark_text(cur, dirs)})')
            continue
        n, size, _ = files_under(c, disk, real)
        what = hb.mark_text(None if verdict == hb.MARK_INHERIT else hb.Mark(*hb.parse_verdict(verdict, dirs)[:3]), dirs)
        line = f'{where} → {what}: {n} файлов, {hb.gb(size)} ГБ' + (' (папка уже перенесена; отметка - по исходному пути)'
                                                                    if inside else '')
        if d and disk in d.disks:
            line += f' - {disk} сам диск этого направления: копируется на остальные его диски, перемещать нельзя'
        if verdict == hb.MARK_INHERIT and cur and cur.legacy:
            line += f' (старое решение «{cur.verdict}» для старых команд остаётся в силе)'
        lines.append(line)
        fields.append([disk, orig, verdict])
    if not fields:
        raise Refused('Записывать нечего: ' + '; '.join(skipped))
    lines.insert(0, f'Будет записано отметок: {len(fields)}.')
    if skipped:
        lines.append('Пропущено (уже так): ' + '; '.join(skipped))
    return dict(fields=fields, lines=lines, skipped=skipped)


def add_marks_batch(disk, rows, note=''):
    """Запись отметок пакетом, всё или ничего (как add_manual_batch): под замком - снова все проверки, копия таблицы,
    одна запись на диск. Решения в базу не применяются (читаются при каждом ответе)."""
    with TableLock():
        pv = marks_preview(disk, rows, snap=_read_snapshot())
        hb.ensure_tables()
        backup(hb.DECISIONS)
        first = append_rows(hb.DECISIONS, [f + [note or ''] for f in pv['fields']])
    pv['line'] = first
    return pv


def _plan(disk, drafts=(), detail=False, snap=None):
    """Снимок таблиц + одно соединение с одним поколением базы (транзакция чтения) -> ядро planner."""
    snap = snap or snapshot()
    c = db()
    check_disk(c, disk)
    c.execute('begin')                                  # всё дальнейшее чтение - одно состояние базы
    try:
        dirs = hb.parse_directions(snap['directions'])
        ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs, drafts)
        P = hb.planner(c, disk, dirs, ms, detail)
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.rollback()
    P.info['signature'] = hb.signature(snap['sig'].encode(), str(gen).encode())
    P.info['built'] = gen
    return P


def razbor(disk, drafts=()):
    """Итог разбора носителя (без записи). drafts - несохранённые отметки окна [(путь, отметка)]: только для показа."""
    return _plan(disk, drafts)


def free_space(disks_):
    """Свободное место подключённых дисков: {диск: (буква, ГиБ)}. Диски не читаются (только размер тома)."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    res = {}
    for d in disks_:
        letter = vols.get(serial_of.get(d, '?'))
        if letter:
            try:
                res[d] = (letter, shutil.disk_usage(letter + '\\').free / hb.GIB)
            except OSError:
                pass
    return res


def _task_meta(task):
    import json
    try:
        return json.loads((Path(task) / 'разбор.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    """Целиком и заменой файла: читатель видит либо старое, либо новое содержимое."""
    import json
    tmp = Path(str(path) + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def same_task(meta, disk, s):
    """Задание разбора meta уже покрывает spec s: тот же носитель, ключ группы, направление и набор «что копировать»
    (смена набора - новое задание, Дискуссия этапа 5, п. 11), и диск s среди его целей (старое общее задание на 45 и
    77 покрывает оба)."""
    return (meta.get('носитель') == disk and meta.get('ключ') == s['key'] and meta.get('направление') == s['num']
            and meta.get('что копировать') == s['kind'] and set(s['targets']) <= set(meta.get('цели') or []))


def razbor_tasks(disk, dry=True, only=None):
    """Задания копирования по отметкам: одно задание - одна группа (решающая отметка + папка), её направление и ОДИН
    диск назначения (этап 5: на 45 и на 77 - отдельные задания одной группы, поле «группа» в разбор.json). Всё под замком таблиц: снимок, расчёт, проверка имён, публикация (два генератора одновременно не работают).
    Публикация: манифест «создаётся» -> папки собираются в «_БАЗА\\разборы\\<…>.tmp» и переносятся в «Запускаемые
    скрипты» -> манифест «готово». Повтор после сбоя: задание с тем же ключом уже есть - «уже подготовлено»,
    создаются только недостающие. Ничего не копирует и не запускает. only - номера направлений (этап 6: кнопка
    ячейки направления; None - все). -> dict."""
    with TableLock():
        P = _plan(disk, detail=True, snap=_read_snapshot())
        if P.errors:
            raise Refused('Итог разбора не сходится (' + '; '.join(P.errors) + ') - задания не создаются.')
        serials = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
        specs = hb.task_specs(P, serials)
        states = hb.group_states(P)
        if only is not None:                                     # этап 6: задания только этих направлений
            only = set(only)
            specs = [s for s in specs if s['num'] in only]
            states = [g for g in states if g['num'] in only]
        made = [(t.name, _task_meta(t)) for t in (sorted(hb.TASKS.iterdir()) if hb.TASKS.exists() else ())
                if t.is_dir() and (t / 'разбор.json').exists()]
        made = [(n_, m) for n_, m in made if m and not m.get('повтор')]
        for s in specs:
            old = next((n_ for n_, m in made if same_task(m, disk, s)), None)
            if old:                                              # уже подготовлено (в том числе общим заданием на
                s['exists'], s['name'] = True, old               # 45 и 77 прежнего вида - под своим именем)
                continue
            base, i = s['name'], 2
            while True:
                meta = _task_meta(hb.TASKS / s['name']) if (hb.TASKS / s['name']).exists() else None
                if not (hb.TASKS / s['name']).exists():
                    break
                if meta and same_task(meta, disk, s):
                    s['exists'] = True
                    break
                s['name'], i = f'{base} ({i})', i + 1
        res = dict(plan=P, specs=specs, states=states, dry=dry, manifest=None)
        if dry or not [s for s in specs if not s.get('exists')]:
            return res
        stamp = time.strftime('%Y-%m-%d %H-%M-%S')
        hb.RAZBORY.mkdir(parents=True, exist_ok=True)
        manifest = hb.RAZBORY / f'{disk} {stamp}.json'
        man = {'носитель': disk, 'дата': time.strftime('%d.%m.%Y %H:%M'), 'статус': 'создаётся',
               'подпись входов': P.info['signature'], 'поколение базы': P.info.get('built'),
               'носитель - диск направления': P.info.get('is_target') or [],
               'перемещать на носителе': not P.info.get('is_target'),
               'отметки': [dict(путь=m.path, решение=m.verdict, строка=m.row) for m in P.marks.by_key.values()],
               'задания': [dict(имя=s['name'], группа=s['group'], папка=s['folder'], направление=s['num'], диски=s['disks'],
                                цели=s['targets'],
                                файлов=s['files'], байт=s['bytes'], уже_было=bool(s.get('exists'))) for s in specs],
               'группы': states}
        _write_json(manifest, man)
        stage = hb.RAZBORY / f'{disk} {stamp}.tmp'
        stage.mkdir()
        hb.TASKS.mkdir(parents=True, exist_ok=True)
        for s in specs:
            if s.get('exists'):
                continue
            t = stage / s['name']
            t.mkdir()
            with io.open(t / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
                for r in s['rows']:
                    f.write('\t'.join(map(str, r)) + '\n')
            with io.open(t / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
                f.write(f'{disk}\t{s["serials"][disk]}\n')
                for d in s['targets']:
                    f.write(f'{d}\t{s["serials"][d]}\n')
            for name in ('Копировать.ps1', 'Запустить.cmd'):
                shutil.copy2(hb.TEMPLATE / name, t / name)
            _write_json(t / 'разбор.json', {
                'носитель': disk, 'ключ': s['key'], 'папка': s['folder'], 'направление': s['num'],
                'имя направления': s['direction'], 'обязательные диски': s['disks'], 'цели': s['targets'],
                'группа': s['group'],
                'что копировать': s['kind'], 'отметка': s['mark'], 'строка отметки': s['mark_row'],
                'подпись входов': P.info['signature'], 'дата': man['дата'], 'манифест': manifest.name,
                'перемещать на носителе': not P.info.get('is_target'),
                'зависимые': {d: [list(x) for x in v] for d, v in s['deps'].items() if v}})
            os.replace(t, hb.TASKS / s['name'])
        try:
            stage.rmdir()
        except OSError:
            pass
        man['статус'] = 'готово'
        _write_json(manifest, man)
        res['manifest'] = manifest
    return res


def contested(disk, folder):
    """«Пересчитать хеши спорных файлов»: папки по дискам и подключён ли диск. -> [(диск, буква или '', [(папка, n)])]."""
    c = db()
    check_disk(c, disk)
    got = hb.contested(c, disk, folder)
    free = free_space(list(got))
    return [(d, free.get(d, ('', 0))[0], got[d]) for d in sorted(got)]


# ---------- экран «Разбор носителя» (логика v3, этап 2, 15.11.2026; razbor_page.py) ----------

def razbor_tree(disk):
    """Всё для дерева экрана «Разбор носителя» одним вызовом, ничего не пишет: папки носителя из таблицы folders
    (суммы по поддереву: файлов, байт, число и байты по 5 типам), служебные папки переноса, направления и сохранённые
    отметки (снимок таблиц под замком - тот же, по которому считает итог), сведения об описи, поколение базы. -> dict."""
    snap = snapshot()
    c = ro()
    try:
        check_disk(c, disk)
        cols = 'folder, files, bytes, ' + ', '.join(f'n{i}, b{i}' for i in range(5))
        folders = {}
        for r in c.execute(f'select {cols} from folders where disk=?', (disk,)):
            folders[r[0]] = (r[1] or 0, r[2] or 0, tuple(r[3 + 2 * i] or 0 for i in range(5)),
                             tuple(r[4 + 2 * i] or 0 for i in range(5)))
        roots = hb.moved_roots(c, disk)
        st = c.execute('select status, scanned, label from disks where disk=?', (disk,)).fetchone() or ('', None, '')
        issues = c.execute('select count(*) from issues where disk=?', (disk,)).fetchone()[0]
        gen = (c.execute("select value from meta where key='built'").fetchone() or [''])[0]
    finally:
        c.close()
    return dict(disk=disk, folders=folders, roots=roots, dirs=hb.parse_directions(snap['directions']),
                rows=hb.mark_rows(disk, snap['decisions']), sig=snap['sig'], built=gen, status=st[0] or '',
                scanned=st[1], label=st[2] or '', issues=issues)


def razbor_have(disk, disks_):
    """Колонка «Уже есть» экрана разбора: файлы носителя С ХЕШЕМ по папкам (непосредственно в папке, без подпапок), по
    типам и по тому, на каких из дисков disks_ уже есть подтверждённая запись (S/C) с тем же SHA-256: 45 и 77 - по
    таблице presence, у других дисков - множество их SHA-256 (как в итоге разбора; поиск по индексу на каждый файл был
    в 4 раза медленнее). Сам носитель среди disks_ считается имеющим файл (как в итоге разбора). Один проход по файлам
    с хешем носителя; ничего не пишет. Замер на настоящей базе: HDD45 (567 тыс. файлов с хешем) - около 5 с.
    -> {папка: {маска: [n0..n8, b0..b8]}} (9 типов derived.copy_kind), бит i маски - диск disks_[i]."""
    disks_ = list(disks_)
    main = [(i, d) for i, d in enumerate(disks_) if d in hb.MAIN and d != disk]
    base = sum(1 << i for i, d in enumerate(disks_) if d == disk)
    sel = ''.join(f", coalesce(p.e{d[3:]} in ('S','C'), 0)" for _, d in main)
    q = (f'select f.path, f.size, f.name_lc, f.sha{sel} from files f ' +
         ('left join presence p on p.sha=f.sha ' if main else '') + 'where f.disk=? and f.sha is not null')
    ft = hb.fast_folder_type(fine=True)
    res = collections.defaultdict(dict)
    c = ro()
    try:
        sets = [(1 << i, {x for (x,) in c.execute('select sha from files where disk=? and sha is not null', (d,))})
                for i, d in enumerate(disks_) if d not in hb.MAIN and d != disk]
        bits = [1 << i for i, _ in main]
        for r in c.execute(q, (disk,)):
            path, size, sha = r[0], r[1] or 0, r[3]
            mask = base
            for b, x in zip(bits, r[4:]):
                if x:
                    mask |= b
            for b, s_ in sets:
                if sha in s_:
                    mask |= b
            k = ft(path, r[2], size)
            cell = res[hb.parent_of(path)].get(mask)
            if cell is None:
                cell = res[hb.parent_of(path)][mask] = [0] * (2 * hb.N_TYPES)
            cell[k] += 1
            cell[hb.N_TYPES + k] += size
    finally:
        c.close()
    return dict(res)


# ---------- экран «Направления» и шаблон копирования 2.4 (логика v3, этап 4, 15.11.2026; directions_page.py) ----------
# Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 4». Описание направления («что собирается на этих дисках») -
# 7-я колонка направления.tsv (hb_core/directions.py). Смена дисков у направления с заданиями: предпросмотр показывает
# задания по журналам и отметки; убрать диск, на который у направления есть задания, - только с подтверждением (ack).

DESC_MAX = 200
GOOD_COPY = ('скопирован', 'уже есть')


def direction_usage(num, dirs=None, root=None):
    """Что уже сделано по направлению: задания (по разбор.json в папках заданий) с ходом по каждой цели ПО ЖУРНАЛАМ
    и число действующих отметок папок. -> dict(tasks=[dict(name, disks, targets, per={диск: (хорошо, всего)},
    state)], marks={носитель: n}). «хорошо» - строки журнала «скопирован…» или «уже есть» (это не доказательство
    копии: подтверждение даёт только база по SHA-256)."""
    dirs = directions() if dirs is None else dirs
    root = Path(root or hb.TASKS)
    tasks_ = []
    if root.exists():
        for t in sorted(p for p in root.iterdir() if p.is_dir()):
            meta = _task_meta(t)
            if not meta or meta.get('направление') != num:
                continue
            total = collections.Counter(f[0] for f in hb.read_tsv(t / 'список.tsv') if len(f) >= 3) \
                if (t / 'список.tsv').exists() else collections.Counter()
            good = collections.defaultdict(set)
            logs = sorted(t.glob('Журнал копирования *.tsv'))
            for log in logs:
                for f in hb.read_tsv(log)[1:]:
                    if len(f) >= 7 and f[2].startswith(GOOD_COPY):
                        good[f[1]].add(f[5].lower())
            per = {d: (min(len(good[d]), total[d]), total[d]) for d in (meta.get('цели') or sorted(total))}
            if not logs:
                state = 'не запускалось'
            elif all(g >= n for g, n in per.values()):
                state = 'по журналам все строки пройдены'
            else:
                state = 'по журналам не всё'
            tasks_.append(dict(name=t.name, disks=meta.get('обязательные диски') or [], targets=meta.get('цели') or [],
                               per=per, state=state))
    marks = collections.Counter()
    data = hb.table_bytes(hb.DECISIONS)
    last = {}
    for i, f in enumerate(hb.tsv_rows(data[:data.rfind(b'\n') + 1]), start=1):
        f = [x.strip() for x in f] + [''] * 3
        if i == 1 and f[0].lower() == 'диск':
            continue
        if f[1].lower().startswith('класс:') or not f[2]:
            continue
        last[(f[0], f[1].strip(SEP).lower())] = f[2]
    for (disk, _p), verdict in last.items():
        kind, n, _, _ = hb.parse_verdict(verdict, dirs)
        if kind == hb.R_DIR and n == num:
            marks[disk] += 1
    return dict(tasks=tasks_, marks=dict(marks))


def copied_name(d):
    return d.folder() or f'Скопировано на {d.name} (диск не назначен)'


def _disk_has_data(disk, c=None):
    """Есть ли в базе файлы на диске (подтверждённые копии могли попасть туда и без папок заданий). Только чтение."""
    own = c is None
    try:
        c = c or ro()
        try:
            return c.execute('select 1 from files where disk=? limit 1', (disk,)).fetchone() is not None
        finally:
            if own:
                c.close()
    except Refused:                                      # базы ещё нет (ro): данных о диске нет
        return False
    except Exception:                                    # noqa: BLE001 - ошибка чтения базы: переспросить на всякий случай
        return True


def _usage_lines(cur, nd, dirs, root=None, c=None):
    """Строки предпросмотра смены дисков. -> (строки, убранные диски, на которые у направления есть задания,
    нужно ли переспросить владельца). Переспрос (этап 5, п. 2): убирается или заменяется диск, а у направления есть
    задания или на убираемом диске есть данные в базе (Дискуссия этапа 5, п. 9: копии могли лечь туда и без заданий).
    Только добавление диска - без переспроса."""
    use = direction_usage(cur.num, dirs, root)
    old, new = list(cur.disks), list(nd.disks)
    removed, added = [d for d in old if d not in new], [d for d in new if d not in old]
    lines = []
    if use['tasks']:
        lines.append(f'У направления уже подготовлено заданий: {len(use["tasks"])}. Ход по журналам копирования '
                     '(журнал - не подтверждение; подтверждает база по SHA-256):')
        for t in use['tasks'][:8]:
            per = ', '.join(f'{d}: {g} из {n}' for d, (g, n) in t['per'].items())
            lines.append(f'  «{t["name"]}» - {t["state"]} ({per})')
        if len(use['tasks']) > 8:
            lines.append(f'  … и ещё {len(use["tasks"]) - 8}')
        lines.append('Уже созданные задания и перемещения по ним по-прежнему требуют копий на своих прежних дисках '
                     f'({", ".join(sorted({d for t in use["tasks"] for d in t["disks"]}))}).')
    if use['marks']:
        lines.append('Отмечено папок этим направлением: ' + ', '.join(f'{d}: {n}' for d, n in sorted(use['marks'].items()))
                     + '. Новые задания по этим отметкам пойдут на новый набор дисков.')
    if old:
        lines.append('Прежние копии на новый диск сами не попадут: что не хватает на новом диске, покажет итог разбора '
                     'носителя (строка «копировать на …»).')
        lines.append(f'Папки «{copied_name(cur)}» на носителях не переименовываются; новые будут «{copied_name(nd)}».')
    risky, confirm = [], False
    for d in removed:
        n = sum(1 for t in use['tasks'] if d in t['targets'] or d in t['disks'])
        data = _disk_has_data(d, c)
        lines.append(f'Диск {d} перестаёт быть диском направления; всё, что на нём уже скопировано, остаётся на нём, '
                     'но направлению больше не засчитывается: «уже есть» для новых заданий считается только по новым '
                     'дискам. Для перемещения файлов, которые прежние задания ставили на этот диск, он остаётся '
                     'обязательным.' + (f' На этот диск у направления заданий: {n} - нужно подтверждение.' if n else ''))
        if n:
            risky.append(d)
        if n or use['tasks'] or data:
            confirm = True
    for d in added:
        busy = [f'{x.num} «{x.name}»' for x in dirs.values() if x.num != cur.num
                and any(d in t['targets'] for t in direction_usage(x.num, dirs, root)['tasks'])]
        if busy:
            lines.append(f'На диск {d} раньше шли задания направлений {", ".join(busy)}: их копии остаются там.')
    return lines, risky, confirm


def direction_save_preview(num=None, name=None, disks=None, kind=None, desc=None, dirs=None, c=None, root=None):
    """Окно «Направления»: новое направление (num=None) или полная новая версия: имя, диски (ПОЛНЫЙ список; None -
    оставить), что копировать, описание (None - оставить). Проверки - ядро direction_preview (имя, прежние имена,
    один диск - одному направлению, диск есть в базе). Одна строка таблицы.
    -> dict(fields, lines, direction, needs_ack=[убранные диски, на которые есть задания], confirm - окну переспросить
    владельца перед записью (этап 5: только смена/удаление диска у направления с заданиями или данными))."""
    import dataclasses
    dirs = directions() if dirs is None else dirs
    d_txt = None if desc is None else ' '.join(str(desc).split())
    if d_txt is not None and len(d_txt) > DESC_MAX:
        raise Refused(f'Описание длиннее {DESC_MAX} знаков.')
    cur = None
    if num:
        cur = dirs.get(hb.norm_num(num)) or hb.find_direction(dirs, num)
        if not cur:
            raise Refused(f'Нет направления «{num}».')
    want = None if disks is None else list(dict.fromkeys(x.strip() for x in disks if x and x.strip()))
    core_same = cur is not None and (name is None or name.strip() == cur.name) \
        and (want is None or want == list(cur.disks)) and (kind is None or _norm_kind(kind) == cur.kind)
    if core_same:
        if d_txt is None or d_txt == (cur.desc or ''):
            raise Refused('Ничего не меняется.')
        nd = dataclasses.replace(cur, desc=d_txt)
        lines = [f'Изменить {cur.num} «{cur.name}»: только описание.']
    else:
        pv = direction_preview(num=cur.num if cur else None, name=name, disks=want, kind=kind, dirs=dirs, c=c)
        nd = dataclasses.replace(pv['direction'], desc=d_txt if d_txt is not None else ((cur.desc or '') if cur else ''))
        lines = list(pv['lines'])
    if d_txt is not None and d_txt != ((cur.desc or '') if cur else ''):
        lines.append(f'Что собирается на дисках: «{d_txt}».' if d_txt else 'Описание будет стёрто.')
    risky, confirm = [], False
    if cur and list(cur.disks) != list(nd.disks):
        more, risky, confirm = _usage_lines(cur, nd, dirs, root, c)
        lines += more
    return dict(fields=hb.direction_row(nd), lines=lines, direction=nd, needs_ack=risky, confirm=confirm or bool(risky))


def direction_save(ack=False, **kw):
    """Запись из окна: под замком таблиц снова предпросмотр по свежей таблице, затем одна строка (копия - в архив)."""
    with TableLock():
        snap = _read_snapshot()
        pv = direction_save_preview(dirs=hb.parse_directions(snap['directions']), **kw)
        if pv['needs_ack'] and not ack:
            raise Refused('Диск ' + ', '.join(pv['needs_ack']) + ' убирается из направления, у которого есть задания на '
                          'него. Поставьте галочку «Понимаю…» и сохраните снова.')
        _ensure_directions()
        backup(hb.DIRECTIONS)
        pv['line'] = append_row(hb.DIRECTIONS, pv['fields'])
    return pv


TEMPLATE_VER_RE = re.compile(r'версия (\d+)\.(\d+)')


def copy_template_version(task):
    """Версия шаблона копирования в папке задания: (2, 4) / (2, 3) / None. Для очереди: -Confirmed понимают только
    задания 2.4 и новее; старые в автоматическую очередь не включаются (Дискуссия этапа 4, р2-7)."""
    try:
        with open(Path(task) / 'Копировать.ps1', encoding='utf-8-sig') as f:
            m = TEMPLATE_VER_RE.search(f.readline())
    except OSError:
        return None
    return (int(m.group(1)), int(m.group(2))) if m else None


def copy_task_fingerprint(task):
    """Отпечаток задания для подтверждения в окне (шаблон 2.4, параметр -Expect): SHA-256 байтов список.tsv + 0 +
    тома.tsv + 0 + разбор.json (нет файла - пусто), заглавными; и объём по целям из ТЕХ ЖЕ байтов: {цель: (файлов,
    байт)}. Окно показывает владельцу объём по целям, шаблону передаёт отпечаток: изменилось что-то - шаблон не начнёт."""
    import hashlib
    task = Path(task)
    lst = (task / 'список.tsv').read_bytes()
    vol = (task / 'тома.tsv').read_bytes()
    raz = (task / 'разбор.json').read_bytes() if (task / 'разбор.json').exists() else b''
    sha = hashlib.sha256(lst + b'\0' + vol + b'\0' + raz).hexdigest().upper()
    per = collections.defaultdict(lambda: [0, 0])
    for f in hb.tsv_rows(lst):
        if len(f) >= 3 and f[2].strip().isdigit():
            per[f[0]][0] += 1
            per[f[0]][1] += int(f[2])
    return dict(sha=sha, per={k: tuple(v) for k, v in per.items()})


# ---------- логика v3, этап 3: «Повторить копирование» остального (после «Переместить скопированное») ----------
# Старое задание не перезапускается: после переноса скопированной части его строки дали бы «нет источника».
# Создаётся новое задание «<задание> — повтор N» только из пар (цель, путь), у которых последний результат по журналам
# исходного задания и всех прежних повторов - не «скопирован…» и не «уже есть». Ничего не копирует и не запускает.

RETRY_WORD = ' — повтор'


def _copy_group(name):
    """Исходное задание разбора и все его повторы -> (папка исходного, разбор.json исходного, [папки повторов])."""
    t = hb.TASKS / name
    meta = _task_meta(t)
    if not meta:
        raise Refused(f'«{name}» - не задание разбора (нет разбор.json).')
    if meta.get('повтор'):
        t = hb.TASKS / meta['повтор']
        meta = _task_meta(t)
        if not meta:
            raise Refused(f'Нет исходного задания «{t.name}».')
    retries = []
    if hb.TASKS.exists():
        for d in sorted(p for p in hb.TASKS.iterdir() if p.is_dir()):
            m = _task_meta(d) if (d / 'разбор.json').exists() else None
            if m and m.get('повтор') == t.name:
                retries.append(d)
    return t, meta, retries


def copy_left(name):
    """Что не скопировано: [(строка списка.tsv исходного задания)], по паре (цель, путь) и последнему результату."""
    t, _meta, retries = _copy_group(name)
    last = {}
    logs = []
    for d in [t] + retries:
        logs += [(hb.log_time(x), x) for x in d.glob('Журнал копирования *.tsv')]
    for _w, log in sorted(logs, key=lambda x: (x[0], x[1].name)):
        rows = hb.read_tsv(log)
        head = [h.strip().lower() for h in rows[0]] if rows else []
        if not all(x in head for x in ('цель', 'результат', 'источник')):
            continue
        i_t, i_r, i_s = head.index('цель'), head.index('результат'), head.index('источник')
        for f in rows[1:]:
            if len(f) > max(i_t, i_r, i_s):
                last[(f[i_t].strip(), hb.rel_of(f[i_s])[1])] = f[i_r]
    sub = ''
    vols = [f for f in hb.read_tsv(t / 'тома.tsv') if len(f) >= 2]
    if vols and len(vols[0]) >= 3:
        sub = vols[0][2].strip().strip(SEP)
    res = []
    for f in hb.read_tsv(t / 'список.tsv'):
        if len(f) < 3 or not f[0].strip():
            continue
        key = (f[0].strip(), (sub + SEP + f[1]) if sub else f[1])
        r = last.get(key, '')
        if not (r.startswith('скопирован') or r == 'уже есть'):
            res.append(f)
    return res


def retry_copy_task(name):
    """«Повторить копирование»: новое задание из того, что не скопировано. -> dict(task, files, bytes)."""
    t, meta, retries = _copy_group(name)
    running = running_scripts()
    for d in [t] + retries:
        st = task_state(d, running)
        if st and st['state'] == 'идёт':
            raise Refused(f'Задание «{d.name}» сейчас идёт - дождитесь конца.')
    rows = copy_left(t.name)
    if not rows:
        raise Refused(f'В задании «{t.name}» всё скопировано - повторять нечего.')
    n = len(retries) + 1
    while (hb.TASKS / f'{t.name}{RETRY_WORD} {n}').exists():
        n += 1
    new = f'{t.name}{RETRY_WORD} {n}'
    hb.RAZBORY.mkdir(parents=True, exist_ok=True)
    stage = hb.RAZBORY / (new + '.tmp')
    if stage.exists():
        raise Refused(f'Осталась папка прошлой попытки: {stage}. Уберите её и повторите.')
    stage.mkdir()
    with io.open(stage / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write('\t'.join(r) + '\n')
    shutil.copy2(t / 'тома.tsv', stage / 'тома.tsv')
    for fn in ('Копировать.ps1', 'Запустить.cmd'):
        shutil.copy2(hb.TEMPLATE / fn, stage / fn)
    _write_json(stage / 'разбор.json', dict(meta, повтор=t.name, **{'дата повтора': time.strftime('%d.%m.%Y %H:%M')}))
    os.replace(stage, hb.TASKS / new)
    size = 0
    for r in rows:
        try:
            size += int(r[2])
        except (IndexError, ValueError):
            pass
    return dict(task=hb.TASKS / new, files=len(rows), bytes=size)


# ---------- экран «Разбор носителя» по замечаниям владельца (логика v3, этап 6, 15.11.2026) ----------
# Документ - «Логика_v3_разбор_носителя.md», раздел «Этап 6». Вместимость по каждому диску направления и быстрая
# сверка оглавления подключённого носителя с описью перед созданием заданий. Ничего не пишет.

CLUSTER = 4096                       # кластер, если узнать настоящий у тома не удалось
RESERVE_MIN = 2 * 1024 ** 3          # запас на диске: не меньше 2 ГиБ ...
RESERVE_PART = 0.01                  # ... и не меньше 1 % объёма диска
MTIME_SLACK = 0                      # даты в описи - целые секунды (floor); сверка точная (критик GPT, п. 6)


def disk_space(disks_):
    """Свободное место, объём и кластер подключённых дисков: {диск: (буква, свободно байт, объём байт, кластер байт)}.
    Диски не читаются (только сведения о томе, как free_space). Неподключённого диска в ответе нет: место неизвестно."""
    serial_of = {v: k for k, v in hb.serial_map(bp.find_jobs()).items()}
    try:
        vols = volumes()
    except (OSError, AttributeError):
        vols = {}
    res = {}
    for d in disks_:
        letter = vols.get(serial_of.get(d, '?'))
        if letter:
            try:
                u = shutil.disk_usage(letter + '\\')
                res[d] = (letter, u.free, u.total, cluster_of(letter))
            except OSError:
                pass
    return res


def cluster_of(letter):
    """Размер кластера тома (байт): GetDiskFreeSpaceW; не удалось - 4 КиБ."""
    try:
        import ctypes
        spc, bps, a, b = (ctypes.c_ulong() for _ in range(4))
        if ctypes.windll.kernel32.GetDiskFreeSpaceW(letter.rstrip('\\') + '\\', ctypes.byref(spc), ctypes.byref(bps),
                                                     ctypes.byref(a), ctypes.byref(b)):
            return spc.value * bps.value or CLUSTER
    except (OSError, AttributeError):
        pass
    return CLUSTER


def reserve_of(total):
    return max(RESERVE_MIN, int((total or 0) * RESERVE_PART))


def queued_copy(exclude_disk=None, root=None):
    """Незапущенные задания копирования ДРУГИХ носителей (журналов ещё нет): {диск назначения: [заданий, байт]}.
    Их файлы ещё не на диске, а место займут. Задания этого носителя не считаются: их недостающее уже в части Б
    (носитель задания - первая строка его тома.tsv). -> {диск: [заданий, байт, файлов]}."""
    root = Path(root or hb.TASKS)
    res = collections.defaultdict(lambda: [0, 0, 0])
    if not root.exists():
        return {}
    for t in root.iterdir():
        lst = t / 'список.tsv'
        if not t.is_dir() or not lst.exists() or list(t.glob('Журнал копирования *.tsv')):
            continue
        src = ''
        try:
            vol = hb.read_tsv(t / 'тома.tsv')
            src = vol[0][0] if vol and vol[0] else ''
        except OSError:
            pass
        if exclude_disk and src == exclude_disk:
            continue
        per, cnt = collections.Counter(), collections.Counter()
        for r in hb.read_tsv(lst):
            if len(r) >= 3:
                try:
                    per[r[0]] += int(r[2])
                    cnt[r[0]] += 1
                except ValueError:
                    pass
        for d, b in per.items():
            res[d][0] += 1
            res[d][1] += b
            res[d][2] += cnt[d]
    return dict(res)


def capacity(part_b, space, queued=None, disks=()):
    """Поместится ли на каждый диск части Б то, чего на нём ещё нет (часть Б: по SHA-256; файлы без хеша - всегда).
    нужно = байты + файлов × кластер тома (каждый файл теряет меньше кластера - верхняя граница) + незапущенные
    задания других носителей на этот диск; запас =
    max(2 ГиБ, 1 % объёма). -> {диск: dict(files, bytes, need, reserve, queued, free, total, letter,
    state 'ok' | 'short' | 'unknown' (не подключён) | 'none' (писать нечего))}. disks - ещё диски (диски направлений), на
    которые копировать нечего: у них запись 'none' (и место, если подключён)."""
    res = {}
    queued = queued or {}
    rows = dict(part_b)
    for d in disks:
        rows.setdefault(d, (0, 0))
    for d, (n, b) in rows.items():
        q = (list(queued.get(d, ())) + [0, 0, 0])[:3]
        cl = space[d][3] if d in space and len(space[d]) > 3 else CLUSTER
        need = b + n * cl + q[1] + q[2] * cl
        x = dict(files=n, bytes=b, need=need, queued=q, reserve=None, free=None, total=None, letter='', cluster=cl)
        if d in space:
            letter, free, total = space[d][:3]
            x.update(letter=letter, free=free, total=total, reserve=reserve_of(total))
        if not n:
            x['state'] = 'none'
        elif d in space:
            x['state'] = 'ok' if need + x['reserve'] <= free else 'short'
        else:
            x['state'] = 'unknown'
        res[d] = x
    return res


def short_directions(dirs, cap):
    """Направления, которым не хватает места хотя бы на одном их диске (тогда задания не создаются ни на один)."""
    return sorted(n for n, d in dirs.items() if any(cap.get(x, {}).get('state') == 'short' for x in d.disks))


def toc_targets(P, specs):
    """Что сверять перед созданием заданий specs: физические папки их групп (исходный путь и его копия внутри
    служебной папки переноса - те, что есть в описи), вложенные свёрнуты в верхние; файлы прямо в корне - флаг;
    зоны - отметки внутри сверяемых папок: (физический путь, сверять ли). Файл сверяется по САМОЙ ГЛУБОКОЙ зоне над
    ним: отметка другого направления или «не копировать» - не сверяется (его файлы в эти задания не входят), отметка
    направления сверяемых заданий или папка их группы глубже - снова сверяется (критик GPT, п. 7: переопределения на
    нескольких уровнях). -> (папки, корень, зоны)."""
    c = ro()
    try:
        have = {f.lower(): f for (f,) in c.execute('select folder from folders where disk=?', (P.disk,))}
    finally:
        c.close()
    roots = P.info.get('roots') or []
    want, root_files = set(), False
    nums = {s['num'] for s in specs}
    groups = {s['folder'].lower() for s in specs if s['folder'] is not None}

    def phys(f):
        return [have[x.lower()] for x in [f] + [r + SEP + f for r in roots] if x.lower() in have]
    for s in specs:
        f = s['folder']
        if f is None:                                   # группа «(файлы в корне)»
            root_files = True
            continue
        want.update(phys(f))
    zones = {}
    for m in P.marks.by_key.values():
        if m.path and any(m.path.lower().startswith(g + SEP) for g in groups):
            keep = m.path.lower() in groups or (m.kind == hb.R_DIR and m.num in nums)
            for x in phys(m.path):
                zones[x] = keep
    tops = []
    for f in sorted(want, key=lambda x: (x.count(SEP), x.lower())):
        if not any(f.lower() == t.lower() or f.lower().startswith(t.lower() + SEP) for t in tops):
            tops.append(f)
    return tops, root_files, sorted(zones.items())


def toc_check(disk, folders, root_files=False, zones=(), limit=3):
    """Быстрая сверка оглавления подключённого носителя с описью: пути, размеры, даты (os.scandir/stat - содержимое
    файлов не читается, хешей нет), по тем же правилам пропуска служебных папок и файлов, что опись сканера.
    -> dict(connected, reason, letter, checked, problems=[dict(folder, gone, new, size, date, unread, examples)]).
    Носитель не подключён -> connected=False и причина (сверка невозможна - задания не создаются)."""
    try:
        letter = disk_letter(disk)
    except Refused as e:
        return dict(connected=False, reason=str(e), letter='', checked=0, problems=[])
    rescan, inventory = _scanner()
    root = letter.rstrip('\\') + '\\'
    c = ro()
    try:
        excl = {p.lower() for (p,) in c.execute('select path from excluded where disk=?', (disk,))}
        excl_dirs = [f.lower() + SEP for f in hb.read_exclusions().get(disk, ())]

        def skipped(rel):
            """Одно правило для описи и оглавления: исключённое владельцем (таблица excluded и папки исключений),
            файлы и папки, которые опись сканера не описывает (inventory.excluded_file, EXCLUDED_DIRS)."""
            k = rel.lower()
            if k in excl or any(k.startswith(x) for x in excl_dirs):
                return True
            parts = k.split(SEP)
            return inventory.excluded_file(parts[-1]) or any(x in inventory.EXCLUDED_DIRS for x in parts[:-1])

        def base_rows(folder):
            if folder is None:
                return c.execute('select path, size, mtime from files where disk=? and instr(path, ?) = 0', (disk, SEP))
            cond, args = hb.inside_cond('path', folder)
            return c.execute(f'select path, size, mtime from files where disk=? and {cond}', [disk] + args)
        zl = sorted(((z.lower() + SEP, keep) for z, keep in zones), key=lambda x: -len(x[0]))

        def wanted(k):
            """Самая глубокая зона над файлом решает, сверять ли его; вне зон - сверять."""
            return next((keep for z, keep in zl if k.startswith(z)), True)
        problems, checked = [], 0
        for folder in ([None] if root_files else []) + list(folders):
            exp = {}
            for p, s, mt in base_rows(folder):
                if not skipped(p):
                    exp.setdefault(p.lower(), []).append((p, s or 0, mt))
            unread = []
            if folder is None:
                cur = {}
                try:
                    with os.scandir(root) as it:
                        for e in it:
                            if inventory.excluded_file(e.name):
                                continue
                            try:
                                st = e.stat(follow_symlinks=False)
                                if (stat_mod.S_ISREG(st.st_mode)
                                        and not getattr(st, 'st_file_attributes', 0) & 0x400):
                                    cur[e.name] = dict(size=st.st_size, mtime_ns=st.st_mtime_ns)
                            except OSError as exc:
                                unread.append(f'{e.name}: {exc}')
                except OSError as exc:
                    unread.append(f'корень: {exc}')
            elif not os.path.isdir(os.path.join(root, folder)):
                cur = {}
                unread.append('папки нет на носителе')
            else:
                cur, errors, _rep = rescan.walk(root, [folder], info=False)
                unread += [f'{os.path.relpath(p, root)}: {msg}' for p, _op, msg in errors]
            if zl:
                cur = {r: v for r, v in cur.items() if wanted(r.lower())}
                exp = {k: v for k, v in exp.items() if wanted(k)}
            new, size, date, seen = [], [], [], set()
            for rel, v in cur.items():
                k = rel.lower()
                if skipped(rel):
                    continue
                checked += 1
                cand = exp.get(k)
                if not cand:
                    new.append(rel)
                    continue
                seen.add(k)
                e = next((x for x in cand if x[0] == rel), cand[0])      # точное написание - первым
                if v['size'] != e[1]:
                    size.append(rel)
                elif e[2] is not None and abs(v['mtime_ns'] // 1_000_000_000 - e[2]) > MTIME_SLACK:
                    date.append(rel)
            gone = [x[0] for k, v in exp.items() if k not in seen for x in v]
            if gone or new or size or date or unread:
                problems.append(dict(folder=folder, gone=len(gone), new=len(new), size=len(size), date=len(date),
                                     unread=len(unread),
                                     examples=dict(gone=sorted(gone)[:limit], new=sorted(new)[:limit],
                                                   size=sorted(size)[:limit], date=sorted(date)[:limit],
                                                   unread=unread[:limit])))
    finally:
        c.close()
    return dict(connected=True, reason='', letter=letter, checked=checked, problems=problems)


def toc_lines(toc):
    """Текст сверки для окна: «папка — что не так»."""
    if not toc['connected']:
        return ['Носитель не подключён — сверка оглавления с описью невозможна, поэтому задания не создаются. '
                'Подключите носитель и нажмите ещё раз. (' + toc['reason'] + ')']
    L = []
    for p in toc['problems']:
        where = '(файлы прямо в корне носителя)' if p['folder'] is None else p['folder']
        bits = [f'{w} {p[k]}' for k, w in (('gone', 'исчезли'), ('new', 'новые'), ('size', 'другой размер'),
                                           ('date', 'другая дата'), ('unread', 'не прочитано')) if p[k]]
        ex = '; '.join(x for k in ('gone', 'new', 'size', 'date', 'unread') for x in p['examples'][k][:2])
        L.append(f'{where} — ' + ', '.join(bits) + (f' (например: {ex})' if ex else ''))
    return L
