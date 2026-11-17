"""«Я сделал в Проводнике»: обход выбранных папок диска и сравнение с базой."""
import os
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

from hb_core import api as hb
import service as sv
from explorer_diff_base import SEP, EXCLUDED_DIRS, excluded_file, Stopped, key, under
from explorer_diff_group import group


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
