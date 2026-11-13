"""Общая база хешей: быстрые ответы на типовые вопросы без чтения дисков и без подсчётов в чате.

Одна база SQLite собирается из описей всех носителей (hashes.sqlite) и поправок:
  - журналы скриптов копирования, перемещения и корзины из «Каталог дисков\\<задача>\\Журнал*.tsv»;
  - «Каталог дисков\\_БАЗА\\ручные операции.tsv» - то, что пользователь сделал в Проводнике;
  - «Каталог дисков\\_БАЗА\\решения.tsv» - решения пользователя («не нужно», «раздел: …»).
Рабочая база пересобирается сама, если появился новый журнал или изменились эти таблицы; снимок описей
(все 11,3 млн файлов) собирается один раз и заново только при изменении самих описей.
Фото и видео сравниваются по SHA-256 - точно. Остальные файлы (без хеша) - по имени и размеру:
«копия не найдена» / «вероятная копия»; для ответа «можно удалять» вероятная копия не засчитывается.
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
  py catalog\\hashbase.py build                               пересобрать базу сейчас
  py catalog\\hashbase.py stats                               что в базе и какие поправки учтены
В чат печатается короткая сводка; полный список по файлам - в «Каталог дисков\\_БАЗА\\ответы\\».
"""
import argparse
import collections
import csv
import glob
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
    global BASE_DIR, DB, SNAP, MANUAL, DECISIONS, ANSWERS, TEMPLATE
    BASE_DIR = Path(out_dir) / '_БАЗА'
    DB = BASE_DIR / 'хеши.sqlite'          # рабочая база: снимок описей + поправки
    SNAP = BASE_DIR / 'описи.sqlite'       # снимок описей; пересобирается, только если изменились сами описи
    MANUAL = BASE_DIR / 'ручные операции.tsv'
    DECISIONS = BASE_DIR / 'решения.tsv'
    ANSWERS = BASE_DIR / 'ответы'
    TEMPLATE = Path(out_dir) / '_ШАБЛОН копирования'


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
SNAPSHOT_VERSION = 2          # менять при изменении структуры снимка

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

def scans_signature(jobs):
    sig = [('версия снимка', SNAPSHOT_VERSION)]
    for d, j in jobs.items():
        for fn in ('hashes.sqlite', 'inventory.sqlite'):
            p = j['dir'] / fn
            if p.exists():
                sig.append((d, fn, p.stat().st_mtime_ns, p.stat().st_size))
    return json.dumps(sig, ensure_ascii=False, sort_keys=True)


def sources_signature(jobs):
    sig = [('программа', os.path.getmtime(__file__)),      # изменилась программа - поправки накладываются заново
           ('описи', scans_signature(jobs))]
    for p in sorted(glob.glob(str(bp.OUT_DIR / '*' / 'Журнал*.tsv'))):
        sig.append((p, os.path.getmtime(p), os.path.getsize(p)))
    for p in (MANUAL, DECISIONS):
        if p.exists():
            sig.append((str(p), p.stat().st_mtime_ns, p.stat().st_size))
    return json.dumps(sig, ensure_ascii=False, sort_keys=True)


def ensure_tables():
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    ANSWERS.mkdir(exist_ok=True)
    if not MANUAL.exists():
        MANUAL.write_text(MANUAL_HEAD + '\n', encoding='utf-8-sig')
    if not DECISIONS.exists():
        DECISIONS.write_text(DECISION_HEAD + '\n', encoding='utf-8-sig')


def read_tsv(path):
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        return [r for r in csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE) if r and any(x.strip() for x in r)]


def serial_map(jobs):
    m = {}
    for d, j in jobs.items():
        try:
            ser = json.loads((j['dir'] / 'job.json').read_text(encoding='utf-8'))['record']['volume_serial']
            m[str(ser).upper()] = d
        except (OSError, ValueError, KeyError):
            pass
    return m


def apply_log(c, log, jobs, serials, report):
    task = Path(log).parent
    rows = read_tsv(log)
    if len(rows) < 2:
        return
    head = [h.strip().lower() for h in rows[0]]
    body = rows[1:]
    name = f'{task.name}\\{Path(log).name}'
    added = removed = moved = nosha = 0
    lookup = lambda disk, rel: c.execute('select sha, size, mtime from files where disk=? and path=?', (disk, rel)).fetchone()

    def put(disk, path, size, sha, mtime=None):
        c.execute('insert or replace into files(disk, path, size, sha, origin, name_lc, mtime) values (?,?,?,?,?,?,?)',
                  (disk, path, size, sha, 'журнал: ' + name, name_key(path), mtime))

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
            dst = rel_of(f[i_dst])[1]
            sha = (f[i_h].strip().lower() if i_h is not None and len(f) > i_h else '') or None
            got = lookup(src_disk, rel_of(f[i_src])[1]) if src_disk else None
            if not sha and got:
                sha = got[0]
            if not sha:
                nosha += 1                 # файл без хеша: в базе будет числиться по имени и размеру
            put(disk, dst, int(f[i_s]), sha, got[2] if got else None)
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
                put(db_, rb, int(f[i_s]), got[0] if got else None, got[2] if got else None); added += 1
                if not (got and got[0]):
                    nosha += 1
            elif f[i_r].startswith('перемещ'):
                if got:
                    c.execute('delete from files where disk=? and path=?', (da, ra))
                    put(db_, rb, got[1], got[0], got[2]); moved += 1
    elif task.name in OLD_LOGS and 'в корзину' in head:
        letters = OLD_LOGS[task.name]
        i_r, i_a = head.index('результат'), head.index('в корзину')
        for f in body:
            if len(f) > i_a and f[i_r].startswith('в корзин'):
                l, r = rel_of(f[i_a])
                if l in letters:
                    removed += c.execute('delete from files where disk=? and path=?', (letters[l], r)).rowcount
    elif task.name in FOLDER_MOVES and head[:3] == ['время', 'результат', 'папка']:
        disk, src_base, dst_base = FOLDER_MOVES[task.name]
        for f in body:
            if len(f) < 3 or not f[1].startswith('перемещ'):
                continue
            old = src_base + SEP + f[2]
            cond, args = prefix_cond('path', old)
            moved += c.execute(f'update files set path = ? || substr(path, ?), origin = ? where disk=? and {cond}',
                               [dst_base + SEP + f[2], len(old) + 1, 'журнал: ' + name, disk] + args).rowcount
    else:
        report['skipped'].append(name)
        return
    report['logs'].append(f'{name}: добавлено {added}, перемещено {moved}, убрано {removed}'
                          + (f' (из добавленных без хеша: {nosha})' if nosha else ''))


def apply_manual(c, report):
    n = 0
    for f in read_tsv(MANUAL)[1:]:
        f = [x.strip() for x in f] + [''] * 7
        date, act, disk, path, disk2, path2 = f[:6]
        act = act.lower()
        cond, args = prefix_cond('path', path)
        if act.startswith('удал'):
            k = c.execute(f'delete from files where disk=? and {cond}', [disk] + args).rowcount
        elif act.startswith(('скопир', 'перемещ')):
            rows = c.execute(f'select path, size, sha, name_lc, mtime from files where disk=? and {cond}', [disk] + args).fetchall()
            base = path.rstrip(SEP)
            for p, size, sha, nm, mt in rows:
                tail = p[len(base):].lstrip(SEP)
                newp = (path2.rstrip(SEP) + (SEP + tail if tail else '')) if tail or path2 else p
                c.execute('insert or replace into files(disk, path, size, sha, origin, name_lc, mtime) values (?,?,?,?,?,?,?)',
                          (disk2, newp, size, sha, f'вручную {date}', nm if tail else name_key(newp), mt))
            if act.startswith('перемещ'):
                c.execute(f'delete from files where disk=? and {cond} and origin not like ?', [disk] + args + [f'вручную {date}'])
            k = len(rows)
        else:
            report['warn'].add(f'ручные операции: непонятное действие «{act}»')
            continue
        n += 1
        report['manual'].append(f'{date} {act} {disk}:{path}' + (f' -> {disk2}:{path2}' if disk2 else '') + f' - {k} файлов')
    return n


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


def build_snapshot(jobs, quiet=False):
    """Снимок описей: все файлы всех носителей (с хешем и без). Долго (минуты), но только когда изменились описи."""
    t0 = time.time()
    tmp = SNAP.with_suffix('.tmp')
    if tmp.exists():
        tmp.unlink()
    c = sqlite3.connect(tmp)
    c.executescript('''
        pragma journal_mode=off; pragma synchronous=off; pragma cache_size=-400000;
        create table files(disk text not null, path text not null, size integer, sha text, origin text,
                           name_lc text, mtime integer, primary key(disk, path)) without rowid;
        create table meta(key text primary key, value text);
        create table disks(disk text primary key, label text, hashed integer, total integer);
    ''')
    n_all = n_hash = 0
    for d, j in jobs.items():
        hp, ip = j['dir'] / 'hashes.sqlite', j['dir'] / 'inventory.sqlite'
        hashes = {}
        if hp.exists():
            with bp.ro(hp) as h:
                hashes = {p: (s, x) for p, s, x in h.execute(
                    "select path, size, lower(sha256) from hashes where status='verified' and sha256 is not null and sha256<>''")}

        def rows():
            seen = set()
            if ip.exists():
                with bp.ro(ip) as inv:
                    for p, size, mt in inv.execute('select path, size, mtime_ns from files order by path'):
                        got = hashes.get(p)
                        if got:
                            seen.add(p)
                        try:
                            mt = int(mt) // 1000000000 if mt else None
                        except (TypeError, ValueError):
                            mt = None
                        yield d, p, (got[0] if got else size) or 0, got[1] if got else None, 'опись', name_key(p), mt
            for p, (size, x) in hashes.items():           # хеш есть, а в описи файла нет - не терять
                if p not in seen:
                    yield d, p, size or 0, x, 'опись', name_key(p), None

        before = c.total_changes
        c.executemany('insert or replace into files values (?,?,?,?,?,?,?)', rows())
        c.execute('insert into disks values (?,?,?,?)', (d, j['label'], len(hashes), c.total_changes - before))
        n_all += c.total_changes - before - 1
        n_hash += len(hashes)
        c.commit()
    c.execute('create index files_sha on files(sha, disk) where sha is not null')
    c.execute('create index files_name on files(name_lc, size, disk)')
    c.execute('insert into meta values (?,?)', ('scans', scans_signature(jobs)))
    c.commit()
    c.close()
    replace_file(tmp, SNAP)
    if not quiet:
        out(f'Снимок описей собран за {time.time() - t0:.0f} с: {len(jobs)} носителей, {n_all} файлов, из них с хешем {n_hash}.')


def snapshot_fresh(jobs):
    if not SNAP.exists():
        return False
    c = sqlite3.connect(SNAP)
    try:
        row = c.execute("select value from meta where key='scans'").fetchone()
    except sqlite3.Error:
        row = None
    finally:
        c.close()
    return bool(row) and row[0] == scans_signature(jobs)


def build(jobs=None, quiet=False):
    """Рабочая база = копия снимка описей + поправки (журналы, ручные операции). Секунды."""
    jobs = jobs or bp.find_jobs()
    ensure_tables()
    if not snapshot_fresh(jobs):
        out('(описи изменились или снимка ещё нет - собираю снимок всех описей, это несколько минут и только один раз)')
        build_snapshot(jobs, quiet)
    t0 = time.time()
    tmp = DB.with_suffix('.tmp')
    if tmp.exists():
        tmp.unlink()
    shutil.copyfile(SNAP, tmp)
    c = sqlite3.connect(tmp)
    c.executescript('pragma journal_mode=off; pragma synchronous=off; pragma cache_size=-200000;')
    report = dict(logs=[], skipped=[], manual=[], warn=set())
    serials = serial_map(jobs)
    for log in sorted(glob.glob(str(bp.OUT_DIR / '*' / 'Журнал*.tsv')), key=os.path.getmtime):
        apply_log(c, log, jobs, serials, report)
    apply_manual(c, report)
    report['warn'] = sorted(report['warn'])
    c.execute('insert into meta values (?,?)', ('signature', sources_signature(jobs)))
    c.execute('insert into meta values (?,?)', ('report', json.dumps(report, ensure_ascii=False)))
    c.execute('insert into meta values (?,?)', ('built', time.strftime('%d.%m.%Y %H:%M')))
    c.commit()
    c.close()
    replace_file(tmp, DB)          # прежняя рабочая база остаётся на месте до этой строки
    if not quiet:
        out(f'Поправки наложены за {time.time() - t0:.0f} с.')
    return report


_last = None      # последнее открытое соединение: закрывается перед пересборкой, иначе Windows не даст заменить файл


def connect():
    global _last
    if _last is not None:
        try:
            _last.close()
        except sqlite3.Error:
            pass
        _last = None
    jobs = bp.find_jobs()
    ensure_tables()
    fresh = False
    if DB.exists():
        c = sqlite3.connect(DB)
        try:
            row = c.execute("select value from meta where key='signature'").fetchone()
        except sqlite3.Error:
            row = None
        finally:
            c.close()          # иначе Windows не даст заменить файл базы
        fresh = bool(row) and row[0] == sources_signature(jobs)
    if not fresh:
        out('(есть новые журналы или поправки - пересобираю рабочую базу)')
        build(jobs, quiet=True)
    _last = sqlite3.connect(f'file:{DB.as_posix()}?mode=ro', uri=True)
    return _last, jobs


def decisions_for(disk):
    res = []
    for f in read_tsv(DECISIONS)[1:]:
        f = [x.strip() for x in f] + [''] * 4
        if f[0] == disk and f[2]:
            res.append((f[1].rstrip(SEP), f[2]))
    return res


def decision_of(path, decs):
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


def table(head, rows, limit=25):
    rows = list(rows)
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows[:limit])) if rows else len(str(h)) for i, h in enumerate(head)]
    line = lambda r: '  '.join(str(x).ljust(w) if i == 0 else str(x).rjust(w) for i, (x, w) in enumerate(zip(r, widths)))
    out(line(head))
    for r in rows[:limit]:
        out(line(r))
    if len(rows) > limit:
        out(f'... ещё {len(rows) - limit} строк - см. файл')


def presence(c, disk, prefix):
    """Каждый файл диска с хешем: (path, size, sha, на45, на77, сколько дисков всего)."""
    cond, args = prefix_cond('f.path', prefix)
    q = f'''select f.path, f.size, f.sha,
                   exists(select 1 from files g where g.sha=f.sha and g.disk=?),
                   exists(select 1 from files g where g.sha=f.sha and g.disk=?),
                   (select count(distinct g.disk) from files g where g.sha=f.sha)
            from files f where f.disk=? and f.sha is not null and {cond}'''
    return c.execute(q, [MAIN[0], MAIN[1], disk] + args).fetchall()


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
    rows = presence(c, a.disk, prefix)
    decs = decisions_for(a.disk)
    agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0, 0])   # файлов, байт, нет45, нет77, нет обоих, только тут
    detail, decided = [], collections.Counter()
    for path, size, sha, on45, on77, ndisks in rows:
        v = decision_of(path, decs)
        if v:
            decided[v] += size
            continue
        if only and ndisks > 1:
            continue
        k = agg[folder_key(path, prefix, a.depth)]
        k[0] += 1; k[1] += size
        if not on45: k[2] += size
        if not on77: k[3] += size
        if not on45 and not on77: k[4] += size
        if ndisks == 1: k[5] += size
        if only or not (on45 and on77):
            detail.append((path, size, 'да' if on45 else 'нет', 'да' if on77 else 'нет', ndisks - 1, sha))
    title = f'{a.disk}' + (f'\\{prefix}' if prefix else '')
    what = 'только на этом диске' if only else f'чего нет на {MAIN[0]} и {MAIN[1]}'
    out(f'{title}: {what} (ГБ, только файлы с SHA-256; всего таких {len(rows)})')
    tot = [sum(v[i] for v in agg.values()) for i in range(6)]
    head = ('папка', 'файлов', 'всего', f'нет на {MAIN[0]}', f'нет на {MAIN[1]}', 'нет на обоих', 'больше нигде')
    order = sorted(agg.items(), key=lambda kv: -(kv[1][1] if only else max(kv[1][2], kv[1][3])))
    body = [(k[:60], v[0], gb(v[1]), gb(v[2]), gb(v[3]), gb(v[4]), gb(v[5])) for k, v in order
            if only or v[2] or v[3]]
    table(head, body + [('ИТОГО', tot[0], gb(tot[1]), gb(tot[2]), gb(tot[3]), gb(tot[4]), gb(tot[5]))])
    for v, size in decided.items():
        out(f'Не показано по решению «{v}»: {gb(size)} ГБ')
    tag = f'{a.disk} {prefix.replace(SEP, " - ")}'.strip()
    p = save(f'{"только" if only else "нет на 45 и 77"} - {tag}',
             ('путь', 'размер', f'на {MAIN[0]}', f'на {MAIN[1]}', 'на скольких других дисках', 'SHA-256'), sorted(detail))
    out(f'По файлам ({len(detail)}): {p}')
    if only:
        unhashed_report(c, a.disk, prefix, decs, f'только, без хеша - {tag}')
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
    out(f'A = {a.disk_a}\\{a.folder_a}    B = {a.disk_b}\\{a.folder_b}    (разных файлов с SHA-256: A {len(A)}, B {len(B)})')
    table(('', 'файлов', 'ГБ'), [('есть в обеих', len(both), gb(s(both, A))), ('только в A', len(oa), gb(s(oa, A))),
                                  ('только в B', len(ob), gb(s(ob, B)))])
    out('Вывод: ' + ('папки одинаковы по содержимому.' if not oa and not ob else
                     'в B есть всё из A.' if not oa else 'в A есть всё из B.' if not ob else 'папки различаются.'))
    detail = [('только в A', *A[k], k) for k in oa] + [('только в B', *B[k], k) for k in ob]
    NA, NB = name_sizes(c, a.disk_a, a.folder_a), name_sizes(c, a.disk_b, a.folder_b)
    if NA or NB:
        nb, na_, nb_ = NA.keys() & NB.keys(), NA.keys() - NB.keys(), NB.keys() - NA.keys()
        out(f'Файлы без SHA-256 (по имени и размеру, не доказательство): в обеих {len(nb)}, только в A {len(na_)}, '
            f'только в B {len(nb_)}')
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


def cmd_candel(a):
    c, jobs = connect()
    check_disk(c, a.disk)
    rows = presence(c, a.disk, a.folder)
    nohash = [r for r in unhashed(c, a.disk, a.folder) if r[3] in SIGNIFICANT]
    lost = [(p, s, k) for p, s, nm, k, others, dup in nohash if others == 0]
    if not rows and not nohash:
        out('В базе нет файлов по этому пути (проверьте написание пути и номер диска).')
        return
    lack = [(p, s, 'да' if o45 else 'нет', 'да' if o77 else 'нет', sha) for p, s, sha, o45, o77, n in rows if not (o45 and o77)]
    out(f'{a.disk}\\{a.folder}: файлов с SHA-256 {len(rows)}, {gb(sum(r[1] for r in rows))} ГБ')
    out(f'  есть и на {MAIN[0]}, и на {MAIN[1]}: {len(rows) - len(lack)}')
    out(f'  нет хотя бы на одном: {len(lack)}, {gb(sum(r[1] for r in lack))} ГБ')
    out(f'Значимых файлов без SHA-256 (документы, проекты, архивы, музыка, прочее): {len(nohash)}')
    if nohash:
        out(f'  копия по имени и размеру НЕ найдена ни на одном другом диске: {len(lost)}, {gb(sum(x[1] for x in lost))} ГБ')
    if lack:
        out('ОТВЕТ: НЕТ - сначала докопировать фото и видео.')
    elif lost:
        out('ОТВЕТ: НЕТ - фото и видео есть на обоих дисках, но у части остальных файлов копия не найдена нигде.')
    elif nohash:
        out('ОТВЕТ: ДА по фото и видео (всё с хешем есть на обоих дисках). Остальные файлы имеют вероятные копии '
            'по имени и размеру - это не доказательство, решает пользователь.')
    else:
        out('ОТВЕТ: ДА - все файлы с хешем есть на обоих дисках.')
    if lost:
        p = save(f'нельзя удалять, без хеша - {a.disk} {a.folder}'.replace(SEP, ' - '), ('путь', 'размер', 'класс'), sorted(lost))
        out(f'Файлы без найденной копии: {p}')
    if lack:
        p = save(f'нельзя удалять - {a.disk} {a.folder}'.replace(SEP, ' - '),
                 ('путь', 'размер', f'на {MAIN[0]}', f'на {MAIN[1]}', 'SHA-256'), sorted(lack))
        out(f'Чего не хватает: {p}')
    out('Учтены описи, журналы скриптов и таблица ручных операций. Удаляет только пользователь.')


def cmd_mklist(a):
    c, jobs = connect()
    check_disk(c, a.disk)
    for t in a.to:
        check_disk(c, t)
    task = bp.OUT_DIR / a.name
    if not a.dry and task.exists() and any(task.iterdir()):
        sys.exit(f'Папка задачи уже есть и не пуста: {task}. Выберите другое имя (--name).')
    decs = decisions_for(a.disk)
    lines, stat = [], collections.defaultdict(lambda: [0, 0])
    skipped = collections.Counter()
    for prefix in (a.folder or ['']):
        cond, args = prefix_cond('f.path', prefix.rstrip(SEP))
        for t in a.to:
            q = f'''select f.path, f.size, f.sha from files f where f.disk=? and f.sha is not null and {cond}
                    and not exists(select 1 from files g where g.sha=f.sha and g.disk=?)'''
            for path, size, sha in c.execute(q, [a.disk] + args + [t]):
                v = decision_of(path, decs)
                if v:
                    skipped[v] += size
                    continue
                lines.append((t, path, size, 'фото/видео', sha.upper()))
                stat[t][0] += 1; stat[t][1] += size
    lines = sorted(set(lines))
    if not lines:
        out('Копировать нечего: всё с хешем уже есть на указанных дисках (или отложено решениями).')
        return
    if a.dry:
        out('Пробный расчёт (--dry): папка задачи не создаётся.')
        for t in a.to:
            out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ')
        for v, size in skipped.items():
            out(f'  не включено по решению «{v}»: {gb(size)} ГБ')
        return
    serials = {v: k for k, v in serial_map(jobs).items()}
    task.mkdir(parents=True, exist_ok=True)
    with io.open(task / 'список.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for r in lines:
            f.write('\t'.join(map(str, r)) + '\n')
    with io.open(task / 'тома.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for d in [a.disk] + list(a.to):
            f.write(f'{d}\t{serials.get(d, "НЕТ_СЕРИЙНОГО_НОМЕРА")}\n')
    for name in ('Копировать.ps1', 'Запустить.cmd'):
        shutil.copy2(TEMPLATE / name, task / name)
    out(f'Папка задачи: {task}')
    for t in a.to:
        out(f'  на {t}: {stat[t][0]} файлов, {gb(stat[t][1])} ГБ -> ПЕРЕНОС с других дисков\\{a.disk}\\<тот же путь>')
    for v, size in skipped.items():
        out(f'  не включено по решению «{v}»: {gb(size)} ГБ')
    out('Запуск - пользователем: двойной щелчок по «Запустить.cmd». Свою папку на цели можно задать третьей колонкой в тома.tsv.')


def cmd_stats(a):
    c, jobs = connect()
    n, h = c.execute('select count(*), count(sha) from files').fetchone()
    out(f'База: {DB}')
    out(f'Собрана {c.execute("select value from meta where key=?", ("built",)).fetchone()[0]}; файлов {n}, '
        f'из них с SHA-256 {h}, без хеша {n - h}; носителей {len(jobs)}')
    rep = json.loads(c.execute("select value from meta where key='report'").fetchone()[0])
    out('Учтённые журналы скриптов:')
    for x in rep['logs']:
        out('  ' + x)
    out('Журналы, которые программа не умеет читать (не учтены):' if rep['skipped'] else 'Все найденные журналы учтены.')
    for x in rep['skipped']:
        out('  ' + x)
    out(f'Ручные операции ({MANUAL.name}): {len(rep["manual"])}')
    for x in rep['manual']:
        out('  ' + x)
    for x in rep['warn']:
        out('ВНИМАНИЕ: ' + x)
    out(f'Решения ({DECISIONS.name}): {len(read_tsv(DECISIONS)) - 1}')


def cmd_recovery_plan(a):
    import recovery_plan
    recovery_plan.cmd_recovery_plan(a, sys.modules[__name__])


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
    sub.add_parser('build'); sub.add_parser('stats')
    p = sub.add_parser('recovery-plan', help='разбор оглавления восстановленной папки, без чтения содержимого')
    p.add_argument('disk'); p.add_argument('--root', type=Path, required=True)
    a = ap.parse_args()
    t0 = time.time()
    if a.cmd == 'build':
        build()
        cmd_stats(a)
    else:
        {'missing': cmd_missing, 'only': lambda x: cmd_missing(x, True), 'cmp': cmd_cmp, 'where': cmd_where,
         'candel': cmd_candel, 'mklist': cmd_mklist, 'stats': cmd_stats, 'recovery-plan': cmd_recovery_plan}[a.cmd](a)
    out(f'[{time.time() - t0:.1f} с]')


if __name__ == '__main__':
    main()
