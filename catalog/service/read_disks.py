"""Чтение для окна: поколение базы, тома и носители, «Обзор», внимание, папки носителя.

Часть пакета service (бывший service.py; шаг А разбивки 17.11.2026, docs/СТРУКТУРА_ПРОГРАММЫ.md)."""
import os
import re
import shutil
import time

import build_pilot as bp
from hb_core import api as hb                 # ядро; hashbase.py - только обёртка командной строки

from .write import ro, SEP
from .directions_v3 import directions, snapshot


# ---------- чтение для окна: каждое обращение - своё соединение только для чтения ----------

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


def base_info():
    """Подвал окна: когда собрана база, сколько в ней носителей и файлов. -> (built, носителей, файлов) или None."""
    if not hb.DB.exists():
        return None
    c = ro()
    try:
        r = c.execute("select value from meta where key='built'").fetchone()
        n, files = c.execute('select count(*), coalesce(sum(total), 0) from disks').fetchone()
        return (r[0] if r else ''), n, files
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
    """Таблица носителей: номер, метка, подключён ли (буква), файлов, ГБ, опись от, состояние; partial - сколько раз
    после полной описи пересканировали выбранные папки (разные времена частичных сканов в scan_folders; этап 16 - не
    число папок), partial_folders - сколько папок; у подключённых - free_gib (свободно, ГиБ) и total_bytes (объём тома)."""
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
        parts, pfolders = {}, {}
        for d, n_t, n_f in c.execute('select disk, count(distinct time), count(*) from scan_folders group by disk'):
            parts[d], pfolders[d] = n_t, n_f
        for d, label, total, status, scanned in c.execute('select disk, label, total, status, scanned from disks order by disk'):
            rows.append(dict(disk=d, label=label.split(' - ', 1)[-1] if label else '', letter=vols.get(serial_of.get(d, '?'), ''),
                             files=total, gib=(size.get(d) or 0) / hb.GIB, status=status,
                             scanned=time.strftime('%d.%m.%Y', time.localtime(scanned)) if scanned else '',
                             partial=parts.get(d, 0), partial_folders=pfolders.get(d, 0)))
    finally:
        c.close()
    for r in rows:                         # свободное место подключённых: сведения о томе, диск не читается
        if r['letter']:
            try:
                u = shutil.disk_usage(r['letter'] + SEP)
                r['free_gib'], r['total_bytes'] = u.free / hb.GIB, u.total
            except OSError:
                pass
    return rows


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
    for key, title, items in (('tasks', 'Задания на копирование с ошибками или прерванные', bad),
                              ('logs', 'Журналы, которые программа не смогла прочитать', list(ov.get('skipped') or [])),
                              ('unique', 'Файлы, которых больше нигде нет', list(ov.get('unique') or [])),
                              ('warn', 'Прочие предупреждения базы', list(ov.get('warn') or []))):
        if items:
            groups.append(dict(key=key, title=title, items=items))
    return groups


def folder_mark(path, ms, dirs, roots):
    """Решение владельца для папки «Диски и папки» (16.11.2026) - действующая отметка разбора v3: своя или от ближайшей
    отмеченной родительской папки (весь носитель - тоже). Служебная папка переноса - своя пометка; отметка носителя в
    неё не наследуется (как в ядре). -> dict(kind 'dir'/'skip'/'unset'/'service'/'' , text, own, src)."""
    top = path.split(SEP, 1)[0] if path else ''
    copied = top in roots and top.startswith(hb.COPIED_PREFIX)     # этап 13: отметки внутри - по нынешнему пути
    if path and SEP not in path and path in roots and not (copied and ms.get(path) is not None):
        return dict(kind='service', text='уже перенесено', own=True, src='')
    if copied:
        orig, inside = path, True
    else:
        orig, inside = hb.original_of(path, roots) if path else ('', False)
    p = orig
    while True:
        m = ms.get(p)
        if m is not None:
            break
        if not p or (inside and SEP not in p):
            return dict(kind='', text='', own=False, src='')
        p = hb.parent_of(p)
    own = p.lower() == orig.lower()
    src = '' if own else ('весь носитель' if not p else p)
    if m.kind == hb.R_DIR and m.num in dirs:
        d = dirs[m.num]
        return dict(kind='dir', text=f'{d.num} {d.name}', own=own, src=src)
    if m.kind == hb.R_SKIP:
        return dict(kind='skip', text='не копировать', own=own, src=src)
    return dict(kind='unset', text=hb.mark_text(m, dirs), own=own, src=src)


def folder_children(disk, folder=''):
    """Подпапки папки (по готовой таблице folders): имя, путь, файлов, ГБ, ГБ по типам (фото, видео, тексты, прочие,
    мусор), решение владельца (старая строка решений, если есть) и mark - действующая отметка разбора (folder_mark)."""
    folder = (folder or '').strip(SEP)
    depth = (folder.count(SEP) + 1 if folder else 0) + 1
    cond, args = hb.prefix_cond('folder', folder)
    decs = hb.decisions_for(disk)
    snap = snapshot()
    dirs = hb.parse_directions(snap['directions'])
    ms = hb.MarkSet.build(hb.mark_rows(disk, snap['decisions']), dirs)
    c = ro()
    try:
        roots = hb.moved_roots(c, disk)
        q = (f'select folder, files, bytes, ' + ', '.join(f'b{i}' for i in range(5)) +
             f' from folders where disk=? and depth=? and {cond} order by bytes desc')
        res = []
        for r in c.execute(q, [disk, depth] + args):
            res.append(dict(path=r[0], name=r[0].rsplit(SEP, 1)[-1], files=r[1], gib=r[2] / hb.GIB,
                            types=[x / hb.GIB for x in r[3:8]], decision=hb.decision_of(r[0], decs) or '',
                            mark=folder_mark(r[0], ms, dirs, roots)))
        return res
    finally:
        c.close()


def folder_missing(disk, folder, targets):
    """«Чего нет на дисках направления» (раздел «Диски и папки»): по каждому диску targets - сколько файлов папки с
    хешем (любого типа) не имеют на этом диске записи с тем же SHA-256 и подтверждённым хешем (S - сканер, C -
    копирование со сверкой). Без хеша и с устаревшим хешем (X - файл изменён после подсчёта) сравнить нельзя -
    отдельными числами nohash и stale (критик GPT, этап 10); weak - из недостающих: на диске есть запись с тем же
    хешем, но копия не проверена. Решения и отметки не учитываются.
    -> dict(files, gib, nohash, stale, missing={диск: (файлов, ГиБ)}, weak={диск: файлов})."""
    folder = (folder or '').strip(SEP)
    cond, args = hb.prefix_cond('f.path', folder)
    c = ro()
    try:
        n, b = c.execute(f'select count(*), coalesce(sum(f.size),0) from files f where f.disk=? and f.sha is not null '
                         f"and coalesce(f.ev, '')<>'X' and {cond}", [disk] + args).fetchone()
        nohash = c.execute(f'select count(*) from files f where f.disk=? and f.sha is null and {cond}',
                           [disk] + args).fetchone()[0]
        missing, weak = {}, {}
        for t in targets:
            if t == disk:
                missing[t] = (0, 0.0)
                continue
            mn, mb = c.execute(
                f"""select count(*), coalesce(sum(f.size),0) from files f where f.disk=? and f.sha is not null and coalesce(f.ev, '')<>'X' and {cond}
                    and not exists (select 1 from files g where g.sha=f.sha and g.disk=? and g.ev in ('S','C'))""",
                [disk] + args + [t]).fetchone()
            missing[t] = (mn, mb / hb.GIB)
            if mn:                         # из недостающих: на диске есть запись с тем же хешем, но копия не проверена
                weak[t] = c.execute(
                    f"""select count(*) from files f where f.disk=? and f.sha is not null and coalesce(f.ev, '')<>'X' and {cond}
                        and not exists (select 1 from files g where g.sha=f.sha and g.disk=? and g.ev in ('S','C'))
                        and exists (select 1 from files g where g.sha=f.sha and g.disk=?)""",
                    [disk] + args + [t, t]).fetchone()[0]
        stale = c.execute(f"select count(*) from files f where f.disk=? and f.ev=? and {cond}",
                          [disk, hb.EV_STALE] + args).fetchone()[0]
        return dict(files=n, gib=b / hb.GIB, nohash=nohash, missing=missing, weak=weak, stale=stale)
    finally:
        c.close()


def rescans_text(n, folders=0):
    """«после полной описи 2 раза пересканированы выбранные папки (5 папок)» (этап 16, вместо «частичных: 2»)."""
    if not n:
        return ''
    word = 'раза' if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else 'раз'
    f = f' ({folders} {"папка" if folders % 10 == 1 and folders % 100 != 11 else "папки" if folders % 10 in (2, 3, 4) and folders % 100 not in (12, 13, 14) else "папок"})' if folders else ''
    return f'после полной описи {n} {word} пересканированы выбранные папки{f}'
