"""«Я сделал в Проводнике»: что изменилось на подключённом диске по сравнению с базой. Без Qt.

Сравнивается то, что база считает лежащим на носителе (таблица files: опись + журналы + ручные операции),
с оглавлением диска сейчас: только пути, размеры, даты. Содержимое файлов НЕ читается.
Различия собираются в «единицы» (папка целиком или файл), владелец отмечает нужные галочками, а строки
ручных операций пишет только service.add_manual_batch (единый путь записи, ПРАВИЛА_ЗАПИСИ_И_СБОРКИ.md, раздел 2).

Правила (спор с GPT - «Проверка Архитектуры сортировки файлов\\Я_сделал_в_Проводнике_v1.md»):
- обход только выбранных папок и только по кнопке; при остановке результат отбрасывается целиком;
- папки, которые не удалось прочитать, служебные папки, точки повторной обработки и исключения - «не проверено»:
  исчезновения внутри них не выводятся;
- ключ пути - path.lower() (как сравнивает NTFS, без нормализации Unicode); два пути с одним ключом -
  «неоднозначно», такие места не записываются;
- пара «перемещено внутри диска» (сохраняет хеш и степень) - только при равных размере И дате изменения каждого
  файла и единственном кандидате с обеих сторон; это предложение, владелец подтверждает его сам;
- появившееся, у которого в базе на другом диске есть ровно такой же файл (имя, размер, дата, один и тот же хеш) -
  предложение «скопировано с HDDxx» (копия «со слов» = степень U); без источника записать нельзя -
  только пересканировать папку (отдельная функция окна, она читает файлы и считает хеши);
- перед записью повторно проверяются том (серийный номер), поколение базы и каждое место на диске.
"""
import collections
import ctypes
import os
import sqlite3
import stat
import sys
import tempfile
import time
from pathlib import Path

import build_pilot as bp
from hb_core import api as hb
import service as sv

SEP = '\\'
BIG_FOLDER = 300000          # папка с таким числом файлов по базе по умолчанию не отмечена: обход долгий
CHILDREN_MAX = 2000          # папку-единицу с большим числом файлов нельзя раскрыть до файлов
UNITS_MAX = 5000             # больше единиц в окне не показываем (и не записываем): сузьте область

try:                         # те же правила пропуска, что у описи
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scanner'))
    from inventory import EXCLUDED_DIRS, excluded_file          # noqa: E402
except Exception:                                               # noqa: BLE001
    EXCLUDED_DIRS = {'$recycle.bin', 'system volume information', 'node_modules', '.git', '.svn', '__pycache__',
                     '.venv', 'venv', '$windows.~bt', 'recycler', '.trashes', '.fseventsd'}

    def excluded_file(name):
        n = name.lower()
        return n == '.env' or n.startswith('.env.') or n.endswith('.env')


class Stopped(Exception):
    """Владелец остановил проверку: результат не используется."""


def key(path):
    return path.lower()


def parent(path):
    return path.rsplit(SEP, 1)[0] if SEP in path else ''


def ancestors(path):
    """'a\\b\\c' -> ['a\\b', 'a'] (без корня)."""
    res = []
    p = parent(path)
    while p:
        res.append(p)
        p = parent(p)
    return res


def under(path_k, keys):
    """Лежит ли путь (ключ) внутри одного из мест (ключи) или совпадает с ним."""
    return any(path_k == k or path_k.startswith(k + SEP) for k in keys)


def plural(n, one, few, many):
    n10, n100 = n % 10, n % 100
    w = one if n10 == 1 and n100 != 11 else few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many
    return f'{n:,} {w}'.replace(',', ' ')


def gb_text(b):
    return f'{(b or 0) / hb.GIB:,.2f} ГБ'.replace(',', ' ').replace('.', ',')


def when_text(t):
    return time.strftime('%d.%m.%Y %H:%M', time.localtime(t)) if t else ''


# ---------- диск ----------

def volume_serial(root):
    ser = ctypes.c_ulong()
    if not ctypes.windll.kernel32.GetVolumeInformationW(str(root), None, 0, ctypes.byref(ser), None, None, None, 0):
        return None
    return f'{ser.value:08X}'


def disk_root(disk):
    """Корень подключённого носителя 'F:\\' и серийный номер его тома. sv.Refused - если не подключён."""
    root = sv.disk_letter(disk) + SEP
    return root, volume_serial(root)


def top_folders(disk, root=None):
    """Папки верхнего уровня для выбора: по базе (число файлов) и по диску (новые помечены).
    Первая строка - файлы в корне диска (path=''). checked - отмечать ли по умолчанию."""
    base = {r['path'].lower(): r for r in sv.folder_children(disk)}
    excl = {x.lower() for x in hb.read_exclusions().get(disk, [])}
    res, seen = [], set()
    on_disk = {}
    if root:
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False) and e.name.lower() not in EXCLUDED_DIRS \
                                and not e.stat(follow_symlinks=False).st_file_attributes & 0x400:
                            on_disk[e.name.lower()] = e.name
                    except OSError:
                        pass
        except OSError:
            pass
    for k, r in base.items():
        if k in excl:
            continue
        res.append(dict(path=r['path'], files=r['files'], gib=r['gib'], on_disk=k in on_disk if root else None,
                        new=False, checked=r['files'] < BIG_FOLDER))
        seen.add(k)
    for k, name in on_disk.items():
        if k not in seen and k not in excl:
            res.append(dict(path=name, files=0, gib=0, on_disk=True, new=True, checked=True))
    res.sort(key=lambda r: r['path'].lower())
    res.insert(0, dict(path='', files=None, gib=None, on_disk=True, new=False, checked=True))
    return res


# ---------- обход и сравнение ----------

class Diff:
    """Итог сравнения: единицы различий и сведения для повторной проверки перед записью."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _walk(root, folders, root_files, excl_k, cur, progress, stop):
    """Оглавление выбранных папок -> таблицы d (файлы) и dirs (папки) во временной базе.
    Возвращает список мест «не проверено» (путь, причина)."""
    bad = []
    stack = [f for f in folders if f]
    done = dict(dirs=0, files=0, started=time.time())

    def add_dir(rel, mt):
        cur.execute('insert or ignore into dirs values (?,?,?)', (key(rel), rel, mt))

    if root_files:                                     # файлы в самом корне (папки корня - только выбранные)
        try:
            with os.scandir(root) as it:
                for e in it:
                    try:
                        if excluded_file(e.name):
                            continue
                        st = e.stat(follow_symlinks=False)
                        if stat.S_ISREG(st.st_mode) and not st.st_file_attributes & 0x400:
                            _put_file(cur, e.name, st)
                            done['files'] += 1
                    except OSError as exc:
                        bad.append((e.name, f'не прочитан: {exc.strerror or exc}'))
        except OSError as exc:
            raise sv.Refused(f'Корень диска не читается: {exc}')
    while stack:
        rel = stack.pop()
        if stop is not None and stop.is_set():
            raise Stopped()
        full = os.path.join(root, rel)
        try:
            add_dir(rel, os.stat(full, follow_symlinks=False).st_mtime_ns // 10 ** 9)
            with os.scandir(full) as it:
                for e in it:
                    sub = rel + SEP + e.name
                    if excluded_file(e.name):
                        continue
                    try:
                        st = e.stat(follow_symlinks=False)
                        if st.st_file_attributes & 0x400 or stat.S_ISLNK(st.st_mode):
                            bad.append((sub, 'точка повторной обработки - не проверяется'))
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            if e.name.lower() in EXCLUDED_DIRS:
                                bad.append((sub, 'служебная папка - не проверяется'))
                            elif key(sub) in excl_k:
                                bad.append((sub, 'папка в исключениях - не проверяется'))
                            else:
                                stack.append(sub)
                            continue
                        if stat.S_ISREG(st.st_mode):
                            _put_file(cur, sub, st)
                            done['files'] += 1
                    except OSError as exc:
                        bad.append((sub, f'не прочитан: {exc.strerror or exc}'))
        except FileNotFoundError:
            if rel in folders:
                continue                               # выбранной папки на диске нет: исчезла целиком
            bad.append((rel, 'папка пропала во время проверки'))
        except OSError as exc:
            bad.append((rel, f'папка не прочитана: {exc.strerror or exc}'))
        done['dirs'] += 1
        if progress:
            progress(dict(done))
    return bad


def _put_file(cur, rel, st):
    born = getattr(st, 'st_birthtime', None) or st.st_ctime
    try:
        cur.execute('insert into d values (?,?,?,?,?)', (key(rel), rel, st.st_size, st.st_mtime_ns // 10 ** 9, int(born)))
    except sqlite3.IntegrityError:
        cur.execute('insert or ignore into dup values (?,?)', (key(rel), rel))


def scan(disk, root, folders, root_files=True, progress=None, stop=None, serial=None):
    """Сравнить базу с оглавлением выбранных папок диска. folders - папки верхнего уровня (как в базе/на диске).
    Только оглавление: размеры и даты; файлы не открываются."""
    folders = [f.strip(SEP) for f in folders if f and f.strip(SEP)]
    if not folders and not root_files:
        raise sv.Refused('Отметьте хотя бы одну папку, где искать изменения.')
    excl = hb.read_exclusions().get(disk, [])
    excl_k = {key(x) for x in excl}
    gen = sv.generation()
    fd, tmp = tempfile.mkstemp(prefix='проводник_', suffix='.sqlite')
    os.close(fd)
    c = sqlite3.connect(f'file:{Path(tmp).as_posix()}', uri=True)     # uri: чтобы подключить базу только для чтения
    try:
        c.create_function('k', 1, lambda p: p.lower() if p is not None else None, deterministic=True)
        c.executescript('''pragma journal_mode=off; pragma synchronous=off;
            create table d(k text primary key, path text, size integer, mtime integer, born integer) without rowid;
            create table dirs(k text primary key, path text, mtime integer) without rowid;
            create table dup(k text, path text, primary key(k, path)) without rowid;
            create table b(k text, path text, size integer, mtime integer, primary key(k, path)) without rowid;''')
        bad = _walk(root, folders, root_files, excl_k, c, progress, stop)
        c.commit()
        if stop is not None and stop.is_set():
            raise Stopped()
        c.execute('attach database ? as base', (f'file:{hb.DB.as_posix()}?mode=ro',))
        conds, args = [], []
        for f in folders:
            cond, a = hb.prefix_cond('path', f)
            conds.append(cond)
            args += a
        if root_files:
            conds.append("instr(path, '\\') = 0")
        c.execute(f'insert or ignore into b select k(path), path, size, mtime from base.files where disk=? and '
                  f'({" or ".join(conds)})', [disk] + args)
        c.execute('insert or ignore into dup select k, path from b where k in (select k from b group by k having count(*) > 1)')
        base_counts = {}
        for f in folders:
            cond, a = hb.prefix_cond('folder', f)
            base_counts.update((r[0], r[1]) for r in c.execute(f'select folder, files from base.folders where disk=? and {cond}', [disk] + a))
        dup_k = {r[0] for r in c.execute('select k from dup')}
        bad_k = [key(p) for p, _ in bad] + sorted(dup_k)
        gone = [r for r in c.execute('select path, size, mtime from b where k not in (select k from d) order by path')
                if not under(key(r[0]), bad_k)]
        new = [r for r in c.execute('select path, size, mtime, born from d where k not in (select k from b) order by path')
               if r[0].lower() not in dup_k]
        changed = c.execute('select d.path, b.size, d.size from d join b on b.k=d.k where b.size <> d.size order by d.path').fetchall()
        case = c.execute('select b.path, d.path from d join b on b.k=d.k where b.path <> d.path and b.size = d.size order by d.path').fetchall()
        touched = c.execute('select d.path, b.mtime, d.mtime from d join b on b.k=d.k where b.size = d.size and b.mtime is not null '
                            'and b.mtime <> d.mtime order by d.path').fetchall()     # тот же размер, другая дата: содержимое могли изменить
        dirs = {r[0]: (r[1], r[2]) for r in c.execute('select k, path, mtime from dirs')}
        units = group(disk, gone, new, base_counts, dirs, c, bad_k)
        res = Diff(disk=disk, root=root, serial=serial, generation=gen, folders=folders, root_files=root_files,
                   units=units, bad=bad, dup=sorted(dup_k), changed=changed, case=case, touched=touched, scanned=len(dirs),
                   files=c.execute('select count(*) from d').fetchone()[0], at=time.time())
        return res
    finally:
        c.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ---------- единицы ----------

def _unit(kind, path, files, size, when, children=None, **kw):
    u = dict(kind=kind, path=path, is_dir=children is not None or kw.pop('is_dir', False), files=files, bytes=size,
             when=when, children=children)
    u.update(kw)
    return u


def group(disk, gone, new, base_counts, dirs, c, bad_k=()):
    """Исчезнувшие и появившиеся файлы -> единицы: самая верхняя папка, где исчезли ВСЕ файлы базы (или где
    появились только новые файлы), иначе - отдельный файл. Затем пары перемещений и источники на других дисках.
    c - временная база сравнения (таблицы d, b, dirs; подключена base)."""
    def dir_time(path):                                  # подсказка: дата изменения ближайшей папки на диске
        for p in [path] + ancestors(path):
            if key(p) in dirs:
                return dirs[key(p)][1]
        return None

    # исчезли
    cnt = collections.Counter()
    for p, size, mt in gone:
        for a in ancestors(p):
            cnt[a] += 1
    full = {a for a, n in cnt.items() if n == base_counts.get(a, -1)}
    tops = {a for a in full if not any(x in full for x in ancestors(a))}
    units = []
    by_top = collections.defaultdict(list)
    for p, size, mt in gone:
        top = next((a for a in reversed(ancestors(p)) if a in tops), None)
        if top:
            by_top[top].append((p, size, mt))
        else:
            units.append(_unit('gone', p, 1, size, dir_time(parent(p)), mtime=mt))
    for top, rows in by_top.items():
        units.append(_unit('gone', top, len(rows), sum(r[1] or 0 for r in rows), dir_time(parent(top)),
                           children=[dict(path=p, bytes=s, mtime=m) for p, s, m in rows] if len(rows) <= CHILDREN_MAX else [],
                           sig=_sig(top, rows)))
    # появились
    disk_cnt = collections.Counter()
    for (p,) in c.execute('select path from d'):
        for a in ancestors(p):
            disk_cnt[a] += 1
    ncnt = collections.Counter()
    for p, *_ in new:
        for a in ancestors(p):
            ncnt[a] += 1
    base_k = {k.lower() for k, n in base_counts.items() if n}
    full = {a for a, n in ncnt.items() if n == disk_cnt[a] and a.lower() not in base_k}
    tops = {a for a in full if not any(x in full for x in ancestors(a))}
    by_top = collections.defaultdict(list)
    for p, size, mt, born in new:
        top = next((a for a in reversed(ancestors(p)) if a in tops), None)
        if top:
            by_top[top].append((p, size, mt, born))
        else:
            units.append(_unit('new', p, 1, size, max(mt or 0, born or 0), mtime=mt))
    for top, rows in by_top.items():
        units.append(_unit('new', top, len(rows), sum(r[1] or 0 for r in rows),
                           max([max(r[2] or 0, r[3] or 0) for r in rows] + [dirs.get(key(top), (0, 0))[1] or 0]),
                           children=[dict(path=p, bytes=s, mtime=m) for p, s, m, _ in rows] if len(rows) <= CHILDREN_MAX else [],
                           sig=_sig(top, [r[:3] for r in rows])))
    for u in units:                  # в папке есть непроверенное место: её нельзя переносить или копировать целиком
        u['tainted'] = u['is_dir'] and any(b.startswith(key(u['path']) + SEP) for b in bad_k)
    _pair_moves(units)
    _find_sources(disk, units, c)
    units.sort(key=lambda u: (u.get('src') or u['path']).lower())
    return units


def _sig(top, rows):
    """Подпись папки: (путь внутри папки в нижнем регистре, размер, дата изменения) всех файлов."""
    n = len(top) + 1
    return tuple(sorted((p[n:].lower(), s, m) for p, s, m in rows))


def _pair_moves(units):
    """Исчезнувшее + появившееся на том же диске = перемещено/переименовано, если совпадение единственное."""
    gone = [u for u in units if u['kind'] == 'gone']
    new = [u for u in units if u['kind'] == 'new']

    def match(g, n):
        if g['tainted'] or n['tainted'] or g['is_dir'] != n['is_dir'] or g['files'] != n['files'] or g['bytes'] != n['bytes']:
            return False
        if g['is_dir']:
            return g['sig'] == n['sig'] and all(x[2] is not None for x in g['sig'])
        if g['mtime'] is None or g['mtime'] != n['mtime']:
            return False
        gname, nname = g['path'].rsplit(SEP, 1)[-1].lower(), n['path'].rsplit(SEP, 1)[-1].lower()
        return gname == nname or parent(g['path']).lower() == parent(n['path']).lower()

    cand_g = collections.defaultdict(list)
    cand_n = collections.defaultdict(list)
    by_size = collections.defaultdict(list)
    for n in new:
        by_size[(n['is_dir'], n['bytes'])].append(n)
    for g in gone:
        for n in by_size.get((g['is_dir'], g['bytes']), []):
            if match(g, n):
                cand_g[id(g)].append(n)
                cand_n[id(n)].append(g)
    drop = set()
    for g in gone:
        ns = cand_g.get(id(g), [])
        if len(ns) == 1 and len(cand_n[id(ns[0])]) == 1:
            n = ns[0]
            g.update(kind='move', src=g['path'], path=n['path'], when=max(g['when'] or 0, n['when'] or 0))
            if g['is_dir']:
                pairs = {x['path'][len(g['src']) + 1:].lower(): x['path'] for x in g['children'] or []}
                g['children'] = [dict(path=pairs[x['path'][len(n['path']) + 1:].lower()], dst=x['path'],
                                      bytes=x['bytes'], mtime=x['mtime']) for x in n['children'] or []] if g['children'] else []
            drop.add(id(n))
    units[:] = [u for u in units if id(u) not in drop]


def _find_sources(disk, units, c):
    """Появившееся, у которого в базе на ДРУГОМ диске есть ровно такие же файлы (имя, размер, дата, один хеш) ->
    предложение «скопировано с того диска»."""
    for u in units:
        if u['kind'] != 'new' or u['files'] == 0 or u['tainted']:
            continue
        if not u['is_dir']:
            src = _same_file(c, disk, u['path'], u['bytes'], u['mtime'])
            if src:
                u.update(kind='copy', src_disk=src[0], src=src[1], others=src[2])
            continue
        if not u['sig']:
            continue
        tail, size, mt = max(u['sig'], key=lambda x: x[1])
        found = None
        name = hb.name_key(tail)
        for d2, p2 in c.execute('select disk, path from base.files where name_lc=? and size=? and disk<>? limit 40',
                                (name, size, disk)):
            if not p2.lower().endswith(SEP + tail):
                continue
            folder = p2[:len(p2) - len(tail) - 1]
            cond, a = hb.prefix_cond('path', folder)
            rows = c.execute(f'select path, size, mtime from base.files where disk=? and {cond}', [d2] + a).fetchall()
            if _sig(folder, rows) == u['sig']:
                found = (d2, folder) if not found or d2 in hb.MAIN else found
        if found:
            u.update(kind='copy', src_disk=found[0], src=found[1], others=0)


def _same_file(c, disk, path, size, mt):
    """Единственный по содержимому источник файла на другом диске: (диск, путь, сколько ещё копий) или None."""
    if mt is None:
        return None
    rows = c.execute('select disk, path, coalesce(sha, sha_exp), ev from base.files where name_lc=? and size=? and mtime=? '
                     'and disk<>? limit 50', (hb.name_key(path), size, mt, disk)).fetchall()
    hashes = {r[2] for r in rows}
    if not rows or None in hashes or len(hashes) != 1:
        return None
    best = sorted(rows, key=lambda r: (r[3] not in ('S', 'C'), r[0] not in hb.MAIN, r[0], r[1]))[0]
    return best[0], best[1], len(rows) - 1


# ---------- что будет записано ----------

def rows_for(disk, unit, chosen=None):
    """Строки ручных операций для единицы: chosen=None - целиком (одна строка), иначе - индексы отмеченных
    файлов внутри папки (строка на файл). Строка: (действие, диск, путь, диск2, путь2, файлов, байт)."""
    k = unit['kind']
    if chosen is None:
        items = [dict(path=unit.get('src') or unit['path'], dst=unit['path'], bytes=unit['bytes'], files=unit['files'])]
    else:
        items = []
        for i in chosen:
            ch = unit['children'][i]
            if k == 'move':
                items.append(dict(path=ch['path'], dst=ch['dst'], bytes=ch['bytes'], files=1))
            elif k == 'copy':
                items.append(dict(path=unit['src'] + ch['path'][len(unit['path']):], dst=ch['path'], bytes=ch['bytes'], files=1))
            else:
                items.append(dict(path=ch['path'], dst=ch['path'], bytes=ch['bytes'], files=1))
    res = []
    for it in items:
        if k == 'gone':
            res.append(('удалено', disk, it['path'], '', '', it['files'], it['bytes']))
        elif k == 'move':
            res.append(('перемещено', disk, it['path'], disk, it['dst'], it['files'], it['bytes']))
        elif k == 'copy':
            res.append(('скопировано', unit['src_disk'], it['path'], disk, it['dst'], it['files'], it['bytes']))
    return res


def summary(rows):
    """«Будет записано: удалено - 3 папки и 5 файлов (1 240 файлов, 12,00 ГБ); …»"""
    if not rows:
        return 'Ничего не отмечено.'
    names = {'удалено': 'удалено', 'перемещено': 'перемещено внутри диска', 'скопировано': 'скопировано с других дисков'}
    parts = []
    for act in ('удалено', 'перемещено', 'скопировано'):
        rs = [r for r in rows if r[0] == act]
        if not rs:
            continue
        nf = sum(1 for r in rs if len(r) > 7 and r[7])          # r[7] - строка на папку целиком
        nfile = len(rs) - nf
        what = ' и '.join(x for x in (plural(nf, 'папка', 'папки', 'папок') if nf else '',
                                       plural(nfile, 'файл', 'файла', 'файлов') if nfile else '') if x)
        files = f'{plural(sum(r[5] for r in rs), "файл", "файла", "файлов")}, ' if nf else ''
        parts.append(f'{names[act]} — {what} ({files}{gb_text(sum(r[6] or 0 for r in rs))})')
    return 'Будет записано: ' + '; '.join(parts) + '.'


def selection_rows(diff, choice):
    """choice: {номер единицы: None (целиком) или [индексы файлов]}. Строки с признаком «папка» в конце."""
    rows = []
    for i, chosen in sorted(choice.items()):
        u = diff.units[i]
        for r in rows_for(diff.disk, u, chosen):
            rows.append(r + (u['is_dir'] and chosen is None,))
    return rows


# ---------- запись ----------

def check_date(c, date, disk, path):
    """Дата операции не раньше описи диска и пересканирования этого места (иначе база её не применит)."""
    when = hb.manual_time(date)
    r = c.execute('select scanned from disks where disk=?', (disk,)).fetchone()
    latest = r[0] if r and r[0] else 0
    pk = key(path)
    for f, t in c.execute('select folder, time from scan_folders where disk=?', (disk,)):
        fk = key(f)
        if under(pk, [fk]) or fk.startswith(pk + SEP):
            latest = max(latest, t or 0)
    if when < latest:
        raise sv.Refused(f'Дата {date} раньше описи или пересканирования {disk}\\{path} '
                         f'({time.strftime("%d.%m.%Y", time.localtime(latest))}): база такую операцию не применит. '
                         'Укажите дату, когда вы сделали это в Проводнике (не раньше этой).')


def verify_disk(diff, rows):
    """Перед записью: тот же том, та же база, и на диске всё ещё так, как показано."""
    if diff.root and diff.serial and volume_serial(diff.root) != diff.serial:
        raise sv.Refused(f'Под буквой {diff.root} сейчас другой диск. Проверьте заново.')
    if sv.generation() != diff.generation:
        raise sv.Refused('База обновилась после проверки (пришли новые журналы или записи). Нажмите «Проверить» ещё раз.')
    for act, d, p, d2, p2, *_ in rows:
        if act in ('удалено', 'перемещено') and d == diff.disk and os.path.lexists(os.path.join(diff.root, p)):
            raise sv.Refused(f'{d}\\{p} снова есть на диске. Нажмите «Проверить» ещё раз.')
        if act in ('перемещено', 'скопировано') and not os.path.lexists(os.path.join(diff.root, p2)):
            raise sv.Refused(f'{d2}\\{p2} уже нет на диске. Нажмите «Проверить» ещё раз.')
    exp = expected(diff)
    for act, d, p, d2, p2, *_ in rows:          # то ли это, что сопоставили при проверке (размер, дата, состав папки)
        e = exp.get(key(p2)) if act in ('перемещено', 'скопировано') else None
        if not e:
            continue
        try:
            if e[0] == 'dir':
                same = disk_sig(diff.root, p2) == e[1]
            else:
                st = os.stat(os.path.join(diff.root, p2), follow_symlinks=False)
                same = (st.st_size, st.st_mtime_ns // 10 ** 9) == (e[1], e[2])
        except OSError:
            same = False
        if not same:
            raise sv.Refused(f'{d2}\\{p2} изменился после проверки. Нажмите «Проверить» ещё раз.')


def disk_sig(root, folder):
    """Подпись папки на диске сейчас (как _sig): только оглавление."""
    rows = []
    for dp, dn, fn in os.walk(os.path.join(root, folder)):
        dn[:] = [x for x in dn if x.lower() not in EXCLUDED_DIRS]
        for f in fn:
            if excluded_file(f):
                continue
            full = os.path.join(dp, f)
            st = os.stat(full, follow_symlinks=False)
            rows.append((os.path.relpath(full, root), st.st_size, st.st_mtime_ns // 10 ** 9))
    return _sig(folder, rows)


def expected(diff):
    """Назначение перемещения/копии -> что нашла проверка: ('dir', подпись) или ('file', размер, дата)."""
    res = {}
    for u in diff.units:
        if u['kind'] not in ('move', 'copy'):
            continue
        if u['is_dir']:
            res[key(u['path'])] = ('dir', u['sig'])
            for ch in u['children'] or []:
                res[key(ch.get('dst') or ch['path'])] = ('file', ch['bytes'], ch['mtime'])
        else:
            res[key(u['path'])] = ('file', u['bytes'], u['mtime'])
    return res


def check_overlap(rows):
    srcs = sorted((r[1], key(r[2])) for r in rows)
    for (d1, a), (d2, b) in zip(srcs, srcs[1:]):
        if d1 == d2 and (a == b or b.startswith(a + SEP)):
            raise sv.Refused(f'Одно место выбрано дважды: {d1}\\{a}. Проверьте заново.')


def write(date, rows, note='окно «Я сделал в Проводнике»', diff=None, add=None, progress=None):
    """Записать строки одним пакетом через service.add_manual_batch: все проверки заранее, все строки - одной записью
    на диск, одно применение к базе; при любой ошибке не пишется ничего. Строки, уже записанные раньше, пропускаются.
    Ответ: dict(written=[(строка, номер)], skipped=[строка уже записана], failed=None | (строка, причина),
    remaining=[не записанные]). add - замена add_manual_batch (тесты)."""
    add = add or sv.add_manual_batch
    if not rows:
        raise sv.Refused('Ничего не отмечено.')
    if not sv.DATE_RE.match(date or ''):
        raise sv.Refused('Дата - в виде ДД.ММ.ГГГГ.')
    rows = [tuple(r[:5]) for r in rows]
    check_overlap(rows)
    if diff is not None:
        verify_disk(diff, rows)
    todo, skipped = [], []
    c = sv.ro()
    try:
        for r in rows:
            if r[0] != 'скопировано':                  # копия не меняет источник: важна только дата назначения
                check_date(c, date, r[1], r[2])
            if r[3]:
                check_date(c, date, r[3], r[4])
    finally:
        c.close()
    already = {tuple(f[:6]) for _, f in hb.manual_rows()}
    for r in rows:
        if (date,) + r in already:                     # записано прошлой попыткой
            skipped.append(r)
            continue
        try:
            sv.manual_preview(date, *r)
            todo.append(r)
        except sv.Refused as e:
            if 'уже записана' in str(e):
                skipped.append(r)
            else:
                raise sv.Refused(f'{r[1]}{SEP}{r[2]}: {e} Ничего не записано.')
    written, failed = [], None
    if todo:
        try:
            res = add(date, todo, note=note)
            written = [(r, ln) for r, (_, ln) in zip(todo, res)]
        except Exception as e:                                   # noqa: BLE001
            failed = (todo[0], str(e))
        if progress:
            progress(len(written), len(todo))
    remaining = todo[1:] if failed else []
    return dict(written=written, skipped=skipped, failed=failed, remaining=remaining)


def result_text(res):
    lines = [f'Записано строк: {len(res["written"])}.']
    if res['skipped']:
        lines.append(f'Уже были записаны раньше (пропущены): {len(res["skipped"])}.')
    if res['failed']:
        r, msg = res['failed']
        lines.append(f'ОСТАНОВЛЕНО: {msg}')
        lines.append(f'Не записано ничего (строк: {len(res["remaining"]) + 1}): запись идёт одним пакетом - всё или '
                     'ничего. Нажмите «Проверить» и «Записать» ещё раз.')
    return '\n'.join(lines)


# ---------- диск не подключён: папки из базы ----------

def offline_rows(disk, act, folders, disk2='', dest=''):
    """Строки для отключённого диска: отмеченные папки (вложенные в отмеченные отбрасываются)."""
    folders = sorted({f.strip(SEP) for f in folders if f.strip(SEP)}, key=str.lower)
    top = [f for f in folders if not any(key(f).startswith(key(g) + SEP) for g in folders if g != f)]
    res = []
    for f in top:
        if act == 'удалено':
            res.append(('удалено', disk, f, '', ''))
        else:
            if not disk2:
                raise sv.Refused('Выберите диск, куда скопировали или переместили.')
            d = dest.strip().strip(SEP)
            res.append((act, disk, f, disk2, (d + SEP if d else '') + f.rsplit(SEP, 1)[-1]))
    return res


# ---------- записанные действия ----------

def recorded(disk=None):
    """Строки «ручные операции.tsv», новые сверху: dict(line, fields, date, act, src, dst, note, text)."""
    res = []
    for ln, f in hb.manual_rows():
        date, act, d, p, d2, p2, note = f[:7]
        if disk and disk not in (d, d2):
            continue
        res.append(dict(line=ln, fields=f[:7], date=date, act=act, src=f'{d}\\{p}', dst=f'{d2}\\{p2}' if d2 else '',
                        note=note, text=describe(f[:7])))
    res.sort(key=lambda r: -r['line'])
    return res


def describe(f):
    date, act, d, p, d2, p2 = (list(f) + [''] * 7)[:6]
    if act == 'удалено':
        return f'{date}: удалено {d}\\{p}'
    if act == 'перемещено' and d == d2:
        return f'{date}: перемещено внутри {d}: {p} → {p2}'
    return f'{date}: {act} {d}\\{p} → {d2}\\{p2}'


def fix_check(fields, disks):
    """Проверка исправленной строки (fix_manual сам поля не проверяет)."""
    date, act, d, p, d2, p2, note = (list(fields) + [''] * 7)[:7]
    if act not in sv.ACTIONS:
        raise sv.Refused('Выберите действие.')
    if not sv.DATE_RE.match(date):
        raise sv.Refused('Дата - в виде ДД.ММ.ГГГГ.')
    if d not in disks:
        raise sv.Refused(f'Носителя «{d}» нет в базе.')
    if p.startswith(SEP) or p2.startswith(SEP):
        raise sv.Refused('Путь пишется от корня диска без буквы и без «\\» в начале, например «Фото\\2014».')
    p = sv.check_rel(p)
    if act == 'удалено':
        d2 = p2 = ''
    else:
        if d2 not in disks:
            raise sv.Refused('Выберите диск, куда скопировали или переместили.')
        p2 = sv.check_rel(p2, 'путь назначения')
    return [date, act, d, p, d2, p2, note]


def fix(line_no, old_fields, fields, reason, fixer=None):
    """Исправить строку: под рукой сервиса; сначала проверяется, что строка не изменилась с момента показа."""
    if not (reason or '').strip():
        raise sv.Refused('Напишите, почему исправляете: это сохранится в комментарии строки.')
    now = dict(hb.manual_rows()).get(line_no)
    if now is None or [x.strip() for x in now[:7]] != [x.strip() for x in old_fields[:7]]:
        raise sv.Refused('Эту строку за это время изменили. Обновите список и выберите её снова.')
    if [x.strip() for x in fields[:7]] == [x.strip() for x in old_fields[:7]]:
        raise sv.Refused('Вы ничего не изменили.')
    (fixer or sv.fix_manual)(line_no, list(fields), reason.strip())
